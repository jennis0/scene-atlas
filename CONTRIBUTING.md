# Contributing to Scene Atlas

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

See [docs/development/building.md](docs/development/building.md) for full setup instructions. Quick start:

```bash
git clone https://github.com/jennis0/scene-atlas.git
cd scene-atlas

# Backend
uv sync --extra dev --extra cpu
uv run python scripts/start.py

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev
```

## Code Style

- **Python:** [ruff](https://docs.astral.sh/ruff/) for linting and formatting. Run `uv run ruff check backend/` and `uv run ruff format backend/`.
- **TypeScript:** ESLint + Prettier. Run `cd frontend && npx eslint . --ext ts,tsx` and `npx prettier --check .`.
- Pre-commit hooks enforce these automatically via Husky + lint-staged.

## Pull Request Process

1. Branch from `main`
2. Make your changes with clear, focused commits
3. Ensure all tests pass: `uv run python -m pytest` and `cd frontend && npx vitest run`
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
