from django.contrib import admin
from .models import ProductCategory, Product, Cart, CartItem, Order, OrderItem, Transaction, BrillsPayLog

# =========================
# Product Category Admin
# =========================
@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('class_name', 'slug', 'is_active')
    search_fields = ('class_name',)
    actions = ['activate_categories', 'deactivate_categories']

    def activate_categories(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} category(s) activated.")
    activate_categories.short_description = "Activate selected categories"

    def deactivate_categories(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} category(s) deactivated.")
    deactivate_categories.short_description = "Deactivate selected categories"

# =========================
# Product Admin
# =========================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at',)
    actions = ['activate_products', 'deactivate_products']

    def activate_products(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} product(s) activated.")
    activate_products.short_description = "Activate selected products"

    def deactivate_products(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} product(s) deactivated.")
    deactivate_products.short_description = "Deactivate selected products"

# =========================
# Cart Admin
# =========================
@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username',)
    readonly_fields = ('created_at', 'updated_at')

# =========================
# CartItem Admin
# =========================
@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'product', 'quantity', 'subtotal', 'total_amount')
    search_fields = ('product__name', 'cart__user__username')

# =========================
# Order Admin
# =========================
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('reference', 'buyer', 'ward', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'total_amount')
    search_fields = ('buyer__username', 'ward__first_name', 'reference')
    readonly_fields = ('created_at', 'reference')

# =========================
# OrderItem Admin
# =========================
@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_name', 'quantity', 'price', 'subtotal', 'total_amount')
    search_fields = ('product_name', 'total_amount')

# =========================
# Transaction Admin
# =========================
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('order', 'gateway_reference', 'amount', 'verified', 'created_at')
    search_fields = ('gateway_reference', 'order__reference', 'order__buyer__username')
    readonly_fields = ('created_at',)

# =========================
# Log Admin
# =========================
@admin.register(BrillsPayLog)
class MPayLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'order', 'created_at')
    readonly_fields = ('created_at',)
    search_fields = ('user__username', 'order__reference', 'action')
