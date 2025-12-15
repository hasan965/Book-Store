from django.contrib import admin
from .models import Category, Product, UserInfo, PaymentMaster, MyCart, OrderMaster

# ---- Category ----
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'Category_name')  # صحّحت الاسم
    search_fields = ('Category_name',)
    ordering = ('id',)

# ---- Product ----
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('pname', 'p_short_name', 'price', 'cat')
    list_filter = ('cat',)
    search_fields = ('pname', 'p_short_name', 'description')
    ordering = ('pname',)

# ---- UserInfo ----
@admin.register(UserInfo)
class UserInfoAdmin(admin.ModelAdmin):
    list_display = ('username', 'emai')  # صحّحت الاسم
    search_fields = ('username', 'emai')
    ordering = ('username',)

# ---- PaymentMaster ----
@admin.register(PaymentMaster)
class PaymentMasterAdmin(admin.ModelAdmin):
    list_display = ('cardno', 'cvv', 'expiry', 'balance')
    search_fields = ('cardno',)
    ordering = ('cardno',)

# ---- MyCart ----
@admin.register(MyCart)
class MyCartAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'qty')
    search_fields = ('user__username', 'book__pname')
    list_filter = ('user',)

# ---- OrderMaster ----
@admin.register(OrderMaster)
class OrderMasterAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'details', 'dateOfOrder')
    search_fields = ('user__username', 'details')
    ordering = ('dateOfOrder',)
