# ORIGIN - API-First Upload Governance Infrastructure

ORIGIN is an enterprise-grade API-first Upload Governance System for UGC ecosystems (music/video/gaming/etc.). It sits in the decision path at ingest time, returns binding decisions (ALLOW / REVIEW / QUARANTINE / REJECT), and issues signed Decision Certificates with immutable Evidence Packs.

## Architecture

- **API-First**: Functions without a portal; any UI is optional
- **Deterministic Decisions**: Policy & Decision Engine produces binding decisions; ML outputs are signals only
- **Tamper-Evident**: Every decision produces a signed, versioned, timestamped Decision Certificate
- **Evidence Packs**: On-demand PDF/JSON/HTML artifacts via API
- **Multi-Tenant**: Strict isolation, robust auditing, idempotency, rate limiting

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Make (optional, for convenience commands)

### Setup

#### Windows (PowerShell or CMD)

**Option 1: Automated Setup (Recommended)**
```powershell
# Run the setup script
.\setup.ps1
```

**Option 2: Manual Setup**
```cmd
# 1. Copy environment file
copy env.example .env

# 2. Start services
docker-compose up -d
# Or use: up.bat

# 3. Run migrations
docker-compose exec api alembic upgrade head
# Or use: migrate.bat

# 4. Seed initial data
docker-compose exec api python -m origin_api.cli seed
# Or use: seed.bat

# 5. Verify health
curl http://localhost:8000/health
```

#### Linux/Mac

```bash
# 1. Copy environment file
cp env.example .env

# 2. Start services
make up
# or: docker-compose up -d

# 3. Run migrations
make migrate

# 4. Seed initial data
make seed

# 5. Verify health
curl http://localhost:8000/health
```

### Test Ingest Endpoint

```bash
curl -X POST http://localhost:8000/v1/ingest \
  -H "x-api-key: demo-api-key-12345" \
  -H "idempotency-key: test-123" \
  -H "Content-Type: application/json" \
  -d '{
    "account_external_id": "user-001",
    "account_type": "user",
    "upload_external_id": "upload-001",
    "metadata": {"title": "Test Upload"},
    "content_ref": "https://example.com/content.mp3"
  }'
```

### Generate Evidence Pack

After an ingest, request an evidence pack:

```bash
# Request evidence pack generation
curl -X POST http://localhost:8000/v1/evidence-packs \
  -H "x-api-key: demo-api-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "certificate_id": "<certificate_id_from_ingest>",
    "format": "json,pdf,html"
  }'

# Response: HTTP 202 Accepted
# {
#   "status": "pending",
#   "certificate_id": "...",
#   "task_id": "evidence_pack_...",
#   "task_status": "PENDING",
#   "pipeline_event": "ENQUEUED",
#   "poll_url": "/v1/evidence-packs/{certificate_id}",
#   "retry_after_seconds": 30
# }

# Poll for status (use Retry-After header for backoff)
curl -X GET http://localhost:8000/v1/evidence-packs/{certificate_id} \
  -H "x-api-key: demo-api-key-12345"

# Response when ready: HTTP 200 OK
# {
#   "status": "ready",
#   "certificate_id": "...",
#   "signed_urls": {"json": "...", "pdf": "...", "html": "..."},
#   "task_status": "SUCCESS",
#   "pipeline_event": "UPDATED_FROM_TASK_RESULT"
# }
```

#### Evidence Pack Lifecycle

1. **Request** (`POST /v1/evidence-packs`):
   - Returns `HTTP 202 Accepted` with `status="pending"`
   - Includes `task_id`, `task_status` (Celery state), `pipeline_event`, and `Retry-After` header
   - Task is enqueued for async generation

2. **Poll** (`GET /v1/evidence-packs/{certificate_id}`):
   - Returns `HTTP 202 Accepted` if still pending (with `Retry-After` header)
   - Returns `HTTP 200 OK` when ready (with `signed_urls` and `download_urls`)
   - Returns `HTTP 503 Service Unavailable` for transient infrastructure failures (broker down, Celery unavailable)
   - Use `Retry-After` header value for polling backoff

3. **Task Fields**:
   - `task_id`: Hash-based deterministic Celery task ID
   - `task_status`: ONLY Celery states (`PENDING`, `STARTED`, `RETRY`, `SUCCESS`, `FAILURE`) or `None` if unknown
   - `task_state`: Deprecated, always mirrors `task_status` for backward compatibility
   - `pipeline_event`: Custom pipeline events (`ENQUEUED`, `POLLING`, `STUCK_REQUEUED`, `UPDATED_FROM_TASK_RESULT`) - separate from `task_status`
   - `error_code`: Set for transient infra failures (broker down) or permanent failures (generation error)

4. **State Machine**:
   - `pending`: May have `error_code` set for transient failures (allows retry)
   - `ready`: Artifacts exist, `signed_urls` available
   - `failed`: Only for deterministic generation failures (task ran and errored), not broker connectivity

### Testing

#### SQLite (Unit Tests)

Unit tests use SQLite in-memory database and don't require external services:

```bash
# Run unit tests only
pytest apps/api/tests -v -m "not integration"
```

#### PostgreSQL (Integration Tests)

Integration tests require a test database and Redis. Use the provided docker-compose setup:

```bash
# Start test dependencies (PostgreSQL + Redis)
docker-compose -f docker-compose.test.yml up -d

# Set test database URL
export TEST_DATABASE_URL=postgresql://origin_test:origin_test_password@localhost:5433/origin_test
export REDIS_URL=redis://localhost:6380/0

# Run integration tests
pytest apps/api/tests -v -m integration

# Run all tests (unit + integration)
pytest apps/api/tests -v
```

**Note:** Tests automatically detect `TEST_DATABASE_URL`:
- If `TEST_DATABASE_URL` starts with `sqlite://`, uses SQLite in-memory (fast unit tests)
- If `TEST_DATABASE_URL` starts with `postgresql://`, uses PostgreSQL (integration tests)

### Running Migrations

Migrations are managed via Alembic:

```bash
# Run migrations
docker-compose exec api alembic upgrade head

# Or manually
cd apps/api
alembic upgrade head
```

**Important:** Always run migrations before starting the API in production.

## Development

#### Windows Commands

```cmd
# Start all services
up.bat
# or: docker-compose up -d

# Run migrations
migrate.bat
# or: docker-compose exec api alembic upgrade head

# Seed data
seed.bat
# or: docker-compose exec api python -m origin_api.cli seed

# Run tests
test.bat
# or: docker-compose exec api pytest tests/ -v

# View logs
logs.bat
# or: docker-compose logs -f

# Stop services
down.bat
# or: docker-compose down
```

#### Linux/Mac Commands

```bash
# Start all services
make up

# Run migrations
make migrate

# Seed data
make seed

# Run tests
make test

# View logs
make logs

# Stop services
make down
```

## API Documentation

Once running, visit:
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Metrics: http://localhost:8000/metrics

## Project Structure

```
origin/
├── apps/
│   ├── api/              # FastAPI service
│   └── worker/           # Celery/RQ worker
├── packages/
│   ├── sdk-python/       # Python SDK
│   └── sdk-node/         # Node.js SDK (optional)
├── data/
│   ├── seeds/            # Seed data
│   └── synthetic/        # Synthetic datasets
├── ml/
│   ├── training/         # Training scripts
│   └── datasets/         # ML datasets
└── infra/
    ├── migrations/       # Database migrations
    └── policies/         # Policy definitions
```

## Architecture Overview

### Core Flow

1. **Ingest** (`POST /v1/ingest`): Content submission with metadata
2. **Identity Resolution**: KYA++ resolves uploader to persistent identity entities
3. **Provenance**: PVID generation and prior sighting detection
4. **ML Signals**: Risk, assurance, anomaly, and synthetic likelihood scores
5. **Policy Evaluation**: Deterministic decision based on policy rules
6. **Certificate**: Signed, tamper-evident decision certificate
7. **Ledger**: Append-only audit trail with hash chaining
8. **Evidence Pack**: On-demand PDF/JSON/HTML artifacts
9. **Webhooks**: Async delivery to tenant systems

### Key Components

- **API Service** (`apps/api/`): FastAPI application with all endpoints
- **Worker** (`apps/worker/`): Celery worker for async tasks (evidence generation)
- **ML Pipeline** (`ml/`): Training scripts, synthetic data generation, inference
- **Database**: PostgreSQL with multi-tenant schema
- **Storage**: MinIO (S3-compatible) for evidence packs

### API Endpoints

#### Public (Tenant) APIs
- `POST /v1/ingest` - Submit content for decision
- `POST /v1/evidence-packs` - Request evidence pack generation
- `GET /v1/evidence-packs/{certificate_id}` - Get evidence pack status
- `GET /v1/evidence-packs/{certificate_id}/download/{format}` - Download artifact
- `POST /v1/webhooks` - Create webhook
- `POST /v1/webhooks/test` - Test webhook delivery

#### Admin APIs
- `POST /admin/tenants` - Create tenant
- `POST /admin/tenants/{id}/rotate-api-key` - Rotate API key

### Python SDK

```python
from origin_sdk import OriginClient

client = OriginClient(api_key="demo-api-key-12345")

# Ingest content
result = client.ingest(
    account_external_id="user-001",
    upload_external_id="upload-001",
    metadata={"title": "My Upload"},
)

# Request evidence pack
evidence = client.request_evidence_pack(
    certificate_id=result["certificate_id"],
    format="pdf",
)
```

## License

Proprietary - Internal Use Only

