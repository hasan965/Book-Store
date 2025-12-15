from django.db import models

class Category(models.Model):
    Category_name = models.CharField(max_length=20)

    def __str__(self):
        return self.Category_name

    class Meta:
        db_table = "Category"


class Product(models.Model):
    pname = models.CharField(max_length=70)
    p_short_name = models.CharField(max_length=30)
    author = models.CharField(max_length=60)
    price = models.FloatField(default=200)
    description = models.CharField(max_length=500)
    size = models.FloatField(default=1)
    quantity = models.IntegerField()
    image = models.ImageField(default="abc.jpg", upload_to="images")
    cat = models.ForeignKey(to="Category", on_delete=models.CASCADE)

    def __str__(self):
        return self.pname

    class Meta:
        db_table = "Product"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    image = models.ImageField(upload_to="images")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "ProductImage"
        ordering = ["order"]


class UserInfo(models.Model):
    username = models.CharField(max_length=20, primary_key=True)
    emai = models.EmailField(max_length=100)
    password = models.CharField(max_length=20)

    def __str__(self):
        return self.username

    class Meta:
        db_table = "UserInfo"


class PaymentMaster(models.Model):
    cardno = models.CharField(max_length=20)
    cvv = models.CharField(max_length=4)
    expiry = models.CharField(max_length=20)
    balance = models.FloatField(default=50000)

    class Meta:
        db_table = "PaymentMaster"


from datetime import datetime

class MyCart(models.Model):
    user = models.ForeignKey(UserInfo, on_delete=models.CASCADE)
    book = models.ForeignKey(Product, on_delete=models.CASCADE)
    qty = models.IntegerField()

    class Meta:
        db_table = "MyCart"

class OrderMaster(models.Model):
    user = models.ForeignKey(UserInfo, on_delete=models.CASCADE)
    amount = models.FloatField(default=0)
    dateOfOrder = models.DateTimeField(default=datetime.now)
    details = models.CharField(max_length=300)
    # Stripe session id to make order creation idempotent when receiving webhooks
    stripe_session_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    # Shipping / recipient details
    recipient_name = models.CharField(max_length=120, null=True, blank=True)
    address_line1 = models.CharField(max_length=255, null=True, blank=True)
    address_line2 = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=30, null=True, blank=True)
    country = models.CharField(max_length=60, null=True, blank=True)
    phone = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        db_table = "OrderMaster"

