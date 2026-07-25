import json
import hashlib
import hmac
from django.test import TestCase, Client
from django.conf import settings
from django.urls import reverse
from unittest.mock import MagicMock
from django.contrib.auth import get_user_model
from payroll.models import PaymentTransaction, PayrollRecord, Payee, PayrollPeriod, PaymentBatch, StaffProfile

User = get_user_model()

class WebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.webhook_url = reverse("mpay:paystack_webhook")
        
        # Setup Data
        self.user = User.objects.create_user(username="testuser", password="password")
        self.payee = Payee.objects.create(
            user=self.user, payee_type="teacher", reference_code="PAY-001"
        )
        self.period = PayrollPeriod.objects.create(month=1, year=2025)
        self.record = PayrollRecord.objects.create(
            payee=self.payee, payroll_period=self.period
        )
        self.batch = PaymentBatch.objects.create(payroll_period=self.period)
        
        self.tx = PaymentTransaction.objects.create(
            payroll_record=self.record,
            batch=self.batch,
            amount=50000,
            bank_name="Test Bank",
            account_number="0000000000",
            paystack_reference="TRF_123456",
            status="pending"
        )

    def _generate_signature(self, payload):
        return hmac.new(
            key=settings.PAYSTACK_SECRET_KEY.encode(),
            msg=json.dumps(payload).encode(),
            digestmod=hashlib.sha512
        ).hexdigest()

    def test_transfer_success_webhook(self):
        payload = {
            "event": "transfer.success",
            "data": {
                "reference": "TRF_123456",
                "recipient": {"risk_action": "default"},
                "amount": 5000000,
                # ... other fields
            }
        }
        
        signature = self._generate_signature(payload)
        
        response = self.client.post(
            self.webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, "success")

    def test_transfer_failed_webhook(self):
        payload = {
            "event": "transfer.failed",
            "data": {
                "reference": "TRF_123456",
                "reason": "Insuficient Funds"
            }
        }
        
        signature = self._generate_signature(payload)
        
        response = self.client.post(
            self.webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, "failed")
        self.assertEqual(self.tx.failure_reason, "Insuficient Funds")
