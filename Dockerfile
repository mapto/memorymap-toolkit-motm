FROM python:3.11-slim-bookworm AS build

# Install Python and build tools 
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt1-dev \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip & setuptools
# RUN python3 -m pip install --upgrade pip "setuptools<60" wheel

# Install app requirements
COPY requirements.txt /tmp/requirements.txt
#RUN python3 -m pip install  --no-cache-dir --prefix=/install -r /tmp/requirements.txt
RUN pip install  --no-cache-dir --prefix=/install -r /tmp/requirements.txt



FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    # trixie libgdal36 libgeos-c1t64 libproj25 \
    libgdal32 libgeos-c1v5 libproj25 \
    gettext \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local
    
# App setup
WORKDIR /app
COPY . /app

# Non-root user
RUN useradd -u 5678 -ms /bin/bash appuser && chown -R appuser /app
USER appuser

# Create folders
RUN mkdir -p static media logs backups

# Copy secret settings
RUN cp memorymap_toolkit/settings/secret_settings_template.py memorymap_toolkit/settings/secret_settings.py

# Start command
CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]
