"""
Simulation Configuration
========================
Central config for the real-time simulation against the deployed
user-management API at https://user-management.10academy.org
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SIMULATION_DIR = Path(__file__).parent
USER_DATA_DIR = SIMULATION_DIR / "user_data"
RESULTS_DIR = SIMULATION_DIR / "results"

# Ensure directories exist
USER_DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# API Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.getenv(
    "SIMULATION_BASE_URL",
    "https://user-management.10academy.org",
)
RUN_STAGE = "simulation"

# Bearer token for authenticated endpoints (admin-single, batch, env)
# Set via environment variable before running:
#   export SIMULATION_AUTH_TOKEN="your-strapi-jwt-token"
AUTH_TOKEN = os.getenv("SIMULATION_AUTH_TOKEN", "")

# ---------------------------------------------------------------------------
# User tiers to simulate
# ---------------------------------------------------------------------------
USER_TIERS = [10, 100, 200, 500, 1000, 2000, 4000, 10000]

# ---------------------------------------------------------------------------
# Simulation Parameters
# ---------------------------------------------------------------------------
# Concurrency per tier (how many parallel requests to fire)
CONCURRENCY_MAP = {
    10: 2,
    100: 10,
    200: 20,
    500: 25,
    1000: 50,
    2000: 50,
    4000: 100,
    10000: 100,
}

# Request timeout in seconds
REQUEST_TIMEOUT = 60

# Batch chunk size for CSV uploads
BATCH_CHUNK_SIZE = 20

# Webhook callback URL (where batch processing reports back)
WEBHOOK_CALLBACK_URL = os.getenv(
    "SIMULATION_WEBHOOK_URL",
    f"{BASE_URL}/webhook",
)

# Delay between tier runs (seconds) to let the server cool down
INTER_TIER_DELAY = 5

# ---------------------------------------------------------------------------
# Trainee template defaults
# ---------------------------------------------------------------------------
DEFAULT_BATCH_ID = "1"   # Strapi batch record ID in simulation-cms
DEFAULT_GROUP_ID = ""    # No groups configured in simulation-cms yet
DEFAULT_ROLE = "trainee"
DEFAULT_PASSWORD = "SimPass10!"
LOGIN_URL = "https://dev-tenx.10academy.org/login"

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
ENDPOINTS = {
    "single":        {"method": "POST", "path": "/trainee/single",        "auth": False},
    "admin_single":  {"method": "POST", "path": "/trainee/admin-single",  "auth": True},
    "batch":         {"method": "POST", "path": "/trainee/batch",         "auth": True},
    "webhook":       {"method": "POST", "path": "/webhook",              "auth": False},
    "env_refresh":   {"method": "POST", "path": "/env/refresh_env_vars",  "auth": True},
    "env_check":     {"method": "POST", "path": "/env/check_env_cache",   "auth": True},
}
