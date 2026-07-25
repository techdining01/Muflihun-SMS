import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_sms.settings')

app = Celery('school_sms')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
