from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Q, Sum
import uuid


class SchoolClass(models.Model):
    LEVEL_CHOICES = [
        ('kindergarten', 'Kindergarten'),
        ('nursery', 'Nursery'),
        ('primary', 'Primary'),
        ('junior_secondary', 'Junior Secondary'),
        ('senior_secondary', 'Senior Secondary'),
    ]

    name = models.CharField(max_length=100, unique=True)
    level = models.CharField(
        max_length=20, choices=LEVEL_CHOICES, 
        default='Kindergarten'
    )
   
    academic_year = models.TextField(blank=False)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="class_teacher"
    )
    assistant_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assistant_class_teacher"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Classes"
        ordering = ['name', 'academic_year']
    
    def __str__(self):
        return f'{self.name} ({self.academic_year})'    


class Subject(models.Model):
    name = models.CharField(max_length=100)
    classes = models.ManyToManyField(SchoolClass, related_name='subjects', blank=True)    
    description = models.TextField(blank=True)
    department = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_subjects')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name}"


class Exam(models.Model):
    TERM_CHOICES = [
        ('first', 'First Term'),
        ('second', 'Second Term'),
        ('third', 'Third Term'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text="e.g. First Term Mathematics Exam for JSS1")
    term = models.CharField(max_length=10, choices=TERM_CHOICES, default='first')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='class_exam')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    duration = models.PositiveIntegerField(help_text='Minutes')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False)
    allow_retake = models.BooleanField(default=False)
    requires_payment = models.BooleanField(default=False)
    price = models.PositiveIntegerField(default=0)
    passing_marks = models.PositiveIntegerField(default=40, help_text="Minimum marks required to pass")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def total_marks(self):
        return self.questions.aggregate(total=Sum('marks'))['total'] or 0


class ExamAccess(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    reason = models.TextField()
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="exam_mercy_grants"
    )
    via_payment = models.BooleanField(default=False)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "exam")


class Question(models.Model):
    EXAM_TYPES = (
        ('objective','Objective'),
        ('subjective','Subjective'),
    )
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    type = models.CharField(max_length=20, choices=EXAM_TYPES)
    marks = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.exam.title} - Q{self.order}"


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.text


class ExamAttempt(models.Model):

    ATTEMPT_STATUS = (
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted'),
        ('archived', 'Archived'),
        ('expired', 'Expired'),
        ('interrupted', 'Interrupted'),
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attempts"
    )

    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name="exam_attempts"
    )

    score = models.PositiveIntegerField(
        default=0,
        help_text="Objective score only"
    )

    status = models.CharField(
        max_length=20,
        choices=ATTEMPT_STATUS,
        default='in_progress'
    )

    verification_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    is_submitted = models.BooleanField(default=False)
    retake_allowed = models.BooleanField(default=False)

    question_order = models.JSONField(default=list)
    remaining_seconds = models.PositiveIntegerField(help_text="Remaining time in seconds")

    interruption_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Browser closed, power outage, network lost, etc."
    )

    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'exam'],
                condition=models.Q(status__in=['in_progress', 'interrupted']),
                name='unique_active_attempt_per_exam'
            )
        ]
        ordering = ['-started_at']

    @property
    def subjective_score(self):
        return (
            self.answers
            .filter(subjective_mark__isnull=False)
            .aggregate(total=Sum("subjective_mark__score"))
            .get("total")
            or 0
        )

    @property
    def total_score(self):
        return self.score + self.subjective_score
    
    @property
    def percentage(self):
        total_marks = self.exam.total_marks
        if total_marks > 0:
            return round((self.total_score / total_marks) * 100, 1)
        return 0

    @property
    def grade(self):
        pct = self.percentage
        if pct >= 70:
            return 'A'
        elif pct >= 60:
            return 'B'
        elif pct >= 50:
            return 'C'
        elif pct >= 45:
            return 'D'
        elif pct >= 40:
            return 'E'
        else:
            return 'F'

    @property
    def is_fully_graded(self):
        total_subjective = self.answers.filter(
            question__type="subjective"
        ).count()

        graded = self.answers.filter(
            question__type="subjective",
            subjective_mark__isnull=False
        ).count()

        return total_subjective == graded

    def save_progress(self, seconds_left, reason=None):
        self.remaining_seconds = max(seconds_left, 0)
        if reason:
            self.interruption_reason = reason
            self.status = 'interrupted'
        self.save(update_fields=[
            'remaining_seconds',
            'interruption_reason',
            'status',
            'last_activity_at'
        ])

    def can_resume(self):
        now = timezone.now()
        return (
            self.status in ['in_progress', 'interrupted']
            and not self.is_submitted
            and now <= self.exam.end_time
            and self.remaining_seconds > 0
        )

    def can_retake(self):
        return self.retake_allowed or self.exam.allow_retake

    def archive_for_retake(self):
        self.status = 'archived'
        self.save(update_fields=['status'])


class StudentAnswer(models.Model):
    attempt = models.ForeignKey(
        ExamAttempt,
        on_delete=models.CASCADE,
        related_name="answers"
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE
    )
    
    answer_text = models.TextField(blank=True)
    selected_choice = models.ForeignKey(
        Choice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        unique_together = ('attempt', 'question')


class SubjectiveMark(models.Model):
    answer = models.OneToOneField(
        StudentAnswer,
        on_delete=models.CASCADE,
        related_name="subjective_mark"
    )

    score = models.PositiveIntegerField()
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    marked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Mark for {self.answer.question}"


class PTARequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        RESOLVED = 'RESOLVED', 'Resolved'

    class RequestType(models.TextChoices):
        MEETING = 'MEETING', 'Meeting Request'
        ATTENTION = 'ATTENTION', 'Attention Needed'
        MESSAGE = 'MESSAGE', 'General Message'

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        limit_choices_to=Q(role='PARENT'), 
        related_name='pta_sent'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        limit_choices_to=Q(role='STAFF'), 
        related_name='pta_received'
    )
    request_type = models.CharField(max_length=10, choices=RequestType.choices)
    title = models.CharField(max_length=100)
    message = models.TextField()
    
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def recipient_name(self):
        return self.recipient.get_full_name() if self.recipient else "N/A"

    def __str__(self):
        return f"{self.parent.username} - {self.get_request_type_display()} to {self.recipient.username}"
    

class RetakeRequest(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, limit_choices_to={"role": "STUDENT"}, related_name='retake_requests')
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='retake_requests')
    reason = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=(("pending", "Pending"), ("approved", "Approved"), ("denied", "Denied")),
        default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="retake_reviews")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.username} → {self.exam.title} ({self.status})"


class Notification(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_notifications')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    related_exam = models.IntegerField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']

    def mark_read(self):
        self.is_read = True
        self.save()

    def __str__(self):
        return f"{self.title} - to {self.recipient.username}"


class Broadcast(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='broadcasts')
    target_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, blank=True, null=True, related_name='broadcasts')
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='received_broadcasts')
    target_role = models.CharField(max_length=20, blank=True, default='', help_text="Optional target role: 'students' or 'parents'")
    title = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        target = self.target_class.name if self.target_class else (self.target_role or 'All')
        return f"Broadcast by {self.sender.username} to {target}"
    

class SystemLog(models.Model):
    LEVEL_CHOICES = (
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    )
    
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    source = models.CharField(max_length=100)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.level} | {self.source}"


class ChatMessage(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_messages')
    message = models.TextField()
    attachment = models.FileField(upload_to='chat_attachments/', null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.message[:20]}"
