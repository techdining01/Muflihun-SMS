@login_required
def init_paystack(request):
    cart = get_active_cart(request.user)

    if not cart or not cart.items.exists():
        return JsonResponse({"error": "Cart empty"}, status=400)

    reference = uuid.uuid4().hex

    tx = Transaction.objects.create(
        reference=reference,
        user=request.user,
        ward=cart.ward,
        amount=cart.total,
        payload={}
    )

    return JsonResponse({
        "reference": reference,
        "email": request.user.email,
        "amount": int(tx.amount * 100),
        "key": settings.PAYSTACK_PUBLIC_KEY,
    })
