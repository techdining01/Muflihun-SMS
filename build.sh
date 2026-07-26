#!/usr/bin/env bash
# exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt && python manage.py collectstatic --noinput

# Run migrations, seed all data, and run server
python manage.py migrate --noinput && python manage.py seed_all && daphne -b 0.0.0.0 -p $PORT school_sms.asgi:application



