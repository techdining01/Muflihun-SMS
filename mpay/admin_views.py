from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from .models import Order, Transaction, Product, MpayLog, PaymentTransaction
from exams.models import ExamAccess, SchoolClass, Exam
from django.db.models import Sum
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.db.models.functions import TruncMonth
from django.utils.timezone import now
from .forms import ProductForm, sync_product_categories_with_school_classes
from django.utils import timezone
from datetime import timedelta
from django.http import HttpResponse
from django.core.paginator import Paginator
import csv

User = get_user_model()

def is_admin(user):
    return user.is_authenticated and user.role == "ADMIN"



@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):

    # ✅ correct status value
    total_sales = Transaction.objects.filter(
        status="success", verified=True
    ).aggregate(total=Sum("amount"))["total"] or 0

    total_orders = Order.objects.count()
    total_transactions = Transaction.objects.count()
    total_products = Product.objects.count()

    recent_orders = Order.objects.select_related(
        "buyer", "ward"
    ).order_by("-created_at")[:5]

    # ===== Monthly Revenue =====
    monthly_qs = (
        Transaction.objects
        .filter(status="success", verified=True)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    monthly_labels = [
        m["month"].strftime("%b %Y") for m in monthly_qs
    ]
    monthly_data = [
        float(m["total"]) for m in monthly_qs
    ]

    # ===== Class-based Revenue =====
    class_qs = (
        Order.objects
        .filter(status="PAID")
        .values("ward__student_class__name")
        .annotate(total=Sum("total_amount"))
    )

    class_labels = [
        c["ward__student_class__name"] or "Unknown"
        for c in class_qs
    ]
    class_data = [
        float(c["total"]) for c in class_qs
    ]

    return render(
        request,
        "mpay/admin/dashboard.html",
        {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "total_transactions": total_transactions,
            "total_products": total_products,
            "recent_orders": recent_orders,

            # charts
            "monthly_labels": monthly_labels,
            "monthly_data": monthly_data,
            "class_labels": class_labels,
            "class_data": class_data,
        }
    )



@staff_member_required
def admin_add_product(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("mpay:admin_product_list")
    else:
        form = ProductForm()

    return render(request,
        "mpay/admin/products/add.html", {"form": form}
    )


@staff_member_required
def admin_product_list(request):
    sync_product_categories_with_school_classes()
    products_qs = Product.objects.select_related("category").order_by("-created_at")
    paginator = Paginator(products_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "mpay/admin/products/product_list.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
        }
    )


@staff_member_required
def admin_product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            return redirect("mpay:admin_product_list")
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "mpay/admin/products/product_edit.html",
        {
            "form": form,
            "product": product
        }
    )



@staff_member_required
def admin_product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == "POST":
        product.delete()
        messages.success(request, f'{product.name} deleted successfully')
        return redirect("mpay:admin_product_list")

    return render(
        request,
        "mpay/admin/products/product_confirm_delete.html",
        {
            "product": product
        }
    )

@staff_member_required
def admin_order_list(request):
    from school_sms.views import mark_seen
    mark_seen(request, 'pending_orders')
    orders_qs = Order.objects.select_related("buyer", "ward").order_by("-created_at")
    paginator = Paginator(orders_qs, 8)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "mpay/admin/orders/list.html",
        {
            "orders": page_obj,
            "page_obj": page_obj,
        }
    )


@staff_member_required
def admin_order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    return render(request, "mpay/admin/orders/detail.html", {
        "order": order
    })


@staff_member_required
def admin_payment_list(request):
    transactions = Transaction.objects.all().order_by('-created_at')
    return render(request, "mpay/admin/payments/list.html", {
        "transactions": transactions
    })


@staff_member_required
def admin_transaction_logs(request):
    logs = MpayLog.objects.select_related("user", "order").order_by('-created_at')
    return render(request, "mpay/admin/logs/list.html", {
        "logs": logs
    })


@login_required
@user_passes_test(is_admin)
def admin_access_list(request):
    accesses_qs = ExamAccess.objects.select_related(
        "student", "exam"
    ).order_by("-granted_at")

    paginator = Paginator(accesses_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "mpay/admin/access_list.html",
        {
            "accesses": page_obj,
            "page_obj": page_obj,
        }
    )


@login_required
@user_passes_test(is_admin)
def admin_payment_detail(request, tx_id):
    tx = get_object_or_404(
        PaymentTransaction.objects.select_related(
            "order", "user"
        ).prefetch_related(
            "order__items__product"
        ),
        id=tx_id
    )

    return render(
        request,
        "mpay/admin/payment_detail.html",
        {"tx": tx}
    )



@login_required
@user_passes_test(is_admin)
def admin_revoke_access(request, access_id):
    access = get_object_or_404(ExamAccess, id=access_id)

    access.delete()

    messages.success(
        request,
        f"Access revoked for {access.student.get_full_name()}"
    )

    return redirect("mpay:admin_access_list")   


@login_required
@user_passes_test(is_admin)
def admin_mercy_access(request):
    classes = SchoolClass.objects.all().order_by("name")
    selected_class_id = request.GET.get("class")
    selected_class = None
    students = []
    exams = []
    access_pairs = []

    if selected_class_id:
        try:
            selected_class = SchoolClass.objects.get(id=selected_class_id)
        except SchoolClass.DoesNotExist:
            selected_class = None

    if selected_class:
        students = (
            User.objects
            .filter(role=User.Role.STUDENT, student_class=selected_class)
            .order_by("last_name", "first_name")
        )
        exams = (
            Exam.objects
            .filter(
                school_class=selected_class,
                is_active=True,
                is_published=True
            )
            .order_by("start_time")
        )

        accesses = ExamAccess.objects.filter(
            exam__in=exams,
            student__in=students
        )

        for access in accesses:
            key = f"{access.student_id}|{access.exam_id}"
            access_pairs.append(key)

    if request.method == "POST" and selected_class:
        student_id = request.POST.get("student_id")
        exam_id = request.POST.get("exam_id")
        action = request.POST.get("action")

        student = get_object_or_404(
            User,
            id=student_id,
            role=User.Role.STUDENT,
            student_class=selected_class
        )
        exam = get_object_or_404(
            Exam,
            id=exam_id,
            school_class=selected_class
        )

        if action == "grant":
            ExamAccess.objects.get_or_create(
                student=student,
                exam=exam,
                defaults={
                    "granted_by": request.user,
                    "reason": "Mercy access from Mpay admin",
                },
            )
            messages.success(
                request,
                f"Access granted for {student.get_full_name()} → {exam.title}",
            )
        elif action == "revoke":
            ExamAccess.objects.filter(
                student=student,
                exam=exam
            ).delete()
            messages.success(
                request,
                f"Access revoked for {student.get_full_name()} → {exam.title}",
            )

        return redirect(f"{request.path}?class={selected_class.id}")

    return render(
        request,
        "mpay/admin/mercy_access.html",
        {
            "classes": classes,
            "selected_class": selected_class,
            "students": students,
            "exams": exams,
            "access_pairs": access_pairs,
        },
    )



@staff_member_required
def admin_grant_access(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    # Example: Exam unlock
    ExamAccess.objects.get_or_create(
        student=order.ward,
        exam=order.exam,
        defaults={"granted_by": request.user}
    )

    order.status = "FULFILLED"
    order.save()
    MpayLog.objects.create(
        user=request.user,
        order=order,
        action="ADMIN_OVERRIDE",
        message="Access granted manually"
    )

    messages.success(request, "Access granted")
    return redirect("mpay:admin_order_detail", pk=order.id)



@staff_member_required
def admin_analytics_dashboard(request):
    range_days = int(request.GET.get("range", 7))
    start_date = timezone.now().date() - timedelta(days=range_days)

    qs = (
        Transaction.objects
        .filter(
            status="success",
            verified=True,
            created_at__date__gte=start_date
        )
        .values("created_at__date")
        .annotate(total=Sum("amount"))
        .order_by("created_at__date")
    )

    labels = [str(x["created_at__date"]) for x in qs]
    data = [float(x["total"]) for x in qs]

    total_revenue = sum(data)
    return render(request, "mpay/admin/analytics.html", {
        "labels": labels,
        "data": data,
        "total_revenue": total_revenue,
        "range_days": range_days,
    })


@staff_member_required
def export_revenue_csv(request):
    qs = (
        Transaction.objects
        .filter(status="success", verified=True)
        .values("created_at__date")
        .annotate(total=Sum("amount"))
        .order_by("created_at__date")
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="revenue_report.csv"'

    writer = csv.writer(response)
    writer.writerow(["Date", "Revenue (₦)"])

    for row in qs:
        writer.writerow([row["created_at__date"], row["total"]])

    return response

