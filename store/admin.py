from django.contrib import admin
from .models import Product, ProductImage, Order, OrderItem


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'sold_out', 'created_at')
    list_filter = ('sold_out', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductImageInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'email', 'total_price', 'created_at')
    search_fields = ('full_name', 'email')
    inlines = [OrderItemInline]