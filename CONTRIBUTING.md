# Contributing to Scene Atlas

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

See [docs/development/building.md](docs/development/building.md) for full setup instructions. Quick start:

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas

# Root dependencies (installs the Husky git hooks)
npm install

# Backend (dev tools + CPU onnxruntime; a bare `uv sync` installs no inference runtime)
uv sync --extra dev --extra cpu
uv run python scripts/models/setup_models.py   # download the embedding model
uv run python scripts/app/start.py

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev
```

## Code Style

- **Python:** [ruff](https://docs.astral.sh/ruff/) for linting and formatting. Run `uv run ruff check backend/ scripts/` and `uv run ruff format backend/ scripts/`.
- **TypeScript:** ESLint + Prettier over `frontend/src`. Run `cd frontend && npm run lint` and `npm run format:check` (or `npm run format` to fix).
- The pre-commit hook (Husky + lint-staged) fixes and formats staged `backend/**/*.py`, `scripts/**/*.py`, `frontend/src/**/*.{ts,tsx}`, and `electron/src/**/*.ts` (Prettier only) files.
- The pre-push hook runs ruff check + format check, backend unit tests, ESLint, Prettier, `tsc --noEmit` (frontend and Electron), and vitest. CI on pull requests adds security scans, integration tests, and a frontend build.

## Pull Request Process

1. Branch from `main`
2. Make your changes with clear, focused commits
3. Ensure all tests pass: `uv run python -m pytest` and `cd frontend && npx vitest run` (or `make test-all`)
4. Describe what your PR does and why
5. Link any related issues

## Architecture

See [design/README.md](design/README.md) for an overview of the system architecture, including:
- API endpoints and services
- Database schema and search system
- Frontend components and state management
- Architecture Decision Records (ADRs)

## Reporting Bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml) to file issues. Include:
- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, deployment mode, browser)
