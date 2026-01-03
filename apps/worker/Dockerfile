FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY apps/worker/pyproject.toml apps/worker/requirements.txt* ./
COPY apps/api/pyproject.toml apps/api/requirements.txt* /app/apps/api/

# Install worker and API packages in editable mode
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -e /app/apps/api && \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# Copy application code
COPY apps/worker/ /app/
COPY apps/api/ /app/apps/api/  # Mount as /app/apps/api for clean imports
COPY infra/ /app/infra/
COPY ml/ /app/ml/

# Set PYTHONPATH so origin_api can be imported cleanly
ENV PYTHONPATH=/app/apps/api:${PYTHONPATH}

# Default command
CMD ["celery", "-A", "origin_worker.celery_app", "worker", "--loglevel=info"]

