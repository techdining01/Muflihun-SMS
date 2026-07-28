from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Q, Avg
import uuid


# ==================== QUESTION BANK MODELS ====================

class QuestionCategory(models.Model):
    """Categories for organizing questions in the bank"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#3498db')  # Hex color
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Question Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.name


class QuestionTag(models.Model):
    """Tags for filtering and organizing questions"""
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class QuestionBank(models.Model):
    """Repository for reusable questions across exams"""
    QUESTION_TYPES = [
        ('objective', 'Objective (MCQ)'),
        ('subjective', 'Subjective (Essay)'),
        ('short_answer', 'Short Answer'),
    ]
    
    text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    category = models.ForeignKey(QuestionCategory, on_delete=models.SET_NULL, null=True)
    marks = models.PositiveIntegerField(default=1)
    difficulty = models.CharField(max_length=10, choices=[
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ], default='medium')
    tags = models.ManyToManyField(QuestionTag, blank=True, related_name='questions')
    explanation = models.TextField(blank=True, help_text="Explanation for correct answer")
    image = models.ImageField(upload_to='question_images/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_published = models.BooleanField(default=False)
    school_class = models.ForeignKey('exams.SchoolClass', on_delete=models.SET_NULL, null=True, blank=True)
    subject = models.ForeignKey('exams.Subject', on_delete=models.SET_NULL, null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'question_type']),
            models.Index(fields=['created_by']),
        ]
    
    def __str__(self):
        return f"{self.text[:50]}... ({self.question_type})"


class QuestionChoice(models.Model):
    """Choices for objective questions in the bank"""
    question = models.ForeignKey(QuestionBank, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
    
    def __str__(self):
        return self.text[:50]


# ==================== ANALYTICS MODELS ====================

class ExamAnalytics(models.Model):
    """Stores analytics data for each exam"""
    exam = models.OneToOneField('exams.Exam', on_delete=models.CASCADE, related_name='analytics')
    total_attempts = models.PositiveIntegerField(default=0)
    total_passed = models.PositiveIntegerField(default=0)
    average_score = models.FloatField(default=0.0)
    highest_score = models.FloatField(default=0.0)
    lowest_score = models.FloatField(default=0.0)
    average_time_taken = models.PositiveIntegerField(default=0)  # in seconds
    pass_rate = models.FloatField(default=0.0)  # percentage
    last_updated = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Analytics - {self.exam.title}"


class StudentPerformance(models.Model):
    """Tracks individual student performance across exams"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='performances')
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE)
    attempt_number = models.PositiveIntegerField(default=1)
    score = models.FloatField()
    total_marks = models.FloatField()
    percentage = models.FloatField()
    time_taken = models.PositiveIntegerField()  # in seconds
    status = models.CharField(max_length=20, choices=[
        ('passed', 'Passed'),
        ('failed', 'Failed'),
    ])
    attempted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('student', 'exam', 'attempt_number')
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['student', 'exam']),
        ]
    
    def __str__(self):
        return f"{self.student.username} - {self.exam.title}"


# ==================== EXAM RETAKES/REVIEW MODELS ====================

class AttemptHistory(models.Model):
    """Tracks all attempts for an exam by a student"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE)
    attempt_number = models.PositiveIntegerField()
    score = models.FloatField()
    total_marks = models.FloatField()
    percentage = models.FloatField()
    status = models.CharField(max_length=20, choices=[
        ('passed', 'Passed'),
        ('failed', 'Failed'),
    ])
    time_taken = models.PositiveIntegerField()  # in seconds
    submitted_at = models.DateTimeField()
    can_retake = models.BooleanField(default=False)
    retake_available_from = models.DateTimeField(null=True, blank=True)
    attempt = models.OneToOneField('exams.ExamAttempt', on_delete=models.CASCADE, null=True)
    
    class Meta:
        unique_together = ('student', 'exam', 'attempt_number')
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['student', 'exam']),
        ]
    
    def __str__(self):
        return f"{self.student.username} - {self.exam.title} (Attempt {self.attempt_number})"


# ==================== ADVANCED GRADING MODELS ====================

class GradingRubric(models.Model):
    """Rubric template for advanced grading"""
    name = models.CharField(max_length=200)
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE, related_name='rubrics', null=True, blank=True)
    description = models.TextField(blank=True)
    total_points = models.PositiveIntegerField(default=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class RubricCriteria(models.Model):
    """Individual criteria/dimension in a rubric"""
    rubric = models.ForeignKey(GradingRubric, on_delete=models.CASCADE, related_name='criteria')
    name = models.CharField(max_length=200)
    description = models.TextField()
    max_points = models.PositiveIntegerField()
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        verbose_name_plural = "Rubric Criteria"
        ordering = ['order']
    
    def __str__(self):
        return f"{self.rubric.name} - {self.name}"


class RubricScore(models.Model):
    """Scoring rubric with performance levels"""
    criteria = models.ForeignKey(RubricCriteria, on_delete=models.CASCADE, related_name='scores')
    level = models.CharField(max_length=100)  # e.g., "Excellent", "Good", "Fair", "Poor"
    points = models.PositiveIntegerField()
    description = models.TextField()
    
    class Meta:
        ordering = ['-points']
    
    def __str__(self):
        return f"{self.criteria.name} - {self.level} ({self.points}pts)"


class RubricGrade(models.Model):
    """Actual grades given using a rubric"""
    attempt = models.ForeignKey('exams.ExamAttempt', on_delete=models.CASCADE, related_name='rubric_grades')
    rubric = models.ForeignKey(GradingRubric, on_delete=models.CASCADE)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    total_score = models.FloatField(default=0.0)
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-graded_at']
    
    def __str__(self):
        return f"Rubric Grade - {self.submission.student.username}"


class RubricCriteriaGrade(models.Model):
    """Grade for each criterion in the rubric"""
    rubric_grade = models.ForeignKey(RubricGrade, on_delete=models.CASCADE, related_name='criteria_grades')
    criteria = models.ForeignKey(RubricCriteria, on_delete=models.CASCADE)
    selected_score = models.ForeignKey(RubricScore, on_delete=models.SET_NULL, null=True, blank=True)
    points_awarded = models.FloatField(default=0.0)
    comment = models.TextField(blank=True)
    
    class Meta:
        unique_together = ('rubric_grade', 'criteria')
        ordering = ['criteria__order']
    
    def __str__(self):
        return f"{self.criteria.name} - {self.points_awarded}pts"


# ==================== EXAM SCHEDULING MODELS ====================

class ExamSchedule(models.Model):
    """Schedule for automatic exam opening/closing"""
    exam = models.OneToOneField('exams.Exam', on_delete=models.CASCADE, related_name='schedule')
    scheduled_date = models.DateTimeField(help_text="Date and time when exam will automatically open")
    auto_open = models.BooleanField(default=False)
    auto_close = models.BooleanField(default=False)
    close_at = models.DateTimeField(null=True, blank=True, help_text="Time when exam will auto-close")
    auto_submit_at_time = models.BooleanField(default=True, help_text="Auto-submit if student still taking exam")
    notify_before_minutes = models.PositiveIntegerField(default=15, help_text="Send notification X minutes before")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['scheduled_date']
    
    def __str__(self):
        return f"Schedule - {self.exam.title} at {self.scheduled_date}"


class ScheduledNotification(models.Model):
    """Track which students were notified about scheduled exams"""
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification_sent_at = models.DateTimeField(auto_now_add=True)
    was_successful = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('exam', 'student')
    
    def __str__(self):
        return f"{self.student.username} - {self.exam.title}"


# ==================== CERTIFICATE MODELS ====================

class Certificate(models.Model):
    """Certificate issued to students"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='certificates')
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE)
    attempt = models.OneToOneField('exams.ExamAttempt', on_delete=models.CASCADE, null=True, blank=True)
    certificate_number = models.CharField(max_length=50, unique=True)
    score = models.FloatField()
    total_marks = models.FloatField()
    percentage = models.FloatField()
    grade = models.CharField(max_length=10, blank=True)  # e.g., A, B, C, etc.
    issued_at = models.DateTimeField(auto_now_add=True)
    pdf_file = models.FileField(upload_to='certificates/', blank=True, null=True)
    is_digitally_verified = models.BooleanField(default=False)
    verification_code = models.CharField(max_length=50, unique=True)
    
    class Meta:
        unique_together = ('student', 'exam')
        ordering = ['-issued_at']
    
    def __str__(self):
        return f"Certificate - {self.student.username} ({self.exam.title})"


class CertificateTemplate(models.Model):
    """Custom certificate templates"""
    name = models.CharField(max_length=200)
    school = models.CharField(max_length=300)
    logo = models.ImageField(upload_to='certificate_logos/', blank=True, null=True)
    background = models.ImageField(upload_to='certificate_backgrounds/', blank=True, null=True)
    text_color = models.CharField(max_length=7, default='#000000')
    font_family = models.CharField(max_length=50, default='Arial')
    custom_message = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-is_default', '-created_at']
    
    def __str__(self):
        return self.name


# ==================== BULK OPERATIONS MODELS ====================

class BulkImportJob(models.Model):
    """Track bulk import jobs (students, exams, questions)"""
    IMPORT_TYPES = [
        ('students', 'Students'),
        ('exams', 'Exams'),
        ('questions', 'Questions'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    import_type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    csv_file = models.FileField(upload_to='bulk_imports/')
    exam = models.ForeignKey('exams.Exam', on_delete=models.SET_NULL, null=True, blank=True, related_name='import_jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_rows = models.PositiveIntegerField(default=0)
    successful_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_import_type_display()} - {self.status}"


class BulkExportJob(models.Model):
    """Track bulk export jobs"""
    EXPORT_TYPES = [
        ('results', 'Exam Results'),
        ('performance', 'Student Performance'),
        ('attendance', 'Attendance Report'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    export_type = models.CharField(max_length=20, choices=EXPORT_TYPES)
    exam = models.ForeignKey('exams.Exam', on_delete=models.CASCADE, null=True, blank=True)
    exported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    file_format = models.CharField(max_length=10, choices=[
        ('csv', 'CSV'),
        ('xlsx', 'Excel'),
        ('pdf', 'PDF'),
    ], default='csv')
    export_file = models.FileField(upload_to='bulk_exports/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_export_type_display()} - {self.status}"


# ==================== ADVANCED PERMISSIONS MODELS ====================

class Role(models.Model):
    """Custom roles for advanced permission management"""
    ROLE_TYPES = [
        ('teacher', 'Teacher'),
        ('department_head', 'Department Head'),
        ('exam_coordinator', 'Exam Coordinator'),
        ('admin', 'Admin'),
        ('bursar', 'Bursar'),
        ('custom', 'Custom'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    role_type = models.CharField(max_length=20, choices=ROLE_TYPES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_roles')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Permission(models.Model):
    """Granular permissions that can be assigned to roles"""
    PERMISSION_CATEGORIES = [
        ('exam_management', 'Exam Management'),
        ('grading', 'Grading'),
        ('analytics', 'Analytics'),
        ('student_management', 'Student Management'),
        ('question_bank', 'Question Bank'),
        ('certificate', 'Certificate'),
        ('bulk_operations', 'Bulk Operations'),
    ]
    
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=PERMISSION_CATEGORIES)
    
    class Meta:
        ordering = ['category', 'code']
    
    def __str__(self):
        return self.name


class RolePermission(models.Model):
    """Link between roles and permissions"""
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ('role', 'permission')
    
    def __str__(self):
        return f"{self.role.name} - {self.permission.code}"


class UserRole(models.Model):
    """Assign roles to users"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assigned_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='role_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Optional expiry for temporary roles
    
    class Meta:
        unique_together = ('user', 'role')
        ordering = ['-assigned_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.role.name}"


# ==================== WEB PUSH SUBSCRIPTION ====================

class PushSubscription(models.Model):
    """Stores browser push subscription endpoints per user"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    p256dh = models.TextField()
    auth = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} — {self.endpoint[:60]}"


# ==================== NOTIFICATION MODELS ====================

class Notification(models.Model):
    """Notification model (from Phase 4, included for completeness)"""
    CATEGORIES = [
        ('info', 'Information'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]
    
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORIES, default='info')
    is_read = models.BooleanField(default=False)
    related_exam = models.ForeignKey('exams.Exam', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.recipient.username}"

# ==================== CHAT (CONFERENCE) MODELS ====================

class ChatRoom(models.Model):
    class RoomType(models.TextChoices):
        GROUP = 'GROUP', 'Group Chat'
        CONFERENCE = 'CONFERENCE', 'Conference Chat'

    name = models.CharField(max_length=120, unique=True)
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.GROUP)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_chat_rooms')
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='chat_rooms', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class ChatRoomMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    attachment = models.FileField(upload_to='room_attachments/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.room.name} - {self.sender.username}: {self.message[:20]}"

class ChatRoomReadStatus(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='read_statuses')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='room_read_statuses')
    last_read_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('room', 'user')

    def __str__(self):
        return f"{self.user.username} read {self.room.name} at {self.last_read_at}"
