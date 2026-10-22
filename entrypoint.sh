#!/bin/bash

# Default to production; development sets DJANGO_SETTINGS_MODULE to the local settings.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-memorymap_toolkit.settings.production}"

echo "Waiting for postgres..."

# Python is used instead of nc, which is not installed in the image.
until python -c "import socket, sys; socket.create_connection((sys.argv[1], 5432), timeout=1)" "$DJANGO_DB_HOST" 2>/dev/null; do
    sleep 0.1
done

echo "PostgreSQL started"

python manage.py migrate
# (python manage.py createsuperuser --noinput || echo 'Assuming preexisting user and continuing...')
python manage.py collectstatic --noinput
python manage.py compilemessages
python manage.py shell < mmt_setup.py



# Run the given command (e.g. dev runserver); otherwise start gunicorn for production.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
exec gunicorn --bind 0.0.0.0:8000 memorymap_toolkit.wsgi
