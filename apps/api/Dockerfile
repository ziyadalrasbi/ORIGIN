FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY apps/api/pyproject.toml apps/api/requirements.txt* ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

# Copy application code
COPY apps/api/ /app/
COPY infra/ /app/infra/
COPY ml/ /app/ml/

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "origin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

