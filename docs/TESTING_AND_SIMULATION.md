# tenx-user-management Testing and Simulation

## Overview

This service manages trainee registration, batch onboarding, environment management,
and webhook processing for the 10Academy platform. All testing is designed to run
**without** live external dependencies:

- **Strapi CMS** (GraphQL mutations, user creation)
- **AWS SES** (email delivery)
- **Google Sheets** (batch data source)
- **AWS Secrets Manager** (credential retrieval)

All external boundaries are mocked at the `conftest.py` level so tests are fast,
deterministic, and CI-safe.

---

## Test Strategy

### 1. Unit Tests (`tests/test_*.py`)

Target individual functions and classes in isolation.

| File | Focus | Tests |
|---|---|---|
| `test_models.py` | Pydantic validation rules | 36 |
| `test_utils.py` | Password generator, logging, error handlers | 21 |
| `test_data_processor.py` | TraineeInfo normalization (name, email, dates) | 22 |
| `test_trainee_service.py` | TraineeService with mocked Strapi | 17 |
| `test_controller.py` | TraineeController orchestration | 8 |
| `test_email_service.py` | EmailService with mocked SES | 10 |
| `test_webhook_service.py` | WebhookService (signature, retry, sanitize) | 15 |
| `test_routes.py` | HTTP integration via TestClient | 12 |

### 2. Integration Tests (`tests/integration/`)

Use FastAPI `TestClient` to send real HTTP requests through the full middleware
stack. Service layer is mocked — tests verify routing, validation, error handling,
CORS, and auth enforcement.

### 3. E2E Tests (`tests/e2e/`)

Cover complete business workflows across the full pipeline:

- **Single trainee registration flow** — full Strapi → profile → trainee pipeline
- **Admin trainee flow** — auth-gated variant with role verification
- **Batch processing flow** — CSV upload → chunked processing → webhook callback
- **Webhook flow** — inbound webhook handling and acknowledgment
- **Environment management flow** — env var refresh and cache check
- **Error recovery edge cases** — partial failures, rollback, cleanup

### 4. Security Tests (`tests/security/`)

| File | Coverage |
|---|---|
| `test_dast_injection.py` | SQL injection, command injection, XSS payloads |
| `test_dast_auth_bypass.py` | Auth bypass attempts, token manipulation |
| `test_dast_headers_cors.py` | Security headers, CORS policy |
| `test_dast_file_upload.py` | Malicious CSV (oversized, wrong encoding, path traversal filenames) |
| `test_dast_info_leakage.py` | Error response information disclosure |
| `test_sast.py` | Static analysis: hardcoded secrets, dangerous functions |

### 5. Performance Tests (`tests/performance/`)

- **Load test** — baseline throughput at expected traffic
- **Stress test** — ramp to breaking point; find degradation threshold
- **Soak test** — sustained load for memory leak and connection pool exhaustion detection

### 6. Contract Tests (`tests/contract/`)

Verify the API's OpenAPI schema, Pydantic model contracts, HTTP response shapes,
and Strapi data shapes match documented specifications. Consumer-Driven Contract
Testing (CDCT) approach.

### 7. Mutation Tests (`tests/mutation/`)

Inline mutation testing for critical business logic: DataProcessor normalization,
TraineeResponse construction, Pydantic validation, WebhookService signature,
and the TraineeService pipeline. Target: ≥80% mutation kill rate.

---

## Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Single layer
python -m pytest tests/integration/ -v
python -m pytest tests/security/ -v
python -m pytest tests/performance/ -v
python -m pytest tests/e2e/ -v

# With coverage
python -m pytest tests/ --cov=api --cov-report=html --cov-report=term-missing

# Generate PDF test report
python generate_test_report.py
```

---

## Simulation

The simulation module exercises the **deployed API** (not the test client) with
realistic load across all endpoints.

### Quick Start

```bash
# Set credentials
export SIMULATION_BASE_URL="https://user-management.10academy.org"
export SIMULATION_AUTH_TOKEN="your-strapi-jwt-token"

# Generate user data (pre-populate tiers)
python -m simulation.generate_users

# Run full simulation
python -m simulation.runner

# Run a single tier
python -m simulation.runner --tier 100

# Run a single endpoint
python -m simulation.runner --endpoint single

# Dry run (validate setup only)
python -m simulation.runner --dry-run
```

### Visualize Results

```bash
# Charts from the latest run
python -m simulation.visualize

# Export PNG charts
python -m simulation.visualize --export-dir simulation/results/charts/

# Console table only
python -m simulation.visualize --table-only
```

### Simulation Tiers

| Tier | Concurrency | Purpose |
|---|---|---|
| 100 | 10 | Warm-up baseline |
| 200 | 20 | Light load |
| 500 | 25 | Moderate load |
| 1,000 | 50 | Peak expected traffic |
| 2,000 | 50 | 2× peak stress |
| 4,000 | 100 | Sustained stress |
| 10,000 | 100 | Extreme load / breaking point |

### Metrics Collected

For each endpoint × tier combination:
- Total requests, successful, failed
- Success rate (%)
- Wall-clock time, throughput (RPS)
- Latency: min, max, mean, median, P95, P99

Results are saved as timestamped JSON in `simulation/results/` and visualized as:
- Latency vs Tier (per endpoint)
- Throughput vs Tier
- Error Rate vs Tier
- P95 Heatmap (endpoint × tier)
- Response Time Distribution

---

## Folder Structure

```
tests/
├── conftest.py                  # Shared fixtures; stubs all external dependencies
├── test_models.py               # Pydantic model unit tests
├── test_utils.py                # Utility function unit tests
├── test_data_processor.py       # DataProcessor unit tests
├── test_trainee_service.py      # TraineeService unit tests
├── test_controller.py           # Controller unit tests
├── test_email_service.py        # EmailService unit tests
├── test_webhook_service.py      # WebhookService unit tests
├── test_routes.py               # HTTP integration tests
├── integration/                 # Full middleware integration tests
├── e2e/                         # End-to-end workflow tests
├── security/                    # DAST + SAST security tests
├── performance/                 # Load, stress, soak tests
├── contract/                    # API contract tests
└── mutation/                    # Mutation quality tests

simulation/
├── config.py                    # Simulation parameters and endpoint registry
├── generate_users.py            # Realistic test data generation
├── runner.py                    # HTTP load runner with tier/endpoint control
├── visualize.py                 # Chart and table generation
├── user_data/                   # Pre-generated user CSV files (100–10K)
└── results/                     # Timestamped JSON run results + charts
```

---

## Notes

- All external services (Strapi, SES, Sheets, Secrets Manager) are fully mocked
  in `tests/conftest.py`. No credentials needed for running tests.
- `is_mock=True` in `ConfigInfo` enables mock mode in the service layer — safe
  to use in development and CI without side effects.
- Performance and simulation tests require a live deployed instance; they are
  not run in standard CI but included in release validation.
