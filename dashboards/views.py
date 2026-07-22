from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Q, Avg, Sum, Count, F
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.http import require_POST
from accounts.models import User
from exams.models import Exam, RetakeRequest, SystemLog, SchoolClass, Broadcast, ExamAttempt, Question, Choice, ChatMessage, Notification, Subject, StudentAnswer
from . import grading_views, exam_views, notification_views
from .models import ChatRoom, ChatRoomMessage, ChatRoomReadStatus
from .forms import SchoolClassForm, StudentForm, ExamForm, QuestionForm, ChoiceForm, SubjectForm
from django.forms import modelformset_factory
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import json
import csv
from datetime import timedelta

# ========================= AUTHENTICATION =========================
def cbt_exam(request):
    return render(request, 'exams/cbt_home.html')

def about_page(request):
    return render(request, 'exams/about.html')

# ========================= DASHBOARDS =========================

@login_required()
def admin_dashboard(request):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
    
    total_students = User.objects.filter(role=User.Role.STUDENT).count()
    total_teachers = User.objects.filter(role=User.Role.TEACHER).count()
    total_exams = Exam.objects.all().count()
    total_classes = SchoolClass.objects.all().count()
    
    return render(request, 'dashboards/admin/dashboard.html', {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_exams': total_exams,
        'total_classes': total_classes
    })

@login_required()
def teacher_dashboard(request):
    if request.user.role != User.Role.TEACHER:
        return redirect('accounts:dashboard_redirect')
    
    teacher = request.user
    
    # 1. Total Exams Created by this teacher
    exams = Exam.objects.filter(created_by=teacher)
    total_exams = exams.count()
    
    # 2. Total Students in Classes managed by this teacher
    # Assuming SchoolClass has a 'teacher' field
    managed_classes = SchoolClass.objects.filter(Q(teacher=teacher) | Q(assistant_teacher=teacher))
    total_students = User.objects.filter(role=User.Role.STUDENT, student_class__in=managed_classes).count()
    
    # 4. Total Graded (Attempts that are fully graded)
    # This includes objective-only attempts AND subjective attempts where all answers are marked
    all_submitted = ExamAttempt.objects.filter(
        exam__created_by=teacher,
        status='submitted'
    )
    
    total_submissions = all_submitted.count()
    
    # An attempt is "ungraded" if it has at least one subjective question without a mark
    ungraded_attempts_ids = ExamAttempt.objects.filter(
        exam__created_by=teacher,
        status='submitted',
        answers__question__type='subjective',
        answers__subjective_mark__isnull=True
    ).values_list('id', flat=True).distinct()
    
    total_graded = all_submitted.exclude(id__in=ungraded_attempts_ids).count()

    # 5. Pending Grading (Count of attempts that need marking)
    pending_grading = ungraded_attempts_ids.count()
    
    # Calculate grading progress percentage
    grading_progress = (total_graded / total_submissions * 100) if total_submissions > 0 else 0
    
    # Recent Exams for the table with performance stats
    from django.db.models import Avg, Sum, FloatField, Value
    from django.db.models.functions import Coalesce
    
    recent_exams = Exam.objects.filter(created_by=teacher).annotate(
        # Total marks available for this exam
        total_exam_marks=Coalesce(Sum('questions__marks'), Value(0)),
        # Average score obtained in submitted attempts
        avg_raw_score=Avg('exam_attempts__score', filter=Q(exam_attempts__status='submitted')),
    ).order_by('-created_at')[:5]

    # Calculate percentage for each exam in memory since total_exam_marks is now available
    for exam in recent_exams:
        if exam.total_exam_marks > 0 and exam.avg_raw_score is not None:
            exam.avg_score_pct = (exam.avg_raw_score / exam.total_exam_marks) * 100
        else:
            exam.avg_score_pct = 0

    context = {
        'total_exams': total_exams,
        'total_students': total_students,
        'pending_grading': pending_grading,
        'total_graded': total_graded,
        'total_submissions': total_submissions,
        'grading_progress': grading_progress,
        'recent_exams': recent_exams,
        
    }
    
    return render(request, 'dashboards/teacher/dashboard.html', context)

@login_required()
def student_dashboard(request):
    if request.user.role != User.Role.STUDENT:
        return redirect('accounts:dashboard_redirect')
    
    user = request.user
    now = timezone.now()

    expired_attempts = ExamAttempt.objects.filter(
        student=user,
        status__in=['in_progress', 'interrupted', 'expired'],
        exam__end_time__lt=now
    ).select_related('exam')

    for attempt in expired_attempts:
        with transaction.atomic():
            objective_questions = attempt.exam.questions.filter(type='objective')
            total_objective_score = 0
            for question in objective_questions:
                try:
                    student_answer = StudentAnswer.objects.get(
                        attempt=attempt,
                        question=question
                    )
                    if student_answer.selected_choice and student_answer.selected_choice.is_correct:
                        total_objective_score += question.marks
                except StudentAnswer.DoesNotExist:
                    pass
            attempt.status = 'submitted'
            attempt.completed_at = attempt.exam.end_time
            attempt.score = total_objective_score
            attempt.save(update_fields=['status', 'completed_at', 'score'])
    
    # Get student's class
    student_class = user.student_class
    
    exams_query = Exam.objects.filter(
        Q(school_class=student_class) | Q(examaccess__student=user),
        is_active=True,
        is_published=True,
        end_time__gte=now
    ).distinct().order_by('start_time')
    
    # Filter out exams that are already submitted and don't allow retake
    # (Simple client-side logic for now, though start_exam view should enforce strict rules)
    available_exams = []
    # Get all attempts for the user to determine status (in_progress, submitted, etc.)
    all_attempts = ExamAttempt.objects.filter(student=user)
    # Map exam_id to list of attempts
    exam_attempts_map = {}
    for attempt in all_attempts:
        if attempt.exam_id not in exam_attempts_map:
            exam_attempts_map[attempt.exam_id] = []
        exam_attempts_map[attempt.exam_id].append(attempt)
    
    # Get retake requests
    requests_query = RetakeRequest.objects.filter(student=user).order_by('exam_id', '-created_at')
    requests_map = {}
    for req in requests_query:
        if req.exam_id not in requests_map:
            requests_map[req.exam_id] = req

    for exam in exams_query:
        attempts = exam_attempts_map.get(exam.id, [])
        latest_request = requests_map.get(exam.id)

        has_submitted = any(a.status == 'submitted' for a in attempts)
        has_in_progress = any(a.status == 'in_progress' for a in attempts)

        if has_in_progress:
            continue

        exam.retake_status = 'none'
        approved_request = None
        if latest_request and latest_request.status == 'approved':
            approved_request = latest_request
            exam.retake_status = 'approved'

        if has_submitted:
            if not approved_request:
                continue
            submitted_after_approval = any(
                a.status == 'submitted'
                and a.completed_at
                and a.completed_at >= approved_request.created_at
                for a in attempts
            )
            if submitted_after_approval:
                continue

        exam.has_submitted = has_submitted
        exam.has_in_progress = has_in_progress
        exam.can_retake = approved_request is not None and not has_submitted

        available_exams.append(exam)

    # Statistics
    attempts = ExamAttempt.objects.filter(student=user, status='submitted')
    completed_exams = attempts.count()
    total_exams = len(available_exams) # Count of currently available exams
    
    average_score = attempts.aggregate(Avg('score'))['score__avg'] or 0
    average_score = round(average_score, 1)
    
    # Class Rank Calculation
    class_rank = "-"
    total_students = 0
    if student_class:
        class_students = User.objects.filter(role=User.Role.STUDENT, student_class=student_class)
        total_students = class_students.count()
        student_scores = []
        for s in class_students:
            # Calculate average score for each student in the class
            s_avg = ExamAttempt.objects.filter(student=s, status='submitted').aggregate(Avg('score'))['score__avg'] or 0
            student_scores.append(s_avg)
        
        # Sort scores in descending order
        student_scores.sort(reverse=True)
        
        try:
            # Find current student's rank
            my_avg = attempts.aggregate(Avg('score'))['score__avg'] or 0
            # handling float precision for index matching might be tricky, but let's try direct match
            class_rank = student_scores.index(my_avg) + 1
        except ValueError:
            pass
            
    # Recent Results
    recent_results = ExamAttempt.objects.filter(student=user, status='submitted').order_by('-completed_at')[:5]

    context = {
        'available_exams': available_exams,
        'total_exams': total_exams,
        'completed_exams': completed_exams,
        'average_score': average_score,
        'class_rank': class_rank,
        'recent_results': recent_results,
        'total_students': total_students
    }

    return render(request, 'dashboards/student/dashboard.html', context)

@login_required()
def parent_dashboard(request):
    if request.user.role != User.Role.PARENT:
        return redirect('accounts:dashboard_redirect')
    
    children = request.user.children.all()
    selected_child = None
    context = {'children': children}
    
    child_id = request.GET.get('child_id')
    if child_id:
        selected_child = children.filter(id=child_id).first()
    elif children.exists():
        selected_child = children.first()
    
    if selected_child:
        context['selected_child'] = selected_child
        completed_attempts = ExamAttempt.objects.filter(
            student=selected_child, 
            status='submitted'
        ).order_by('-started_at')
        
        context['exams_taken'] = completed_attempts.count()
        context['average_score'] = round(completed_attempts.aggregate(Avg('score'))['score__avg'] or 0, 1)
        context['recent_results'] = completed_attempts[:5]
        
        if selected_child.student_class:
            class_students = User.objects.filter(role=User.Role.STUDENT, student_class=selected_child.student_class)
            student_scores = []
            for s in class_students:
                s_avg = s.attempts.filter(status='submitted').aggregate(Avg('score'))['score__avg'] or 0
                student_scores.append(s_avg)
            
            student_scores.sort(reverse=True)
            try:
                current_avg = completed_attempts.aggregate(Avg('score'))['score__avg'] or 0
                
                # Filter out students who have no scores to avoid index errors or misleading ranks
                valid_scores = [score for score in student_scores if score > 0]
                
                if current_avg > 0 and current_avg in student_scores:
                    context['class_rank'] = student_scores.index(current_avg) + 1
                else:
                    context['class_rank'] = "-"
            except (ValueError, TypeError):
                context['class_rank'] = "-"
            
            context['total_students'] = class_students.count()
        else:
            context['class_rank'] = "-"
            context['total_students'] = 0

    return render(request, 'dashboards/parent/dashboard.html', context)

# ========================= ADMIN LISTS =========================

@login_required()
def admin_students_list(request):
    students = User.objects.filter(role=User.Role.STUDENT).order_by('username')
    return render(request, 'dashboards/admin/students_list.html', {'students': students})

@login_required()
def admin_create_student(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Student created successfully.')
            return redirect('dashboards:admin_students_list')
    else:
        form = StudentForm()
    return render(request, 'dashboards/admin/create_student.html', {'form': form})

@login_required()
def admin_edit_student(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, 'Student updated successfully.')
            return redirect('dashboards:admin_students_list')
    else:
        form = StudentForm(instance=student)
    return render(request, 'dashboards/admin/edit_student.html', {'form': form, 'student': student})

@login_required()
def admin_delete_student(request, student_id):
    student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
    if request.method == 'POST':
        student.delete()
        messages.success(request, 'Student deleted successfully.')
        return redirect('dashboards:admin_students_list')
    return render(request, 'dashboards/admin/student_confirm_delete.html', {'student': student})

@login_required()
def admin_exams_list(request):
    exams_list = Exam.objects.all().order_by('-created_at')
    paginator = Paginator(exams_list, 10)  # Show 10 exams per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'dashboards/admin/exams_list.html', {'page_obj': page_obj})

@login_required()
def teacher_exams_list(request):
    exams = Exam.objects.filter(created_by=request.user)
    
    # Filter by search query
    search_query = request.GET.get('search')
    if search_query:
        exams = exams.filter(title__icontains=search_query)
        
    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter == 'Published':
        exams = exams.filter(is_published=True)
    elif status_filter == 'Draft':
        exams = exams.filter(is_published=False)
        
    exams = exams.order_by('-created_at')
    
    # Handle AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.template.loader import render_to_string
        html = render_to_string('dashboards/teacher/partials/exams_table_rows.html', {'exams': exams}, request=request)
        return JsonResponse({'html': html})

    return render(request, 'dashboards/teacher/exams_list.html', {'exams': exams})

# ========================= EXAM MANAGEMENT =========================

@login_required()
def create_exam(request):
    if request.user.role not in [User.Role.ADMIN, User.Role.TEACHER]:
        messages.error(request, 'Access denied')
        return redirect('dashboards:dashboard_redirect')

    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form_data = data.get('exam')
                questions_data = data.get('questions')
                
                form = ExamForm(form_data)
                if form.is_valid():
                    exam = form.save(commit=False)
                    exam.created_by = request.user
                    exam.save()
                    
                    for index, q_data in enumerate(questions_data):
                        question = Question.objects.create(
                            exam=exam,
                            text=q_data.get('text'),
                            type=q_data.get('type'),
                            marks=int(q_data.get('marks', 1)),
                            order=index + 1
                        )
                        
                        if question.type == 'objective':
                            choices = q_data.get('choices', [])
                            for c_data in choices:
                                Choice.objects.create(
                                    question=question,
                                    text=c_data.get('text'),
                                    is_correct=c_data.get('is_correct', False)
                                )
                                
                    redirect_url = reverse('dashboards:teacher_exams_list')
                    if request.user.role == User.Role.ADMIN:
                        redirect_url = reverse('dashboards:admin_exams_list')
                        
                    messages.success(request, 'Exam and questions created successfully.')
                    return JsonResponse({'status': 'success', 'redirect_url': redirect_url})
                else:
                    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
            
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

        form = ExamForm(request.POST)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.created_by = request.user
            exam.save()
            messages.success(request, 'Exam created successfully.')
            if request.user.role == User.Role.ADMIN:
                return redirect('dashboards:admin_exams_list')
            else:
                return redirect('dashboards:teacher_exams_list')
    else:
        form = ExamForm()
    classes = SchoolClass.objects.all()
    
    return render(request, 'exams/create_exam.html', {'form': form, 'classes': classes})

@login_required()
def edit_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    is_owner = exam.created_by_id == request.user.id
    if not is_owner and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('accounts:dashboard_redirect')
        
    if request.method == 'POST':
        form = ExamForm(request.POST, instance=exam)
        if form.is_valid():
            form.save()
            messages.success(request, 'Exam updated successfully.')
            if request.user.role == User.Role.ADMIN:
                return redirect('dashboards:admin_exams_list')
            else:
                return redirect('dashboards:teacher_exams_list')
    else:
        form = ExamForm(instance=exam)
    
    questions = exam.questions.all().order_by('order')
    classes = SchoolClass.objects.all()
    
    return render(request, 'exams/edit_exam.html', {
        'form': form, 
        'exam': exam,
        'questions': questions,
        'classes': classes
    })

@login_required()
def delete_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    is_owner = exam.created_by_id == request.user.id
    if not is_owner and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('accounts:dashboard_redirect')
        
    if request.method == 'POST':
        exam.delete()
        messages.success(request, 'Exam deleted successfully.')
        if request.user.role == User.Role.ADMIN:
            return redirect('dashboards:admin_exams_list')
        else:
            return redirect('dashboards:teacher_exams_list')
            
    return render(request, 'exams/exam_confirm_delete.html', {'exam': exam})

@login_required()
def publish_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    is_owner = exam.created_by_id == request.user.id
    if not is_owner and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:exam_detail', exam_id=exam.id)
    exam.is_published = True
    exam.save()
    messages.success(request, 'Exam published successfully.')
    return redirect('dashboards:exam_detail', exam_id=exam.id)

@login_required()
def unpublish_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    is_owner = exam.created_by_id == request.user.id
    if not is_owner and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:exam_detail', exam_id=exam.id)
    exam.is_published = False
    exam.save()
    messages.warning(request, 'Exam unpublished.')
    return redirect('dashboards:exam_detail', exam_id=exam.id)

@login_required()
def exam_detail(request, exam_id):
    if request.user.role == User.Role.STUDENT:
        messages.error(request, 'Access denied. Students cannot view exam details.')
        return redirect('dashboards:student_dashboard')
        
    exam = get_object_or_404(Exam, id=exam_id)

    is_owner = exam.created_by_id == request.user.id
    if request.user.role == User.Role.TEACHER and not is_owner:
        messages.error(request, 'Access denied. You can only view details of exams you created.')
        return redirect('dashboards:teacher_dashboard')

    return render(request, 'exams/exam_detail.html', {'exam': exam})

# ========================= BROADCAST =========================

@login_required()
def broadcast_center(request):
    if request.user.role not in [User.Role.ADMIN, User.Role.TEACHER]:
        messages.error(request, 'Access denied')
        return redirect('dashboards:dashboard_redirect')
        
    if request.method == 'POST':
        title = request.POST.get('title')
        message_content = request.POST.get('message')
        target_class_id = request.POST.get('target_class')
        target_parents_ids = request.POST.getlist('target_parents')
        
        target_class = None
        if target_class_id:
            target_class = get_object_or_404(SchoolClass, id=target_class_id)
            
        broadcast = Broadcast.objects.create(
            sender=request.user,
            target_class=target_class,
            title=title,
            message=message_content
        )
        
        recipients_queryset = None
        target_role = 'students'
        if target_parents_ids:
            target_role = 'parents'
            recipients_queryset = User.objects.filter(role=User.Role.PARENT, id__in=target_parents_ids)
            broadcast.recipients.add(*recipients_queryset)
        else:
            recipients_queryset = User.objects.filter(role=User.Role.STUDENT)
            if target_class:
                recipients_queryset = recipients_queryset.filter(student_class=target_class)
        
        broadcast.target_role = target_role
        broadcast.save()
        
        SystemLog.objects.create(
            level='INFO',
            source='Broadcast',
            message=f"Broadcast '{title}' sent by {request.user.username} to {target_class.name if target_class else 'All Students'}"
        )
        
        notifications = []
        for recipient in recipients_queryset:
            notifications.append(Notification(
                sender=request.user,
                recipient=recipient,
                title=f"Broadcast: {title}",
                message=message_content
            ))
        Notification.objects.bulk_create(notifications)
        
        messages.success(request, 'Broadcast sent successfully.')
        return redirect('dashboards:broadcast_center')
        
    broadcast_list = Broadcast.objects.all().order_by('-created_at')
    paginator = Paginator(broadcast_list, 5)  # Show 5 broadcasts per page
    
    page_number = request.GET.get('page')
    broadcasts = paginator.get_page(page_number)

    classes = SchoolClass.objects.all()
    parents = User.objects.filter(role=User.Role.PARENT).order_by('first_name')
    
    return render(request, 'dashboards/broadcast_center.html', {
        'broadcasts': broadcasts,
        'classes': classes,
        'parents': parents
    })

# ========================= CHAT SYSTEM =========================

@login_required
def chat_index(request):
   
    user = request.user
    # Ensure only staff/admins can access if that's the rule, or allow students if needed.
    # Based on previous code, it was restricted to ADMIN and TEACHER.
    if user.role not in [User.Role.ADMIN, User.Role.TEACHER]:
         messages.error(request, 'Access denied. Staff only.')
         return redirect('accounts:dashboard_redirect')

    return render(request, 'dashboards/chat/index.html', {
        'user': user,
        'ws_url': 'ws://' + request.get_host() + '/ws/chat/'
    })

@login_required
def chat_api_conversations(request):
    """API to fetch sidebar conversations (DMs and Rooms)"""
    user = request.user
    
    # 1. Fetch DMs (Users with recent interaction + Admins/Teachers)
    # Get all staff users (Admins/Teachers) except self
    staff_users = User.objects.filter(role__in=[User.Role.ADMIN, User.Role.TEACHER]).exclude(id=user.id).order_by('first_name', 'username')
    
    dm_list = []
    for partner in staff_users:
        # Get last message
        last_msg = ChatMessage.objects.filter(
            Q(sender=user, recipient=partner) | Q(sender=partner, recipient=user)
        ).order_by('-created_at').first()
        
        unread = ChatMessage.objects.filter(sender=partner, recipient=user, is_read=False).count()
        
        dm_list.append({
            'type': 'dm',
            'id': partner.id,
            'name': partner.get_full_name() or partner.username,
            'role': partner.get_role_display(),
            'avatar_initials': (partner.first_name[:1] + partner.last_name[:1]).upper() if partner.first_name and partner.last_name else partner.username[:2].upper(),
            'last_message': last_msg.message[:30] + '...' if last_msg else '',
            'timestamp': last_msg.created_at.strftime('%H:%M') if last_msg and last_msg.created_at.date() == timezone.now().date() else (last_msg.created_at.strftime('%d/%m') if last_msg else ''),
            'unread_count': unread
        })
    
    # Sort DMs: Active conversations first
    dm_list.sort(key=lambda x: x['timestamp'] or '', reverse=True)

    # 2. Fetch Rooms (Groups and Conferences)
    rooms = ChatRoom.objects.filter(participants=user).order_by('name')
    group_list = []
    conference_list = []

    for room in rooms:
        last_msg = room.messages.order_by('-created_at').first()
        
        # Calculate unread count
        unread_count = 0
        try:
            read_status = ChatRoomReadStatus.objects.get(room=room, user=user)
            if last_msg and last_msg.created_at > read_status.last_read_at:
                unread_count = room.messages.filter(created_at__gt=read_status.last_read_at).count()
        except ChatRoomReadStatus.DoesNotExist:
            # If never read, all messages are unread
            unread_count = room.messages.count()

        room_data = {
            'type': 'room', # Keep as 'room' for message API compatibility
            'id': room.id,
            'name': room.name,
            'room_type': room.room_type,
            'last_message': f"{last_msg.sender.username}: {last_msg.message[:20]}" if last_msg else "No messages",
            'timestamp': last_msg.created_at.strftime('%H:%M') if last_msg and last_msg.created_at.date() == timezone.now().date() else (last_msg.created_at.strftime('%d/%m') if last_msg else ''),
            'unread_count': unread_count
        }
        
        if room.room_type == ChatRoom.RoomType.CONFERENCE:
            conference_list.append(room_data)
        else:
            group_list.append(room_data)

    return JsonResponse({'dms': dm_list, 'groups': group_list, 'conferences': conference_list})

@login_required
def chat_api_messages(request, chat_type, target_id):
    """API to fetch messages for a specific conversation"""
    user = request.user
    messages_data = []
    target_name = ""
    
    if chat_type == 'dm':
        partner = get_object_or_404(User, id=target_id)
        target_name = partner.get_full_name() or partner.username
        
        # Mark as read
        ChatMessage.objects.filter(sender=partner, recipient=user, is_read=False).update(is_read=True)
        
        msgs = ChatMessage.objects.filter(
            Q(sender=user, recipient=partner) | Q(sender=partner, recipient=user)
        ).order_by('created_at')
        
        for m in msgs:
            messages_data.append({
                'id': m.id,
                'sender_id': m.sender.id,
                'sender_name': m.sender.get_full_name() or m.sender.username,
                'message': m.message,
                'attachment_url': m.attachment.url if m.attachment else None,
                'attachment_name': m.attachment.name.split('/')[-1] if m.attachment else None,
                'created_at': m.created_at.strftime('%H:%M'),
                'is_me': m.sender.id == user.id
            })
            
    elif chat_type == 'room':
        room = get_object_or_404(ChatRoom, id=target_id)
        if user not in room.participants.all():
            return JsonResponse({'error': 'Access denied'}, status=403)
            
        # Mark as read
        ChatRoomReadStatus.objects.update_or_create(
            room=room, user=user,
            defaults={'last_read_at': timezone.now()}
        )
            
        target_name = room.name
        msgs = room.messages.select_related('sender').order_by('created_at')
        
        for m in msgs:
            messages_data.append({
                'id': m.id,
                'sender_id': m.sender.id,
                'sender_name': m.sender.get_full_name() or m.sender.username,
                'message': m.message,
                'attachment_url': m.attachment.url if m.attachment else None,
                'attachment_name': m.attachment.name.split('/')[-1] if m.attachment else None,
                'created_at': m.created_at.strftime('%H:%M'),
                'is_me': m.sender.id == user.id
            })

    return JsonResponse({
        'chat_type': chat_type,
        'target_id': target_id,
        'target_name': target_name,
        'messages': messages_data
    })

@login_required
@require_POST
def chat_api_send(request):
    """API to send a message"""
    user = request.user
    
    # Handle both JSON (legacy/text-only) and Multipart (file upload)
    if request.content_type == 'application/json':
        data = json.loads(request.body)
        chat_type = data.get('type')
        target_id = data.get('target_id')
        message = data.get('message')
        attachment = None
    else:
        chat_type = request.POST.get('type')
        target_id = request.POST.get('target_id')
        message = request.POST.get('message')
        attachment = request.FILES.get('attachment')
    
    if not message and not attachment:
        return JsonResponse({'error': 'Empty message and attachment'}, status=400)

    response_data = {}
    channel_layer = get_channel_layer()

    if chat_type == 'dm':
        recipient = get_object_or_404(User, id=target_id)
        msg_obj = ChatMessage.objects.create(
            sender=user, 
            recipient=recipient, 
            message=message or '',
            attachment=attachment
        )
        
        # Log system event
        SystemLog.objects.create(
            level='INFO',
            source='Chat',
            message=f"DM sent from {user.username} to {recipient.username}"
        )
        
        response_data = {
            'id': msg_obj.id,
            'sender_id': user.id,
            'sender_name': user.get_full_name() or user.username,
            'message': msg_obj.message,
            'attachment_url': msg_obj.attachment.url if msg_obj.attachment else None,
            'attachment_name': msg_obj.attachment.name.split('/')[-1] if msg_obj.attachment else None,
            'created_at': msg_obj.created_at.strftime('%H:%M'),
            'chat_type': 'dm',
            'target_id': user.id # ID of sender (for the recipient to identify who sent it)
        }
        
        # Push to recipient via WebSocket
        group_name = f"chat_user_{recipient.id}"
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'chat_message',
                'data': response_data
            }
        )
        
    elif chat_type == 'room':
        room = get_object_or_404(ChatRoom, id=target_id)
        if user not in room.participants.all():
            return JsonResponse({'error': 'Access denied'}, status=403)
            
        msg_obj = ChatRoomMessage.objects.create(
            room=room, 
            sender=user, 
            message=message or '',
            attachment=attachment
        )
        
        # Update sender's read status
        ChatRoomReadStatus.objects.update_or_create(
            room=room, user=user,
            defaults={'last_read_at': timezone.now()}
        )
        
        response_data = {
            'id': msg_obj.id,
            'sender_id': user.id,
            'sender_name': user.get_full_name() or user.username,
            'message': msg_obj.message,
            'attachment_url': msg_obj.attachment.url if msg_obj.attachment else None,
            'attachment_name': msg_obj.attachment.name.split('/')[-1] if msg_obj.attachment else None,
            'created_at': msg_obj.created_at.strftime('%H:%M'),
            'chat_type': 'room',
            'target_id': room.id
        }
        
        # Push to all participants (simplification: we rely on users subscribing to room updates or broadcasting to their user channels)
        # Since we didn't implement robust room subscriptions in consumer, let's iterate participants and send to their user channels
        # This is inefficient for large groups but fine for small enterprise "rooms"
        for participant in room.participants.all():
             if participant.id != user.id: # Don't send back to sender (they have it locally confirmed)
                async_to_sync(channel_layer.group_send)(
                    f"chat_user_{participant.id}",
                    {
                        'type': 'chat_message',
                        'data': response_data
                    }
                )

    return JsonResponse({'status': 'sent', 'message': response_data})

@login_required
@require_POST
def chat_api_create_room(request):
    """API to create a new chat room"""
    user = request.user
    if user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Only admins can create rooms'}, status=403)
        
    data = json.loads(request.body)
    name = data.get('name')
    participant_ids = data.get('participants', [])
    room_type = data.get('room_type', 'GROUP')
    
    if not name:
        return JsonResponse({'error': 'Room name required'}, status=400)
        
    if ChatRoom.objects.filter(name=name).exists():
        return JsonResponse({'error': 'Room name already exists'}, status=400)
        
    # Validate room_type
    if room_type not in ChatRoom.RoomType.values:
        room_type = ChatRoom.RoomType.GROUP

    room = ChatRoom.objects.create(name=name, created_by=user, room_type=room_type)
    room.participants.add(user)
    
    if participant_ids:
        users_to_add = User.objects.filter(id__in=participant_ids, role__in=[User.Role.ADMIN, User.Role.TEACHER])
        room.participants.add(*users_to_add)
        
    return JsonResponse({'status': 'created', 'id': room.id, 'name': room.name})


# ========================= NOTIFICATIONS =========================

@login_required()
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save()
    return redirect(request.META.get('HTTP_REFERER', 'accounts_redirect'))

@login_required()
def mark_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    messages.success(request, 'All notifications marked as read.')
    return redirect(request.META.get('HTTP_REFERER', 'accounts_redirect'))

# ========================= QUESTION MANAGEMENT =========================

@login_required()
def add_question(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    if request.user != exam.created_by and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:edit_exam', exam_id=exam.id)
        
    ChoiceFormSet = modelformset_factory(Choice, form=ChoiceForm, extra=4, can_delete=True)
    
    if request.method == 'POST':
        form = QuestionForm(request.POST)
        formset = ChoiceFormSet(request.POST, queryset=Choice.objects.none())
        
        if form.is_valid():
            question = form.save(commit=False)
            question.exam = exam
            
            if question.type == 'objective':
                if formset.is_valid():
                    question.save()
                    choices = formset.save(commit=False)
                    for choice in choices:
                        choice.question = question
                        choice.save()
                    messages.success(request, 'Question added successfully.')
                    return redirect('dashboards:edit_exam', exam_id=exam.id)
            else:
                question.save()
                messages.success(request, 'Question added successfully.')
                return redirect('dashboards:edit_exam', exam_id=exam.id)
    else:
        form = QuestionForm(initial={'order': exam.questions.count() + 1})
        formset = ChoiceFormSet(queryset=Choice.objects.none())
        
    return render(request, 'exams/add_question.html', {
        'form': form, 
        'formset': formset,
        'exam': exam
    })

@login_required()
def edit_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    exam = question.exam
    
    if request.user != exam.created_by and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:edit_exam', exam_id=exam.id)
        
    ChoiceFormSet = modelformset_factory(Choice, form=ChoiceForm, extra=1, can_delete=False)
    
    if request.method == 'POST':
        form = QuestionForm(request.POST, instance=question)
        formset = ChoiceFormSet(request.POST, queryset=question.choices.all())
        
        if form.is_valid() and formset.is_valid():
            question = form.save(commit=False)
            
            if question.type == 'objective':
                question.save()
                choices = formset.save(commit=False)
                for choice in choices:
                    choice.question = question
                    choice.save()
                messages.success(request, 'Question updated successfully.')
                return redirect('dashboards:edit_exam', exam_id=exam.id)
            else:
                question.save()
                messages.success(request, 'Question updated successfully.')
                return redirect('dashboards:edit_exam', exam_id=exam.id)
    else:
        form = QuestionForm(instance=question)
        formset = ChoiceFormSet(queryset=question.choices.all())
        
    return render(request, 'exams/edit_question.html', {
        'form': form, 
        'formset': formset,
        'question': question,
        'exam': exam
    })

@login_required()
def delete_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    exam = question.exam
    
    if request.user != exam.created_by and request.user.role != User.Role.ADMIN:
        messages.error(request, 'Access denied')
        return redirect('dashboards:edit_exam', exam_id=exam.id)
        
    question.delete()
    messages.success(request, 'Question deleted successfully.')
    return redirect('dashboards:edit_exam', exam_id=exam.id)


@login_required()
def delete_choice_ajax(request, choice_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)
    
    choice = get_object_or_404(Choice, id=choice_id)
    question = choice.question
    exam = question.exam
    
    if request.user != exam.created_by and request.user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    choice.delete()
    return JsonResponse({'status': 'ok'})

# Placeholders for missing views to prevent import errors in urls.py
@login_required()
def admin_classes_list(request):
    classes = SchoolClass.objects.all().order_by('name')
    return render(request, 'dashboards/admin/classes_list.html', {'classes': classes})

@login_required()
def admin_create_class(request):
    if request.method == 'POST':
        form = SchoolClassForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Class created successfully.')
            return redirect('dashboards:admin_classes_list')
    else:
        form = SchoolClassForm()
    return render(request, 'dashboards/admin/create_class.html', {'form': form, 'title': 'Create Class'})

@login_required()
def admin_edit_class(request, class_id):
    school_class = get_object_or_404(SchoolClass, id=class_id)
    if request.method == 'POST':
        form = SchoolClassForm(request.POST, instance=school_class)
        if form.is_valid():
            form.save()
            messages.success(request, 'Class updated successfully.')
            return redirect('dashboards:admin_classes_list')
    else:
        form = SchoolClassForm(instance=school_class)
    return render(
        request,
        'dashboards/admin/edit_class.html',
        {'form': form, 'title': 'Edit Class', 'school_class': school_class},
    )

@login_required()
def admin_delete_class(request, class_id):
    school_class = get_object_or_404(SchoolClass, id=class_id)
    school_class.delete()
    messages.success(request, 'Class deleted successfully.')
    return redirect('dashboards:admin_classes_list')

# ========================= SUBJECT MANAGEMENT =========================

@login_required()
def admin_subjects_list(request):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    subjects_list = Subject.objects.all().prefetch_related('classes').order_by('name')
    paginator = Paginator(subjects_list, 10) # Show 10 subjects per page.

    page_number = request.GET.get('page')
    subjects = paginator.get_page(page_number)
    return render(request, 'dashboards/admin/subjects_list.html', {'subjects': subjects})

@login_required()
def admin_create_subject(request):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Subject created successfully.')
            return redirect('dashboards:admin_subjects_list')
    else:
        form = SubjectForm()
    return render(request, 'dashboards/admin/create_subject.html', {'form': form, 'title': 'Create Subject'})

@login_required()
def admin_edit_subject(request, subject_id):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    subject = get_object_or_404(Subject, id=subject_id)
    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            messages.success(request, 'Subject updated successfully.')
            return redirect('dashboards:admin_subjects_list')
    else:
        form = SubjectForm(instance=subject)
    return render(request, 'dashboards/admin/edit_subject.html', {'form': form, 'title': 'Edit Subject'})

@login_required()
def admin_delete_subject(request, subject_id):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    subject = get_object_or_404(Subject, id=subject_id)
    subject.delete()
    messages.success(request, 'Subject deleted successfully.')
    return redirect('dashboards:admin_subjects_list')

# ========================= RESULTS MANAGEMENT =========================

@login_required()
def admin_results_dashboard(request):
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    classes_list = SchoolClass.objects.all().order_by('name')
    paginator = Paginator(classes_list, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'dashboards/admin/results_dashboard.html', {
        'classes': page_obj,
        'page_obj': page_obj
    })

@login_required()
def admin_class_results(request, class_id):
    """List students in a class to view their results"""
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    school_class = get_object_or_404(SchoolClass, id=class_id)
    students = User.objects.filter(role=User.Role.STUDENT, student_class=school_class).order_by('last_name', 'first_name')
    
    return render(request, 'dashboards/admin/class_results.html', {
        'school_class': school_class,
        'students': students
    })

@login_required()
def admin_student_result_detail(request, student_id):
    """Show results for a specific student"""
    if request.user.role != User.Role.ADMIN:
        return redirect('accounts:dashboard_redirect')
        
    student = get_object_or_404(User, id=student_id, role=User.Role.STUDENT)
    
    # Logic similar to student_dashboard but for a specific student
    # Get all attempts for the user
    attempts = ExamAttempt.objects.filter(student=student).order_by('-started_at')
    
    # Calculate stats
    total_exams = attempts.count()
    passed_exams = sum(1 for a in attempts if a.score >= (a.exam.passing_marks or 0))
    
    return render(request, 'dashboards/admin/student_result_detail.html', {
        'student': student,
        'attempts': attempts,
        'total_exams': total_exams,
        'passed_exams': passed_exams
    })


@login_required()
def admin_retake_requests(request):
    requests_list = RetakeRequest.objects.all().order_by('-created_at')
    
    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        requests_list = requests_list.filter(status=status_filter)
        
    # Pagination
    paginator = Paginator(requests_list, 10) # Show 10 requests per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'statuses': RetakeRequest._meta.get_field('status').choices,
        'status_filter': status_filter
    }
    return render(request, 'dashboards/admin/retake_requests.html', context)


@login_required()
@require_POST
def update_retake_request_status(request, request_id):
    """Approve or deny a retake request"""
    if request.user.role != User.Role.ADMIN:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    retake_request = get_object_or_404(RetakeRequest, id=request_id)
    action = request.POST.get('action')
    
    if action not in ['approve', 'deny']:
        return JsonResponse({'error': 'Invalid action'}, status=400)
        
    if action == 'approve':
        retake_request.status = 'approved'
        retake_request.reviewed_by = request.user
        retake_request.save()

        ExamAttempt.objects.filter(
            student=retake_request.student,
            exam=retake_request.exam,
            status='submitted'
        ).update(status='archived')
        
        Notification.objects.create(
            sender=request.user,
            recipient=retake_request.student,
            title='Retake Request Approved',
            message=f'Your retake request for exam \"{retake_request.exam.title}\" has been approved.',
            related_exam=retake_request.exam.id
        )
        messages.success(request, f'Retake request for {retake_request.student.get_full_name()} approved.')
        
    elif action == 'deny':
        retake_request.status = 'denied'
        retake_request.reviewed_by = request.user
        retake_request.save()
        
        # Notify student
        Notification.objects.create(
            sender=request.user,
            recipient=retake_request.student,
            title='Retake Request Denied',
            message=f'Your retake request for exam "{retake_request.exam.title}" has been denied.',
            related_exam=retake_request.exam.id
        )
        messages.info(request, f'Retake request for {retake_request.student.get_full_name()} denied.')
        
    return redirect('dashboards:admin_retake_requests')


@login_required()
def admin_system_logs(request): return render(request, 'dashboards/admin/system_logs.html')
@login_required()
def admin_leaderboard(request):
    classes = SchoolClass.objects.all().order_by('name')
    selected_class = None
    leaderboard = []

    class_id = request.GET.get('class')
    if class_id:
        selected_class = get_object_or_404(SchoolClass, id=class_id)
        
        # Calculate leaderboard manually to handle objective + subjective scores correctly
        # Fetch all submitted attempts for this class
        attempts = ExamAttempt.objects.filter(
            exam__school_class=selected_class,
            status='submitted'
        ).annotate(
            sub_score=Sum('answers__subjective_mark__score')
        ).select_related('student')
        
        # Aggregate by student in Python
        student_stats = {}
        for attempt in attempts:
            student = attempt.student
            # Skip if student is not in the selected class (optional, but keeps leaderboard clean)
            if student.student_class_id != selected_class.id:
                continue
                
            total_score = attempt.score + (attempt.sub_score or 0)
            
            if student not in student_stats:
                student_stats[student] = {'total_score': 0, 'exams_count': 0}
            
            student_stats[student]['total_score'] += total_score
            student_stats[student]['exams_count'] += 1
            
        # Build final leaderboard list
        for student, stats in student_stats.items():
            student.average_score = stats['total_score'] / stats['exams_count'] if stats['exams_count'] > 0 else 0
            student.exams_taken = stats['exams_count']
            leaderboard.append(student)
            
        # Sort by average score descending
        leaderboard.sort(key=lambda x: x.average_score, reverse=True)

    return render(request, 'dashboards/admin/leaderboard.html', {
        'classes': classes,
        'selected_class': selected_class,
        'leaderboard': leaderboard
    })
@login_required()
def teacher_subjective_grading(request): return redirect('dashboards:teacher_grading_dashboard')
@login_required()
def teacher_notifications(request): return render(request, 'notifications/list.html')
@login_required()
def student_available_exams(request):
    user = request.user
    now = timezone.now()
    student_class = user.student_class
    
    # Base query: Active & Published
    # Access: Class match OR ExamAccess match
    exams_query = Exam.objects.filter(
        Q(school_class=student_class) | Q(examaccess__student=user),
        is_active=True,
        is_published=True
    ).distinct().order_by('start_time')
    
    available_exams = []
    
      
    # Get latest attempt per exam
    attempts = ExamAttempt.objects.filter(student=user).order_by('exam_id', '-started_at')
    attempts_map = {} # exam_id -> latest attempt
    for attempt in attempts:
        if attempt.exam_id not in attempts_map:
            attempts_map[attempt.exam_id] = attempt
            
    # Get retake requests
    requests_query = RetakeRequest.objects.filter(student=user).order_by('exam_id', '-created_at')
    requests_map = {}
    for req in requests_query:
        if req.exam_id not in requests_map:
            requests_map[req.exam_id] = req
    
    for exam in exams_query:
        latest_attempt = attempts_map.get(exam.id)
        latest_request = requests_map.get(exam.id)

        has_submitted = latest_attempt and latest_attempt.status == 'submitted'
        has_in_progress = latest_attempt and latest_attempt.status == 'in_progress'

        if has_in_progress:
            continue

        exam.has_in_progress = has_in_progress
        exam.retake_status = 'none'
        exam.can_retake = False
        exam.can_request_retake = False

        approved_request = None
        if latest_request and latest_request.status == 'approved':
            approved_request = latest_request
            exam.retake_status = 'approved'

        if has_submitted:
            if not approved_request:
                continue
            if latest_attempt.completed_at and latest_attempt.completed_at >= approved_request.created_at:
                continue

        if has_submitted:
            exam.can_retake = approved_request is not None and not has_in_progress
            exam.can_request_retake = approved_request is None
        else:
            if latest_request:
                exam.retake_status = latest_request.status
                exam.can_retake = (exam.retake_status == 'approved')
                exam.can_request_retake = (exam.retake_status != 'pending' and exam.retake_status != 'approved')
            else:
                exam.can_request_retake = True

        is_expired = exam.end_time < now
        if is_expired and not exam.can_retake:
            continue

        available_exams.append(exam)
        
    paginator = Paginator(available_exams, 9)  # 9 exams per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Also handle search query for pagination links
    search_query = request.GET.get('search', '')
        
    return render(request, 'dashboards/student/available_exams.html', {
        'page_obj': page_obj,
        'search_query': search_query
    })

@login_required()
def student_attempt_history(request):
    user = request.user
    attempts_list = ExamAttempt.objects.filter(student=user).select_related('exam').order_by('-started_at')
    
    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter:
        attempts_list = attempts_list.filter(status=status_filter)
        
    paginator = Paginator(attempts_list, 10) # 10 attempts per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    statuses = ['in_progress', 'submitted', 'interrupted']
    
    return render(request, 'dashboards/student/attempt_history.html', {
        'page_obj': page_obj,
        'statuses': statuses,
        'status_filter': status_filter
    })
@login_required()
def student_class_leaderboard(request):
    user = request.user
    if user.role != User.Role.STUDENT:
        return redirect('accounts:dashboard_redirect')

    school_class = user.student_class

    if not school_class:
        return render(request, 'dashboards/student/class_leaderboard.html', {
            'school_class': None,
            'page_obj': None,
        })

    attempts_qs = ExamAttempt.objects.filter(
        exam__school_class=school_class,
        status='submitted'
    ).annotate(
        sub_score=Sum('answers__subjective_mark__score')
    ).select_related('student')

    student_stats = {}
    for attempt in attempts_qs:
        student = attempt.student
        if student not in student_stats:
            student_stats[student] = {'total_score': 0, 'exams_count': 0}

        total_score = attempt.score + (attempt.sub_score or 0)
        student_stats[student]['total_score'] += total_score
        student_stats[student]['exams_count'] += 1

    leaderboard = []
    for student, stats in student_stats.items():
        if stats['exams_count'] <= 0:
            continue
        avg_score = stats['total_score'] / stats['exams_count']
        leaderboard.append({
            'student': student,
            'avg_score': avg_score,
            'attempt_count': stats['exams_count'],
            'is_self': student.id == user.id,
        })

    leaderboard.sort(key=lambda e: e['avg_score'], reverse=True)

    for idx, entry in enumerate(leaderboard, start=1):
        entry['rank'] = idx

    if not leaderboard:
        page_obj = None
    else:
        paginator = Paginator(leaderboard, 10)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

    return render(request, 'dashboards/student/class_leaderboard.html', {
        'school_class': school_class,
        'page_obj': page_obj,
    })
@login_required()
def student_notifications(request): return render(request, 'notifications/list.html')
@login_required()
def parent_children_list(request):
    children = request.user.children.all().annotate(
        attempts_count=Count('attempts', filter=Q(attempts__status='submitted')),
        avg_score=Avg('attempts__score', filter=Q(attempts__status='submitted'))
    )
    paginator = Paginator(children, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'dashboards/parent/children_list.html', {'page_obj': page_obj})
@login_required()
def parent_child_results(request, child_id):
    child = get_object_or_404(User, id=child_id, role=User.Role.STUDENT)
    
    # Security: Check if child belongs to parent
    if child not in request.user.children.all():
        messages.error(request, "Unauthorized access to student results.")
        return redirect('dashboards:parent_dashboard')
        
    attempts = ExamAttempt.objects.filter(
        student=child, 
        status='submitted'
    ).order_by('-started_at')
    
    paginator = Paginator(attempts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'dashboards/parent/child_results.html', {
        'child': child,
        'page_obj': page_obj
    })
@login_required()
def parent_notifications(request): return render(request, 'notifications/list.html')
@login_required()
def student_request_retake(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    
    reason = None
    if request.method == 'POST':
        reason = request.POST.get('reason')
        
    # Check if already has pending request
    existing = RetakeRequest.objects.filter(student=request.user, exam=exam, status='pending').exists()
    if not existing:
        RetakeRequest.objects.create(student=request.user, exam=exam, reason=reason)
        messages.success(request, 'Retake requested successfully. Please wait for approval.')
    else:
        messages.warning(request, 'You already have a pending request.')
    
    return redirect(request.META.get('HTTP_REFERER', 'dashboards:student_available_exams'))
