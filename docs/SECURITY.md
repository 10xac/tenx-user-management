# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.x | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do NOT** create a public GitHub issue.
2. Email the security team at **security@10academy.org** with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
   - Suggested fix (if any)
3. You will receive an acknowledgment within **48 hours**.
4. A fix will be prioritized based on severity.

---

## Security Measures

### Authentication
- **Bearer Token Auth:** All admin endpoints require a valid Strapi JWT token validated against the `/users/me` GraphQL endpoint.
- **Role-Based Access:** Admin endpoints (`/trainee/admin-single`, `/trainee/batch`, `/env/*`) require `Authenticated` or `Staff` role.
- **API Key Auth:** Optional `X-API-Key` header validation via AWS Secrets Manager.

### Data Protection
- **Password Handling:** Passwords are never stored in plain text in application logs. Default password is `10@Academy` which users are prompted to change on first login.
- **Secrets Management:** API tokens and secrets are stored in AWS Secrets Manager, not in environment files or code.
- **Input Validation:** All request payloads are validated through Pydantic models with custom validators for email format, name content, and data types.

### Network Security
- **CORS Policy:** Origin validation via regex pattern matching (`10academy.org`, `gettenacious.com`) plus explicit localhost origins for development.
- **HTTPS:** Production deployments enforce HTTPS via the load balancer.

### Webhook Security
- **HMAC Signing:** Outbound webhooks include an `X-Webhook-Signature` header with SHA-256 HMAC of the payload.
- **Payload Sanitization:** All webhook payloads are sanitized to prevent injection of non-serializable data.

### Known Limitations
- The `/trainee/single` endpoint currently has authentication commented out — this should be re-enabled for production.
- Error responses may include internal data in `error_data` fields — consider sanitizing for production.
- Debug `print()` statements in auth module should be replaced with proper logging.

---

## Dependencies

Security-relevant dependencies:

| Package | Purpose | Notes |
|---|---|---|
| `fastapi` | Web framework | Keep updated for security patches |
| `pydantic` | Data validation | Input sanitization layer |
| `httpx` | HTTP client | Used for Strapi auth and webhook delivery |
| `boto3` | AWS SDK | SES, Secrets Manager access |
| `python-jose` | JWT handling | Token processing |
