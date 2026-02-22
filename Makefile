.PHONY: test test-unit test-integration test-cov lint

test: test-unit test-integration

test-unit:
	uv run python -m pytest backend/tests/unit -v

test-integration:
	uv run python -m pytest backend/tests/integration -v

test-cov:
	uv run python -m pytest backend/tests/unit --cov --cov-report=
	uv run python -m pytest backend/tests/integration --cov --cov-append --cov-report=term-missing

lint:
	uv run ruff check backend/
	uv run ruff format --check backend/
