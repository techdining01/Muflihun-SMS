from django.db import models
from django.db.models import Sum, F
from django.conf import settings
from django.utils import timezone
import uuid
from exams.models import SchoolClass, Exam

User = settings.AUTH_USER_MODEL

# =========================
# Product Category (Class)
# =========================
class ProductCategory(models.Model):
    """
    Class-based category (e.g. JSS1, SSS3).
    """
    class_name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.class_name

# Default categories you can create via migrations or admin
# DEFAULT_CATEGORIES = ["JSS1", "JSS2", "JSS3", "SSS1", "SSS2", "SSS3"]

# =========================
# Product
# =========================
class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="products"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.PositiveIntegerField(default=0)
    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category.class_name})"

# =========================
# Cart
# ========================= 
class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    ward = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ward_carts",
        limit_choices_to={"role": "STUDENT"}
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "ward")

    @property
    def subtotal(self):
        return sum(item.product.price * item.quantity for item in self.items.all())

    
    @property
    def total_items(self):
        """
        Number of unique products in cart
        """
        return self.items.count()
    
    
    @property
    def total_quantity(self):
        return self.items.aggregate(
            total=Sum("quantity")
        )["total"] or 0

    
    @property
    def total_amount(self):
        return sum(item.subtotal for item in self.items.all())


    def __str__(self):
        return f"Cart - {self.user.username}"


# =========================
# CartItem
# =========================
class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("cart", "product")

    @property
    def subtotal(self):
        return self.product.price * self.quantity
    
    @property
    def total_amount(self):
        return sum(item.subtotal for item in self.items.all())




# =========================
# Order
# =========================
class Order(models.Model):
    STATUS = [
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("OVERRIDDEN", "Admin Override"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    ward = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="ward_orders",
        limit_choices_to={"role": "STUDENT"},
        help_text="The student this purchase is for"
    )
    reference = models.CharField(max_length=50, unique=True, editable=False)
    exam = models.ForeignKey(Exam, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS, default="PENDING")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_override = models.BooleanField(default=False, help_text="Admin manually approved this order")
    stock_deducted = models.BooleanField(default=False, help_text="Stock has been deducted for this order")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"MP-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.status}"

# =========================
# OrderItem
# =========================
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def subtotal(self):
        return self.price * self.quantity

    @property
    def total_amount(self):
        return sum(item.subtotal for item in self.items.all())
    
    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

# =========================
# Transaction
# =========================
class Transaction(models.Model):
    STATUS = (
        ("initialized", "Initialized"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("abandoned", "Abandoned"),
    )
    

    # Paystack's reference (from API response)
    gateway_reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Paystack's reference (T683902755095139)"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payer')
    ward = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="transaction")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    verified = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS, default="initialized")
    payload = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Use order.reference to avoid redundant internal_reference field
        return f"{self.status} {getattr(self.order, 'reference', '')} {self.gateway_reference}"
    


class PaymentTransaction(models.Model):
    """ Stores EVERY Paystack interaction. Webhook-safe, audit-safe. """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payment_transactions")
    gateway_reference = models.CharField(max_length=100, unique=True)
    gateway_name = models.CharField(max_length=20, default="paystack")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    verified = models.BooleanField(default=False)
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    
    def __str__(self):
        return self.gateway_reference

# =========================
# Log (optional)
# =========================
class MpayLog(models.Model):
    ACTIONS = [
        ("PAYMENT_INIT", "Payment Initialized"),
        ("PAYMENT_SUCCESS", "Payment Success"),
        ("PAYMENT_FAILED", "Payment Failed"),
        ("ADMIN_OVERRIDE", "Admin Override"),
        ("ORDER_CREATED", "Order Created"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTIONS)
    message = models.TextField()
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} @ {self.created_at}"


