from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse
from datetime import timedelta
import csv
from django.http import HttpResponse
from django.contrib import messages
from .forms import LeaveTypeForm
from payroll.models import Payee, PayrollPeriod
from loans.models import LoanApplication
from .models import LeaveRequest, LeaveType
from .forms import LeaveRequestForm
from .services import has_overlapping_leave, calculate_leave_balance



@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:staff_dashboard")
@login_required
def admin_dashboard(request):
    pending_periods = PayrollPeriod.objects.filter(
        is_generated=True, is_approved_by_admin=False
    ).order_by("-year", "-month")

    pending_loans = LoanApplication.objects.filter(status="pending").order_by("-applied_at")
    pending_leaves = LeaveRequest.objects.filter(status="pending").order_by("-start_date")

    from django.db.models import Count
    # Analytics data for the chart
    leave_usage = LeaveRequest.objects.filter(status='approved').values('leave_type__name').annotate(count=Count('id'))
    chart_data = {item['leave_type__name']: item['count'] for item in leave_usage}

    context = {
        "pending_periods": Paginator(pending_periods, 5).get_page(
            request.GET.get("p_periods")
        ),
        "pending_loans": Paginator(pending_loans, 5).get_page(
            request.GET.get("p_loans")
        ),
        "pending_leaves": Paginator(pending_leaves, 5).get_page(
            request.GET.get("p_leaves")
        ),
        "data": chart_data,
    }
    return render(request, "leaves/admin/dashboard.html", context)



@login_required
def staff_dashboard(request):
    if request.user.role != "TEACHER":
        messages.error(request, "You do not have permission to access this page.")
        return redirect("leaves:admin_dashboard")

    try:
        payee = getattr(request.user, "payee", None)
    except AttributeError:
        messages.error(request, "Payee profile not found. Please complete your profile.")
        return redirect("leaves:staff_dashboard")
    try:
        leaves = LeaveRequest.objects.filter(payee=payee).order_by("-start_date")
    except LeaveRequest.DoesNotExist:
        messages.error(request, "No leave requests found.")
        return redirect("leaves:staff_dashboard")   
    
    approved_count = LeaveRequest.objects.filter(payee=payee, status="approved").count()
    balance = calculate_leave_balance(payee)

    context = {
        "leave_balance": balance,
        "leaves": Paginator(leaves, 5).get_page(
            request.GET.get("page")
        ),
        "approved_count": approved_count,
    }
    return render(request, "leaves/staff/dashboard.html", context)


@login_required
def leave_balance_view(request):
    year = timezone.now().year
    balances = []

    for lt in LeaveType.objects.all():
        balances.append({
            "type": lt,
            **calculate_leave_balance(request.user.payee, lt, year)
        })

    return render(
        request,
        "leaves/staff/leave_balance.html",
        {"balances": balances, "year": year}
    )


@login_required
def request_leave(request):
    try:
        payee = Payee.objects.get(user=request.user)
    except Payee.DoesNotExist:
        messages.error(request, "Payee profile not found. Please complete your profile.")
        return redirect("leaves:staff_dashboard")

    if request.method == "POST":
        form = LeaveRequestForm(request.POST)
        form.instance.payee = payee  # Assign BEFORE validation for model clean()
        if form.is_valid():
            start = form.cleaned_data["start_date"]
            end = form.cleaned_data["end_date"]

            if has_overlapping_leave(payee, start, end):
                messages.error(request, "You already have a leave in this period.")
                return redirect("leaves:request_leave")

            form.save()
            messages.success(request, "Leave request submitted.")
            return redirect("leaves:staff_dashboard")
    else:
        form = LeaveRequestForm()

    return render(request, "leaves/staff/leave_request.html", {"form": form})



@login_required
def dashboard_router(request):
    if request.user.role in ["ADMIN", "BURSAR"]:
        return redirect("dashboard:admin_dashboard")
    return redirect("dashboard:staff_dashboard")



@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:staff_dashboard")
@login_required
@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:admin_dashboard")
def approve_leave(request, leave_id):
    """Approve a leave request after checking balance."""
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    
    # Check if already processed
    if leave.status != "pending":
        messages.warning(request, f"This leave request is already {leave.status}.")
        return redirect("leaves:admin_dashboard")

    year = leave.start_date.year
    balance = calculate_leave_balance(
        leave.payee, leave.leave_type, year
    )

    if leave.duration() > balance["remaining"]:
        messages.warning(
            request,
            f"Leave approved with insufficient balance. Remaining: {balance['remaining']} days, Required: {leave.duration()} days"
        )
    else:
        messages.success(request, f"Leave approved for {leave.payee.user.get_full_name()}.")

    leave.status = "approved"
    leave.reviewed_by = request.user
    leave.reviewed_at = timezone.now()
    leave.save()

    return redirect("leaves:admin_dashboard")



@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:staff_dashboard")
@login_required
@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:admin_dashboard")
def reject_leave(request, leave_id):
    """Reject a leave request."""
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    
    # Check if already processed
    if leave.status != "pending":
        messages.warning(request, f"This leave request is already {leave.status}.")
        return redirect("leaves:admin_dashboard")

    leave.status = "rejected"
    leave.reviewed_by = request.user
    leave.reviewed_at = timezone.now()
    leave.save()

    messages.success(request, f"Leave rejected for {leave.payee.user.get_full_name()}.")
    return redirect("leaves:admin_dashboard")


@login_required
def leave_history(request):
    qs = LeaveRequest.objects.all().order_by("-start_date")

    if request.user.role not in ["ADMIN", "BURSAR"]:
        qs = qs.filter(payee__user=request.user)

    page = Paginator(qs, 10).get_page(request.GET.get("page"))

    return render(request, "leaves/leave_history.html", {"page": page})



@login_required
def leave_heatmap(request):
    leaves = LeaveRequest.objects.filter(status="approved")

    data = {}
    for l in leaves:
        day = l.start_date.strftime("%m-%Y")
        data[day] = data.get(day, 0) + l.duration()

    return render(
        request,
        "leaves/leave_heatmap.html",
        {"data": data}
    )


@login_required
def leave_calendar_feed(request):
    qs = LeaveRequest.objects.filter(status="approved")

    if request.user.role not in ["ADMIN", "BURSAR"]:
        qs = qs.filter(payee__user=request.user)

    data = [
        {
            "title": lr.payee.full_name,
            "start": lr.start_date.isoformat(),
            "end": lr.end_date.isoformat(),
        }
        for lr in qs
    ]

    return JsonResponse(data, safe=False)


from django.utils.timezone import now

@user_passes_test(lambda u: u.role == "ADMIN" or u.is_superuser, login_url="leaves:staff_dashboard")
@login_required
def leave_calendar(request):
    year = now().year
    leaves = LeaveRequest.objects.filter(
        start_date__year=year
    ).select_related("payee")

    return render(
        request,
        "leaves/leave_calendar.html",
        {"leaves": leaves}
    )


@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:staff_dashboard")
@login_required
def export_leave_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="leave_report.csv"'

    writer = csv.writer(response)
    writer.writerow(["Staff", "From", "To", "Days", "Status"])

    for l in LeaveRequest.objects.all():
        writer.writerow([
            l.payee, l.start_date, l.end_date, l.duration(), l.status
        ])

    return response


@user_passes_test(lambda u: u.role in ["ADMIN", "BURSAR"] or u.is_superuser, login_url="leaves:staff_dashboard")
def add_leave_type(request):
    if request.user.role not in ["ADMIN", "BURSAR"]:
        messages.error(request, "Permission denied")
       
   
    if request.method == "POST":
        form = LeaveTypeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Leave type created successfully.")
            return redirect("leaves:add_leave_type")
    else:
        form = LeaveTypeForm()
    return render(request, "leaves/admin/add_leave_type.html", {"form": form})
