# Security and Verification Fixes

This document summarizes the security and verification improvements implemented for ORIGIN.

## A) IP Allowlist Fail-Closed in Production ✅

**Problem**: IP allowlist failed open (allowed access) on parsing errors, even in production.

**Solution**:
- Added `IP_ALLOWLIST_FAIL_OPEN` setting (auto-detects based on environment)
- Development: Fail-open with warning log
- Production/Staging: Fail-closed with warning log + metric increment
- Proper error handling for invalid JSON, malformed allowlists, and unexpected errors

**Files**:
- `apps/api/origin_api/middleware/auth.py` - Updated `_check_ip_allowlist()` method
- `apps/api/origin_api/settings.py` - Added `ip_allowlist_fail_open` setting
- `apps/api/origin_api/utils/metrics.py` - Added IP allowlist error metrics

**Tests**:
- `apps/api/tests/test_ip_allowlist.py` - Tests for valid CIDR, exact IP, invalid JSON in production

## B) Webhook Signing Uses Raw Body Bytes ✅

**Problem**: Webhook signing used re-serialized JSON, which could fail if JSON key ordering differed.

**Solution**:
- Standardized signing message: `timestamp_bytes + b"." + raw_body_bytes`
- ORIGIN's webhook sender signs the exact raw JSON bytes as delivered
- Updated `verify_webhook()` in SDK to accept and verify raw bytes
- Updated Express.js example to capture raw body before JSON parsing
- Python/FastAPI example already uses `await request.body()` (kept as canonical)

**Files**:
- `apps/api/origin_api/webhooks/service.py` - Updated `_compute_signature()` and `_attempt_delivery()`
- `packages/sdk-python/origin_sdk/webhook.py` - Updated to use raw bytes
- `README.md` - Updated examples with raw body capture instructions

**Tests**:
- `apps/api/tests/test_webhook_raw_body.py` - Tests for different JSON ordering, raw body verification

## C) Certificate/JWKS Algorithm Matches Actual Signing ✅

**Problem**: JWKS advertised RS256 but signers used RSA-PSS (PS256), causing verification failures.

**Solution**:
- Updated `DevLocalSigner.get_public_jwk()` to advertise `alg: "PS256"`
- Updated `KmsSigner.get_public_jwk()` to advertise `alg: "PS256"`
- Updated `CertificateService.generate_certificate()` to use algorithm from signer JWK
- Updated certificate model default to `PS256`
- Added algorithm matching verification in docs

**Files**:
- `apps/api/origin_api/ledger/signer.py` - Updated JWK `alg` fields to PS256
- `apps/api/origin_api/ledger/certificate.py` - Use signer's algorithm
- `apps/api/origin_api/models/policy.py` - Updated default to PS256
- `README.md` - Updated verification example with PS256

**Tests**:
- `apps/api/tests/test_certificate_algorithm.py` - Tests for algorithm matching and signature verification

## D) Documentation Consistency ✅

**Problem**: TODOs in docs for features that exist, missing integrator checklist.

**Solution**:
- Removed TODO from `PRODUCTION_IMPROVEMENTS.md` (webhook secrets are encrypted)
- Added "Integrator Checklist" section to README with:
  - API key authentication
  - Idempotency usage
  - Webhook verification (raw body)
  - Certificate verification (JWKS + alg)
- Updated all examples to use correct algorithms and raw body bytes
- Clarified webhook verification requirements

**Files**:
- `README.md` - Added integrator checklist, updated examples
- `PRODUCTION_IMPROVEMENTS.md` - Removed TODOs, updated security notes

## Summary

All security and verification fixes implemented:

✅ IP allowlist fail-closed in production
✅ Webhook signing uses raw body bytes
✅ Certificate/JWKS algorithm matches (PS256)
✅ Documentation consistency and integrator checklist

**No breaking API changes** - only added `signing_alg` field clarification and webhook verification requirements.

