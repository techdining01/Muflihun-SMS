from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import PickupAuthorization, PickupStudent, PickupVerificationLog
from .utils import generate_pickup_qr
import uuid
from datetime import timedelta
from django.core.paginator import Paginator

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Table,
    TableStyle,
    Image as RLImage,
    Spacer
)
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from io import BytesIO
from django.http import HttpResponse
from django.conf import settings
from django.utils import timezone

import qrcode
from PIL import Image


from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from django.http import HttpResponse



def is_parent(user):
    return user.is_authenticated and user.role == "PARENT"

def is_admin_or_staff(user):
    return user.is_authenticated and user.role in ["ADMIN", "STAFF"]

def is_admin(user):
    return user.is_authenticated and user.role == "ADMIN"



import logging
logger = logging.getLogger("system")


@login_required
@user_passes_test(is_parent)
def parent_dashboard(request):
    pickups = PickupAuthorization.objects.filter(parent=request.user).order_by("-created_at")

    return render(request, "pickups/parent/dashboard.html", {
        "pickups": pickups
    })


@login_required
@user_passes_test(is_parent)
def generate_pickup_code(request):
    if request.method == "POST":
        student_ids = request.POST.getlist("students")
        bearer_name = request.POST.get("bearer_name")
        relationship = request.POST.get("relationship")

        expires_at = timezone.now() + timedelta(hours=11)

        pickup = PickupAuthorization.objects.create(
            parent=request.user,
            bearer_name=bearer_name,
            relationship=relationship,
            expires_at=expires_at
        )

        students = User.objects.filter(id__in=student_ids, role="STUDENT")

        for student in students:
            PickupStudent.objects.create(
                pickup=pickup,
                student=student
            )
        
        pickup.generate_qr()
        pickup.save()

        messages.success(request, "Pickup code generated successfully")
        return redirect("pickup:parent_pickup_history")
    

    students = User.objects.filter(
        parents=request.user,
        role="STUDENT"
    )

    return render(request, "pickups/parent/generate.html", {
        "students": students
    })



@login_required
@user_passes_test(lambda u: u.role == "PARENT")
def parent_pickup_history(request):
    pickups = PickupAuthorization.objects.filter(parent=request.user).prefetch_related('students__student').order_by('-expires_at')
    return render(
        request,
        "pickups/parent/history.html",
        {"pickups": pickups}
    )



@login_required
@user_passes_test(is_admin)
def verify_pickup(request, reference):
    pickup = PickupAuthorization.objects.filter(
        reference__startswith=reference
    ).prefetch_related("students").first()

    if not pickup:
        return render(request, "pickups/admin/verify_error.html", {
            "message": "Invalid pickup reference"
        })

    status = "VALID"
    if pickup.is_used:
        status = "USED"
    elif pickup.is_expired():
        status = "EXPIRED"

    if request.method == "POST" and status == "VALID":
        pickup.is_used = True
        pickup.save()

        PickupVerificationLog.objects.create(
            pickup=pickup,
            verified_by=request.user,
            status="SUCCESS"
        )

        messages.success(request, "Pickup verified successfully")
        return redirect("pickup:verify_pickup_detail", pickup.reference[:8])

    return render(request, "pickups/admin/verify_pickup.html", {
        "pickup": pickup,
        "status": status
    })



@login_required
@user_passes_test(is_admin)
def verify_pickup_detail(request, reference):
    pickup = (
        PickupAuthorization.objects
        .select_related("parent")
        .prefetch_related(
            "students__student__student_class"
        )
        .filter(reference__startswith=reference)
        .first()
    )

    if not pickup:
        PickupVerificationLog.objects.create(
            pickup=None,
            verified_by=request.user,
            status="INVALID"
        )
        return render(
            request,
            "pickups/admin/error.html",
            {"message": "Invalid pickup reference"}
        )

    if pickup.is_used:
        status = "USED"
    elif pickup.is_expired():
        status = "EXPIRED"
    else:
        status = "SUCCESS"
        pickup.is_used = True
        pickup.save(update_fields=["is_used"])

    
    PickupVerificationLog.objects.create(
        pickup=pickup,
        verified_by=request.user,
        status=status
    )

    return render(
        request,
        "pickups/admin/verify_detail.html",
        {
            "pickup": pickup,
            "pickup_students": pickup.students.all(), 
        }
    )



@login_required
@user_passes_test(is_admin)
def pickup_scan(request):
    if request.method == "POST":
        reference = request.POST.get("reference", "").strip()

        if not reference:
            messages.error(request, "Pickup reference is required")
            return redirect("pickup:pickup_scan")

        try:
            pickup = PickupAuthorization.objects.get(
                reference__startswith=reference
            )
        except PickupAuthorization.DoesNotExist:
            messages.error(request, "Invalid pickup reference")
            return redirect("pickup:pickup_scan")

        return redirect(
            "pickup:verify_pickup_detail",
            reference=pickup.reference
        )

    return render(request, "pickups/admin/scan.html")



@login_required
def admin_pickup_logs(request):
    logs = PickupVerificationLog.objects.select_related(
        "pickup", "verified_by"
    ).order_by("-verified_at")
    return render(request, "pickups/admin/logs.html", {"logs": logs})


@login_required
@user_passes_test(is_admin)
def force_expire_pickup(request, pickup_id):
    pickup = get_object_or_404(PickupAuthorization, id=pickup_id)

    pickup.expires_at = timezone.now()
    pickup.save(update_fields=["expires_at"])

    PickupVerificationLog.objects.create(
        pickup=pickup,
        verified_by=request.user,
        status="FORCE_EXPIRED"
    )

    messages.success(request, "Pickup force-expired successfully.")
    return redirect("pickup:admin_dashboard")



@login_required
@user_passes_test(is_admin)
def pickup_audit_log_pdf(request):
    logs = PickupVerificationLog.objects.select_related(
        "pickup", "verified_by"
    ).order_by("-verified_at")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = "attachment; filename=pickup_audit_log.pdf"

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()

    data = [
        ["Date", "Reference", "Status", "Verified By"]
    ]

    for log in logs:
        data.append([
            log.verified_at.strftime("%d-%m-%Y %H:%M"),
            str(log.pickup.reference)[:8] if log.pickup else "INVALID",
            log.status,
            log.verified_by.get_full_name()
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("FONT", (0,0), (-1,0), "Helvetica-Bold"),
    ]))

    doc.build([
        Paragraph("Pickup Verification Audit Log", styles["Title"]),
        table
    ])

    return response



@login_required
@user_passes_test(is_admin)
def daily_pickup_report_pdf(request):
    today = timezone.now().date()

    logs = PickupVerificationLog.objects.filter(
        verified_at__date=today
    ).select_related("pickup", "verified_by")

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f"attachment; filename=pickup_report_{today}.pdf"
    )

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()

    data = [["Time", "Ref", "Status", "Verifier"]]

    for log in logs:
        data.append([
            log.verified_at.strftime("%H:%M"),
            str(log.pickup.reference)[:8] if log.pickup else "INVALID",
            log.status,
            log.verified_by.get_full_name()
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
    ]))

    doc.build([
        Paragraph(f"Daily Pickup Report – {today}", styles["Title"]),
        table
    ])

    return response




def is_admin(user):
    return user.is_superuser or user.role == "ADMIN"



@login_required
@user_passes_test(is_admin)
def pickup_admin_dashboard(request):
    from school_sms.views import mark_seen
    mark_seen(request, 'active_pickups')
    pickup_qs = (
        PickupAuthorization.objects
        .select_related("parent")
        .prefetch_related(
            "students__student",
            "students__student__student_class"
        )
        .order_by("-created_at")
    )

    paginator = Paginator(pickup_qs, 15)  
    page_number = request.GET.get("page")
    pickups = paginator.get_page(page_number)

    stats = {
        "total": pickup_qs.count(),
        "active": pickup_qs.filter(
            is_used=False,
            expires_at__gt=timezone.now()
        ).count(),
        "expired": pickup_qs.filter(
            expires_at__lt=timezone.now(),
            is_used=False
        ).count(),
        "used": pickup_qs.filter(is_used=True).count(),
    }

    return render(
        request,
        "pickups/admin/dashboard.html",
        {
            "pickups": pickups,
            "stats": stats,
        }
    )

