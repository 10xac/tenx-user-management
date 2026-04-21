# 10Academy User Management Service

## Architecture

### Overview
The User Management service is a **FastAPI-based backend** responsible for creating and managing trainee and admin users within the 10Academy platform. It supports both single-user creation and batch processing from CSV files, integrates with Strapi CMS for user/profile storage, and sends welcome email notifications.

### Technology Stack
- **Framework:** FastAPI (Python)
- **Server:** Uvicorn
- **CMS Integration:** Strapi (REST + GraphQL) for user, alluser, profile, and trainee records
- **Configuration:** Pydantic `BaseSettings` with `.env` support
- **Authentication:** Bearer token validation via Strapi user info lookup
- **Background Tasks:** FastAPI `BackgroundTasks` for async email sending
- **File Processing:** Pandas for CSV parsing and validation
- **Containerization:** Docker

### Application Structure
```
api/
├── main.py                    # FastAPI app entry, CORS, exception handlers, router includes
├── core/
│   ├── config.py              # Settings: app name, CORS, run stage, file limits, required columns
│   └── auth.py                # Token validation and admin access verification
├── routes/
│   ├── trainee_routes.py      # POST /trainee/single, POST /trainee/admin-single
│   ├── batch_routes.py        # POST /batch/upload - CSV batch trainee creation
│   ├── webhook_routes.py      # Webhook endpoints for external integrations
│   └── env_routes.py          # Environment management endpoints
├── controllers/
│   └── trainee_controller.py  # Business logic orchestration for trainee creation
├── services/
│   ├── trainee_service.py     # Core user creation: user, alluser, profile, trainee records
│   └── batch_service.py       # CSV processing, per-row trainee creation, notifications
├── models/
│   └── trainee.py             # Pydantic models: TraineeCreate, TraineeInfo, ConfigInfo, TraineeResponse
├── Dockerfile
└── .env
```

### Key Design Patterns
- **MVC-like Layering:** Routes → Controllers → Services, with clear separation of concerns.
- **Pydantic Validation:** Request/response models with custom validators for name, email, and config fields.
- **Background Email Tasks:** Admin trainee creation triggers async welcome emails via `BackgroundTasks`.
- **Batch Processing with Error Handling:** CSV rows are processed individually; failures on one row don't block others. Partial success results are returned.
- **Cleanup on Failure:** If any step in the multi-record creation pipeline fails, previously created records are rolled back.

---

## Functionality

### Core Features
1. **Single Trainee Creation** — Create a single trainee user with user, alluser, profile, and trainee records in Strapi.
2. **Admin Trainee Creation** — Admin-authorized trainee creation with automatic welcome email dispatch.
3. **Batch Trainee Processing** — Upload a CSV file to create multiple trainees at once, with row-level validation and error reporting.
4. **Webhook Integration** — External system callbacks for event-driven user operations.
5. **Environment Management** — Endpoints to manage runtime environment configuration.

### API Endpoints
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trainee/single` | Create a single trainee (no email) |
| `POST` | `/trainee/admin-single` | Admin creates trainee + sends welcome email |
| `POST` | `/batch/upload` | Upload CSV for batch trainee creation |
| Various | `/webhook/*` | Webhook event handlers |
| Various | `/env/*` | Environment configuration |

### Data Flow — Single Trainee Creation
1. Route receives `TraineeCreate` payload (validated by Pydantic).
2. Controller invokes `TraineeService.create_trainee_services()`.
3. Service processes trainee data → creates `user` → creates `alluser` → creates `profile` → creates `trainee` in Strapi.
4. On failure at any step, cleanup removes all previously created records.
5. For admin creation, a `BackgroundTask` sends a welcome email on success.

### Data Flow — Batch Processing
1. CSV file uploaded, validated for size (`MAX_FILE_SIZE: 10MB`) and type (`text/csv`).
2. Required columns checked: `name`, `email`.
3. Each row processed individually via `_process_trainee_record`.
4. Results aggregated: success count, failure count, per-row error details.
5. Notification sent on batch completion.

### Configuration
- **`RUN_STAGE`** — Environment selector (dev, prod, etc.)
- **`DEFAULT_ROLE`** — Default role for new users (`trainee`)
- **`MAX_FILE_SIZE`** — 10MB limit for CSV uploads
- **`REQUIRED_COLUMNS`** — `["name", "email"]`
- **CORS** — Regex-based origin matching for `10academy.org` and `gettenacious.com`

---

## Source Guide

### Entry Point
- **`api/main.py`** — Creates FastAPI app with title "10 Academy User API". Configures CORS (regex pattern for production domains + explicit additional origins). Registers exception handlers. Includes routers: `trainee_routes`, `batch_routes`, `webhook_routes`, `env_routes`.

### Configuration
- **`api/core/config.py`** — `Settings` class defines app name, CORS origins, run stage, default role, file processing limits, allowed file types, and required CSV columns.

### Authentication
- **`api/core/auth.py`** — `verify_admin_access` dependency validates Bearer tokens against Strapi and checks admin role. Used as a `Depends` guard on admin-only routes.

### Models
- **`api/models/trainee.py`** — Pydantic models:
  - `ConfigInfo` — `run_stage`, `batch`, `role`, `is_mock`, `group_id`, `login_url`
  - `TraineeInfo` — `name`, `email`, `password`, `status` with validators
  - `TraineeCreate` — Combines `TraineeInfo` + `ConfigInfo`
  - `TraineeResponse` — Standard API response with success status and data

### Controllers
- **`api/controllers/trainee_controller.py`** — `TraineeController` orchestrates service calls and optional email sending.

### Services
- **`api/services/trainee_service.py`** — `TraineeService` handles the full user creation pipeline (user → alluser → profile → trainee) with cleanup on failure.
- **`api/services/batch_service.py`** — `BatchService` parses CSV, validates rows, creates trainees per-row, aggregates results, and sends completion notifications.
