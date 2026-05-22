# Popcorn N Such

A Django 5.2 e-commerce and fundraising platform for popcorn sales.

---

## Table of Contents

- [Local Development](#local-development)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)
  - [Render (recommended)](#render-recommended)
  - [Docker](#docker)
  - [Any Linux Server](#any-linux-server)
- [Production Checklist](#production-checklist)
- [Media Files](#media-files)
- [Database](#database)
- [Background Tasks](#background-tasks)
- [Monitoring](#monitoring)

---

## Local Development

**Requirements:** Python 3.12+, PostgreSQL (or SQLite for quick start)

```bash
# 1. Clone and create a virtual environment
git clone <repo-url>
cd popcorn_n_such
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY

# 4. Apply migrations
python manage.py migrate

# 5. Seed demo data (optional)
python manage.py seed_demo_data

# 6. Run the dev server
python manage.py runserver
```

Default dev credentials after seeding:

| Username     | Password        | Role           |
|--------------|-----------------|----------------|
| `admin`      | `adminpass123!` | Superuser      |
| `staffuser`  | `staffpass123!` | Staff          |
| `customer1`  | `custpass123!`  | Customer       |

Admin panel: <http://localhost:8000/admin/>

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values. Every variable is documented inline in that file.

Key variables:

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Long random string — never reuse across environments |
| `DATABASE_URL` | Yes (prod) | `postgres://user:pass@host:port/db` |
| `DJANGO_ALLOWED_HOSTS` | Yes (prod) | Comma-separated hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Yes (prod) | Comma-separated full origins (with scheme) |
| `REDIS_URL` | Recommended | Enables Redis cache + session storage |
| `USE_S3` | Recommended | `true` to store uploads on S3/R2/Spaces |
| `SENTRY_DSN` | Recommended | Error tracking DSN |
| `PAYMENTS_WEBHOOK_SECRET` | Yes (prod) | Webhook signature verification |

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## Deployment

### Render (recommended)

The project includes a `render.yaml` Blueprint. One-click deploy:

1. Push the repo to GitHub.
2. In Render dashboard → **New → Blueprint** → connect the repo.
3. Render provisions Postgres, Redis, and the web service automatically.
4. Set the remaining secret env vars in the Render dashboard (payment keys, Sentry DSN, shipping API keys, etc.). See `.env.example` for the full list.
5. Deploy. The `release` command in `Procfile` runs `migrate` before traffic shifts.

**Health check:** Render polls `/health/` every 30 seconds. The endpoint returns `200 {"status":"ok"}` when the database is reachable, and `503` otherwise.

**Custom domain:**
- Add your domain in Render → Settings → Custom Domains.
- Update `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to include it.
- Render provisions a free TLS certificate automatically.

---

### Docker

```bash
# Build
docker build -t popcorn-n-such .

# Run (pass env file)
docker run -p 8000:8000 \
  --env-file .env \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  popcorn-n-such
```

**docker-compose** (example for local PostgreSQL + Redis):

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: popcorn_n_such
      POSTGRES_USER: popcorn
      POSTGRES_PASSWORD: popcorn
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  web:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      DATABASE_URL: postgres://popcorn:popcorn@db:5432/popcorn_n_such
      REDIS_URL: redis://redis:6379/0
      DJANGO_SETTINGS_MODULE: config.settings.prod
    depends_on:
      - db
      - redis

volumes:
  pgdata:
```

---

### Any Linux Server

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (systemd, .env, or export)
export DJANGO_SETTINGS_MODULE=config.settings.prod
export DJANGO_SECRET_KEY=<your-secret>
export DATABASE_URL=postgres://...
# ... remaining vars

# Collect static files
python manage.py collectstatic --noinput

# Apply migrations
python manage.py migrate --noinput

# Run with gunicorn (behind nginx / Caddy)
gunicorn config.wsgi:application \
  --bind unix:/run/popcorn.sock \
  --workers 4 \
  --threads 2 \
  --worker-class gthread \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

**Nginx config snippet:**

```nginx
server {
    listen 443 ssl;
    server_name popcornnsuch.com;

    location /static/ {
        alias /app/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        # Only if NOT using S3 — serve from disk
        alias /app/media/;
    }

    location / {
        proxy_pass http://unix:/run/popcorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Production Checklist

Before going live:

- [ ] `DJANGO_SECRET_KEY` is long, random, and unique to production
- [ ] `DJANGO_DEBUG=false`
- [ ] `DATABASE_URL` points to PostgreSQL (not SQLite)
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` include your domain
- [ ] `DB_SSL_REQUIRE=true` if your host requires it
- [ ] `REDIS_URL` is set (sessions and cache)
- [ ] `USE_S3=true` and S3/R2 credentials are set (user-uploaded media)
- [ ] `SENTRY_DSN` is set for error tracking
- [ ] `PAYMENTS_WEBHOOK_SECRET` is set and matches the processor's dashboard
- [ ] `SHIPPING_FROM_*` address fields are filled in
- [ ] Email is configured and `DEFAULT_FROM_EMAIL` is set
- [ ] `DJANGO_ADMIN_EMAIL` is set for 500-error notifications
- [ ] `python manage.py check --deploy` passes with no errors
- [ ] At least one superuser account exists (`python manage.py createsuperuser`)
- [ ] HSTS preload submitted if using a custom domain (<https://hstspreload.org>)

---

## Media Files

User-uploaded media (product images, label files, organization documents) must be stored outside the container in production — the local disk is ephemeral on Render and most PaaS platforms.

**Recommended: Cloudflare R2** (S3-compatible, no egress fees)

```bash
USE_S3=true
AWS_STORAGE_BUCKET_NAME=popcorn-n-such-media
AWS_S3_REGION_NAME=auto
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=<r2-access-key>
AWS_SECRET_ACCESS_KEY=<r2-secret-key>
AWS_S3_CUSTOM_DOMAIN=media.popcornnsuch.com   # optional CDN domain
```

Alternatives: AWS S3, DigitalOcean Spaces (same S3-compatible env vars, different endpoint).

When `USE_S3=false` (local dev), Django serves media from `MEDIA_ROOT` via the dev server.

---

## Database

- **Development:** SQLite (default, zero config)
- **Production:** PostgreSQL 15+ required

Run migrations:
```bash
python manage.py migrate
```

Check for unapplied migrations (useful in CI):
```bash
python manage.py migrate --check
```

Create the first superuser:
```bash
python manage.py createsuperuser
```

Seed demo data (dev only):
```bash
python manage.py seed_demo_data
python manage.py seed_demo_data --flush  # wipe and re-seed
```

---

## Background Tasks

The project does not yet include a task queue (Celery/Dramatiq). Long-running operations — sending emails, webhook processing, abandoned-cart reminders — are currently synchronous. Before heavy production load, add Redis + Celery:

```bash
pip install celery[redis]
celery -A config worker -l info
celery -A config beat -l info   # for periodic tasks
```

---

## Monitoring

| Concern | Tool | Config |
|---|---|---|
| Error tracking | Sentry | `SENTRY_DSN` |
| Uptime | Render health checks / UptimeRobot | poll `/health/` |
| Performance | Sentry Tracing | `SENTRY_TRACES_SAMPLE_RATE` |
| Logs | Render log stream / Papertrail | stdout (gunicorn `--access-logfile -`) |
| DB metrics | Render dashboard / pg_stat_statements | — |

Security audit events (label creation, login throttling, role changes) are logged via the `security_audit` app and written to stdout at `INFO` level.
