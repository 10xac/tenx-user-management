# Deployment Guide

## Overview

The 10Academy User Management Service is deployed as a Docker container, typically behind an AWS Application Load Balancer or as part of an ECS task definition.

---

## Prerequisites

- Docker 20.10+
- AWS CLI configured with appropriate credentials
- Access to the target Strapi CMS environment
- AWS SES verified sender email (for email notifications)
- AWS Secrets Manager access (for environment variable management)

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `STRAPI_STAGE` | Yes | `unknown` | Strapi environment (dev, prod, apply, kaim, etc.) |
| `STRAPI_TOKEN` | Yes | — | Strapi API token (or via AWS SSM) |
| `AWS_REGION` | No | `us-east-1` | AWS region for SES and Secrets Manager |
| `SES_SOURCE_EMAIL` | No | — | Verified SES email for sending notifications |

---

## Docker Build

### Build the image

```bash
docker build -t tenx-user-management .
```

### Run locally

```bash
docker run -p 8000:8000 \
  -e STRAPI_STAGE=dev \
  -e STRAPI_TOKEN=your-token \
  tenx-user-management
```

### Using docker-compose

```bash
docker-compose up --build
```

---

## Build Script

The `build.sh` script automates the build and push process:

```bash
chmod +x build.sh
./build.sh
```

---

## Production Deployment Checklist

1. **Environment variables** — Verify all required env vars are set in the deployment target.
2. **Strapi connectivity** — Confirm the service can reach the target Strapi CMS.
3. **AWS SES** — Verify the source email address is verified in the target AWS region.
4. **Secrets Manager** — Ensure the service role has `secretsmanager:GetSecretValue` permission.
5. **CORS origins** — Review the allowed origins in `api/main.py` for the production domain.
6. **Health check** — The root `/` endpoint can be used for ALB health checks.
7. **Logging** — Ensure the `logs/` directory is writable or mounted as a volume.

---

## Rollback

If a deployment fails:

1. Revert to the previous Docker image tag.
2. Verify Strapi connectivity from the reverted service.
3. Check logs for any data inconsistencies from partial deployments.

---

## Monitoring

- **Application logs** — JSON-formatted logs in `logs/batch_processing.log` and `logs/errors.log`.
- **Health endpoint** — `GET /` returns application info.
- **OpenAPI docs** — `GET /docs` for Swagger UI.
