"""Guard the desktop app's backend against callers other than the app's own window.

The desktop sidecar listens on 127.0.0.1, and in app mode two checks run on every request
(design/security.md, sections 6c and 6d):

- DNS rebinding: a web page whose domain re-resolves to 127.0.0.1 becomes same-origin with
  the backend, but its requests still carry that domain in ``Host``. Only loopback names
  are accepted.
- The launch token: loopback is open to every user and program on the computer. Electron
  makes a secret at each launch, passes it to the backend in its environment
  (``SCENE_ATLAS_APP_TOKEN``) and sets it as an HttpOnly, SameSite=Strict cookie on the
  app's own session, so the window's requests (images and downloads included) carry it.
  Electron's own requests send it as a header. With no token set (development, the
  browser E2E tests) this check is off.

Server mode is left to the reverse proxy. Checked per request rather than when the app is
built, so tests can switch modes.
"""

import hmac
from http.cookies import CookieError, SimpleCookie

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
TOKEN_COOKIE = "scene_atlas_token"  # noqa: S105  # the cookie's name, not a secret
TOKEN_HEADER = b"x-scene-atlas-token"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


def _host_name(scope: Scope) -> str:
    host = (_header(scope, b"host") or "").lower()
    if host.startswith("["):  # [::1]:8000
        return host.split("]")[0] + "]"
    return host.split(":")[0]


def _presented_token(scope: Scope) -> str | None:
    header = _header(scope, TOKEN_HEADER)
    if header:
        return header
    cookies = _header(scope, b"cookie")
    if not cookies:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookies)
    except CookieError:
        return None
    morsel = jar.get(TOKEN_COOKIE)
    return morsel.value if morsel else None


def _has_token(scope: Scope, token: str) -> bool:
    presented = _presented_token(scope)
    return presented is not None and hmac.compare_digest(
        presented.encode("utf-8"), token.encode("utf-8")
    )


class LoopbackHostMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and settings.app_mode == "app":
            refusal = None
            if _host_name(scope) not in LOOPBACK_HOSTS:
                refusal = PlainTextResponse("Invalid host header", status_code=400)
            elif settings.app_token and not _has_token(scope, settings.app_token):
                refusal = PlainTextResponse("Not the Scene Atlas app", status_code=403)
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)
