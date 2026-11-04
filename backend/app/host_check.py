"""Guard the desktop app's backend against callers other than the app's own window.

The desktop sidecar listens on 127.0.0.1, and in app mode two checks run on every request
(design/security.md §6d):

- DNS rebinding: a web page whose domain re-resolves to 127.0.0.1 becomes same-origin with
  the backend, but its requests still carry that domain in ``Host``. Only loopback names
  are accepted.
- The launch token: loopback is open to every user and program on the computer. Electron
  makes a secret for each backend it starts, passes it in the backend's environment
  (``SCENE_ATLAS_APP_TOKEN``) and adds it as the ``X-Scene-Atlas-Token`` header to its
  window's requests to this backend's origin (page loads, images and downloads too), and
  its own. With no token set (development, the browser E2E tests) this check is off.

Server mode is left to the reverse proxy. Checked per request rather than when the app is
built, so tests can switch modes.
"""

import hmac

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
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


def _has_token(scope: Scope, token: str) -> bool:
    presented = _header(scope, TOKEN_HEADER)
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
