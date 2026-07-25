import hmac
import hashlib
import json
import requests

# Your secret key from settings
SECRET_KEY = "sk_test_7456d2b313eee51a650ed592d21f9782a4816328"  # Replace with your actual test secret key

# Test payload
payload = {
    "event": "charge.success",
    "data": {
        "reference": "TEST_REF_001",
        "amount": 10000,
        "metadata": {
            "order_id": "123e4567-e89b-12d3-a456-426614174000",  # Your order UUID
            "user_id": "1"
        }
    }
}

# Convert to JSON string
payload_str = json.dumps(payload)
payload_bytes = payload_str.encode('utf-8')

# Generate signature
secret = SECRET_KEY.encode('utf-8')
signature = hmac.new(secret, payload_bytes, hashlib.sha512).hexdigest()

print(f"Payload: {payload_str}")
print(f"Signature: {signature}")

# Send request
headers = {
    "Content-Type": "application/json",
    "X-Paystack-Signature": signature
}

response = requests.post(
    "http://localhost:8000/mpay/paystack/webhook/",
    data=payload_bytes,
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")