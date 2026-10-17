"""Reject requests addressed to another host name in the desktop app (DNS rebinding).

The desktop sidecar listens on 127.0.0.1 without authentication (design/security.md).
A web page whose domain re-resolves to 127.0.0.1 becomes same-origin with it and could
call the API; its requests still carry that domain in ``Host``. In app mode only
loopback names are accepted. Server mode is left to the reverse proxy.

Checked per request rather than when the app is built, so tests can switch modes.
"""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})


def _host_name(scope: Scope) -> str:
    for key, value in scope.get("headers", ()):
        if key == b"host":
            host = value.decode("latin-1").lower()
            if host.startswith("["):  # [::1]:8000
                return host.split("]")[0] + "]"
            return host.split(":")[0]
    return ""


class LoopbackHostMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] in ("http", "websocket")
            and settings.app_mode == "app"
            and _host_name(scope) not in LOOPBACK_HOSTS
        ):
            response = PlainTextResponse("Invalid host header", status_code=400)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
