web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2 --worker-class gthread --timeout 120 --access-logfile - --error-logfile -
worker: celery -A config worker -l info --concurrency 2
beat: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
release: python manage.py migrate --noinput
