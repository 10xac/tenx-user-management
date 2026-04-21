# API Reference

## Base URL

```
http://localhost:8000
```

## Authentication

Most endpoints require authentication via a **Bearer token** in the `Authorization` header. Admin endpoints additionally verify the user has `Authenticated` or `Staff` role in Strapi.

```
Authorization: Bearer <strapi_jwt_token>
```

---

## Trainee Endpoints

### POST `/trainee/single`

Create a single trainee with all related records (user, alluser, profile, trainee).

**Auth:** None (open endpoint — auth is commented out in current code)

**Request Body:**

```json
{
  "config": {
    "run_stage": "dev",
    "batch": "5",
    "role": "trainee",
    "is_mock": false,
    "group_id": "12",
    "login_url": "https://dev-tenx.10academy.org/login"
  },
  "trainee": {
    "name": "John Doe",
    "email": "john.doe@example.com",
    "password": "SecureP@ss1",
    "nationality": "Kenya",
    "gender": "Male",
    "date_of_birth": "1995-01-01",
    "vulnerable": "No",
    "status": "Accepted",
    "bio": "A short bio",
    "city_of_residence": "Nairobi",
    "other_info": {}
  }
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Trainee created successfully",
  "data": {
    "alluser_id": "200",
    "profile": { "data": { "createProfileInformation": { "data": { "id": "300" } } } },
    "trainee": { "id": "400" }
  }
}
```

**Error Response (422):**

```json
{
  "success": false,
  "message": "Error occurred during trainee creation",
  "error": {
    "error_type": "VALIDATION_ERROR",
    "error_message": "Invalid email format",
    "error_location": "email_validation",
    "error_data": { "field": "email", "value": "bad" }
  }
}
```

---

### POST `/trainee/admin-single`

Create a trainee as an admin. Optionally sends a welcome email.

**Auth:** Bearer token with `Authenticated` or `Staff` role required.

**Request Body:** Same as `/trainee/single`.

**Response:** Same as `/trainee/single`.

---

### POST `/trainee/batch`

Upload a CSV file for batch trainee creation. Processing runs in the background.

**Auth:** Bearer token with `Authenticated` or `Staff` role required.

**Content-Type:** `multipart/form-data`

**Form Fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | File (required) | — | CSV file with `name` and `email` columns |
| `run_stage` | string | `"dev"` | Strapi environment stage |
| `batch` | string | `""` | Batch identifier |
| `role` | string | `"trainee"` | Default role |
| `group_id` | string | `null` | Group ID |
| `delimiter` | string | `","` | CSV delimiter |
| `encoding` | string | `"utf-8"` | File encoding |
| `chunk_size` | int | `20` | Processing chunk size |
| `is_mock` | bool | `false` | Create mock users |
| `login_url` | string | `null` | Login URL for welcome emails |

**Response (200):**

```json
{
  "success": true,
  "message": "Batch processing started",
  "total_processed": 0,
  "successful": 0,
  "failed": 0,
  "data": { "status": "processing", "batch": "5" },
  "batch_info": { "batch": "5", "admin_email": "admin@10academy.org" }
}
```

---

## Webhook Endpoints

### POST `/webhook`

Handle incoming webhooks for batch processing notifications.

**Request Body:**

```json
{
  "status": "success",
  "batch": "5",
  "errors": []
}
```

**Response (200):**

```json
{
  "status": "received",
  "message": "Webhook processed successfully",
  "data": { "status": "success", "batch": "5", "errors": [] }
}
```

---

## Environment Endpoints

### POST `/env/refresh_env_vars`

Force refresh secrets from AWS Secrets Manager.

**Auth:** Bearer token with admin role required.

**Request Body:**

```json
{
  "key": null,
  "sname": "tenx/env/vars",
  "run_stage": "dev"
}
```

**Response (200):**

```json
{
  "success": true,
  "message": "Successfully refreshed 10 secrets from tenx/env/vars",
  "secrets_count": 10,
  "api_key_cache_cleared": true,
  "masked_secrets": { "KEY_NAME": "****" }
}
```

---

### POST `/env/check_env_cache`

Check the status of the secrets cache.

**Auth:** Bearer token with admin role required.

**Request Body:**

```json
{
  "key": null,
  "sname": "tenx/env/vars",
  "run_stage": "dev"
}
```

**Response (200):**

```json
{
  "success": true,
  "cache_metadata": {
    "memory_cache_exists": true,
    "cache_age_seconds": 3600,
    "is_fresh": true,
    "num_keys": 10
  },
  "sample_keys": ["KEY1", "KEY2"]
}
```

---

## Error Codes

| Error Type | HTTP Status | Description |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request payload validation failed |
| `AUTH_ERROR` | 200* | Authentication/authorization failed |
| `USER_CREATION_ERROR` | 200* | Failed to create Strapi user |
| `ALLUSER_CREATION_ERROR` | 200* | Failed to create alluser record |
| `PROFILE_CREATION_ERROR` | 200* | Failed to create profile |
| `TRAINEE_CREATION_ERROR` | 200* | Failed to create trainee record |
| `DATA_PROCESSING_ERROR` | 200* | Data processing/validation failed |
| `UNEXPECTED_ERROR` | 200*/400 | Unhandled exception |

> *Note: Some error responses return HTTP 200 with `"success": false` in the body. This is a known design pattern in this service.
