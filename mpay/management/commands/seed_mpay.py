from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal

from mpay.models import ProductCategory, Product
from exams.models import SchoolClass  


class Command(BaseCommand):
    help = "Seed BrillsPay with categories and class-based products"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Seeding BrillsPay data..."))

        categories = ["JSS1", "JSS2", "JSS3", "SSS1", "SSS2", "SSS3"]

        with transaction.atomic():

            # -------------------------
            # Create Categories
            # -------------------------
            category_map = {}
            for class_name in categories:
                category, _ = ProductCategory.objects.get_or_create(
                    class_name=class_name,
                    defaults={"slug": class_name.lower()}
                )
                category_map[class_name] = category

            # -------------------------
            # Create Products per Class
            # -------------------------
            for class_obj in SchoolClass.objects.all():

                cat = category_map.get(class_obj.name)
                if not cat:
                    self.stdout.write(
                        self.style.WARNING(f"Skipping {class_obj.name}: no category")
                    )
                    continue

                products = [
                    {
                        "name": f"{class_obj.name} CBT Exam Access",
                        "price": Decimal("5000.00"),
                        "stock_quantity": 100,
                        "description": f"Full CBT exam access for {class_obj.name}",
                    },
                    {
                        "name": f"{class_obj.name} Result Analytics",
                        "price": Decimal("2500.00"),
                        "stock_quantity": 100,
                        "description": f"Advanced performance analytics for {class_obj.name}",
                    },
                ]

                for p in products:
                    Product.objects.get_or_create(
                        name=p["name"],
                        category=cat,
                        defaults={
                            "price": p["price"],
                            "stock_quantity": p["stock_quantity"],
                            "description": p["description"],
                            "is_active": True,
                        },
                    )

        self.stdout.write(self.style.SUCCESS("✅ MPay seed completed successfully"))
