# E2E Tests for erg-ha

End-to-end tests that run the erg Home Assistant integration inside a real HA container against a mock Go backend. Tests exercise all user-facing operations through HA's REST API and Playwright browser automation.

## Architecture

```
pytest + Playwright  ──HTTP──▶  Home Assistant (Podman)
                                      │
                                      │ HTTP
                                      ▼
                               Mock Backend (aiohttp)
```

- **Home Assistant container**: runs the erg custom component from the repo
- **Mock backend**: implements all Go API endpoints with canned responses and request recording
- **pytest**: drives tests via HA REST API and Playwright (headless Chromium)

## Prerequisites

- Podman with `podman compose` (v2+ compose spec)
- Python 3.12+
- Chromium (installed via Playwright)

## Setup

```bash
cd /home/nick.farrell/git/erg-ha/e2e

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium --with-deps
```

## Running Tests

```bash
# Start services
podman compose up -d --build

# Run all tests
pytest -v

# Run only API tests (no browser needed)
pytest -m api -v

# Run only UI/Playwright tests
pytest -m ui -v

# Teardown
podman compose down -v
```

The `conftest.py` fixtures handle service startup/teardown automatically when running `pytest` directly, so manual `podman compose up` is optional. To run with manual container management (useful for debugging), start the containers first, then run pytest.

## Test Modules

| Module                   | Marker | What it tests                                                            |
| ------------------------ | ------ | ------------------------------------------------------------------------ |
| `test_setup.py`          | api    | Integration loads, global entities exist, solve status                   |
| `test_entities.py`       | api    | Global/per-job sensor values, switch/number/select/text controls         |
| `test_services.py`       | api    | `erg.create_job`, `erg.update_job`, `erg.delete_job`, `erg.check_health` |
| `test_coordinator.py`    | api    | Schedule request structure, system fields, job boxes                     |
| `test_calendar.py`       | api    | Calendar entity state and events                                         |
| `test_executor.py`       | api    | Entity on/off based on scheduled slots                                   |
| `test_error_handling.py` | api    | Backend 500/401 handling, recovery                                       |
| `test_config_flow.py`    | ui     | Integration page, config entry in browser                                |
| `test_options_flow.py`   | ui     | Options wizard navigation                                                |
| `test_job_lifecycle.py`  | api    | Job CRUD lifecycle, duplicates, multiple jobs                            |

## Mock Backend

The mock backend (`mock_backend/server.py`) implements all endpoints the integration calls. It also exposes test control endpoints:

| Endpoint         | Method | Purpose                                                                                      |
| ---------------- | ------ | -------------------------------------------------------------------------------------------- |
| `/mock/requests` | GET    | Returns all recorded requests (method, path, headers, body)                                  |
| `/mock/config`   | POST   | Override endpoint behavior: `{"endpoint": "/api/v1/schedule", "status": 500, "body": {...}}` |
| `/mock/reset`    | POST   | Reset request log and overrides to defaults                                                  |

Response JSON files in `mock_backend/responses/` use `__NOW__`, `__NOW+15m__`, `__NOW-15m__` placeholders that are replaced with real timestamps at request time.

## Failure Artifacts

On test failure, the following are captured in `e2e/artifacts/`:

- `{test_name}.png` — browser screenshot (Playwright tests only)
- `{test_name}_states.json` — all HA entity states
- `{test_name}_ha.log` — HA container logs
- `{test_name}_requests.json` — mock backend request log

JUnit XML and HTML reports are also written to `artifacts/`.

## Directory Structure

```
e2e/
  docker-compose.yml          # Podman compose: HA + mock backend
  configuration.yaml          # Minimal HA config with test entities
  pytest.ini                  # pytest configuration
  requirements.txt            # Python dependencies
  conftest.py                 # Session and function fixtures
  mock_backend/
    server.py                 # aiohttp mock of Go backend
    responses/*.json          # Canned response templates
  helpers/
    ha_bootstrap.py           # HA onboarding automation
    ha_client.py              # HA REST API wrapper
    wait.py                   # Polling utilities
    debug.py                  # Failure artifact capture
  tests/
    test_setup.py             # Integration loading
    test_entities.py          # Entity states and controls
    test_services.py          # Service calls
    test_coordinator.py       # Schedule cycle
    test_calendar.py          # Calendar events
    test_executor.py          # Entity control
    test_error_handling.py    # Error paths
    test_config_flow.py       # Config flow UI
    test_options_flow.py      # Options wizard UI
    test_job_lifecycle.py     # Job CRUD
  artifacts/                  # Gitignored; screenshots, logs, dumps
```
