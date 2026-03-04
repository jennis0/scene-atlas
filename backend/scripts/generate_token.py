"""Convenience script: generate a secure random bearer token for server mode.

Usage:
    uv run python -m backend.scripts.generate_token

Copy both output lines to the appropriate .env files:
    backend/.env  →  AUTH_TOKEN=<token>
    frontend/.env →  VITE_AUTH_TOKEN=<token>
"""

import secrets


def main():
    token = secrets.token_urlsafe(32)
    print(f"AUTH_TOKEN={token}")
    print(f"VITE_AUTH_TOKEN={token}")
    print()
    print("Copy AUTH_TOKEN to your backend .env and VITE_AUTH_TOKEN to frontend/.env")
    print("Then rebuild the frontend: cd frontend && npm run build")


if __name__ == "__main__":
    main()
