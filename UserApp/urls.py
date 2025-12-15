from django.urls import path
from . import views

urlpatterns = [
    path("", views.homepage, name="homepage"),
    path("signin", views.signin, name="signin"),
    path("signup", views.signup, name="signup"),
    path("signout", views.signout, name="signout"),
    path("userProfile", views.userProfile, name="userProfile"),
    path("search", views.search, name="search"),
    path("ShowBooks/<int:id>", views.ShowBooks, name="ShowBooks"),
    # path("ViewDetails/<id>", views.ViewDetails),
    path("addToCart", views.addToCart, name="addToCart"),
    path("ShowAllCartItems", views.ShowAllCartItems, name="ShowAllCartItems"),
    path('removeItem', views.removeItem, name='removeItem'),
    path("MakePayment", views.MakePayment, name="MakePayment"),
    path("payments", views.payments, name="payments"),

    # ✅ روابط الدفع باستخدام Stripe
    path("payment/success/", views.payment_success, name="payment_success"),
    path("payment/cancel/", views.payment_cancel, name="payment_cancel"),
    path("webhook/stripe/", views.stripe_webhook, name="stripe_webhook"),

    path("shipping", views.shipping, name="shipping"),
    path("returns", views.returns, name="returns"),
    path("aboutTheProg", views.aboutTheProg, name="aboutTheProg"),
    path("t&c", views.tandc, name="tandc"),
    path("contactUs", views.contactUs, name="contactUs"),
    path("aboutus", views.aboutus, name="aboutus"),
    path("careers", views.careers, name="careers"),
    path("privacypolicy", views.privacypolicy, name="privacypolicy"),
    path("faq", views.faq, name="faq"),
    path('ViewDetails/<int:id>/', views.view_details, name='view_details'),
    path('product/<int:id>/json/', views.product_json, name='product_json'),
]
