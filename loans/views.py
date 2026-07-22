from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import JsonResponse, HttpResponse
from decimal import Decimal
import csv

from .models import LoanApplication
from .forms import LoanApplicationForm
from payroll.models import Payee



@login_required
def apply_for_loan(request):
    # Check if user has a Payee profile using the correct related_name
    try:
        payee = Payee.objects.get(user=request.user)
    except Payee.DoesNotExist:
        messages.error(request, "You need a staff profile (Payee) to apply for a loan.")
        return redirect("loans:staff_loan_dashboard")

    if request.method == "POST":
        form = LoanApplicationForm(request.POST)
        if form.is_valid():
            loan = form.save(commit=False)
            loan.payee = payee
            loan.status = "pending"
            loan.save()

            messages.success(request, "Loan application submitted successfully.")
            # Redirect admins back to admin dashboard, others to staff dashboard
            if request.user.role in ["ADMIN", "BURSAR"]:
                return redirect("loans:admin_loan_dashboard")
            return redirect("loans:staff_loan_dashboard")
    else:
        form = LoanApplicationForm()

    return render(request, "loans/staff/apply_loan.html", {"form": form})


@login_required
def admin_loan_dashboard(request):
    if request.user.role not in ["ADMIN", "BURSAR"]:
        messages.error(request, "Permission denied.")
        return redirect("payroll:staff_payroll_dashboard")

    loans_qs = LoanApplication.objects.order_by("-applied_at")
    
    # Pagination
    paginator = Paginator(loans_qs, 10)  # 10 loans per page
    page_number = request.GET.get("page")
    loans = paginator.get_page(page_number)

    # Chart Data
    total_loan = loans_qs.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    total_outstanding = loans_qs.aggregate(Sum('outstanding_balance'))['outstanding_balance__sum'] or 0
    total_approved = loans_qs.filter(status="approved").count()
    total_pending = loans_qs.filter(status="pending").count()

    context = {
        "loans": loans,
        "total_loan_amount": total_loan,
        "total_outstanding": total_outstanding,
        "total_approved": total_approved,
        "total_pending": total_pending,
    }

    return render(request, "loans/admin/loan_dashboard.html", context)


# AJAX endpoint for chart (optional)
@login_required
def admin_loan_chart_data(request):
    if request.user.role not in ["ADMIN", "BURSAR"]:
        return JsonResponse({"error": "Permission denied."}, status=403)

    data = LoanApplication.objects.values('status').annotate(total=Sum('loan_amount'))
    chart_data = {
        "labels": [d['status'].capitalize() for d in data],
        "data": [float(d['total']) for d in data],
    }
    return JsonResponse(chart_data)


@login_required
def admin_loan_detail(request, loan_id):
    loan = get_object_or_404(LoanApplication, id=loan_id)
    repayments = loan.repayments.order_by("-created_at")
    
    # Calculate progress for this loan
    loan.progress = 0
    if loan.loan_amount > 0:
        loan.progress = int((loan.loan_amount - loan.outstanding_balance) / loan.loan_amount * 100)
    
    total_paid = loan.loan_amount - loan.outstanding_balance
    
    return render(request, "loans/admin/loan_detail.html", {
        "loan": loan, 
        "repayments": repayments,
        "total_paid": total_paid
    })

@login_required
def approve_loan(request, loan_id):
    loan = get_object_or_404(LoanApplication, id=loan_id)
    if request.user.role not in ["ADMIN", "BURSAR"]:
        messages.error(request, "Permission denied.")
        return redirect("loans:admin_loan_detail", loan.id)
    
    try:
        loan.approve(request.user)
        messages.success(request, "Loan approved successfully.")
    except Exception as e:
        messages.error(request, str(e))
    
    return redirect("loans:admin_loan_detail", loan.id)

@login_required
def reject_loan(request, loan_id):
    loan = get_object_or_404(LoanApplication, id=loan_id)
    if request.user.role not in ["ADMIN", "BURSAR"]:
        messages.error(request, "Permission denied.")
        return redirect("loans:staff_loan_dashboard")
    
    try:
        loan.reject(request.user)
        messages.success(request, "Loan rejected successfully.")
    except Exception as e:
        messages.error(request, str(e))
    
    return redirect("loans:admin_loan_detail", loan.id)



@login_required
def staff_loan_dashboard(request):
    if request.user.role not in ['BURSAR', 'ADMIN', 'TEACHER', 'NON_TEACHER']:
        messages.error(request, "Permission denied.")
        return redirect("loans:staff_loan_dashboard")
    try:
        payee = Payee.objects.get(user=request.user)
        
    except Payee.DoesNotExist:
        messages.error(request, "No loans found.")
        

    loans_qs = LoanApplication.objects.filter(payee__user=request.user).order_by("-applied_at")

    paginator = Paginator(loans_qs, 5) 
    page_number = request.GET.get("page")
    loans = paginator.get_page(page_number)

    # Calculate progress percentage
    for loan in loans:
        loan.progress = 0
        if loan.loan_amount > 0:
            loan.progress = int((loan.loan_amount - loan.outstanding_balance) / loan.loan_amount * 100)

    return render(request, "loans/staff/loan_dashboard.html", {"loans": loans})


@login_required
def loan_list(request):
    if request.user.role not in ['STAFF', 'BURSAR', 'ADMIN', 'TEACHER']:
        messages.error(request, "Permission denied.")
        return redirect("loans:staff_loan_dashboard")
    loans = LoanApplication.objects.filter(payee__user=request.user).order_by("-applied_at")
    return render(request, "loans/staff/loan_dashboard.html", {"loans": loans})


@login_required
def export_loans(request):
    """Export all loans to CSV."""
    if request.user.role not in ["ADMIN", "BURSAR"]:
        messages.error(request, "Permission denied.")
        return redirect("loans:admin_loan_dashboard")
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="loans_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Loan ID',
        'Payee Name',
        'Email',
        'Loan Amount',
        'Outstanding Balance',
        'Status',
        'Monthly Deduction',
        'Tenure Months',
        'Applied Date',
        'Approved Date'
    ])
    
    # Fetch all loans
    loans = LoanApplication.objects.select_related('payee', 'payee__user').order_by('-applied_at')
    
    for loan in loans:
        writer.writerow([
            loan.id,
            loan.payee.user.get_full_name(),
            loan.payee.user.email,
            loan.loan_amount,
            loan.outstanding_balance,
            loan.status,
            loan.monthly_deduction,
            loan.tenure_months,
            loan.applied_at.strftime('%Y-%m-%d') if loan.applied_at else '',
            loan.approved_at.strftime('%Y-%m-%d') if loan.approved_at else ''
        ])
    
    return response
