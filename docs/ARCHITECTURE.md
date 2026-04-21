# Architecture

## System Overview

```
┌──────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Frontend   │────▶│  User Management API │────▶│  Strapi CMS     │
│  (Next.js)   │     │  (FastAPI, port 8000)│     │  (GraphQL+REST) │
└──────────────┘     └──────────┬───────────┘     └─────────────────┘
                                │
                     ┌──────────┴───────────┐
                     │                      │
              ┌──────▼──────┐      ┌────────▼────────┐
              │  AWS SES    │      │  AWS Secrets Mgr │
              │  (Email)    │      │  (Env vars)      │
              └─────────────┘      └──────────────────┘
```

## Application Layers

### 1. Routes (HTTP Layer)
- **Location:** `api/routes/`
- **Responsibility:** Define HTTP endpoints, parse requests, validate input, delegate to controllers/services.
- **Files:**
  - `trainee_routes.py` — Single trainee creation endpoints
  - `batch_routes.py` — CSV batch processing endpoint
  - `webhook_routes.py` — Webhook receiver for external notifications
  - `env_routes.py` — Environment/secrets management endpoints

### 2. Controllers (Orchestration Layer)
- **Location:** `api/controllers/`
- **Responsibility:** Coordinate between services, handle business logic flow, manage background tasks.
- **Files:**
  - `trainee_controller.py` — Orchestrates trainee creation and welcome email dispatch

### 3. Services (Business Logic Layer)
- **Location:** `api/services/`
- **Responsibility:** Core business logic, external API integration, data transformation.
- **Files:**
  - `trainee_service.py` — Full trainee creation pipeline (user → alluser → profile → trainee) with cleanup on failure
  - `batch_service.py` — CSV parsing, per-row processing, result aggregation, notification dispatch
  - `data_processor.py` — Data validation, cleaning, and transformation
  - `email_service.py` — AWS SES email sending (welcome, batch summary, CSV attachment)
  - `webhook_service.py` — Outbound webhook delivery with retry and HMAC signing

### 4. Models (Data Layer)
- **Location:** `api/models/`
- **Responsibility:** Pydantic models for request/response validation.
- **Files:**
  - `trainee.py` — `TraineeInfo`, `ConfigInfo`, `TraineeCreate`, `TraineeResponse`, `BatchConfig`, `BatchProcessingResponse`, etc.

### 5. Core (Infrastructure Layer)
- **Location:** `api/core/`
- **Responsibility:** Cross-cutting concerns — auth, config, logging, error handling.
- **Files:**
  - `config.py` — `Settings` (Pydantic BaseSettings), `get_strapi_params()` for multi-stage CMS routing
  - `auth.py` — Bearer token validation via Strapi GraphQL, admin role verification
  - `security.py` — API key validation via AWS Secrets Manager
  - `error_handlers.py` — Custom exception handlers for validation errors
  - `logging_config.py` — JSON-structured logging with file and console handlers

---

## Data Flow — Single Trainee Creation

```
Request (JSON)
    │
    ▼
Route (trainee_routes.py)
    │  validates TraineeCreate model
    ▼
Controller (trainee_controller.py)
    │  creates TraineeService
    ▼
DataProcessor.process_single_trainee()
    │  cleans name, email, dates; sets defaults
    ▼
TraineeService._insert_user_and_alluser()
    │  → Strapi REST: create user
    │  → Strapi GraphQL: create alluser
    ▼
TraineeService._insert_profile()
    │  → Strapi GraphQL: create profile
    ▼
TraineeService._insert_trainee()
    │  → Strapi REST: create trainee
    ▼
Response (JSON)
```

**Cleanup on failure:** If any step fails, all previously created resources are deleted in reverse order.

---

## Data Flow — Batch Processing

```
Request (multipart/form-data with CSV)
    │
    ▼
Route (batch_routes.py)
    │  validates file, config, auth
    │  returns immediate "processing started" response
    ▼
BackgroundTask: process_batch_background()
    │
    ▼
BatchService.process_batch_trainees()
    │  parses CSV → validates columns → iterates rows
    │  for each row:
    │    → DataProcessor.process_single_trainee()
    │    → TraineeService.create_trainee_services()
    │  aggregates results
    ▼
BatchService._send_notifications()
    │  → EmailService: send summary + CSV to admin
    │  → WebhookService: POST results to callback URL (if configured)
    ▼
Done (results logged)
```

---

## External Dependencies

| Service | Protocol | Purpose |
|---|---|---|
| Strapi CMS | GraphQL + REST | User, alluser, profile, trainee CRUD |
| AWS SES | AWS SDK (boto3) | Send welcome and batch summary emails |
| AWS Secrets Manager | AWS SDK (boto3) | Retrieve environment secrets and API tokens |
| Google Sheets | gspread API | Read applicant data for batch processing |

---

## Multi-Stage CMS Support

The service supports multiple Strapi environments via `get_strapi_params()`:

| Stage Prefix | CMS Root | Token SSM Key |
|---|---|---|
| `dev` | `dev-cms` | `TENX_DEV_STRAPI_TOKEN` |
| `prod` | `cms` | `TENX_PROD_STRAPI_TOKEN` |
| `devapply` | `dev-apply-cms` | `APPLY_DEV_STRAPI_TOKEN` |
| `apply` | `apply-cms` | `APPLY_PROD_STRAPI_TOKEN` |
| `kaim` | `kaimcms` | `KAIM_PROD_STRAPI_TOKEN` |
| `simulation` | `simulation-cms` | `TENX_SIMULATION_STRAPI_TOKEN` |
| `tenacious` | `tenaciouscms` | `TENACIOUS_PROD_STRAPI_TOKEN` |
| ... | ... | ... |
