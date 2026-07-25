from django import forms
from django.utils.text import slugify
from .models import Product, ProductCategory
from exams.models import SchoolClass


def sync_product_categories_with_school_classes():
    """
    Sync ProductCategory table with active SchoolClass records.
    Creates new ProductCategory entries for missing classes,
    reactivates inactive ones, and leaves custom categories alone.
    Returns (created_count, reactivated_count).
    """
    created = 0
    reactivated = 0

    active_classes = SchoolClass.objects.filter(is_active=True)
    school_class_names = set(active_classes.values_list("name", flat=True))

    existing_categories = {
        cat.class_name: cat
        for cat in ProductCategory.objects.filter(class_name__in=school_class_names)
    }

    for school_class in active_classes:
        class_name_value = school_class.name
        category = existing_categories.get(class_name_value)
        if category is None:
            ProductCategory.objects.create(
                class_name=class_name_value,
                slug=slugify(class_name_value),
                is_active=True,
            )
            created += 1
        elif not category.is_active:
            category.is_active = True
            category.save(update_fields=["is_active"])
            reactivated += 1

    return created, reactivated


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        exclude = ('slug',)
        fields = ['name', 'category', 'description', 'price', 'stock_quantity', 'image']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sync_product_categories_with_school_classes()
        self.fields['category'].queryset = ProductCategory.objects.filter(
            is_active=True
        ).order_by('class_name')

