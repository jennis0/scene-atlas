.PHONY: test test-unit test-integration test-frontend test-all test-cov \
       lint lint-fix format-check check

# ── Quick check (what pre-commit does) ─────────────────────────────────────
check: lint format-check

# ── Linting ────────────────────────────────────────────────────────────────
lint:
	uv run ruff check backend/
	cd frontend && npx eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0

lint-fix:
	uv run ruff check --fix backend/
	uv run ruff format backend/
	cd frontend && npx eslint . --ext ts,tsx --fix
	cd frontend && npx prettier --write src/

format-check:
	uv run ruff format --check backend/
	cd frontend && npx prettier --check src/

# ── Tests ──────────────────────────────────────────────────────────────────
test: test-unit test-frontend

test-all: test-unit test-integration test-frontend

test-unit:
	uv run python -m pytest backend/tests/unit -v

test-integration:
	uv run python -m pytest backend/tests/integration -v

test-frontend:
	cd frontend && npx vitest run

# ── Coverage ───────────────────────────────────────────────────────────────
test-cov:
	uv run python -m pytest backend/tests/unit --cov --cov-report=
	uv run python -m pytest backend/tests/integration --cov --cov-append --cov-report=term-missing
	cd frontend && npx vitest run --coverage
