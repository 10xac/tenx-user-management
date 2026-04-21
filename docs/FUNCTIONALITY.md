# Functionality

## Overview

The 10Academy User Management Service handles trainee onboarding for the 10 Academy platform — creating user accounts, profiles, and trainee records in Strapi CMS, with support for single creation, admin creation with welcome emails, and batch CSV processing.

---

## Core Features

### 1. Single Trainee Creation
- Create a full trainee record: Strapi user → alluser → profile → trainee
- Automatic data cleaning: name title-casing, email lowering, date parsing
- Resource cleanup on failure: previously created records are deleted in reverse order
- **Endpoint:** `POST /trainee/single`

### 2. Admin Trainee Creation
- Same pipeline as single creation, but requires admin authentication
- Optionally sends a welcome email to the new trainee via AWS SES
- **Endpoint:** `POST /trainee/admin-single`

### 3. Batch CSV Processing
- Upload a CSV file with `name` and `email` columns for bulk trainee creation
- Processing runs as a FastAPI `BackgroundTask` (immediate response returned)
- Configurable chunk size for processing batches
- Results aggregated and notifications sent:
  - Admin email with summary + CSV attachment
  - Webhook POST to callback URL (if configured) with HMAC-signed payload
- **Endpoint:** `POST /trainee/batch`

### 4. Webhook Notifications
- Receive and process incoming webhooks for batch processing status
- **Endpoint:** `POST /webhook`

### 5. Environment/Secrets Management
- Force refresh secrets from AWS Secrets Manager at runtime
- Check status of the in-memory secrets cache
- **Endpoints:** `POST /env/refresh_env_vars`, `POST /env/check_env_cache`

---

## Key Processing Components

### DataProcessor (`api/services/data_processor.py`)
- Standardizes names (title-casing), emails (lowercase, strip), dates
- Validates required fields
- Detects duplicates (case-insensitive)
- Prepares DataFrames for batch processing

### TraineeService (`api/services/trainee_service.py`)
- Full creation pipeline: user → alluser → profile → trainee
- Each step calls Strapi REST or GraphQL
- On failure: cleanup deletes all previously created resources in reverse order

### BatchService (`api/services/batch_service.py`)
- Parses CSV file content
- Iterates rows through DataProcessor + TraineeService
- Aggregates results (success/failure counts, error details)
- Sends notifications via EmailService and WebhookService

### EmailService (`api/services/email_service.py`)
- AWS SES integration for sending emails
- Welcome emails to new trainees
- Batch summary emails to admins (with CSV attachment)

### WebhookService (`api/services/webhook_service.py`)
- Outbound webhook delivery with retry and exponential backoff
- HMAC-SHA256 signature in `X-Webhook-Signature` header
- Payload sanitization (NaN, None, non-serializable values)

---

## Configuration

### Multi-Stage CMS Support
The `run_stage` parameter determines which Strapi CMS instance is used. Mapping is defined in `api/core/config.py` → `get_strapi_params()`. Stages include dev, prod, apply, kaim, simulation, tenacious, and more.

### Authentication
- Bearer token validated against Strapi `/users/me` GraphQL endpoint
- Role-based access: `Authenticated` or `Staff` role required for admin endpoints
- Optional API key validation via `X-API-Key` header and AWS Secrets Manager
