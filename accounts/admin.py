from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Student
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

from .models import User, Student, Parent, Teacher

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    list_display = (
        "username",
        'student_class',
        "email",
        "role",
        "is_active",
        "is_approved",
        "profile_preview",
        "date_joined",
    )

    list_filter = ("role", "is_active", "is_approved", "student_class")

    search_fields = ("username", "email", "first_name", "last_name", "student_class")

    ordering = ("-date_joined",)

    fieldsets = (
        ("Account Info", {
            "fields": ("username", "password", "email")
        }),
        ("Personal Info", {
            "fields": (
                "first_name",
                "last_name",
                "phone_number",
                "address",
                "profile_picture",
            )
        }),
        ("Role & Status", {
            "fields": (
                "role",
                "student_class",
                "parents",
                "is_active",
                "is_approved",
                "is_staff",
                "is_superuser",
            )
        }),
        ("Permissions", {
            "fields": ("groups", "user_permissions")
        }),
        ("Dates", {
            "fields": ("last_login", "date_joined")
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username",
                "email",
                "password1",
                "password2",
                "role",
                "is_approved",
            ),
        }),
    )

    filter_horizontal = ("groups", "user_permissions", "parents")

    def profile_preview(self, obj):
        if obj.profile_picture:
            return format_html(
                '<img src="{}" width="35" style="border-radius:50%;" />',
                obj.profile_picture.url
            )
        return "—"

    profile_preview.short_description = "Photo"



@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("username", "admission_number", "student_class", "is_approved")
    list_filter = ("student_class",)
    search_fields = ("username", "admission_number")


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "is_approved")
    search_fields = ("username", "email")


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("username", "email","admission_number", "is_approved")
    search_fields = ("username", "email","admission_number")


# Define fieldsets for non-Student roles (Admin/Staff/Parent)
STAFF_USER_FIELDSETS = (
    (None, {'fields': ('username', 'password')}),
    ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')}),
    ('Role and Status', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser')}),
    ('Permissions', {'fields': ('groups', 'user_permissions')}),
    ('Important dates', {'fields': ('last_login', 'date_joined')}),
)

# Define fieldsets for Student role
STUDENT_USER_FIELDSETS = (
    (None, {'fields': ('username', 'password')}),
    ('Personal Info', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'address')}),
    ('Academic Details', {'fields': ('student_class', 'admission_number', 'parent')}), # student_class is HERE
    ('Status', {'fields': ('is_active',)}),
    ('Emergency Contact', {'fields': ('emergency_contact', 'emergency_phone')}),
)
# from .forms import CustomUserCreationForm # Use the base creation form

User = get_user_model()

# Custom Action for Admin Approval
@admin.action(description='Approve selected users')
def approve_users(modeladmin, request, queryset):
    # Set is_approved and also set is_active to True, as they can now log in
    queryset.update(is_approved=True, is_active=True)

admin.site.site_header = "Muflihun High School Management System"
admin.site.site_title = "Muflihun High School SMS Admin Portal"   
