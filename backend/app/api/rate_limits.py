"""Shared rate limiter instance for the application.

Kept in its own module to avoid circular imports between main.py and
the API route modules that apply per-endpoint limits.

When deployed behind a reverse proxy, the proxy MUST overwrite (not
append to) X-Forwarded-For so that get_remote_address returns the real
client IP.  See design/security.md for deployment guidance.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import settings

limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)
