# Changelog

All notable changes to the 10Academy User Management Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive unit and integration test suite (141 tests)
- `docs/` folder with industry-standard documentation
  - `API_REFERENCE.md` — Full API endpoint documentation
  - `ARCHITECTURE.md` — System architecture and data flow diagrams
  - `CONTRIBUTING.md` — Developer onboarding and contribution guide
  - `DEPLOYMENT.md` — Docker build and production deployment guide
  - `CHANGELOG.md` — This file
  - `SECURITY.md` — Security policy and vulnerability reporting
  - `TESTING.md` — Test strategy and execution guide
- `pytest.ini` configuration
- `tests/conftest.py` with shared fixtures and external dependency stubs

### Changed
- (No changes to existing code in this release)

### Fixed
- (No fixes in this release)

---

## [1.0.0] — Initial Release

### Added
- Single trainee creation endpoint (`POST /trainee/single`)
- Admin trainee creation with welcome email (`POST /trainee/admin-single`)
- Batch CSV trainee processing (`POST /trainee/batch`)
- Webhook receiver for batch notifications (`POST /webhook`)
- Environment secrets management (`POST /env/refresh_env_vars`, `POST /env/check_env_cache`)
- Multi-stage Strapi CMS support (dev, prod, apply, kaim, simulation, etc.)
- AWS SES email integration (welcome, batch summary, CSV attachment)
- Webhook delivery with HMAC signing and retry logic
- Pydantic v2 request/response models with validators
- JSON-structured logging
- Docker and docker-compose support
- Resource cleanup on partial creation failure
