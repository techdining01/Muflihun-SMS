
from .models import Cart

def get_or_create_cart(user, ward):
    cart, _ = Cart.objects.get_or_create(
        user=user,
        ward=ward
    )
    return cart
