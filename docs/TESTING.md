# Testing Guide

## Overview

The test suite covers all layers of the application with **141 tests** across 8 test modules. External dependencies (Strapi, AWS SES, Google Sheets) are fully mocked to enable fast, isolated testing.

---

## Quick Start

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=api --cov-report=html --cov-report=term-missing
```

---

## Test Structure

```
tests/
├── conftest.py                  # Shared fixtures & external dependency stubs
├── test_models.py               # 36 tests — Pydantic models & validators
├── test_utils.py                # 21 tests — Password generator, config, logging, error handlers
├── test_data_processor.py       # 22 tests — DataProcessor unit tests
├── test_trainee_service.py      # 17 tests — TraineeService with mocked Strapi
├── test_controller.py           # 8 tests  — TraineeController unit tests
├── test_email_service.py        # 10 tests — EmailService with mocked SES
├── test_webhook_service.py      # 15 tests — WebhookService unit tests
└── test_routes.py               # 12 tests — HTTP integration tests (TestClient)
```

---

## Test Categories

### Unit Tests (models, utils, data_processor, services)
- Test individual functions and classes in isolation.
- All external dependencies are mocked via `conftest.py` fixtures.
- No network calls, no database access.

### Integration Tests (routes)
- Use FastAPI `TestClient` to send real HTTP requests through the full middleware stack.
- Verify request validation, error handling, CORS, and router registration.
- Service layer is mocked to isolate the HTTP layer.

---

## Key Fixtures (`conftest.py`)

| Fixture | Description |
|---|---|
| `valid_trainee_payload` | Complete valid `TraineeCreate` dict |
| `valid_batch_config_payload` | Complete valid `BatchConfig` dict |
| `mock_strapi` | Mocked `StrapiGraphql` instance |
| `mock_communication_manager` | Mocked `CommunicationManager` with success returns |
| `mock_strapi_methods` | Mocked `StrapiMethods` instance |

### External Dependency Stubs

The `conftest.py` stubs the following modules at import time to prevent failures:

- `review_scripts` (StrapiGraphql, StrapiMethods, CommunicationManager)
- `utils.secret` (get_auth, force_refresh_secrets, etc.)
- `utils.gdrive` (gsheet)
- `pathfig`

---

## What Each Module Tests

### `test_models.py`
- **ConfigInfo** — Defaults, custom values
- **TraineeInfo** — Name validation (empty, whitespace, no letters), email validation (format, strip, lowercase), status defaults, optional field stripping, date_of_birth handling, other_info JSON parsing
- **TraineeCreate** — Composite model creation
- **ErrorDetail** — `to_dict()` serialization
- **TraineeResponse** — `success_response()`, `error_response()`, `to_dict()` with optional fields
- **BatchConfig** — Defaults, required columns
- **BatchProcessingResponse** — Success/error responses, `to_dict()`

### `test_utils.py`
- **generate_secure_password** — Length, character sets (uppercase, lowercase, digits, special), randomness
- **Settings** — Default values, `get_settings()` caching
- **get_strapi_params** — All 12+ stage mappings (dev, prod, apply, kaim, etc.)
- **JSONFormatter** — Valid JSON output, extra_data inclusion
- **Error handlers** — `validation_exception_handler`, `pydantic_validation_exception_handler`

### `test_data_processor.py`
- **process_single_trainee** — Name title-casing, email lowering, password defaults, batch/group from config, date parsing, status defaults, other_info filtering, bio/city
- **change_name_fullname** — Single/multi-word first names
- **process_dataframe** — Column renaming, cleaning, batch assignment
- **find_duplicates** — No duplicates, with duplicates (case-insensitive)

### `test_trainee_service.py`
- **_cleanup_resources** — Cleanup at each step (alluser, profile, trainee), exception swallowing
- **_insert_user_and_alluser** — Mock user success, user creation error, alluser creation error
- **_insert_profile** — Success, failure with cleanup
- **_insert_trainee** — Success, failure with cleanup
- **create_trainee_services** — Full pipeline success, failure at each stage

### `test_controller.py`
- **create_trainee_controller** — Success, exception handling
- **create_admin_trainee_controller** — Non-mock success, mock success, exception handling
- **_send_welcome_email** — Successful send, exception handling

### `test_email_service.py`
- **_send_email** — Success, no source email, ClientError, unexpected error
- **_format_error_details** — Empty, None, with errors
- **_format_successful_details** — Empty, None, with credentials

### `test_webhook_service.py`
- **Init** — Requires callback_url, retry count/delay clamping
- **_generate_webhook_signature** — Hex output, consistency, different payloads, empty secret
- **_sanitize_payload** — Basic dict, NaN, None, pandas Series, nested structures, non-serializable
- **_send_webhook_with_retry** — Success on first attempt, no callback URL
- **notify_callback** — Calls send, handles exceptions

### `test_routes.py`
- **POST /trainee/single** — Valid request, missing name (422), invalid email (422), missing config (422)
- **POST /webhook** — Valid webhook, partial success, failed, invalid JSON
- **App setup** — CORS middleware present, all routers registered

---

## Running Specific Tests

```bash
# Single test file
python -m pytest tests/test_models.py -v

# Single test class
python -m pytest tests/test_models.py::TestTraineeInfo -v

# Single test function
python -m pytest tests/test_models.py::TestTraineeInfo::test_valid_name -v

# Tests matching a keyword
python -m pytest tests/ -k "email" -v

# Only async tests
python -m pytest tests/ -k "asyncio" -v
```

---

## Adding New Tests

1. Create test functions prefixed with `test_` in the appropriate test module.
2. Use fixtures from `conftest.py` for common mocks.
3. Mock new external dependencies in `conftest.py` if needed.
4. Run the full suite to verify no regressions: `python -m pytest tests/ -v`
