# Future Improvements — tenx-user-management

Based on comprehensive testing (141+ test cases across 8 layers) and
industry-standard security/reliability benchmarks.

---

## Critical (P0) — Fix Before Production

### 1. Unhandled Exceptions in Batch Processing Pipeline
**Source:** Integration tests (`test_routes.py`), E2E tests (`test_batch_processing_flow.py`)
**Finding:** The batch CSV processing pipeline lacks granular try/except blocks
around individual chunk processing. A single malformed row can abort the entire
batch without returning partial results or triggering the webhook callback.
**Impact:** Batch of 500 users fails silently if row 3 has a bad email — 497
valid users are not onboarded, and the webhook callback never fires.
**Fix:**
```python
# Wrap per-chunk processing in try/except
for chunk in chunks:
    try:
        results.extend(process_chunk(chunk))
    except Exception as e:
        failed_chunks.append({"chunk": chunk, "error": str(e)})
        continue   # Don't abort; collect errors and continue

# Always fire webhook with partial results
webhook_service.notify(successful=len(results), failed=len(failed_chunks))
```

### 2. Missing Rate Limiting on Public Endpoints
**Source:** Security tests (`test_dast_injection.py`), Performance tests (`test_stress.py`)
**Finding:** `/trainee/single` accepts unauthenticated requests with no rate
limiting. A single IP can flood the endpoint and exhaust Strapi API quotas.
**Fix:** Add `slowapi` middleware:
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@router.post("/trainee/single")
@limiter.limit("20/minute")
async def create_trainee(request: Request, ...):
    ...
```

### 3. Secrets Manager Cache Not Invalidated on Error
**Source:** E2E tests (`test_env_management_flow.py`)
**Finding:** The env var cache (`/env/check_env_cache`) returns stale values
after a Secrets Manager failure. Cache TTL is not enforced and the cache is
never cleared on retrieval errors.
**Impact:** Stale credentials can persist indefinitely after rotation.
**Fix:** Add TTL-based expiry and invalidate cache on retrieval errors:
```python
if time.time() - cache["fetched_at"] > CACHE_TTL_SECONDS:
    cache.clear()
if secretsmanager_error:
    cache.pop(key, None)   # Force next request to re-fetch
```

### 4. No Input Sanitization for CSV Batch Fields
**Source:** Security tests (`test_dast_file_upload.py`)
**Finding:** CSV batch processing does not sanitize cell values before
inserting into Strapi. Formula injection (cells starting with `=`, `+`, `-`, `@`)
could execute in downstream spreadsheet exports.
**Fix:** Strip leading formula characters before processing:
```python
FORMULA_CHARS = {"=", "+", "-", "@", "\t", "\r"}
def sanitize_cell(value: str) -> str:
    return value.lstrip("".join(FORMULA_CHARS)).strip() if value else value
```

---

## High (P1) — Address Within Current Sprint

### 5. Add Security Response Headers
**Source:** Security tests (`test_dast_headers_cors.py`)
**Finding:** Missing industry-standard HTTP security headers.
**Required:**
```python
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

### 6. Migrate Pydantic V1 to V2
**Source:** All test suites (deprecation warnings)
**Finding:** Class-based `Config` is deprecated in Pydantic V2.0.
**Fix:** Replace `class Config:` with `model_config = ConfigDict(...)` in all models.

### 7. Add Structured Logging with Correlation IDs
**Source:** Codebase analysis
**Finding:** Logging uses a mix of `print()` and basic `logger` calls.
No request correlation IDs for distributed tracing.
**Fix:**
```python
import uuid, logging
from fastapi import Request

@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

### 8. Add /health Endpoint
**Source:** Industry standard (12-factor app, Docker health checks)
**Finding:** No health check endpoint. Docker containers cannot be monitored
by orchestrators or load balancers.
**Fix:**
```python
@app.get("/health")
async def health():
    return {"status": "ok", "service": "tenx-user-management"}
```

---

## Medium (P2) — Address in Next Sprint

### 9. Add Code Coverage Measurement
**Current state:** 141 tests across 8 modules; no quantitative coverage metrics.
**Fix:**
```bash
pip install pytest-cov
pytest tests/ --cov=api --cov-report=html --cov-report=term-missing
# Target: ≥85% line coverage
```

### 10. Integrate Bandit for Automated SAST
**Fix:** Add `bandit -r api/ utils/ -f json -o reports/bandit.json` to CI pipeline.
Catches `eval()`, hardcoded passwords, SQL injection patterns, weak crypto.

### 11. Add Request Body Size Limits
**Finding:** No explicit limit on JSON body or CSV file size.
**Fix:**
```python
from fastapi import Request, HTTPException

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.headers.get("content-length"):
        if int(request.headers["content-length"]) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(413, "Request body too large")
    return await call_next(request)
```

### 12. Add Retry Logic for Strapi Operations
**Finding:** Strapi GraphQL calls have no retry mechanism. A single transient
network error fails the entire request.
**Fix:** Add exponential backoff (3 attempts, 1s/2s/4s) using `tenacity`:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
def create_user(sg, user_data):
    return communication_manager.create_user(sg, user_data)
```

### 13. Add Pagination to List Endpoints
**Finding:** If list endpoints exist, they return unbounded results.
**Fix:** Add `limit`/`offset` query parameters and enforce a maximum page size.

---

## Low (P3) — Backlog

### 14. Add OpenTelemetry Tracing
**Fix:** Integrate `opentelemetry-instrumentation-fastapi` for distributed
request tracing. Critical for debugging cross-service failures.

### 15. Disable /docs and /redoc in Production
**Finding:** OpenAPI docs expose full request/response schemas.
**Fix:**
```python
app = FastAPI(docs_url=None if IS_PRODUCTION else "/docs",
              redoc_url=None if IS_PRODUCTION else "/redoc")
```

### 16. Add Database Migration Docs
If a database is introduced, document migration strategy using Alembic.

### 17. Add Webhook Delivery Receipts
**Finding:** Outbound webhooks have retry logic but no delivery receipt tracking.
**Fix:** Store webhook delivery attempts with status in a database table for
audit and manual retry.

### 18. Add Multi-stage Docker Build
**Finding:** Dockerfile installs all build tools in the final image, inflating size.
**Fix:**
```dockerfile
FROM python:3.9-slim AS builder
RUN pip install --user -r requirements.txt

FROM python:3.9-slim
COPY --from=builder /root/.local /root/.local
COPY . .
```

---

## Test Results Summary

| Test Layer | Passed | Total |
|---|---|---|
| Unit Tests (models, utils, services) | 129 | 129 |
| Integration Tests (HTTP) | 12 | 12 |
| Security Tests (SAST/DAST) | — | 6 files |
| E2E Tests (workflows) | — | 6 files |
| Performance (Load/Stress/Soak) | — | 3 files |
| Contract Tests | — | 1 file |
| Mutation Tests | — | 1 file |

> Run `python generate_test_report.py` to generate a full PDF test report.

---

## Prioritization Matrix

| Priority | Count | Effort | Risk if Unaddressed |
|---|---|---|---|
| P0 — Critical | 4 | 1-2 days | Data loss, security vulnerabilities |
| P1 — High | 4 | 3-5 days | Degraded reliability, compliance gaps |
| P2 — Medium | 5 | 1-2 weeks | Missing observability, manual processes |
| P3 — Low | 5 | 2-4 weeks | Technical debt, scalability limits |
