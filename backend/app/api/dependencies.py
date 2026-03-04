"""Shared FastAPI dependencies for API route handlers."""

import hmac

from fastapi import Header, HTTPException, Request

from ..config import settings
from ..models import get_session_local


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def verify_auth(authorization: str | None = Header(None)) -> None:
    """Verify bearer token if AUTH_TOKEN is configured.

    When AUTH_TOKEN is not set, this dependency is a no-op — all requests
    pass through. This preserves backwards compatibility with Electron and
    developer mode.
    """
    if not settings.auth_token:
        return

    _www_auth = {"WWW-Authenticate": 'Bearer realm="scene-atlas"'}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers=_www_auth,
        )

    token = authorization[len("Bearer ") :]
    if not hmac.compare_digest(token, settings.auth_token):
        raise HTTPException(status_code=401, detail="Invalid token", headers=_www_auth)
