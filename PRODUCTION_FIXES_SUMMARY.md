# Production Fixes Summary - Evidence Pack Async Pipeline

## Overview
This document summarizes the production-critical fixes applied to the evidence pack async pipeline to ensure correct task field handling, proper HTTP status codes, secure task ID generation, and unambiguous router registration.

## Changes Made

### STEP 1: Fixed task_state/task_status Correctness (BUGFIX)
**File:** `apps/api/origin_api/routes/evidence.py`

**Issue:** `task_state` was incorrectly set to `task_id` value instead of mirroring `task_status`.

**Fix:**
- Updated all response payloads to ensure `task_state` always mirrors `task_status`
- Fixed line 314: Changed `task_state: evidence_pack.task_id` to `task_state: None` (mirrors `task_status: None`)
- Fixed line 419: Added `task_status` field and ensured `task_state` mirrors it
- Fixed line 522: Added `task_status` field and ensured `task_state` mirrors it
- Updated `EvidencePackResponse` docstring to clarify that `task_state` always mirrors `task_status`

**Tests Added:**
- `apps/api/tests/test_evidence_task_fields.py` - Verifies `task_state` never equals `task_id` and always mirrors `task_status`

### STEP 2: Return 503 for Broker/Enqueue Failures
**File:** `apps/api/origin_api/routes/evidence.py`

**Issue:** Broker connectivity failures were not properly handled with 503 status codes.

**Fix:**
- Added explicit handling for `ConnectionError` and `TimeoutError` before general exception handler
- Added broker error detection for kombu-style exceptions (OperationalError, KombuError, etc.)
- All broker failures now return:
  - HTTP 503 Service Unavailable
  - `error_code: "BROKER_UNAVAILABLE"`
  - `Retry-After: 30` header
  - Safe error messages (truncated to 200 chars)

**Tests Added:**
- `apps/api/tests/test_evidence_503_broker.py` - Verifies broker failures return 503 with Retry-After

### STEP 3: Harden Deterministic task_id Generation (Hash-Based)
**File:** `apps/api/origin_api/routes/evidence.py`

**Issue:** Task IDs used raw string concatenation which could lead to unsafe lengths or characters.

**Fix:**
- Replaced `_get_deterministic_task_id()` to use SHA256 hash of idempotency key
- Format: `evidence_pack_{sha256_hash[:32]}`
- Guarantees safe length (32 hex chars) and character set
- Still deterministic (same inputs = same task_id)
- Stuck requeue still appends `_retry_{timestamp}` suffix safely

**Tests Added:**
- `test_evidence_task_fields.py` includes tests for task_id format and determinism

### STEP 4: Ensure Router Registration is Unambiguous
**Files:** `apps/api/origin_api/main.py`, `apps/api/tests/test_evidence_routes.py`

**Issue:** Need to ensure deprecated router is never accidentally imported.

**Fix:**
- Enhanced `test_evidence_routes.py` to:
  - Verify no routes come from deprecated module
  - Check that main.py doesn't import deprecated router
  - Assert only one evidence router is registered

**Verification:**
- Deprecated router (`_deprecated_evidence_old_do_not_use.py`) raises `RuntimeError` on import
- Main.py only imports `evidence` router, not deprecated one

### STEP 5: Fix Runtime Errors and Hygiene
**File:** `apps/api/origin_api/routes/webhooks.py`

**Issue:** Potential missing imports or unused code.

**Fix:**
- Reviewed webhooks.py - no missing datetime imports found (datetime not used in routes)
- All imports verified and correct

### STEP 6: Tests Added/Updated
**New Test Files:**
1. `apps/api/tests/test_evidence_task_fields.py`
   - Tests task_state mirrors task_status
   - Tests task_id format and determinism
   - Verifies task_state never equals task_id

2. `apps/api/tests/test_evidence_503_broker.py`
   - Tests ConnectionError returns 503
   - Tests TimeoutError returns 503
   - Tests kombu OperationalError returns 503
   - Tests ImportError returns 503
   - Verifies Retry-After header presence

**Updated Test Files:**
- `apps/api/tests/test_evidence_routes.py` - Enhanced router registration verification

## Migration Implications

**None.** All changes are backward compatible:
- `task_state` field still present (deprecated but functional)
- API response structure unchanged (only field values corrected)
- Task ID format change is internal (doesn't affect API contracts)
- HTTP status codes improved (503 instead of 500 for broker failures)

## Backward Compatibility

✅ All changes maintain backward compatibility:
- Existing API clients will continue to work
- `task_state` field still returned (mirrors `task_status`)
- Response structure unchanged
- No breaking changes to request/response schemas

## Testing

Run tests with:
```bash
# Unit tests
pytest apps/api/tests/test_evidence_task_fields.py -v
pytest apps/api/tests/test_evidence_503_broker.py -v
pytest apps/api/tests/test_evidence_routes.py -v

# All evidence tests
pytest apps/api/tests/test_evidence*.py -v
```

## Files Modified

1. `apps/api/origin_api/routes/evidence.py` - Main fixes
2. `apps/api/tests/test_evidence_task_fields.py` - New tests
3. `apps/api/tests/test_evidence_503_broker.py` - New tests
4. `apps/api/tests/test_evidence_routes.py` - Enhanced tests
5. `PRODUCTION_FIXES_SUMMARY.md` - This document

## Summary

All production-critical issues have been addressed:
- ✅ Task fields are correct (task_state mirrors task_status)
- ✅ Broker failures return HTTP 503 with Retry-After
- ✅ Task IDs use secure hash-based generation
- ✅ Router registration is unambiguous
- ✅ Tests verify all behaviors
- ✅ No breaking changes introduced

