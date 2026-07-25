from django.urls import path
from . import views
from . import exam_views
from . import grading_views
from . import notification_views
from . import views_phase5
from . import views_backup


app_name = 'dashboards'

urlpatterns = [
    # Authentication
    path('', views.cbt_exam, name='cbt'),
    path('about/', views.about_page, name='about'),
    
    # Admin Dashboard
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/classes/', views.admin_classes_list, name='admin_classes_list'),
    path('admin/classes/create/', views.admin_create_class, name='admin_create_class'),
    path('admin/classes/<int:class_id>/edit/', views.admin_edit_class, name='admin_edit_class'),
    path('admin/classes/<int:class_id>/delete/', views.admin_delete_class, name='admin_delete_class'),
    path('admin/subjects/', views.admin_subjects_list, name='admin_subjects_list'),
    path('admin/subjects/create/', views.admin_create_subject, name='admin_create_subject'),
    path('admin/subjects/<int:subject_id>/edit/', views.admin_edit_subject, name='admin_edit_subject'),
    path('admin/subjects/<int:subject_id>/delete/', views.admin_delete_subject, name='admin_delete_subject'),
    path('admin/results/', views.admin_results_dashboard, name='admin_results_dashboard'),
    path('admin/results/class/<int:class_id>/', views.admin_class_results, name='admin_class_results'),
    path('admin/results/student/<int:student_id>/', views.admin_student_result_detail, name='admin_student_result_detail'),
    path('admin/exams/', views.admin_exams_list, name='admin_exams_list'),
    path('admin/students/', views.admin_students_list, name='admin_students_list'),
    path('admin/students/create/', views.admin_create_student, name='admin_create_student'),
    path('admin/students/<int:student_id>/edit/', views.admin_edit_student, name='admin_edit_student'),
    path('admin/students/<int:student_id>/delete/', views.admin_delete_student, name='admin_delete_student'),
    path('broadcast/', views.broadcast_center, name='broadcast_center'),
    path('admin/retake-requests/', views.admin_retake_requests, name='admin_retake_requests'),
    path('admin/retake-requests/<int:request_id>/update/', views.update_retake_request_status, name='update_retake_request_status'),
    path('admin/system-logs/', views.admin_system_logs, name='admin_system_logs'),
    path('admin/backup-restore/', views_backup.admin_backup_restore, name='admin_backup_restore'),
    path('admin/backup/trigger/', views_backup.trigger_backup, name='trigger_backup'),
    path('admin/backup/restore/', views_backup.trigger_restore, name='trigger_restore'),
    path('admin/backup/delete/', views_backup.delete_backup, name='delete_backup'),
    path('admin/leaderboard/', views.admin_leaderboard, name='admin_leaderboard'),
    
    # Teacher Dashboard
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/exams/', views.teacher_exams_list, name='teacher_exams_list'),
    path('teacher/exams/', views.teacher_exams_list, name='teacher_exams'),  # Alias for templates
    path('teacher/grading/', views.teacher_subjective_grading, name='teacher_subjective_grading'),
    path('teacher/notifications/', views.teacher_notifications, name='teacher_notifications'),
    
    # Student Dashboard
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('student/exams/', views.student_available_exams, name='student_available_exams'),
    path('student/attempts/', views.student_attempt_history, name='student_attempt_history'),
    path('student/leaderboard/', views.student_class_leaderboard, name='student_class_leaderboard'),
    path('student/notifications/', views.student_notifications, name='student_notifications'),
    
    # Parent Dashboard
    path('parent/', views.parent_dashboard, name='parent_dashboard'),
    path('parent/children/', views.parent_children_list, name='parent_children_list'),
    path('parent/child/<int:child_id>/results/', views.parent_child_results, name='parent_child_results'),
    path('parent/notifications/', views.parent_notifications, name='parent_notifications'),
    
    # Notification Actions
    path('notification/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/read-all/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    
    # Phase 4: Notifications (WebSocket + API)
    path('notifications/', notification_views.notifications_list, name='notifications_list'),
    path('api/notifications/unread/', notification_views.get_unread_notifications, name='get_unread_notifications'),
    path('api/notifications/mark-read/', notification_views.mark_as_read, name='mark_as_read'),
    path('api/notifications/mark-all-read/', notification_views.mark_all_as_read, name='mark_all_as_read'),
    path('api/notifications/<int:notification_id>/delete/', notification_views.delete_notification, name='delete_notification'),
    path('notification/<int:notification_id>/detail/', notification_views.notification_detail, name='notification_detail'),

    # Web Push
    path('api/push/subscribe/', notification_views.push_subscribe, name='push_subscribe'),
    path('api/push/unsubscribe/', notification_views.push_unsubscribe, name='push_unsubscribe'),
    path('api/push/vapid-public-key/', notification_views.push_vapid_public_key, name='push_vapid_public_key'),
    
    # ========================= PHASE 2: EXAM TAKING =========================
    # Exam taking interface
    path('exam/<int:exam_id>/start/', exam_views.start_exam, name='start_exam'),
    path('exam/<int:exam_id>/begin/', exam_views.create_exam_attempt, name='create_exam_attempt'),
    path('exam/attempt/<int:attempt_id>/take/', exam_views.take_exam, name='take_exam'),
    path('exam/attempt/<int:attempt_id>/answer/', exam_views.save_answer, name='save_answer'),
    path('exam/attempt/<int:attempt_id>/resume/', exam_views.resume_exam, name='resume_exam'),
    path('exam/attempt/<int:attempt_id>/submit/', exam_views.submit_exam, name='submit_exam'),
    path('exam/attempt/<int:attempt_id>/result/', exam_views.exam_result, name='exam_result'),
    path('exam/attempt/<int:attempt_id>/interrupt/', exam_views.interrupt_exam, name='interrupt_exam'),
    
    # Exam management
    path('exam/<int:exam_id>/', views.exam_detail, name='exam_detail'),
    path('exam/<int:exam_id>/publish/', views.publish_exam, name='publish_exam'),
    path('exam/<int:exam_id>/unpublish/', views.unpublish_exam, name='unpublish_exam'),
    path('exam/create/', views.create_exam, name='create_exam'),
    path('exam/<int:exam_id>/edit/', views.edit_exam, name='edit_exam'),
    path('exam/<int:exam_id>/question/add/', views.add_question, name='add_question'),
    path('question/<int:question_id>/edit/', views.edit_question, name='edit_question'),
    path('question/<int:question_id>/delete/', views.delete_question, name='delete_question'),
    path('exam/<int:exam_id>/delete/', views.delete_exam, name='delete_exam'),
    path('choice/<int:choice_id>/delete/', views.delete_choice_ajax, name='delete_choice_ajax'),

    # Student Retake
    path('student/retake/create/<int:exam_id>/', views.student_request_retake, name='student_request_retake'),

    # Chat
    path('chat/', views.chat_index, name='chat_list'), # Kept name for compatibility
    path('chat/api/conversations/', views.chat_api_conversations, name='chat_api_conversations'),
    path('chat/api/messages/<str:chat_type>/<int:target_id>/', views.chat_api_messages, name='chat_api_messages'),
    path('chat/api/send/', views.chat_api_send, name='chat_api_send'),
    path('chat/api/room/create/', views.chat_api_create_room, name='chat_api_create_room'),
    path('chat/dashboard/', views.chat_index, name='chat_dashboard'), # Kept for backward compatibility
    
    # ========================= PHASE 3: GRADING & RESULTS =========================
    # Teacher grading
    path('teacher/grading/dashboard/', grading_views.teacher_grading_dashboard, name='teacher_grading_dashboard'),
    path('exam/<int:exam_id>/grade/', grading_views.grade_subjective_answers, name='grade_subjective_answers'),
    path('grade/submit/', grading_views.submit_subjective_grade, name='submit_subjective_grade'),
    
    # Results viewing
    path('result/<int:attempt_id>/detail/', grading_views.student_result_detail, name='student_result_detail'),
    path('result/<int:attempt_id>/parent/', grading_views.parent_child_result, name='parent_child_result'),
    path('result/<int:attempt_id>/pdf/', grading_views.download_result_pdf, name='download_result_pdf'),
    
    # Analytics
    path('exam/<int:exam_id>/analytics/', grading_views.exam_analytics, name='exam_analytics'),
    
    # ========================= PHASE 5: ENTERPRISE FEATURES =========================
    # ANALYTICS VIEWS
    path('analytics/', views_phase5.analytics_dashboard, name='analytics_dashboard'),
    path('analytics/exam/<int:exam_id>/', views_phase5.exam_analytics, name='exam_analytics_phase5'),
    path('analytics/student/<int:student_id>/', views_phase5.student_performance_detail, name='student_performance_detail'),
    path('api/analytics/statistics/<int:exam_id>/', views_phase5.api_exam_statistics, name='api_exam_statistics'),
    
    # GRADING & RUBRICS VIEWS
    path('rubrics/', views_phase5.rubric_list, name='rubric_list'),
    path('rubrics/<int:rubric_id>/', views_phase5.rubric_detail, name='rubric_detail'),
    path('rubrics/create/', views_phase5.rubric_create, name='rubric_create'),
    path('rubrics/<int:rubric_id>/edit/', views_phase5.rubric_edit, name='rubric_edit'),
    
    # SCHEDULING VIEWS
    path('schedule/exam/<int:exam_id>/', views_phase5.schedule_exam_view, name='schedule_exam'),
    
    # CERTIFICATE VIEWS
    path('certificates/', views_phase5.certificate_list, name='certificate_list'),
    path('certificates/<int:certificate_id>/', views_phase5.certificate_detail, name='certificate_detail'),
    path('certificates/<int:certificate_id>/download/', views_phase5.certificate_download, name='certificate_download'),
    path('certificates/batch-issue/<int:exam_id>/', views_phase5.batch_issue_certificates, name='batch_issue_certificates'),
    
    # BULK OPERATIONS VIEWS
    path('bulk/import/', views_phase5.bulk_import_view, name='bulk_import'),
    path('bulk/import/<int:job_id>/', views_phase5.bulk_import_job_detail, name='bulk_import_job_detail'),
    path('bulk/export/', views_phase5.bulk_export_view, name='bulk_export'),
    path('bulk/export/<int:job_id>/', views_phase5.bulk_export_job_detail, name='bulk_export_job_detail'),
    path('bulk/template/<str:format_type>/', views_phase5.download_import_template, name='download_import_template'),
    
    # PERMISSION & ROLE MANAGEMENT VIEWS
    path('roles/', views_phase5.role_management, name='role_management'), 
    path('roles/assign/<int:user_id>/', views_phase5.assign_role_view, name='assign_role'),
    path('permissions/', views_phase5.permission_list, name='permission_list'),
    
    # QUESTION BANK VIEWS
    path('questions/', views_phase5.question_bank_list, name='question_bank_list'),
    path('questions/<int:question_id>/', views_phase5.question_bank_detail, name='question_bank_detail'),
    path('questions/create/', views_phase5.question_bank_create, name='question_bank_create'),
    path('questions/<int:question_id>/edit/', views_phase5.question_bank_edit, name='question_bank_edit'),
]
