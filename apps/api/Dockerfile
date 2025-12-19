FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY apps/api/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY apps/api/ /app/
COPY apps/api/pyproject.toml ./
COPY infra/ /app/infra/
COPY ml/ /app/ml/

# Install package in editable mode (optional, for development)
# Note: This may fail if pyproject.toml is not properly configured, but that's OK
RUN pip install --no-cache-dir -e . || echo "Skipping editable install"

# Expose port
EXPOSE 8000

# Default command
CMD ["python", "-m", "uvicorn", "origin_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

