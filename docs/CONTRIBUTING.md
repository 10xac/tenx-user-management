# Contributing Guide

## Getting Started

### Prerequisites

- Python 3.10+
- pip
- Access to the 10Academy Strapi CMS (dev environment minimum)
- AWS credentials (for SES email service and Secrets Manager)

### Local Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd tenx-user-management
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # macOS/Linux
   ```

3. **Install dependencies:**
   ```bash
   pip install -r api/requirements.txt
   pip install pytest pytest-asyncio httpx  # dev dependencies
   ```

4. **Set environment variables:**
   ```bash
   cp .env.example .env  # if available
   export STRAPI_STAGE=dev
   ```

5. **Run the server:**
   ```bash
   python -m api.main
   # or
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## Development Workflow

### Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code |
| `dev` | Integration branch for development |
| `feature/*` | New features |
| `bugfix/*` | Bug fixes |
| `hotfix/*` | Urgent production fixes |

### Creating a Feature Branch

```bash
git checkout dev
git pull origin dev
git checkout -b feature/your-feature-name
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add batch CSV validation endpoint
fix: handle empty password field in trainee creation
docs: update API reference for batch endpoint
test: add unit tests for DataProcessor
refactor: extract email template logic
```

---

## Code Standards

### Style

- Follow **PEP 8** for Python code style.
- Use **type hints** for function signatures.
- Use **docstrings** (Google style) for all public functions and classes.
- Keep functions focused — single responsibility principle.

### Project Structure

```
api/
├── controllers/    # Business logic orchestration
├── core/           # Config, auth, logging, error handlers
├── models/         # Pydantic request/response models
├── routes/         # FastAPI router definitions
├── services/       # External service integrations
└── utils/          # Utility functions
```

### Adding a New Endpoint

1. Define Pydantic models in `api/models/`.
2. Create service logic in `api/services/`.
3. Add controller in `api/controllers/` (if needed).
4. Define the route in `api/routes/`.
5. Include the router in `api/main.py`.
6. Write tests in `tests/`.

---

## Testing

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_models.py -v

# Run with coverage
python -m pytest tests/ --cov=api --cov-report=html
```

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures, external dependency stubs
├── test_models.py           # Pydantic model & validator tests
├── test_utils.py            # Password generator, config, logging, error handlers
├── test_data_processor.py   # DataProcessor unit tests
├── test_trainee_service.py  # TraineeService unit tests (mocked Strapi)
├── test_controller.py       # TraineeController unit tests
├── test_email_service.py    # EmailService unit tests (mocked SES)
├── test_webhook_service.py  # WebhookService unit tests
└── test_routes.py           # HTTP integration tests (FastAPI TestClient)
```

### Writing Tests

- All external dependencies (Strapi, AWS, Google Sheets) must be **mocked**.
- Use `conftest.py` fixtures for shared mocks.
- Name tests descriptively: `test_<what>_<condition>_<expected>`.
- Mark async tests with `@pytest.mark.asyncio`.

---

## Pull Request Process

1. Ensure all tests pass: `python -m pytest tests/ -v`
2. Update documentation if adding/changing endpoints.
3. Fill out the PR template with description, testing steps, and screenshots (if UI-related).
4. Request review from at least one team member.
5. Squash merge into `dev` after approval.

---

## Reporting Issues

- Use GitHub Issues with the appropriate labels (`bug`, `enhancement`, `documentation`).
- Include reproduction steps, expected behavior, and actual behavior.
- Attach relevant logs if applicable.
