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
curl -X POST http://localhost:8000/v1/evidence-packs \
  -H "x-api-key: demo-api-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "certificate_id": "<certificate_id_from_ingest>",
    "format": "json,pdf,html"
  }'
```

### Development

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
4. **Feature Computation**: Real-time feature extraction from database (account age, velocity, prior decisions)
5. **ML Signals**: Risk, assurance, anomaly, and synthetic likelihood scores
6. **Policy Evaluation**: Deterministic decision based on policy rules
7. **Certificate**: Signed, tamper-evident decision certificate (KMS-ready)
8. **Ledger**: Append-only audit trail with deterministic hash chaining
9. **Evidence Pack**: Async generation with S3/MinIO storage
10. **Webhooks**: Durable background delivery with retries

### Production Features

- **Scalable API Key Auth**: O(1) prefix+digest lookup (no O(n) bcrypt loops)
- **Deterministic Ledger**: Tenant-sequenced events with verifiable hash chains
- **KMS-Ready Signing**: Abstract signer interface supporting local dev and AWS KMS
- **Real Feature Computation**: Database-driven features (no placeholders)
- **Async Evidence Packs**: Celery tasks with object storage
- **Durable Webhooks**: Background delivery with HMAC signing and retries
- **Tenant Isolation**: IP allowlists and strict query scoping
- **Structured Logging**: Correlation IDs, tenant IDs, structured JSON logs

### Key Components

- **API Service** (`apps/api/`): FastAPI application with all endpoints
- **Worker** (`apps/worker/`): Celery worker for async tasks (evidence generation)
- **ML Pipeline** (`ml/`): Training scripts, synthetic data generation, inference
- **Database**: PostgreSQL with multi-tenant schema
- **Storage**: MinIO (S3-compatible) for evidence packs

### API Endpoints

#### Public (Tenant) APIs
- `POST /v1/ingest` - Submit content for decision
- `POST /v1/evidence-packs` - Request evidence pack generation (async)
- `GET /v1/evidence-packs/{certificate_id}` - Get evidence pack status + signed URLs
- `GET /v1/evidence-packs/{certificate_id}/download/{format}` - Download artifact
- `GET /v1/keys/jwks.json` - Get public keys for certificate verification
- `GET /v1/certificates/{certificate_id}` - Get certificate with verification metadata
- `POST /v1/webhooks` - Create webhook
- `POST /v1/webhooks/test` - Test webhook delivery
- `GET /v1/webhooks/{webhook_id}/deliveries` - View webhook delivery history

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

## API Key Authentication

ORIGIN uses scalable prefix+digest authentication:

1. **Format**: API keys are stored with:
   - `prefix`: First 8 characters (indexed for O(1) lookup)
   - `digest`: HMAC-SHA256(server_secret, raw_key) (indexed)

2. **Lookup**: 
   - Extract prefix from raw key
   - Query `api_keys` where `prefix` matches (indexed lookup)
   - Constant-time compare `digest` using `hmac.compare_digest()`
   - Never iterates over all keys (O(1) performance)

3. **Header**: `x-api-key: <your-api-key>`

## Ingest Flow

1. Client sends `POST /v1/ingest` with content metadata
2. ORIGIN:
   - Resolves identity (KYA++)
   - Generates PVID (provenance ID)
   - Computes features from database (account age, velocity, prior decisions)
   - Runs ML inference (risk, assurance, anomaly scores)
   - Evaluates policy (deterministic decision)
   - Creates signed certificate
   - Appends ledger event
   - Enqueues webhook delivery (async)
3. Returns decision + certificate_id + ledger_hash

**Response Time**: P95 < 3 seconds

## Evidence Pack Request/Download

### Request Evidence Pack
```bash
POST /v1/evidence-packs
{
  "certificate_id": "abc-123",
  "format": "json,pdf,html",
  "audience": "INTERNAL"
}
```

Returns: `status: "pending"` (generation is async)

### Get Status + Signed URLs
```bash
GET /v1/evidence-packs/{certificate_id}
```

Returns:
```json
{
  "status": "ready",
  "formats": ["json", "pdf", "html"],
  "signed_urls": {
    "json": "https://minio:9000/evidence/abc-123/evidence.json?X-Amz-Algorithm=...",
    "pdf": "..."
  }
}
```

### Download Artifact
```bash
GET /v1/evidence-packs/{certificate_id}/download/pdf
```

Returns: Binary PDF with appropriate Content-Type headers

## Webhook Verification

Webhooks are signed with HMAC-SHA256 and include replay protection:

**Headers:**
- `X-Origin-Signature`: `sha256=<hmac_hex>` (signs timestamp + body)
- `X-Origin-Event`: Event type (e.g., "decision.created")
- `X-Origin-Correlation-Id`: Request correlation ID
- `X-Origin-Event-Id`: Delivery attempt ID
- `X-Origin-Timestamp`: Unix timestamp (replay protection)

**Verification (with replay protection):**
```python
import hmac
import hashlib
import time

signature_header = request.headers.get("X-Origin-Signature")
timestamp = request.headers.get("X-Origin-Timestamp")
body = request.body.decode() if isinstance(request.body, bytes) else request.body
secret = "your_webhook_secret"  # Retrieved from encrypted storage

# Verify timestamp is recent (within 5 minutes)
if abs(int(time.time()) - int(timestamp)) > 300:
    raise ValueError("Webhook timestamp too old (replay attack?)")

# Reconstruct signed message: timestamp + "." + body
message = f"{timestamp}.{body}"
expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
expected_header = f"sha256={expected}"

# Constant-time comparison
is_valid = hmac.compare_digest(signature_header, expected_header)
if not is_valid:
    raise ValueError("Invalid webhook signature")
```

**Security Notes:**
- Webhook secrets are encrypted at rest using AWS KMS (production) or Fernet (local dev)
- Secrets are never stored in plaintext
- Timestamp prevents replay attacks (reject if > 5 minutes old)
- Use constant-time comparison to prevent timing attacks

## Certificate Verification

### Get Public Keys
```bash
GET /v1/keys/jwks.json
```

Returns JWKS (JSON Web Key Set) with public keys for signature verification.

**Response:**
```json
{
  "keys": [
    {
      "kty": "RSA",
      "kid": "arn:aws:kms:us-east-1:123456789012:key/abc-123:v1",
      "use": "sig",
      "alg": "RS256",
      "n": "...",
      "e": "AQAB"
    }
  ]
}
```

### Verify Certificate
1. Get certificate: `GET /v1/certificates/{certificate_id}`
2. Get public key from JWKS using `certificate.key_id`
3. Verify signature using RSA-PSS with SHA-256 (or RSASSA_PKCS1_V1_5_SHA_256 for KMS)
4. Verify ledger hash chain integrity

**Verification Example:**
```python
import json
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
import jwt

# Get certificate and JWKS
certificate = requests.get(f"/v1/certificates/{cert_id}").json()
jwks = requests.get("/v1/keys/jwks.json").json()

# Find matching key
key_data = next(k for k in jwks["keys"] if k["kid"] == certificate["key_id"])

# Verify signature (simplified - use proper JWT library in production)
# Certificate data includes: certificate_id, tenant_id, upload_id, policy_version,
# inputs_hash, outputs_hash, ledger_hash, issued_at, evidence_hashes (if available)
```

### Key Rotation

- Multiple active public keys supported
- New certificates use newest key (highest key_id)
- Old certificates remain verifiable via JWKS
- Rotate keys by updating `SIGNING_KEY_ID` and restarting
- KMS key rotation: Create new key version, update `SIGNING_KEY_ID`, restart service

## Performance

- **Ingest P95**: < 3 seconds
- **API Key Lookup**: < 10ms (O(1) indexed)
- **Evidence Generation**: Async, typically < 30s
- **Webhook Delivery**: Async, < 5s per attempt

## Security

- **API Keys**: Stored as HMAC-SHA256 digest, never plaintext. O(1) indexed lookup.
- **API Key Scopes**: Enforced per endpoint (ingest, evidence, read)
- **Tenant Isolation**: All queries enforce tenant_id scoping
- **IP Allowlists**: Optional per-tenant IP/CIDR restrictions
- **Structured Logging**: No PII, correlation IDs for tracing
- **Ledger Integrity**: Hash-chained, tamper-evident audit trail
- **Webhook Secrets**: Encrypted at rest (AWS KMS or Fernet)
- **Webhook Replay Protection**: Timestamp-based, rejects old requests
- **Evidence Pack Integrity**: SHA-256 hashes stored and included in download headers
- **Certificate Signing**: KMS-ready (AWS KMS or local RSA keypair)
- **Key Management**: Supports key rotation without breaking old certificates

## License

Proprietary - Internal Use Only

