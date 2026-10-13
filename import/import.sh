#!/usr/bin/env bash
set -e

export SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR/.."

echo "Flushing database..."
docker compose exec memorymaptoolkit python manage.py flush --no-input

echo "Creating admin user..."
docker compose exec memorymaptoolkit python manage.py createsuperuser --noinput --username admin --email admin@example.com 2>/dev/null || true
docker compose exec memorymaptoolkit python manage.py shell -c "
from django.contrib.auth.models import User
u = User.objects.get(username='admin')
u.set_password('admin')
u.save()
"

cd "$SCRIPT_DIR"

echo "Importing metadata..."
uv run jupyter execute metadati.ipynb

echo "Importing quotes..."
uv run jupyter execute belege.ipynb

echo "Importing chronotopi..."
uv run jupyter nbconvert --execute --to markdown --stdout chronotopi.ipynb
# uv run papermill chronotopi.ipynb /tmp/executed.ipynb && uv run jupyter nbconvert --to markdown --stdout /tmp/executed.ipynb && rm /tmp/executed.ipynb

echo "Import complete."