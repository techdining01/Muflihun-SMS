from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Q
from PIL import Image
from django.utils import timezone 
from django.utils.crypto import get_random_string
from django.contrib.auth.models import BaseUserManager
from django.utils import timezone
import uuid

class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        TEACHER = "TEACHER", "Teacher"
        NON_TEACHER = "NON_TEACHER", "Non-Teacher"
        PARENT = "PARENT", "Parent"
        STUDENT = "STUDENT", "Student"
        BURSAR = "BURSAR", "Bursar"
        SERVICE_PROVIDER = "SERVICE_PROVIDER", "Service-Provider"

    base_role = Role.PARENT


    role = models.CharField(
        max_length=50,
        choices=Role.choices,
        default=Role.STUDENT,
        help_text="Role of the user in the school management system."
        )
    
    
    admission_number = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='Admission Number',
        blank=True, 
        null=True
    )

    student_class = models.ForeignKey(
        'exams.SchoolClass', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='students',
        help_text="The academic class this student belongs to."
    )

    parents = models.ManyToManyField(
        'self', # Self-referential Many-to-Many relationship
        limit_choices_to=Q(role='PARENT'), # Only allow users with role='PARENT'
        symmetrical=False,
        blank=True,
        related_name='children', # Access: parent_user.children.all()
        verbose_name='Parent/Guardian'
    )

    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)

    profile_picture = models.ImageField(
        upload_to='user_profiles/',     # Saves files to /media/user_profiles/ in S3
        null=True, 
        blank=True,
        default='user_profiles/default_profile.png',
        help_text="User profile image"
    )

     # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
  

    def generate_unique_reg_no(self):
        year = timezone.now().year
        random_part = get_random_string(length=5).upper()

        if self.role == User.Role.ADMIN or self.role == User.Role.TEACHER or self.role == User.Role.NON_TEACHER or self.role == User.Role.BURSAR:
            return f"MHS/STF/{year}/{random_part}"

        if self.role == User.Role.STUDENT:
            return f"MHS/{year}/{random_part}"

        return None  # parent gets nothing


    def create_unique_reg_no(self):
        reg_no = self.generate_unique_reg_no()
        if not reg_no:
            return None

        while User.objects.filter(admission_number=reg_no).exists():
            reg_no = self.generate_unique_reg_no()
        return reg_no

    def save(self, *args, **kwargs):
        if not self.pk:
            self.role = self.base_role

        if self.email:
            self.email = self.email.lower()

        # ✅ Generate admission number ONLY for non-parent users
        if (
            self.role in [User.Role.STUDENT, User.Role.TEACHER, User.Role.ADMIN]
            and not self.admission_number
        ):
            self.admission_number = self.create_unique_reg_no()

        # Resize profile picture
        if self.profile_picture and hasattr(self.profile_picture, 'path'):
            try:
                img = Image.open(self.profile_picture.path)
                if img.height > 300 or img.width > 300:
                    img.thumbnail((300, 300))
                    img.save(self.profile_picture.path, optimize=True, quality=85)
            except (FileNotFoundError, ValueError):
                pass

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"
    

# ==============================================================================

class CustomRoleManager(BaseUserManager):
    """
    A base class for role managers, inheriting BaseUserManager 
    for compatibility with Django's authentication system and email normalization.
    """
    
    # Required method inherited from BaseUserManager
    def normalize_email(self, email):
        return BaseUserManager.normalize_email(email)

    # Required method inherited from BaseUserManager
    def get_queryset(self):
        # This will be overridden in the specific role managers below
        return super().get_queryset()
        
    # These methods are often required if you create users directly via the manager
    def create_user(self, username, email, password=None, **extra_fields):
        # A minimal implementation
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)

        # ✅ Ensure username is unique
        if not username:
            username = f"user_{uuid.uuid4().hex[:10]}"
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        # The role filter is applied by the subclass's manager
        user.save(using=self._db)
        return user


# ==============================================================================
# 2. Role-Specific Managers
# ==============================================================================

class StudentManager(CustomRoleManager):
    """Custom manager for the Student proxy model."""
    def get_queryset(self):
        return super().get_queryset().filter(role=User.Role.STUDENT)

class ParentManager(CustomRoleManager):
    """Custom manager for the Parent proxy model."""
    def get_queryset(self):
        # CRITICAL: Filters the User queryset to only include PARENT roles
        return super().get_queryset().filter(role=User.Role.PARENT)

class TeacherManager(CustomRoleManager):
    """Custom manager for the Teacher proxy model."""
    def get_queryset(self):
        # CRITICAL: Filters the User queryset to only include TEACHER roles
        return super().get_queryset().filter(role=User.Role.TEACHER)

# ==============================================================================
# 3. Proxy Models
# ==============================================================================

class Student(User):
    base_role = User.Role.STUDENT
  
    objects = StudentManager()

    class Meta:
        verbose_name = "Student"
        verbose_name_plural = "Students"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
     
    
class Parent(User):
    """
    Proxy model for Parent/Guardian users.
    Filters the base User model to only include users with the PARENT role.
    """
    base_role = User.Role.PARENT
    
    # CRITICAL: Assign the custom manager to ensure proper filtering.
    # Assumes ParentManager class is defined above/imported correctly.
    objects = ParentManager() 

    class Meta:
        proxy = True  # Defines this as a proxy model (no new table created)
        verbose_name = "Parent/Guardian"
        verbose_name_plural = "Parents/Guardians"

    def get_full_name(self):
        # A utility method specific to this role, if needed.
        return f"{self.first_name} {self.last_name}"


class Teacher(User):
    """
    Proxy model for Staff users (Teachers, Non-Teaching Staff).
    Filters the base User model to only include users with the TEACHER role.
    """
    base_role = User.Role.TEACHER
    
    # CRITICAL: Assign the custom manager to ensure proper filtering.
    # Assumes TeacherManager class is defined above/imported correctly.
    objects = TeacherManager()

    class Meta:
        proxy = True
        verbose_name = "Staff Member"
        verbose_name_plural = "Staff Members"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

   



   
