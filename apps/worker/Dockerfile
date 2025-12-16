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
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# Copy application code
COPY apps/worker/ /app/
COPY infra/ /app/infra/
COPY ml/ /app/ml/

# Default command
CMD ["celery", "-A", "origin_worker.celery_app", "worker", "--loglevel=info"]

