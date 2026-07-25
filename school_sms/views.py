from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from exams.models import Exam, ExamAttempt
from django.utils import timezone
from mpay.models import Transaction, Order
from pickup.models import PickupAuthorization
from django.db.models import Sum, Q
from exams.models import ChatMessage
from loans.models import LoanApplication
from payroll.models import PayrollPeriod
from leaves.models import LeaveRequest


User = get_user_model()

def is_admin(user):
    return user.is_authenticated and user.role == User.Role.ADMIN


def landing_page(request):
    # if request.user.is_authenticated:
    #     return redirect('accounts:dashboard_redirect')
    return render(request, 'exams/landing.html')


def cbt_exam(request):
    return render(request, 'exams/cbt_home.html')


def about_page(request):
    return render(request, 'exams/about.html')

@login_required(login_url='accounts:login')
@user_passes_test(is_admin)
def admin_grand_dashboard(request):
    # ==========================
    # USERS
    # ==========================
    total_users = User.objects.count()
    pending_users = User.objects.filter(is_approved=False).count()
    students = User.objects.filter(role=User.Role.STUDENT).count()
    parents = User.objects.filter(role=User.Role.PARENT).count()
    staff = User.objects.filter(role=User.Role.TEACHER).count()

    # ==========================
    # EXAMS
    # ==========================
    total_exams = Exam.objects.count()
    active_exams = Exam.objects.filter(
        is_active=True,
        start_time__lte=timezone.now(),
        end_time__gte=timezone.now()
    ).count()
    attempts_today = ExamAttempt.objects.filter(
        started_at__date=timezone.now().date()
    ).count()

    # ==========================
    # PAYMENTS
    # ==========================
    total_revenue = Transaction.objects.filter(
        verified=True,
    ).aggregate(total=Sum("amount"))["total"] or 0

    pending_orders = Order.objects.filter(status="pending").count()

    # ==========================
    # CHAT
    # ==========================

    """Chat conversation with a specific user"""
    user = request.user

    # Restrict to Admin and Teacher only
    if user.role not in [User.Role.ADMIN, User.Role.TEACHER]:
        messages.error(request, 'Access denied. Chat is available for staff only.')
        return redirect('accounts:dashboard_redirect')
    
    # Get users who have exchanged messages
    sent_to = ChatMessage.objects.filter(sender=user).values_list('recipient', flat=True)
    received_from = ChatMessage.objects.filter(recipient=user).values_list('sender', flat=True)
    
    user_ids = set(list(sent_to) + list(received_from))
    
    # Also include admins if user is teacher, or teachers if user is admin
    if user.role == User.Role.TEACHER:
        admins = User.objects.filter(role=User.Role.ADMIN).values_list('id', flat=True)
        user_ids.update(admins)
    elif user.role == User.Role.ADMIN:
        teachers = User.objects.filter(role=User.Role.TEACHER).values_list('id', flat=True)
        user_ids.update(teachers)
        
    # Filter out students from the conversation list just in case
    conversations = User.objects.filter(id__in=user_ids).exclude(id=user.id).exclude(role=User.Role.STUDENT)
    
    # Annotate with last message
    conversation_list = []
    for partner in conversations:
        last_msg = ChatMessage.objects.filter(
            Q(sender=user, recipient=partner) | Q(sender=partner, recipient=user)
        ).order_by('-created_at').first()
        
        unread_count = ChatMessage.objects.filter(
            sender=partner, recipient=user, is_read=False
        ).count()
        
        conversation_list.append({
            'user': partner,
            'last_message': last_msg,
            'unread_count': unread_count
        })
    
    # Sort by last message time
    conversation_list.sort(key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.now(), reverse=True)
    unread_count = sum([conv['unread_count'] for conv in conversation_list])
    

    # ==========================
    # PICKUPS
    # ==========================
    active_pickups = PickupAuthorization.objects.filter(
        is_used=False,
        expires_at__gt=timezone.now()
    ).count()

    # ==========================
    # LEAVES & PAYROLL & LOANS
    # ==========================
    pending_leaves = LeaveRequest.objects.filter(status="pending").count()
    pending_loans = LoanApplication.objects.filter(status="pending").count()
    pending_payroll = PayrollPeriod.objects.filter(is_generated=True, is_approved_by_admin=False, is_locked=False).count()

    context = {
        "stats": {
            "total_users": total_users,
            "pending_users": pending_users,
            "students": students,
            "parents": parents,
            "staff": staff,
            "total_exams": total_exams,
            "active_exams": active_exams,
            "attempts_today": attempts_today,
            "total_revenue": total_revenue,
            "pending_orders": pending_orders,
            "unread_count": unread_count,
            "active_pickups": active_pickups,
            "pending_leaves": pending_leaves,
            "pending_loans": pending_loans,
            "pending_payroll": pending_payroll,
        }
    }

    return render(request, "exams/admin_grand_dashboard.html", context)
