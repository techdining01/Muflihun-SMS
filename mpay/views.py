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
    MpayLog,
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
from django.db.models import Sum, F
from django.db import transaction as db_transaction
import requests
from mpay.utils import get_or_create_cart
from mpay.forms import sync_product_categories_with_school_classes

User = get_user_model()

logger = logging.getLogger("system")


def _deduct_stock_from_order(order):
    """
    Atomically deduct stock for every item in the order.
    Uses select_for_update on Order to guarantee only one caller
    ever executes the deduction — the stock_deducted flag is the
    single source of truth checked inside the locked transaction.
    Returns list of deduction dicts, or [] if already deducted.
    """
    with db_transaction.atomic():
        # Lock the order row so concurrent webhook + callback can't both deduct
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.stock_deducted:
            return []  # already done — idempotent exit

        deductions = []
        items = locked_order.items.select_related("product").exclude(product__isnull=True)

        for item in items:
            product = item.product
            previous_stock = product.stock_quantity
            qty = item.quantity

            # Atomic decrement — never go below 0
            Product.objects.filter(pk=product.pk, stock_quantity__gte=qty).update(
                stock_quantity=F("stock_quantity") - qty
            )
            # If stock was less than qty, clamp to 0
            Product.objects.filter(pk=product.pk, stock_quantity__lt=0).update(
                stock_quantity=0
            )

            deductions.append({
                "product_id": str(product.pk),
                "product_name": product.name,
                "qty": qty,
                "previous_stock": previous_stock,
                "new_stock": max(0, previous_stock - qty),
            })

        # Mark deducted inside the same atomic block
        locked_order.stock_deducted = True
        locked_order.save(update_fields=["stock_deducted"])

    return deductions


@login_required
def select_ward(request):
    wards = User.objects.filter(parents=request.user, role="STUDENT")

    if request.method == "POST":
        ward_id = request.POST.get("ward_id")
        return redirect(f"/mpay/products/?ward={ward_id}")

    return render(request, "mpay/select_ward.html", {"wards": wards})


@login_required
def product_list(request):
    sync_product_categories_with_school_classes()
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
        "mpay/product_list.html",
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

    return render(request, "mpay/partials/cart_sidebar.html", {"cart": cart})


# @login_required
# def cart_count(request):
#     ward_id = request.GET.get("ward")
#     cart = Cart.objects.filter(user=request.user, ward_id=ward_id).first()
#     count = cart.items.count() if cart else 0
#     return JsonResponse({"count": count})


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
    logger = logging.getLogger("mpay")

    ward = get_object_or_404(User, id=ward_id, role="STUDENT")
    cart = get_or_create_cart(request.user, ward)

    if not cart.items.exists():
        messages.error(request, "Cart is empty")
        return redirect("mpay:products")

    total = sum(item.product.price * item.quantity for item in cart.items.all())

    with db_transaction.atomic():
        # Always create a fresh order
        order = Order.objects.create(
            buyer=request.user, ward=ward, total_amount=total, status="PENDING"
        )

        #  ALWAYS create order items
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

        MpayLog.objects.create(
            user=request.user,
            order=order,
            action="ORDER_CREATED",
            message="Order created from cart",
        )
        #  CLEAR CART AFTER SUCCESS
        cart.items.all().delete()

        return redirect("mpay:checkout_detail", order_id=order.id)


@login_required
def checkout_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, buyer=request.user, status="PENDING")

    items = order.items.all()

    return render(request, "mpay/checkout.html", {"order": order, "items": items})


logger = logging.getLogger("mpay")


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
            return redirect("mpay:checkout")

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
        return redirect("mpay:checkout_detail", order_id=order.id)


def _verify_and_update_transaction(reference):
    """
    Call Paystack's verify endpoint and update Transaction/Order if successful.
    Idempotent: safe to call multiple times. Returns the updated Transaction or None.
    """
    try:
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        res = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers=headers,
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        if not data.get("status"):
            return None

        tx = Transaction.objects.select_related("order").get(gateway_reference=reference)

        if data["data"].get("status") == "success" and not tx.verified:
            # First persist the Paystack verification payload
            tx.payload = data
            tx.save(update_fields=["payload"])

            # Centralized finalization (deducts stock, unlocks exams, clears cart, logs)
            finalized = handle_successful_transaction(tx)

            # Additional audit log specific to callback/polling verification path
            MpayLog.objects.create(
                user=tx.user,
                order=tx.order,
                action="PAYSTACK_VERIFY_SUCCESS",
                message="Paystack API verification confirmed success",
                metadata={
                    "gateway_reference": reference,
                    "was_already_finalized": finalized["was_already_finalized"],
                    "stock_deductions": finalized["stock_deductions"],
                    "exams_granted": finalized["exams_granted"],
                },
            )

        elif data["data"].get("status") == "failed" and tx.status != "failed":
            tx.status = "failed"
            tx.payload = data
            tx.save(update_fields=["status", "payload"])

            order = tx.order
            if order.status == "PENDING":
                order.status = "FAILED"
                order.save(update_fields=["status"])

            MpayLog.objects.create(
                user=tx.user,
                order=tx.order,
                action="PAYMENT_FAILED",
                message="Paystack payment failed via callback verification",
                metadata={"gateway_reference": reference},
            )

        return tx

    except Exception as e:
        logger.error(f"_verify_and_update_transaction failed for {reference}: {e}")
        return None


def paystack_callback(request):
    reference = request.GET.get("reference")
    trxref = request.GET.get("trxref")
    effective_ref = reference or trxref

    if not effective_ref:
        messages.error(request, "Invalid payment reference")
        return redirect("mpay:products")

    try:
        tx = Transaction.objects.select_related("order").get(gateway_reference=effective_ref)
    except Transaction.DoesNotExist:
        messages.error(request, "Transaction not found")
        return redirect("mpay:products")

    if not tx.verified:
        _verify_and_update_transaction(effective_ref)
        try:
            tx.refresh_from_db()
        except Exception:
            pass

    if tx.verified:
        messages.success(request, "Payment successful")
    elif tx.status == "failed":
        messages.error(request, "Payment failed. Please try again.")
    else:
        messages.info(request, "Payment received. Verification in progress.")

    return render(request, "mpay/payment_status.html", {"transaction": tx})


def payment_status_check(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"status": "unauthenticated", "verified": False, "login_required": True},
            status=401,
        )

    reference = request.GET.get("ref")
    if not reference:
        return JsonResponse({"status": "unknown", "verified": False})
    try:
        tx = Transaction.objects.select_related("order").get(
            gateway_reference=reference, user=request.user
        )
    except Transaction.DoesNotExist:
        return JsonResponse({"status": "unknown", "verified": False})

    if not tx.verified and tx.status not in ("failed", "abandoned"):
        _verify_and_update_transaction(reference)
        try:
            tx.refresh_from_db()
        except Exception:
            pass

    return JsonResponse({
        "status": tx.status,
        "verified": tx.verified,
        "order_id": str(tx.order_id),
    })


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

    #  Verify signature
    computed_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), payload, hashlib.sha512
    ).hexdigest()

    if signature != computed_signature:
        logger.error(" Invalid Paystack signature")
        return HttpResponse(status=400)

    data = json.loads(payload)
    event = data.get("event")
    reference = data.get("data", {}).get("reference")

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

        # Persist the raw webhook payload first
        transaction.payload = data
        transaction.save(update_fields=["payload"])

        # Centralized finalization (deducts stock, unlocks exams, clears cart, logs)
        finalized = handle_successful_transaction(transaction)

        # Additional audit log specific to the Paystack webhook event
        MpayLog.objects.create(
            user=transaction.user,
            order=transaction.order,
            action="PAYSTACK_WEBHOOK_SUCCESS",
            message="Paystack webhook charge.success received and processed",
            metadata={
                "gateway_reference": reference,
                "amount": data["data"].get("amount"),
                "was_already_finalized": finalized["was_already_finalized"],
                "stock_deductions": finalized["stock_deductions"],
                "exams_granted": finalized["exams_granted"],
            },
        )

        logger.info(f"Payment verified for order {transaction.order.reference}")

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


def unlock_cbt_from_order(order, actor=None):
    """
    Grants CBT access after successful MPay payment.
    Checks:
    1) order.exam (top-level exam link if set)
    2) item.product.exam FK if the Product has one
    Creates ExamAccess with required fields: student, exam, reason.
    """
    granted = []

    if order.exam_id:
        _, created = ExamAccess.objects.get_or_create(
            student=order.ward,
            exam=order.exam,
            defaults={
                "reason": f"Paid via order {order.reference}",
                "via_payment": True,
                "granted_by": actor,
            },
        )
        if created:
            granted.append(str(order.exam_id))

    items_with_product = order.items.select_related("product").exclude(product__isnull=True)
    for item in items_with_product:
        product_exam_id = getattr(item.product, "exam_id", None)
        if not product_exam_id:
            continue
        _, created = ExamAccess.objects.get_or_create(
            student=order.ward,
            exam_id=product_exam_id,
            defaults={
                "reason": f"Paid via order {order.reference} (product: {item.product_name})",
                "via_payment": True,
                "granted_by": actor,
            },
        )
        if created:
            granted.append(str(product_exam_id))

    return granted


def handle_successful_transaction(tx: Transaction):
    """
    Centralized finalization for ALL payment success paths.
    stock_deducted on Order is the sole idempotency guard for deduction.
    """
    order = tx.order
    was_already_finalized = tx.verified and tx.status == "success"

    # Always mark transaction verified (safe to repeat)
    tx.verified = True
    tx.status = "success"
    tx.save(update_fields=["verified", "status"])

    # Always update order status (safe to repeat)
    if not order.is_override and order.status != "PAID":
        order.status = "PAID"
        order.save(update_fields=["status"])

    # _deduct_stock_from_order is fully atomic + idempotent via stock_deducted flag
    # called unconditionally — it self-guards with select_for_update
    stock_deductions = _deduct_stock_from_order(order)
    exams_granted = unlock_cbt_from_order(order, actor=tx.user)

    # Always clear cart (idempotent)
    Cart.objects.filter(user=tx.user, ward=tx.ward).delete()

    if not was_already_finalized:
        MpayLog.objects.create(
            user=tx.user,
            order=order,
            action="PAYMENT_SUCCESS",
            message=(
                "Payment verified successfully (admin override)"
                if order.is_override
                else "Payment verified successfully"
            ),
            metadata={
                "reference": tx.gateway_reference or str(tx.pk),
                "amount": str(tx.amount),
                "stock_deductions": stock_deductions,
                "exams_granted": exams_granted,
            },
        )

    return {
        "stock_deductions": stock_deductions,
        "exams_granted": exams_granted,
        "was_already_finalized": was_already_finalized,
    }


def admin_override_order(order: Order, admin_user):
    if hasattr(order, "transaction"):
        raise ValueError("Order already has a transaction")

    # Leave verified=False / status=initialized so handle_successful_transaction()
    # will do the real work (idempotent finalization including stock deduction).
    tx = Transaction.objects.create(
        reference=f"ADMIN-{uuid.uuid4().hex[:10].upper()}",
        user=admin_user,
        ward=order.ward,
        order=order,
        amount=order.total_amount,
        verified=False,
        status="initialized",
        payload={"source": "admin_override"},
    )

    order.status = "OVERRIDDEN"
    order.is_override = True
    order.save(update_fields=["status", "is_override"])

    MpayLog.objects.create(
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
        "mpay/receipt.html",
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
        "mpay/admin/transactions.html",
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
        request, "mpay/store.html", {"products": products, "wards": wards}
    )


@login_required
def parent_orders(request):
    orders = Order.objects.filter(buyer=request.user).select_related(
        "ward", "transaction"
    ).order_by("-created_at")
    return render(request, "mpay/parent/orders.html", {"orders": orders})


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
    tx = get_object_or_404(Transaction.objects.select_related("order", "user", "ward"), id=tx_id)
    order = tx.order
    reference = tx.gateway_reference or order.reference

    if not request.user.is_staff and order.buyer_id != request.user.id:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You are not allowed to view this receipt.")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="receipt_{reference}.pdf"'

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
            f"<b>Transaction Ref:</b> {reference}<br/>"
            f"<b>Order Ref:</b> {order.reference}<br/>"
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

    table_data.append(["", "", "Grand Total", f"₦{order.total_amount}"])

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
    from django.core.paginator import Paginator
    qs = Transaction.objects.order_by("-created_at")
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "mpay/webhook_monitor.html", {"transactions": page_obj, "page_obj": page_obj})
