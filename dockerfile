# Use official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# Copy project
COPY . /app/

# Run collectstatic with dummy vars so it doesn't need DB or Redis at build time
RUN SECRET_KEY=build-dummy-key \
    DB_HOST=localhost \
    REDIS_URL=redis://localhost:6379/0 \
    DJANGO_SETTINGS_MODULE=school_sms.settings \
    python manage.py collectstatic --noinput

# Wait for postgres to be ready, then migrate + start
CMD ["sh", "-c", \
    "python manage.py migrate --noinput && \
    python manage.py ensure_superuser && \
    if [ \"$SEED_ON_START\" = \"true\" ]; then python manage.py seed_all; fi && \
    daphne -b 0.0.0.0 -p ${PORT:-8000} school_sms.asgi:application"]
