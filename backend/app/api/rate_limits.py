"""Shared rate limiter instance for the application.

Kept in its own module to avoid circular imports between main.py and
the API route modules that apply per-endpoint limits.

get_remote_address reads request.client, which main.py's ProxyHeadersMiddleware
sets from X-Forwarded-For on connections from FORWARDED_ALLOW_IPS only.
See design/security.md.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import settings

limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)
