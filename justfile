# Recipes shell out only to `uv`, which resolves the project venv on every
# platform — no .venv/bin vs .venv\Scripts split, no bash dependency.
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# List available recipes
default:
    @just --list

# ============================================================================
# Setup
# ============================================================================

# Create the venv and install the exact locked dependencies + git hooks
install:
    uv sync
    uv run pre-commit install
    @echo "Ready. Copy .env.template to .env and fill in your credentials."

# Re-resolve the lockfile after changing dependencies in pyproject.toml
lock:
    uv lock
    uv sync

# Verify the environment matches uv.lock exactly, without modifying either
verify-lock:
    uv lock --check
    uv sync --locked --dry-run

# ============================================================================
# Quality
# ============================================================================

# Run every check: lint, format, types, tests, coverage floor, agent docs
check: lint typecheck check-agents coverage-gate
    @echo "All checks passed."

# Lint and auto-fix, then format
fmt:
    uv run ruff check src/ tests/ scripts/ --fix
    uv run ruff format src/ tests/ scripts/

# Lint without fixing — fails on any finding
lint:
    uv run ruff check src/ tests/ scripts/
    uv run ruff format --check src/ tests/ scripts/

# Serve the real app on its own port (:8100), for inspecting the UI
preview *args: web-build
    uv run python scripts/preview.py {{ args }}

# Screenshot every view into web/.shots (starts and stops its own preview)
shots *args: web-build
    cd web && pnpm shoot {{ args }}

# Authorize this machine with Yahoo (opens a browser); --force replaces the token
yahoo-login *args:
    uv run python scripts/yahoo_login.py {{ args }}

# Score the win-probability simulation on weeks already played (reads the live league)
backtest *args:
    uv run python scripts/backtest.py {{ args }}

# Report what this machine is configured for, and flag typo'd .env keys
doctor:
    uv run python scripts/doctor.py

# Verify AGENTS.md symlinks, length limits and skill frontmatter
check-agents:
    uv run python scripts/check_agent_docs.py

# Type check
typecheck:
    uv run pyrefly check

# Run the hermetic test suite
test *args:
    uv run pytest {{args}}

# Test suite with a coverage report
coverage:
    uv run pytest --cov --cov-report=term-missing

# Fail if coverage drops below the agreed floor
coverage-gate:
    uv run pytest --cov --cov-report=term-missing --cov-fail-under=95

# Run the tests that hit live APIs (needs credentials)
test-integration:
    uv run pytest -m integration

# Run all hooks against every file, as pre-commit would
hooks:
    uv run pre-commit run --all-files

# ============================================================================
# Run
# ============================================================================

# Start the interactive CLI
run:
    uv run python -m thefrontoffice

# Build the UI and serve everything from one process (http://localhost:8000)
ui: web-build
    uv run python -m thefrontoffice.adapters.inbound.web.api

# API only, reloading on change. Pair with `just web` in a second terminal.
api:
    uv run uvicorn thefrontoffice.adapters.inbound.web.api:app --reload --port 8000

# UI dev server with hot reload (http://localhost:5173), proxying /api to `just api`
web:
    cd web && pnpm dev

# Install front-end dependencies
web-install:
    cd web && pnpm install

# Compile the UI into web/dist, which `ui` then serves
web-build: web-install
    cd web && pnpm build

# Lint the front end. From inside web/, because corepack picks the pnpm
# version from the directory it starts in: from the repo root, which pins
# none, it runs its own default, and a newer major refuses web/'s pin outright.
lint-web:
    cd web && pnpm lint

# Lint, typecheck, test and build the front end — this is what CI runs
check-web: web-install lint-web
    cd web && pnpm exec tsc -b
    cd web && pnpm test
    # Builds because the bundle budget is checked by the build and nothing
    # else. Without this the recipe passes on a change CI then rejects.
    cd web && pnpm build

# ============================================================================
# Housekeeping
# ============================================================================

# Delete caches and build artefacts (leaves .env and auth tokens alone)
clean:
    uv run python scripts/clean.py

# Delete the cached platform responses so the next run refetches
clean-data:
    uv run python scripts/clean.py --data-only
