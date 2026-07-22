import os
import uuid
import json
import hmac
import hashlib
import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from exams.models import ExamAccess
from .models import (
    Product,
    Cart,
    CartItem,
    Order,
    Transaction,
    PaymentTransaction,
    OrderItem,
    BrillsPayLog,
)
from django.contrib import messages
from django.contrib.auth import get_user_model
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.db import transaction as db_transaction
import requests
from brillspay.utils import get_or_create_cart

User = get_user_model()

logger = logging.getLogger("system")


@login_required
def select_ward(request):
    wards = User.objects.filter(parents=request.user, role="STUDENT")

    if request.method == "POST":
        ward_id = request.POST.get("ward_id")
        return redirect(f"/brillspay/products/?ward={ward_id}")

    return render(request, "brillspay/select_ward.html", {"wards": wards})


@login_required
def product_list(request):
    ward_id = request.GET.get("ward")
    if not ward_id:
        return HttpResponse(
            "You must have registered child/children whom you buy for, contact admin for more"
        )
    ward = get_object_or_404(User, id=ward_id, role="STUDENT")
    cart = get_or_create_cart(request.user, ward)

    # If ward has a class, try to filter by category class_name
    if ward.student_class:
        products = Product.objects.filter(
            category__class_name=ward.student_class.name, is_active=True
        )
    else:
        products = Product.objects.none()

    cart_product_ids = set(cart.items.values_list("product_id", flat=True))

    return render(
        request,
        "brillspay/product_list.html",
        {
            "products": products,
            "ward": ward,
            "cart_product_ids": cart_product_ids,
            "cart": cart,
        },
    )


def get_cart(user, ward_id):
    cart, _ = Cart.objects.get_or_create(user=user, ward_id=ward_id)
    return cart


@login_required
def add_to_cart(request):
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        ward_id = request.POST.get("ward_id")

        product = get_object_or_404(Product, id=product_id)
        cart = get_cart(request.user, ward_id)

        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, defaults={"quantity": 1}
        )

        if not created:
            item.quantity += 1
            item.save()

        return JsonResponse({"success": True, "count": cart.items.count()})


@login_required
def update_cart_item(request):
    if request.method == "POST":
        item_id = request.POST.get("item_id")
        action = request.POST.get("action")

        item = get_object_or_404(CartItem, id=item_id)

        if action == "inc":
            item.quantity += 1
        elif action == "dec":
            item.quantity -= 1
            if item.quantity <= 0:
                item.delete()
                return JsonResponse({"removed": True})

        item.save()
        return JsonResponse({"qty": item.quantity})


@login_required
def remove_cart_item(request):
    item_id = request.POST.get("item_id")

    try:
        item = CartItem.objects.select_related("cart").get(
            id=item_id, cart__user=request.user
        )
        cart = item.cart
        product_name = item.product.name

        item.delete()

        logger.info(
            "CART ITEM REMOVED | user=%s | product=%s | ward=%s",
            request.user.id,
            product_name,
            cart.ward_id,
        )

        return JsonResponse({"status": "removed"})

    except CartItem.DoesNotExist:
        return JsonResponse({"status": "error"}, status=400)


@login_required
def clear_cart(request):
    ward_id = request.POST.get("ward_id")

    cart = Cart.objects.filter(user=request.user, ward_id=ward_id).first()

    if cart:
        cart.items.all().delete()

        logger.warning("CART CLEARED | user=%s | ward=%s", request.user.id, ward_id)

    return JsonResponse({"status": "cleared"})


@login_required
def cart_sidebar(request):
    ward_id = request.GET.get("ward")
    cart = Cart.objects.filter(user=request.user, ward_id=ward_id).first()

    return render(request, "brillspay/partials/cart_sidebar.html", {"cart": cart})


@login_required
def cart_count(request):
    ward_id = request.GET.get("ward")
    cart = Cart.objects.filter(user=request.user, ward_id=ward_id).first()
    count = cart.items.count() if cart else 0
    return JsonResponse({"count": count})


@login_required
def cart_count(request):
    ward_id = request.GET.get("ward")

    if not ward_id or ward_id in ("null", "undefined"):
        return JsonResponse({"count": 0})

    try:
        cart = Cart.objects.filter(user=request.user, ward_id=ward_id).first()
    except (ValueError, TypeError):
        return JsonResponse({"count": 0})

    return JsonResponse({"count": cart.total_items if cart else 0})


@login_required
@require_POST
def checkout(request):
    ward_id = request.POST.get("ward_id")
    logger = logging.getLogger("brillspay")

    ward = get_object_or_404(User, id=ward_id, role="STUDENT")
    cart = get_or_create_cart(request.user, ward)

    if not cart.items.exists():
        messages.error(request, "Cart is empty")
        return redirect("brillspay:brillspay_products")

    total = sum(item.product.price * item.quantity for item in cart.items.all())

    with db_transaction.atomic():
        # Always create a fresh order
        order = Order.objects.create(
            buyer=request.user, ward=ward, total_amount=total, status="PENDING"
        )

        # 🔥 ALWAYS create order items
        for item in cart.items.select_related("product"):
            OrderItem.objects.create(
                order=order,
                product=item.product,
                product_name=item.product.name,
                price=item.product.price,
                quantity=item.quantity,
            )

        # Create transaction
        transaction_obj = Transaction.objects.create(
            order=order,
            user=request.user,
            ward=ward,
            amount=total,
            status="initialized",
        )

        # LOG
        logger.info(
            "CHECKOUT_CREATED | user=%s ward=%s order=%s amount=%s",
            request.user.id,
            ward.id,
            order.id,
            total,
        )

        BrillsPayLog.objects.create(
            user=request.user,
            order=order,
            action="ORDER_CREATED",
            message="Order created from cart",
        )
        # 🔥 CLEAR CART AFTER SUCCESS
        cart.items.all().delete()

    return redirect("brillspay:checkout_detail", order_id=order.id)


# @login_required
# @require_POST
# def checkout(request):
#     ward_id = request.POST.get("ward_id")
#     logger = logging.getLogger("brillspay")

#     try:
#         ward = get_object_or_404(User, id=ward_id, role="STUDENT")
#     except (ValueError, User.DoesNotExist):
#         logger.exception("Failed to resolve ward in checkout; ward_id=%r POST=%r", ward_id, dict(request.POST))
#         messages.error(request, "Invalid ward selected. Please re-select ward and try again.")
#         return redirect("brillspay:brillspay_products")

#     cart = get_or_create_cart(request.user, ward)
#     if not cart or not cart.items.exists():
#         messages.error(request, "Cart is empty")
#         return redirect("brillspay:brillspay_products")

#     total = sum(item.product.price * item.quantity for item in cart.items.all())

#     try:
#         with db_transaction.atomic():
#             order, created = Order.objects.get_or_create(
#                 buyer=request.user,
#                 ward=ward,
#                 status="PENDING",
#                 defaults={"total_amount": total}
#             )

#             # Ensure server-side total correctness
#             if order.total_amount != total:
#                 order.total_amount = total
#                 order.save(update_fields=["total_amount"])

#             # Create order items if the order was just created
#             if created:
#                 for item in cart.items.all():
#                     OrderItem.objects.create(
#                         order=order,
#                         product_name=item.product.name,
#                         price=item.product.price,
#                         quantity=item.quantity,
#                     )

#             # Create transaction (no internal_reference field — use order.reference when needed)
#             trans_defaults = {
#                 "user": request.user,
#                 "ward": ward,
#                 "amount": total,
#                 "status": "initialized",
#             }

#             transaction_obj, t_created = Transaction.objects.get_or_create(
#                 order=order,
#                 defaults=trans_defaults
#             )

#             BrillsPayLog.objects.create(
#                 user=request.user,
#                 order=order,
#                 action="ORDER_CREATED",
#                 message="Order created from cart"
#             )

#     except (IntegrityError, OperationalError) as e:
#         logger.exception("checkout DB error: %s; user=%s ward=%s", e, request.user.id, getattr(ward, "id", None))
#         if isinstance(e, OperationalError) and 'no such column' in str(e):
#             messages.error(request, "Database schema mismatch detected for BrillsPay. Please run `py manage.py migrate` to apply pending migrations.")
#         else:
#             messages.error(request, "Unable to create order/transaction. Please contact support.")
#         return redirect("brillspay:brillspay_products")

#     return redirect("brillspay:checkout_detail", order_id=order.id)


@login_required
def checkout_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user, status="PENDING")

    items = order.items.all()

    return render(request, "brillspay/checkout.html", {"order": order, "items": items})


# @login_required
# def checkout_detail(request, order_id):
#     order = get_object_or_404(
#         Order,
#         id=order_id,
#         buyer=request.user,
#         status="PENDING"
#     )

#     # attach images to order items when possible (best-effort lookup by product name)
#     items = []
#     for item in order.items.all():
#         product = Product.objects.filter(name=item.product_name).first()
#         image_url = product.image.url if product and getattr(product, 'image', None) else None
#         items.append({"item": item, "image_url": image_url})

#     return render(request, "brillspay/checkout.html", {
#         "order": order,
#         "transaction": order.transaction,
#         "items": items
#     })


logger = logging.getLogger("brillspay")


def csrf_failure(request, reason=""):
    logger.warning(
        "CSRF failure: reason=%s cookies=%s headers=%s POST=%s",
        reason,
        request.COOKIES,
        {k: request.META.get(k) for k in ["HTTP_REFERER"]},
        dict(request.POST),
    )
    return HttpResponse("CSRF failure (logged)", status=403)


@login_required
def paystack_initialize(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user, status="PENDING")

    transaction = order.transaction

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    # Use order.reference as the internal reference (no separate model field)
    payload = {
        "email": request.user.email,
        "amount": int(order.total_amount * 100),
        "callback_url": settings.PAYSTACK_CALLBACK_URL,
        "metadata": {
            "order_id": str(order.id),
            "ward_id": str(order.ward.id),
            "user_id": str(request.user.id),
            "internal_reference": str(order.reference),
        },
    }

    try:
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("status"):
            messages.error(request, "Unable to initialize payment.")
            return redirect("brillspay:checkout")

        # Get Paystack's reference
        paystack_ref = data["data"]["reference"]

        # Update Transaction with gateway reference
        transaction.gateway_reference = paystack_ref
        transaction.save(update_fields=["gateway_reference"])

        # Create PaymentTransaction record for audit
        PaymentTransaction.objects.create(
            order=order,
            gateway_reference=paystack_ref,
            amount=order.total_amount,
            verified=False,
            raw_response=data,
        )

        return redirect(data["data"]["authorization_url"])

    except requests.RequestException as e:
        logger.error(f"Paystack initialization failed: {str(e)}")
        messages.error(request, "Payment service unavailable. Please try again.")
        return redirect("brillspay:checkout")


def paystack_callback(request):
    reference = request.GET.get("reference")

    if not reference:
        messages.error(request, "Invalid payment reference")
        return redirect("brillspay:brillspay_products")

    # The 'reference' param from Paystack is the gateway reference; look up by gateway_reference
    tx = get_object_or_404(Transaction, gateway_reference=reference)

    # Do NOT trust browser redirect for verification
    # Webhook will confirm payment later

    if tx.verified:
        messages.success(request, "Payment successful")
    else:
        messages.info(request, "Payment received. Verification in progress.")

    return render(request, "brillspay/payment_status.html", {"transaction": tx})


@login_required
def payment_status_check(request):
    reference = request.GET.get("ref")
    try:
        tx = Transaction.objects.get(gateway_reference=reference, user=request.user)
        return JsonResponse({"status": tx.status, "verified": tx.verified})
    except Transaction.DoesNotExist:
        return JsonResponse({"status": "unknown", "verified": False})


import json
import hmac
import hashlib
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction as db_transaction

from .models import (
    Transaction,
    PaymentTransaction,
    Cart,
    BrillsPayLog,
)
from exams.models import ExamAccess


@csrf_exempt
def paystack_webhook(request):
    logger.info("Paystack webhook received")

    if request.method != "POST":
        logger.warning(" Webhook called with non-POST")
        return HttpResponse(status=405)

    payload = request.body
    signature = request.headers.get("x-paystack-signature")

    if not signature:
        logger.error(" Missing Paystack signature")
        return HttpResponse(status=400)

    # 🔐 Verify signature
    computed_signature = hmac.new(
        key=settings.PAYSTACK_SECRET_KEY.encode(), msg=payload, digestmod=hashlib.sha512
    ).hexdigest()

    if signature != computed_signature:
        logger.error(" Invalid Paystack signature")
        return HttpResponse(status=400)

    data = json.loads(payload)
    event = data.get("event")
    reference = data.get("data", {}).get("reference")

    logger.info(f"Event: {event}")
    logger.info(f"Reference: {reference}")

    logger.info(f"Event: {event}")
    logger.info(f"Reference: {reference}")

    # ==========================
    # HANDLE CHARGE (Payments)
    # ==========================
    if event == "charge.success":
        try:
            transaction = Transaction.objects.select_related("order").get(
                gateway_reference=reference
            )
        except Transaction.DoesNotExist:
            logger.error(f" Transaction not found for ref {reference}")
            return HttpResponse(status=200)

        if transaction.verified:
            logger.info("Transaction already verified")
            return HttpResponse(status=200)

        # ✅ Mark transaction successful
        transaction.status = "success"
        transaction.verified = True
        transaction.payload = data
        transaction.save(update_fields=["status", "verified", "payload"])

        # ---- STEP 5: UPDATE ORDER ----
        order = transaction.order
        order.status = "PAID"
        order.save(update_fields=["status"])

        # ---- STEP 6: AUTO-UNLOCK CBT / EXAM ----
        if order.exam:
            ExamAccess.objects.get_or_create(
                student=order.ward, exam=order.exam, defaults={"via_payment": True}
            )

        # ---- STEP 7: CLEAR CART ----
        Cart.objects.filter(user=transaction.user, ward=transaction.ward).delete()

        BrillsPayLog.objects.create(
            user=transaction.user,
            order=order,
            action="PAYMENT_SUCCESS",
            message="Paystack payment confirmed via webhook",
            metadata={"gateway_reference": reference, "amount": data["data"]["amount"]},
        )

        logger.info(f"Payment verified for order {order.reference}")

    # ==========================
    # HANDLE TRANSFERS (Payroll)
    # ==========================
    elif event == "transfer.success":
        from payroll.models import PaymentTransaction as PayrollTx

        try:
            # Paystack sends the transfer-reference.
            # Our PayrollTx stores the 'paystack_reference' (which is the transfer code or transfer-reference?)
            # In initiate_transfer, we stored data["data"]["reference"] into tx.paystack_reference
            # In transfer.success webhook, data["data"]["reference"] is the same reference.

            tx = PayrollTx.objects.get(paystack_reference=reference)
            tx.status = "success"
            tx.save()
            logger.info(f"Payroll Transfer success for {reference}")

        except PayrollTx.DoesNotExist:
            logger.warning(f"Payroll Transaction not found for ref {reference}")

    elif event == "transfer.failed" or event == "transfer.reversed":
        from payroll.models import PaymentTransaction as PayrollTx

        try:
            tx = PayrollTx.objects.get(paystack_reference=reference)
            tx.status = "failed"
            tx.failure_reason = data.get("data", {}).get("reason", "Transfer Failed")
            tx.save()
            logger.warning(
                f"Payroll Transfer failed for {reference}: {tx.failure_reason}"
            )

        except PayrollTx.DoesNotExist:
            logger.warning(f"Payroll Transaction not found for ref {reference}")

    return HttpResponse(status=200)


@login_required
def verify_payment(request, reference):
    tx = get_object_or_404(Transaction, reference=reference)

    res = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
    )

    data = res.json()["data"]

    if data["status"] == "success":
        tx.status = "success"
        tx.payload = data
        tx.save()

    else:
        tx.status = "failed"
        tx.save()

    return JsonResponse({"status": tx.status})


def unlock_cbt_from_order(order):
    """
    Grants CBT access after successful BrillsPay payment.
    """
    for item in order.items.all():
        ExamAccess.objects.get_or_create(
            student=order.ward,
            exam_name=item.product_name,
            defaults={"via_payment": True},
        )


def handle_successful_transaction(tx: Transaction):
    """
    Finalizes transaction and order.
    """
    if tx.verified and tx.status == "success":
        return

    tx.verified = True
    tx.status = "success"
    tx.save(update_fields=["verified", "status"])

    order = tx.order
    order.status = "PAID"
    order.save(update_fields=["status"])

    unlock_cbt_from_order(order)

    BrillsPayLog.objects.create(
        user=tx.user,
        order=order,
        action="PAYMENT_SUCCESS",
        message="Payment verified successfully",
        metadata={"reference": tx.reference, "amount": str(tx.amount)},
    )


def admin_override_order(order: Order, admin_user):
    if hasattr(order, "transaction"):
        raise ValueError("Order already has a transaction")

    tx = Transaction.objects.create(
        reference=f"ADMIN-{uuid.uuid4().hex[:10].upper()}",
        user=admin_user,
        ward=order.ward,
        order=order,
        amount=order.total_amount,
        verified=True,
        status="success",
        payload={"source": "admin_override"},
    )

    order.status = "OVERRIDDEN"
    order.is_override = True
    order.save(update_fields=["status", "is_override"])

    BrillsPayLog.objects.create(
        user=admin_user,
        order=order,
        action="ADMIN_OVERRIDE",
        message="Order approved via admin override",
        metadata={"reference": tx.reference},
    )

    handle_successful_transaction(tx)


@login_required
def receipt_view(request, reference):
    tx = get_object_or_404(Transaction, reference=reference, user=request.user)

    return render(
        request,
        "brillspay/receipt.html",
        {
            "transaction": tx,
            "order": tx.order,
        },
    )


def unlock_exams_for_order(order, actor):
    """
    Unlocks CBT access after successful payment.
    """
    for item in order.items.all():
        exams = getattr(item, "exams", None)

        if not exams:
            continue

        for exam in exams.all():
            ExamAccess.objects.get_or_create(
                student=order.ward,
                exam=exam,
                defaults={
                    "via_payment": True,
                    "granted_by": actor,
                },
            )


@staff_member_required
def admin_transaction_dashboard(request):
    qs = Transaction.objects.select_related("user", "ward", "order").order_by(
        "-created_at"
    )

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    total_revenue = (
        qs.filter(verified=True, status="success").aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )

    return render(
        request,
        "brillspay/admin/transactions.html",
        {
            "transactions": qs,
            "total_revenue": total_revenue,
        },
    )


@login_required
def store_view(request):
    products = Product.objects.filter(is_active=True, stock_quantity__gt=0)
    wards = request.user.children.filter(role="STUDENT")  # adjust if needed

    return render(
        request, "brillspay/store.html", {"products": products, "wards": wards}
    )


@login_required
def parent_orders(request):
    orders = Order.objects.filter(buyer=request.user)
    return render(request, "brillspay/parent/orders.html", {"orders": orders})


class WatermarkCanvas(canvas.Canvas):
    def draw_watermark(self):
        self.saveState()
        self.setFont("Helvetica-Bold", 60)
        self.setFillColorRGB(0.85, 0.85, 0.85)
        self.translate(300, 400)
        self.rotate(45)
        self.drawCentredString(0, 0, settings.RECEIPT_WATERMARK)
        self.restoreState()

    def showPage(self):
        self.draw_watermark()
        super().showPage()

    def save(self):
        self.draw_watermark()
        super().save()


@login_required
def payment_receipt_pdf(request, tx_id):
    tx = get_object_or_404(PaymentTransaction, id=tx_id)
    order = tx.order

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="receipt_{tx.reference}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Logo
    if os.path.exists(settings.SCHOOL_LOGO_PATH):
        elements.append(Image(settings.SCHOOL_LOGO_PATH, width=80, height=80))

    elements.append(Paragraph(f"<b>{settings.SCHOOL_NAME}</b>", styles["Title"]))

    elements.append(
        Paragraph("<br/><b>PAYMENT RECEIPT</b><br/><br/>", styles["Normal"])
    )

    elements.append(
        Paragraph(
            f"<b>Transaction Ref:</b> {tx.reference}<br/>"
            f"<b>Paid By:</b> {tx.user.get_full_name()}<br/>"
            f"<b>Ward:</b> {order.ward.get_full_name()}<br/>"
            f"<b>Date:</b> {tx.created_at.strftime('%d %b %Y %H:%M')}<br/><br/>",
            styles["Normal"],
        )
    )

    # Items Table
    table_data = [["Item", "Qty", "Unit Price", "Total"]]

    for item in order.items.all():
        table_data.append(
            [
                item.product.name,
                item.quantity,
                f"₦{item.price}",
                f"₦{item.price * item.quantity}",
            ]
        )

    table_data.append(["", "", "Grand Total", f"₦{order.amount}"])

    table = Table(table_data, colWidths=[200, 60, 100, 100])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )

    elements.append(table)

    elements.append(
        Paragraph(
            "<br/>Thank you for your payment.<br/>This receipt is system-generated.",
            styles["Italic"],
        )
    )

    doc.build(elements, canvasmaker=WatermarkCanvas)
    return response


@staff_member_required
def webhook_monitor(request):
    txs = Transaction.objects.order_by("-created_at")[:20]
    return render(request, "brillspay/webhook_monitor.html", {"transactions": txs})
