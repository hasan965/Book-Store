from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from AdminApp.models import Category, Product, UserInfo, PaymentMaster
from UserApp.models import MyCart, OrderMaster
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.contrib import messages
from datetime import datetime
from .models import Product, Category, MyCart as LocalMyCart, UserInfo as LocalUserInfo
from django.contrib.auth.hashers import make_password, check_password
import logging

import stripe
from django.conf import settings
from django.urls import reverse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json

stripe.api_key = settings.STRIPE_SECRET_KEY

# logger for payments and security events
logger = logging.getLogger('userapp')
if not logger.handlers:
    # basic config if none set by project
    logging.basicConfig(level=logging.INFO)


def MakePayment(request):
    if request.method == "POST":
        total = request.session.get("total", 0)

        # Read shipping details from the form and store them in session + pass to Stripe metadata
        shipping = {
            'recipient_name': request.POST.get('recipient_name', ''),
            'address_line1': request.POST.get('address_line1', ''),
            'address_line2': request.POST.get('address_line2', ''),
            'city': request.POST.get('city', ''),
            'postal_code': request.POST.get('postal_code', ''),
            'country': request.POST.get('country', ''),
            'phone': request.POST.get('phone', ''),
        }
        try:
            request.session['shipping'] = shipping
        except Exception:
            pass

        # تحويل المبلغ إلى سنتات بأمان (تعامل مع الحالات حيث total قد يكون None أو string)
        try:
            amount_cents = int(float(total) * 100)
            if amount_cents < 0:
                raise ValueError("Negative amount")
        except Exception:
            messages.error(request, "المبلغ غير صالح للدفع.")
            return redirect('ShowAllCartItems')

        try:
            # include shipping details in metadata so webhook can extract them later
            metadata = {
                'username': request.session.get('uname', '')
            }
            # copy non-empty shipping fields into metadata (Stripe metadata requires strings)
            for k, v in shipping.items():
                if v:
                    metadata[f'ship_{k}'] = str(v)[:250]

                session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": "Book Order"},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }],
                mode="payment",
                    # include the checkout session id on the success redirect so we can verify and create the order
                    success_url=request.build_absolute_uri(reverse('payment_success')) + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
                    # Attach metadata (username + shipping fields)
                    metadata=metadata,
                    client_reference_id=request.session.get('uname', ''),
            )
        except stripe.error.StripeError as e:
            messages.error(request, "حدث خطأ أثناء إنشاء جلسة الدفع. حاول مرة أخرى.")
            return redirect('ShowAllCartItems')

        return redirect(session.url, code=303)

    # provide shipping defaults to the template to avoid complex template expressions
    shipping = request.session.get('shipping', {})
    return render(request, "MakePayment.html", {
        "STRIPE_PUBLIC_KEY": getattr(settings, 'STRIPE_PUBLIC_KEY', ''),
        "shipping": shipping,
    })


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhooks. Create OrderMaster and clear user's MyCart when
    checkout.session.completed is received.

    Requirements:
    - Set STRIPE_WEBHOOK_SECRET in settings (recommended). If not set we'll accept
      unsigned events (less secure).
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

    try:
        if endpoint_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        else:
            # Fallback for local testing (no signature verification)
            event = json.loads(payload)
    except ValueError:
        print('WEBHOOK: invalid payload')
        logger.error('Stripe webhook: invalid payload')
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        print('WEBHOOK: signature verification failed')
        logger.error('Stripe webhook: signature verification failed')
        return HttpResponse(status=400)

    # Debug: log the raw event for troubleshooting local tests
    try:
        # do not log full payload in production; this is for local debug only
        logger.info('Stripe webhook received: %s', getattr(event, 'get', lambda k: None)('type') if isinstance(event, dict) else str(type(event)))
        print('WEBHOOK RECEIVED:', event if isinstance(event, dict) else 'non-dict event')
    except Exception:
        pass

    # Handle the checkout.session.completed event
    if (isinstance(event, dict) and event.get('type') == 'checkout.session.completed') or (
        hasattr(event, 'get') and event.get('type') == 'checkout.session.completed'):
        session = event['data']['object'] if isinstance(event, dict) else event['data']['object']

        # Attempt to get the username from metadata (set when creating the session)
        metadata = session.get('metadata', {}) if isinstance(session, dict) else {}
        username = metadata.get('username') if metadata else None

        # amount_total is in cents
        amount_total = session.get('amount_total', 0) if isinstance(session, dict) else 0
        amount = float(amount_total) / 100.0 if amount_total else 0

        # Debug: log extracted session info
        try:
            session_id_dbg = session.get('id') if isinstance(session, dict) else None
            logger.info('Stripe session: id=%s username=%s amount=%s', session_id_dbg, username, amount)
            print(f'WEBHOOK: session id={session_id_dbg} username={username} amount={amount}')
        except Exception:
            pass

        if username:
            try:
                user = UserInfo.objects.get(username=username)

                # idempotency: if we've already created an order for this stripe session, skip
                session_id = session.get('id') if isinstance(session, dict) else None
                if session_id and OrderMaster.objects.filter(stripe_session_id=session_id).exists():
                    logger.info(f"Webhook received for already-processed session {session_id}")
                    return HttpResponse(status=200)

                # Validate amount against current cart total for this user to avoid tampering
                items = MyCart.objects.filter(user=user).select_related('book')
                expected_total = 0.0
                for item in items:
                    try:
                        expected_total += float(item.qty) * float(item.book.price)
                    except Exception:
                        # if any problem, log and abort creating order
                        logger.warning(f"Could not compute expected total for user {username}")
                        expected_total = None
                        break

                logger.info('Computed expected_total=%s from cart rows count=%d', expected_total, items.count())
                print(f'WEBHOOK: expected_total={expected_total} items_count={items.count()}')

                # add shipping/handling logic if your app adds fixed charge (e.g., +40)
                if expected_total is not None:
                    if expected_total > 249:
                        expected_total = round(expected_total, 2)
                    elif expected_total == 0:
                        expected_total = 0.0
                    else:
                        expected_total = round(expected_total + 40, 2)

                if expected_total is None:
                    logger.error(f"Aborting order creation: expected_total None for user {username}")
                    print(f'WEBHOOK: aborting because expected_total is None for user {username}')
                    return HttpResponse(status=400)

                # Compare amounts (allow small rounding differences)
                if abs(expected_total - float(amount)) > 0.5:
                    logger.error(f"Payment amount mismatch for user {username}: stripe={amount}, expected={expected_total}")
                    print(f'WEBHOOK: amount mismatch stripe={amount} expected={expected_total}')
                    # Do not clear cart or create order; investigate
                    return HttpResponse(status=400)

                # create order record
                order = OrderMaster()
                order.user = user
                order.amount = amount
                order.stripe_session_id = session_id

                details = ""
                for item in items:
                    try:
                        details += (item.book.p_short_name) + ","
                    except Exception:
                        details += str(item.book.id) + ","
                    # remove item after adding to order
                    item.delete()

                order.details = details
                # attach shipping details from Stripe session metadata if present
                try:
                    md = metadata if isinstance(metadata, dict) else {}
                    order.recipient_name = md.get('ship_recipient_name')
                    order.address_line1 = md.get('ship_address_line1')
                    order.address_line2 = md.get('ship_address_line2')
                    order.city = md.get('ship_city')
                    order.postal_code = md.get('ship_postal_code')
                    order.country = md.get('ship_country')
                    order.phone = md.get('ship_phone')
                except Exception:
                    pass

                order.save()
                logger.info(f"Order created for user {username}, session {session_id}, amount {amount}")
            except UserInfo.DoesNotExist:
                logger.warning(f"Webhook: user {username} not found when processing session")
                pass

    return HttpResponse(status=200)

def payment_success(request):
    # Try to create the order immediately using the Checkout Session id returned by Stripe
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.success(request, "تم الدفع بنجاح 💳")
        return redirect('homepage')

    try:
        # retrieve the session from Stripe to validate payment
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.error(f"Could not retrieve Stripe session {session_id}: {e}")
        messages.error(request, "حدث خطأ أثناء التحقق من الدفعة.")
        return redirect('homepage')

    # Check payment status
    paid = False
    try:
        # Stripe Checkout Session has payment_status == 'paid' when payment is successful
        paid = (session.get('payment_status') == 'paid') if isinstance(session, dict) else getattr(session, 'payment_status', None) == 'paid'
    except Exception:
        paid = False

    if not paid:
        messages.error(request, "الدفع لم يكتمل بعد.")
        return redirect('ShowAllCartItems')

    # Extract username from metadata or client_reference_id
    try:
        metadata = session.get('metadata', {}) if isinstance(session, dict) else {}
        username = metadata.get('username') if metadata else (session.get('client_reference_id') if isinstance(session, dict) else getattr(session, 'client_reference_id', None))
    except Exception:
        username = None

    if not username:
        messages.error(request, "تعذر تحديد المستخدم المرتبط بهذه الدفعة.")
        return redirect('homepage')

    try:
        user = UserInfo.objects.get(username=username)
    except UserInfo.DoesNotExist:
        messages.error(request, "المستخدم غير موجود.")
        return redirect('homepage')

    # idempotency: avoid duplicating orders if webhook already created one
    try:
        if session_id and OrderMaster.objects.filter(stripe_session_id=session_id).exists():
            messages.success(request, "تم تسجيل الطلب مسبقًا.")
            return redirect('homepage')
    except Exception:
        pass

    # compute expected total from cart
    items = MyCart.objects.filter(user=user).select_related('book')
    expected_total = 0.0
    for item in items:
        try:
            expected_total += float(item.qty) * float(item.book.price)
        except Exception:
            expected_total = None
            break

    if expected_total is None:
        messages.error(request, "حدث خطأ أثناء حساب إجمالي السلة.")
        return redirect('homepage')

    # apply shipping if applicable (same logic as webhook)
    if expected_total > 249:
        expected_total = round(expected_total, 2)
    elif expected_total == 0:
        expected_total = 0.0
    else:
        expected_total = round(expected_total + 40, 2)

    # amount from stripe session
    amount_total = session.get('amount_total', 0) if isinstance(session, dict) else getattr(session, 'amount_total', 0)
    amount = float(amount_total) / 100.0 if amount_total else 0

    # allow small rounding differences
    if abs(expected_total - amount) > 0.5:
        logger.error(f"Payment amount mismatch in success handler for user {username}: stripe={amount}, expected={expected_total}")
        messages.error(request, "مشكلة تطابق المبلغ، لم يتم إنشاء الطلب تلقائيًا.")
        return redirect('ShowAllCartItems')

    # create order and clear cart
    order = OrderMaster()
    order.user = user
    order.amount = amount
    order.stripe_session_id = session_id

    details = ""
    for item in items:
        try:
            details += (item.book.p_short_name) + ","
        except Exception:
            details += str(getattr(item.book, 'id', '')) + ","
        item.delete()

    order.details = details
    order.save()
    messages.success(request, "تم إنشاء الطلب بنجاح 🎉")
    logger.info(f"Order created in success handler for user {username}, session {session_id}, amount {amount}")
    return redirect('homepage')

def payment_cancel(request):
    messages.error(request, "تم إلغاء عملية الدفع ❌")
    return redirect('ShowAllCartItems')






def cart_item_count(request):
    total_qty = 0
    if "uname" in request.session:
        try:
            user = UserInfo.objects.get(username=request.session["uname"])
            items = MyCart.objects.filter(user=user)
            # Sum the quantities of all cart rows so the badge shows total items, not distinct products
            try:
                total_qty = sum(int(item.qty) for item in items)
            except Exception:
                # Fallback: count rows if qty isn't numeric for some reason
                total_qty = items.count()
        except UserInfo.DoesNotExist:
            total_qty = 0
    return {'cart_count': total_qty}

# from django.db.models import 

product_per_page = 16
# Create your views here.
def homepage(request):
    # Fetch all records from category table
    cats = Category.objects.all()

    ordering = request.GET.get('ordering', "")     # http://www.wondershop.in:8000/listproducts/?page=1&ordering=price
    search = request.GET.get('query', "")
    price = request.GET.get('price', "")

    # Pagination logic
    items = Product.objects.all().order_by("id")
    paginator = Paginator(items, product_per_page)
    page_number = request.GET.get('page')
    ServiceDataFinal = paginator.get_page(page_number)
    totalPage = ServiceDataFinal.paginator.num_pages

    # Dictionary لكل فئة والكتب التابعة لها
    cat_books = {}
    for cat in cats:
        cat_books[cat] = Product.objects.filter(cat=cat)

    return render(request, "index.html", {
        "cats": cats,
        "books": [n+1 for n in range(totalPage)],
        "ServiceData": ServiceDataFinal,
        "lastpage": totalPage,
        "cat_books": cat_books  # ← جديد
    })

def signin(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    if(request.method == "GET"):
        return render(request,"signin.html",{"cats":cats, "books":books})
    else:
        uname = request.POST["uname"]
        password = request.POST["password"]
        try:
            user = UserInfo.objects.get(username=uname)
            if not check_password(password, user.password):
                # invalid password
                messages.error(request, "بيانات الدخول غير صحيحة")
                return redirect('signin')
        except UserInfo.DoesNotExist:
            messages.error(request, "بيانات الدخول غير صحيحة")
            return redirect('signin')

        # Create session
        request.session["uname"] = uname
        return redirect(homepage)

def signup(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    if(request.method == "GET"):
        return render(request,"signup.html",{"cats":cats, "books":books})
    else:
        uname = request.POST["uname"]
        email = request.POST["email"]
        password = request.POST["password"]
        # store hashed password
        hashed = make_password(password)
        user = UserInfo(username=uname, emai=email, password=hashed)
        user.save()
        return redirect(homepage)

def search(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    from django.db.models import Q

    query = request.GET.get("query", "").strip()
    cat_filter = request.GET.get('cat', '') or request.GET.get('category', '')

    qs = Product.objects.all()

    # If a category filter (id) is provided, apply it first
    if cat_filter:
        try:
            # numeric id
            cid = int(cat_filter)
            qs = qs.filter(cat__id=cid)
        except Exception:
            # assume category name; filter by category name containing the term
            qs = qs.filter(cat__Category_name__icontains=cat_filter)

    if query:
        # search by product name, short name, author or category name
        q_obj = (
            Q(pname__icontains=query) |
            Q(p_short_name__icontains=query) |
            Q(author__icontains=query) |
            Q(cat__Category_name__icontains=query)
        )
        qs = qs.filter(q_obj).distinct()

    return render(request, 'search.html', {"cats": cats, "books": books, "allProd": qs, "query": query})

def userProfile(request):
    cats = Category.objects.all()  
    books = Product.objects.all()
    return render(request,"Profile.html",{"cats":cats,"books":books})

def signout(request):
    request.session.clear()
    return redirect(homepage)        

def addToCart(request):
    if request.method == "POST":
        if "uname" in request.session:
            bookid = request.POST["bookid"]
            qty = request.POST.get("qty", 1)  # default 1 if not provided
            username = request.session["uname"]

            # Prevent accidental double-adds: use a short cooldown per product stored in session
            try:
                cooldowns = request.session.get('recently_added', {})
            except Exception:
                cooldowns = {}
            import time
            now = int(time.time())
            last = cooldowns.get(str(bookid), 0)
            COOLDOWN_SECONDS = 5
            is_quick_duplicate = (now - last) < COOLDOWN_SECONDS

            book = Product.objects.get(id=bookid)
            user = UserInfo.objects.get(username=username)

            # If this is a quick duplicate click, do not increment again
            if is_quick_duplicate:
                # recompute total quantity for response
                items = MyCart.objects.filter(user=user)
                try:
                    total_qty = sum(int(item.qty) for item in items)
                except Exception:
                    total_qty = items.count()
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'cart_count': total_qty, 'message': 'تمت إضافة المنتج إلى السلة'})
                messages.info(request, "تمت إضافة المنتج مسبقاً للتو")
                return redirect(request.META.get('HTTP_REFERER', '/'))

            try:
                cart = MyCart.objects.get(book=book, user=user)
                cart.qty += int(qty)
                cart.save()
                messages.success(request, "تم تحديث الكمية في السلة 🛒")
            except MyCart.DoesNotExist:
                cart = MyCart(book=book, user=user, qty=qty)
                cart.save()
                messages.success(request, "تمت إضافة المنتج إلى السلة 🛍️")

            # record this add action timestamp in session to prevent immediate duplicates
            try:
                cooldowns[str(bookid)] = now
                request.session['recently_added'] = cooldowns
            except Exception:
                pass

            # If this is an AJAX request, return JSON with new cart total quantity
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # recompute total quantity for this user
                items = MyCart.objects.filter(user=user)
                try:
                    total_qty = sum(int(item.qty) for item in items)
                except Exception:
                    total_qty = items.count()
                return JsonResponse({
                    'success': True,
                    'cart_count': total_qty,
                    'message': 'تمت إضافة المنتج إلى السلة'
                })

            # 👇 بدال ما نحول دغري على السلة
            return redirect(request.META.get('HTTP_REFERER', '/'))

        else:
            messages.error(request, "يجب تسجيل الدخول أولاً قبل إضافة منتج إلى السلة.")
            return redirect('signin')

    return redirect('homepage')

def ShowAllCartItems(request):
    cats = Category.objects.all()
    books = Product.objects.all()

    unam = request.session["uname"]
    user = UserInfo.objects.get(username=unam)

    if request.method == "GET":
        # materialize queryset and join Product to avoid lazy FK re-evaluation issues
        cart_qs = list(MyCart.objects.filter(user=user).select_related('book'))
        cart_rows = []
        total_p = 0.0

        for c in cart_qs:
            try:
                unit_price = float(c.book.price)
            except Exception:
                unit_price = 0.0
            try:
                line_total = round(int(c.qty) * unit_price, 2)
            except Exception:
                line_total = 0.0

            row = {
                'cart_id': c.id,
                'book_id': getattr(c.book, 'id', None),
                'image_url': getattr(getattr(c.book, 'image', None), 'url', ''),
                'title': getattr(c.book, 'p_short_name', getattr(c.book, 'pname', '')),
                'author': getattr(c.book, 'author', ''),
                'unit_price': unit_price,
                'qty': int(c.qty),
                'line_total': line_total,
            }
            cart_rows.append(row)
            total_p += line_total

        # Debug: server console output to verify mapping
        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug('Cart rows for user %s: %s', user.username, cart_rows)
            print('DEBUG Cart rows for user {}: {}'.format(getattr(user, 'username', None), cart_rows))
        except Exception:
            pass

        if total_p > 249:
            request.session["total"] = total_p
        elif total_p == 0:
            request.session["total"] = 0
        else:
            request.session["total"] = total_p + 40

        return render(
            request,
            "ShowAllCartItems.html",
            {"items": cart_rows, "cats": cats, "books": books},
        )

    else:
        # Some POSTs may not include bookid (e.g., accidental submits). Handle gracefully.
        b_id = request.POST.get("bookid")
        if not b_id:
            # nothing to do, redirect back to cart
            return redirect(ShowAllCartItems)

        action = request.POST.get("action", "update")  # 👈 determine Update or Remove

        try:
            book = Product.objects.get(id=b_id)
        except Product.DoesNotExist:
            return redirect(ShowAllCartItems)

        if action == "remove":
            # remove the cart item
            MyCart.objects.filter(user=user, book=book).delete()
        else:
            # Update quantity
            qty = request.POST.get("qty", 1)
            try:
                cart = MyCart.objects.get(book=book, user=user)
                cart.qty = int(qty)
                cart.save()
            except MyCart.DoesNotExist:
                # if cart row missing, create one
                MyCart.objects.create(user=user, book=book, qty=int(qty))

        return redirect(ShowAllCartItems)


def removeItem(request):
    # بصراحة مش محتاجها إذا دمجت فوق
    u_name = request.session["uname"]
    user = UserInfo.objects.get(username=u_name)
    b_id = request.POST["bookid"]
    book = Product.objects.get(id=b_id)

    MyCart.objects.filter(user=user, book=book).delete()  # 👈 delete بس
    return redirect(ShowAllCartItems)

# def MakePayment(request):
#     if(request.method == "GET"):
#         return render(request,"MakePayment.html",{})
#     else:
#         cardno = request.POST["cardno"]
#         cvv = request.POST["cvv"]
#         expiry = request.POST["expiry"]
#         try:
#             buyer = PaymentMaster.objects.get(cardno=cardno, cvv=cvv, expiry=expiry)
#         except:
#             return redirect(MakePayment)
#         else:
#             # it is a Match
#             owner = PaymentMaster.objects.get(cardno='1111 2222 3333 4444', cvv='549', expiry='10/2028')
#             owner.balance += request.session["total"]
#             buyer.balance -= request.session["total"]
#             owner.save()
#             buyer.save()
#             # Delete data from cart
#             unam = request.session["uname"]
#             user = UserInfo.objects.get(username=unam)
#             order = OrderMaster()
#             order.user = user
#             order.amount = request.session["total"]
#             details = ""
#             items = MyCart.objects.filter(user=user)
#             for item in items:
#                 details += (item.book.p_short_name)+","
#                 item.delete()     
#             order.details = details
#             order.save()
#             messages.success(request,"Ordered Successfully 💐")
#             return redirect(homepage)


def ShowBooks(request, id):
    # جلب الفئة المختارة
    selected_category = get_object_or_404(Category, id=id)
    
    # كل الكتب ضمن الفئة
    books_in_category = Product.objects.filter(cat=selected_category)
    
    # كل الفئات
    cats = Category.objects.all()

    # نرسل نفس البيانات لقالب index.html مع تخصيص cat_books للفئة المختارة
    cat_books = {selected_category: books_in_category}

    # To avoid showing the same books twice (ServiceData + cat_books), send ServiceData empty
    # and pass selected_category so the template can show category heading.
    return render(request, "index.html", {
        "cats": cats,
        "ServiceData": [],
        "cat_books": cat_books,
        "selected_category": selected_category,
        "books": [],
        "lastpage": 1
    })

# def ViewDetails(request,id):
#     # cart items
    
#     cats = Category.objects.all()
#     books = Product.objects.all()

#     book = Product.objects.get(id=id)
#     return render(request,"ViewDetais.html",{"book":book,"cats":cats, "books":books})
    

def payments(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"payments.html",{"cats":cats, "books":books})

def returns(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"returns.html",{"cats":cats, "books":books})

def aboutTheProg(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"aboutTheProg.html",{"cats":cats, "books":books})

def tandc(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"t&c.html",{"cats":cats, "books":books})

def contactUs(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"contactUs.html",{"cats":cats, "books":books})

def shipping(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"shipping.html",{"cats":cats, "books":books})

def aboutus(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"aboutus.html",{"cats":cats, "books":books})

def careers(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"careers.html",{"cats":cats, "books":books})

def faq(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"FAQs.html",{"cats":cats, "books":books})

def privacypolicy(request):
    cats = Category.objects.all()
    books = Product.objects.all()
    return render(request,"Pri-Pol.html",{"cats":cats, "books":books})

def view_details(request, id):
    book = Product.objects.get(id=id)
    suggestions = Product.objects.filter(cat=book.cat).exclude(id=book.id)[:4]

    print("Book:", book.pname)
    print("Book category:", book.cat)
    print("Suggestions count:", suggestions.count())
    print("Total books in this category:", Product.objects.filter(cat=book.cat).count())

    for s in suggestions:
        print(" - ", s.pname)

    return render(request, "ViewDetais.html", {
        "book": book,
        "suggestions": suggestions
    })
    
def product_json(request, id):
    """Return product data as JSON for Quick View AJAX."""
    try:
        prod = Product.objects.get(id=id)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    # collect image URLs (main image + additional ProductImage rows)
    images = []
    if getattr(prod, 'image', None):
        try:
            images.append(prod.image.url)
        except Exception:
            pass

    # related ProductImage objects (if any)
    try:
        extra_imgs = prod.productimage_set.all()
        for it in extra_imgs:
            if it.image:
                try:
                    images.append(it.image.url)
                except Exception:
                    continue
    except Exception:
        extra_imgs = []

    data = {
        'id': prod.id,
        'name': getattr(prod, 'p_short_name', prod.pname if hasattr(prod, 'pname') else ''),
        'price': str(prod.price),
        'images': images,
        'description': prod.description if hasattr(prod, 'description') else '',
        'author': getattr(prod, 'author', ''),
        'category': prod.cat.Category_name if getattr(prod, 'cat', None) else ''
    }
    return JsonResponse(data)


