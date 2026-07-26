from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from exams.models import SchoolClass
import os


class Command(BaseCommand):
    help = "Ensure at least one superuser exists"

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            return
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "super")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "super@example.com")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "superpassword")
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
            role=User.Role.ADMIN,
        )
        user.is_approved = True
        user.is_superuser = True
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created."))

