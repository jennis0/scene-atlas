.PHONY: test test-unit test-integration test-frontend test-all test-heavy evaluate-onnx \
       test-cov test-e2e test-e2e-ui lint lint-fix format-check check ensure-model

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

test-integration: ensure-model
	EMBEDDING_MODEL=small uv run python -m pytest backend/tests/integration -v

test-frontend:
	cd frontend && npx vitest run

test-heavy: ensure-model
	uv run python -m pytest -m heavy -v

# ── Model download ────────────────────────────────────────────────────────
ensure-model:
	@uv run python scripts/models/setup_models.py small

evaluate-onnx:
	uv run python scripts/models/export_model_onnx.py clip-vit-b-32 --image-dir data/store/images

test-e2e:
	cd e2e && npx playwright test --project=chromium

test-e2e-ui:
	cd e2e && npx playwright test --ui

# ── Coverage ───────────────────────────────────────────────────────────────
test-cov: ensure-model
	uv run python -m pytest backend/tests/unit --cov --cov-report=
	EMBEDDING_MODEL=small uv run python -m pytest backend/tests/integration --cov --cov-append --cov-report=term-missing
	cd frontend && npx vitest run --coverage
