# syntax=docker/dockerfile:1
##############################################################################
# Popcorn N Such — production Docker image
# Multi-stage: builder installs deps, final image is lean.
##############################################################################

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

# System deps needed to compile psycopg / Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg-dev \
    libwebp-dev \
    zlib1g-dev \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

# Runtime system libraries only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
  && rm -rf /var/lib/apt/lists/*

# Non-root user for the application
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source
COPY --chown=app:app . .

# Collect static files at build time
# (DATABASE_URL not needed for collectstatic — disable DB check)
RUN DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

USER app

EXPOSE ${PORT}

# Migrate then start gunicorn; in production, migrations run via Procfile
# `release` command or a separate init container — here we keep it simple.
CMD ["sh", "-c", \
  "python manage.py migrate --noinput && \
   gunicorn config.wsgi:application \
     --bind 0.0.0.0:$PORT \
     --workers 2 \
     --threads 2 \
     --worker-class gthread \
     --timeout 120 \
     --access-logfile - \
     --error-logfile -"]
