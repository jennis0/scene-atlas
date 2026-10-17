"""FastAPI application for Scene Atlas."""

import asyncio
import logging
import signal
import sys
import threading
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound

from .api import export, groups, images, imports, jobs, search, system, tags
from .api import models as models_api
from .api import settings as settings_api
from .api.rate_limits import limiter
from .config import settings
from .logging_config import setup_logging
from .models import (
    get_engine,
    get_session_local,
    init_db,
    seed_default_settings,
    seed_tag_categories,
)
from .process_utils import get_rss_mb
from .services.prepare_pool import init_prepare_pool, shutdown_prepare_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Configure logging first so all startup messages go to our handlers.
    setup_logging(settings.app_data_dir, debug=settings.debug)

    # Startup
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)

    # Initialize database
    try:
        engine = get_engine(settings.database_url)
        init_db(engine)
    except Exception:
        db_path = settings.database_url.replace("sqlite:///", "")
        logger.critical(
            "STARTUP ERROR: Could not initialize database at %s. "
            "Check that the directory exists and is writable.",
            db_path,
        )
        raise
    logger.info("Database initialized")

    # Seed tag categories + backfill search_text for FTS5
    SessionLocal = get_session_local(engine)
    session = SessionLocal()
    try:
        seed_tag_categories(session)
        logger.info("Tag categories seeded")

        try:
            seed_default_settings(session)
        except Exception:
            logger.critical("STARTUP ERROR: Could not seed default settings.")
            raise
        logger.info("App settings seeded")

        from .services.fts_service import backfill_search_text

        backfill_search_text(session)

        from .services.app_settings import get_settings as get_app_settings

        app_config = get_app_settings(session)
    finally:
        session.close()

    # Initialize prepare pool with the system-wide concurrency limit
    init_prepare_pool(app_config.max_concurrent_prepare)

    # Store engine in app state
    app.state.db_engine = engine

    # Admission control: limit concurrent heavy operations (seal, archive expansion)
    # to prevent GIL thrashing from unbounded asyncio.to_thread() calls.
    # Created here (not at module level) because asyncio.Semaphore() requires
    # a running event loop on Python 3.12+ / Windows.
    app.state.heavy_op_semaphore = asyncio.Semaphore(app_config.max_concurrent_heavy_requests)

    # Derive vector_size from the model manifest before any service is
    # created.  The manifest is a lightweight JSON read — no model loading.
    # This ensures LanceDBService creates tables with the correct dimension
    # regardless of which model is active (CLIP 512-d, SigLIP2 768-d, etc.).
    from .services.clip_service import _default_models_dir, _load_manifest

    try:
        manifest = _load_manifest(_default_models_dir())
        manifest_dim = manifest.get("embedding_dim", 512)
        if settings.vector_size != manifest_dim:
            logger.info(
                "Setting vector_size=%d from model manifest (was %d)",
                manifest_dim,
                settings.vector_size,
            )
            settings.vector_size = manifest_dim
    except Exception:
        logger.debug("Could not read model manifest for vector size — using default", exc_info=True)

    # Start embedding model loading in background — does not block server startup.
    # get_clip_service() will wait for it; empty-query searches skip CLIP entirely.
    from .services.clip_service import start_clip_background_load

    logger.info("Starting embedding model background load...")
    start_clip_background_load()

    # Start background job runner (eagerly, so it's ready for requests)
    from .services.job_runner import get_job_runner, shutdown_job_runner

    runner = get_job_runner()

    # Reconcile the vector index with SQLite by image id once the model has
    # loaded: re-embeds images missing a vector (crash between commit and vector
    # write, or a freshly switched model) and drops vectors with no image.
    def _reconcile_embeddings_when_ready() -> None:
        from ..pipeline.ingest_worker import get_ingest_worker
        from ..pipeline.vector_reconcile import reconcile_vectors
        from .services.clip_service import get_clip_unavailable_reason, wait_for_clip_ready

        wait_for_clip_ready()
        # The worker may have paused for "waiting for the AI model"; re-check now
        # rather than at its next scheduled probe.
        get_ingest_worker().probe_now()
        if get_clip_unavailable_reason() is None:
            runner.submit(reconcile_vectors, name="Reconcile embeddings")

    threading.Thread(
        target=_reconcile_embeddings_when_ready, daemon=True, name="embedding-reconcile"
    ).start()

    # Ingest worker: re-queue items interrupted by the last shutdown (nothing is
    # deleted), then start processing.
    from ..pipeline.ingest_worker import get_ingest_worker

    ingest_worker = get_ingest_worker()
    if settings.ingest_worker_enabled:
        recovered = ingest_worker.recover()
        if recovered["recovered"] or recovered["crashed"]:
            logger.warning("Ingest recovery on startup: %s", recovered)
        ingest_worker.start()
        logger.info("Ingest worker started")

    # Start scheduler for periodic maintenance. Overdue tasks run shortly after
    # startup, so short desktop sessions still get maintenance.
    from .services.scheduler import Scheduler

    scheduler = Scheduler(settings.app_data_dir / "scheduler")
    if app_config.scheduler_enabled:
        from ..pipeline.ingest_maintenance import run_ingest_maintenance
        from ..pipeline.maintenance import backup_database, sweep_orphaned_store_files
        from ..pipeline.vector_reconcile import reconcile_vectors

        scheduler.register(backup_database, hours=24, name="backup_database")
        scheduler.register(run_ingest_maintenance, hours=6, name="ingest_maintenance")
        scheduler.register(sweep_orphaned_store_files, hours=24, name="sweep_orphaned_store_files")
        scheduler.register(reconcile_vectors, hours=24, name="reconcile_vectors")
        await scheduler.start()
        logger.info("Scheduler started")

    # Warn if server mode is using default localhost-only CORS origins — a common
    # misconfiguration when deploying behind a reverse proxy.
    _default_cors = {"http://localhost:3000", "http://localhost:5173", "http://localhost:8000"}
    if settings.app_mode == "server" and set(settings.cors_origins) == _default_cors:
        logger.warning(
            "CORS origins are still set to localhost defaults but APP_MODE=server. "
            "Set CORS_ORIGINS in your .env to your actual frontend origin."
        )

    logger.info("Server ready on %s:%s", settings.api_host, settings.api_port)
    # Signal to desktop shell (Electron) that the backend is ready.
    # CLIP is still loading in the background — the app is usable immediately;
    # searches with a query will wait for CLIP; empty queries use SQL only.
    print(f"SCENE_ATLAS_READY port={settings.api_port}", flush=True)

    # Diagnostic: event loop heartbeat
    # Logs every 15s from the event loop. If these lines stop appearing in the
    # log while the process is still alive, the event loop is blocked.
    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(15)
            rss_mb = get_rss_mb()
            rss_info = f", RSS={rss_mb:.0f} MB" if rss_mb is not None else ""
            active_threads = threading.active_count()
            logger.info(
                "[heartbeat] event loop alive — threads=%d%s",
                active_threads,
                rss_info,
            )

    heartbeat_task = asyncio.create_task(_heartbeat())

    # Diagnostic: SIGUSR1 thread dump
    # Send `kill -USR1 <pid>` to dump all thread stack traces to the log.
    def _dump_threads(signum, frame) -> None:  # noqa: ARG001
        lines = ["\n=== THREAD DUMP (SIGUSR1) ==="]
        for tid, stack in sys._current_frames().items():
            tname = "?"
            for t in threading.enumerate():
                if t.ident == tid:
                    tname = t.name
                    break
            lines.append(f"\n--- Thread {tname} (id={tid}) ---")
            lines.extend(traceback.format_stack(stack))
        logger.warning("".join(lines))

    if sys.platform != "win32":
        try:
            signal.signal(signal.SIGUSR1, _dump_threads)
        except ValueError:
            pass  # Not in main thread (e.g. test runner)

    yield

    heartbeat_task.cancel()

    # Shutdown
    logger.info("Shutting down application")
    await scheduler.stop()
    # Let the batch in progress commit; anything left is recovered next start.
    await asyncio.to_thread(ingest_worker.stop, 60.0)
    shutdown_job_runner()
    shutdown_prepare_pool()

    from .services.lancedb_service import shutdown_lancedb_service

    shutdown_lancedb_service()


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)


# Security headers middleware (pure ASGI — avoids BaseHTTPMiddleware
# performance issues with streaming responses and background tasks).
# HSTS intentionally omitted — must come from the reverse proxy to avoid
# breaking non-TLS deployments (Electron, local dev).
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=()"),
]


class SecurityHeadersMiddleware:
    """Add static security headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

# Rate limiting middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]
app.add_middleware(SlowAPIMiddleware)

# Include API routers
app.include_router(images.router, prefix=f"{settings.api_prefix}/images", tags=["images"])
app.include_router(search.router, prefix=f"{settings.api_prefix}/search", tags=["search"])
app.include_router(tags.router, prefix=f"{settings.api_prefix}/tags", tags=["tags"])
app.include_router(imports.router, prefix=f"{settings.api_prefix}/imports", tags=["imports"])
app.include_router(groups.router, prefix=f"{settings.api_prefix}/groups", tags=["groups"])
app.include_router(jobs.router, prefix=f"{settings.api_prefix}/jobs", tags=["jobs"])
app.include_router(export.router, prefix=f"{settings.api_prefix}/export", tags=["export"])
app.include_router(system.router, prefix=f"{settings.api_prefix}/system", tags=["system"])
app.include_router(settings_api.router, prefix=f"{settings.api_prefix}/settings", tags=["settings"])
app.include_router(models_api.router, prefix=f"{settings.api_prefix}/models", tags=["models"])

# SPA static file serving
# When a built frontend exists (Docker / production), serve it from the backend.
# The frontend build outputs to frontend/dist/ relative to the project root.
# Must be mounted AFTER API routers so /api/v1/* routes take precedence.
_FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"
_spa_enabled = _FRONTEND_DIR.is_dir() and (_FRONTEND_DIR / "index.html").exists()

if _spa_enabled:
    logger.info("Serving frontend SPA from %s", _FRONTEND_DIR)
    # Serve static assets (JS, CSS, images) under /assets/
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="frontend-assets")


@app.get("/")
async def root(request: Request):
    """Root endpoint.

    When a built frontend is available, serves the SPA index.html for
    browser requests.  In server mode without a frontend build, returns
    an HTML status page.  Otherwise returns a JSON health summary.
    """
    if _spa_enabled:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return FileResponse(_FRONTEND_DIR / "index.html", media_type="text/html")
    accept = request.headers.get("accept", "")
    if settings.app_mode == "server" and "text/html" in accept:
        return await _server_status_page(request)
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


async def _server_status_page(request: Request) -> HTMLResponse:
    """Build a self-contained HTML status page for server mode.

    Derives a simple healthy/needs-attention status from the /health
    subsystem checks without exposing any sensitive details.
    """
    # Run the same logic as /health to determine overall status
    all_ok = True
    try:
        with request.app.state.db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        all_ok = False

    try:
        from .services.lancedb_service import get_lancedb_service

        info = get_lancedb_service().get_collection_info()
        if not info:
            all_ok = False
    except Exception:
        all_ok = False

    from .services.clip_service import _clip_error, _clip_ready

    if _clip_ready.is_set() and _clip_error is not None:
        all_ok = False

    if all_ok:
        status_text = "All systems operational"
        indicator_color = "#4caf50"
    else:
        status_text = "Some systems need attention"
        indicator_color = "#ff9800"

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scene Atlas</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:#0e1118;color:#ede8dc;
  font-family:system-ui,-apple-system,sans-serif;
  background-image:radial-gradient(circle,rgba(237,232,220,0.04) 1px,transparent 1px);
  background-size:28px 28px;
}}
.card{{
  max-width:440px;width:100%;
  background:#161c28;border:1px solid #1e2736;border-radius:8px;
  padding:2.5rem;text-align:center;
}}
h1{{font-size:1.5rem;letter-spacing:0.15em;margin-bottom:0.5rem;font-weight:500}}
.divider{{
  width:80px;height:1px;margin:0.75rem auto;
  background:linear-gradient(90deg,transparent,#d4a853,transparent);
}}
.status{{
  display:inline-flex;align-items:center;gap:0.5rem;
  margin:1.25rem 0;font-size:0.9375rem;
}}
.dot{{
  width:10px;height:10px;border-radius:50%;
  background:{indicator_color};
  box-shadow:0 0 6px {indicator_color}80;
}}
.hint{{font-size:0.8125rem;color:rgba(237,232,220,0.45);line-height:1.6;margin-top:1rem}}
.api-hint{{
  margin-top:1.25rem;font-size:0.75rem;
  color:rgba(237,232,220,0.3);
  font-family:'Courier New',monospace;
}}
</style>
</head>
<body>
<div class="card">
  <h1>Scene Atlas</h1>
  <div class="divider"></div>
  <div class="status"><span class="dot"></span>{status_text}</div>
  <p class="hint">Visit the frontend application to get started.</p>
  <p class="api-hint">For API access, use the /api/v1/ endpoint prefix</p>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.exception_handler(NoResultFound)
async def not_found_handler(request: Request, exc: NoResultFound) -> JSONResponse:
    """A row that must exist (``Session.get_one``) was deleted by a concurrent request."""
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all unhandled exceptions, log them, return a clean JSON error.

    FastAPI's built-in HTTPException handler takes precedence over this, so
    HTTP 4xx/5xx responses from endpoints still reach the client unchanged.
    This handler catches unexpected programming errors that would otherwise
    return raw 500 responses with stack traces.
    """
    logger.error("Unhandled exception on %s %s", request.method, request.url, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health(request: Request):
    """Deep health check: DB connectivity + LanceDB collection status.

    Returns 200 with status "healthy" when all systems are up, or "degraded"
    when one or more checks fail.  Useful for diagnosing "why isn't search
    working?" without tailing logs.
    """
    checks: dict[str, Any] = {}
    overall = "healthy"

    # Database check
    try:
        with request.app.state.db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "error"
        logger.warning("Health check — database error: %s", exc)
        overall = "degraded"

    # Vector DB check
    try:
        from .services.lancedb_service import get_lancedb_service

        info = get_lancedb_service().get_collection_info()
        if info:
            checks["vector_db"] = f"ok ({info.get('points_count', '?')} points)"
        else:
            checks["vector_db"] = "error"
            logger.warning("Health check — LanceDB returned empty collection info")
            overall = "degraded"
    except Exception as exc:
        checks["vector_db"] = "error"
        logger.warning("Health check — LanceDB error: %s", exc)
        overall = "degraded"

    # Embedding model check
    from .services.clip_service import _clip_error, _clip_ready

    if not _clip_ready.is_set():
        checks["embedding"] = "loading"
    elif _clip_error is not None:
        checks["embedding"] = f"error: {_clip_error}"
        overall = "degraded"
    else:
        checks["embedding"] = "ok"

    # Job runner status
    from .services.job_runner import get_job_runner

    checks["job_runner"] = get_job_runner().status

    return {"status": overall, "mode": settings.app_mode, "checks": checks}


# SPA catch-all route
# Must be registered LAST so it doesn't shadow API routes or /health.
# Serves index.html for any path not matched by an API endpoint, enabling
# client-side routing (e.g. /gallery, /import).
if _spa_enabled:

    @app.get("/{full_path:path}")
    async def spa_catch_all(request: Request, full_path: str):
        """Serve the SPA index.html for client-side routes."""
        # Let static files (favicon, manifest, etc.) in the frontend dist root
        # be served directly if they exist.
        candidate = _FRONTEND_DIR / full_path
        if candidate.is_file() and ".." not in full_path:
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIR / "index.html", media_type="text/html")


if __name__ == "__main__":
    import argparse
    import os

    import uvicorn

    parser = argparse.ArgumentParser(description="Scene Atlas backend")
    parser.add_argument("--port", type=int, default=None, help="Override API port")
    parser.add_argument("--data-dir", type=str, default=None, help="Override data directory")
    args = parser.parse_args()

    # Set env vars so Settings() picks them up (must happen before re-import)
    if args.data_dir:
        os.environ["APP_DATA_DIR"] = args.data_dir
    if args.port:
        os.environ["API_PORT"] = str(args.port)

    host = settings.api_host
    port = args.port or settings.api_port

    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=settings.debug,
    )
