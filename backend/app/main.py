"""FastAPI application for Scene Atlas."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import export, groups, images, imports, jobs, search, system, tags
from .api import settings as settings_api
from .config import settings
from .models import (
    get_engine,
    get_session_local,
    init_db,
    seed_default_settings,
    seed_tag_categories,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize database
    engine = get_engine(settings.database_url)
    init_db(engine)
    logger.info("Database initialized")

    # Seed tag categories + backfill search_text for FTS5
    SessionLocal = get_session_local(engine)
    session = SessionLocal()
    try:
        seed_tag_categories(session)
        logger.info("Tag categories seeded")

        seed_default_settings(session)
        logger.info("App settings seeded")

        from .services.fts_service import backfill_search_text

        backfill_search_text(session)

        from .services.app_settings import get_settings as get_app_settings

        app_config = get_app_settings(session)
    finally:
        session.close()

    # Store engine in app state
    app.state.db_engine = engine

    # Start CLIP loading in background — does not block server startup.
    # get_clip_service() will wait for it; empty-query searches skip CLIP entirely.
    from .services.clip_service import start_clip_background_load

    logger.info("Starting CLIP model background load...")
    start_clip_background_load()

    # Start background job runner (eagerly, so it's ready for requests)
    from .services.job_runner import get_job_runner, shutdown_job_runner

    get_job_runner()

    # Clean up any stale staging dirs left over from crashes or previous sessions
    from ..pipeline.maintenance import cleanup_stale_staging

    cleanup_stale_staging()

    # Start scheduler for periodic maintenance (backup, staging cleanup)
    from .services.scheduler import Scheduler

    scheduler = Scheduler()
    if app_config.scheduler_enabled:
        from ..pipeline.maintenance import backup_database, cleanup_staging, expire_stale_jobs

        scheduler.register(backup_database, hours=24, name="backup_database")
        scheduler.register(cleanup_staging, hours=6, name="cleanup_staging")
        scheduler.register(expire_stale_jobs, hours=6, name="expire_stale_jobs")
        await scheduler.start()
        logger.info("Scheduler started")

    logger.info(f"Server ready on {settings.api_host}:{settings.api_port}")
    # Signal to desktop shell (Electron) that the backend is ready.
    # CLIP is still loading in the background — the app is usable immediately;
    # searches with a query will wait for CLIP; empty queries use SQL only.
    print(f"SCENE_ATLAS_READY port={settings.api_port}", flush=True)

    yield

    # Shutdown
    logger.info("Shutting down application")
    await scheduler.stop()
    shutdown_job_runner()

    from .services.qdrant_service import shutdown_qdrant_service

    shutdown_qdrant_service()


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
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


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
    """Deep health check: DB connectivity + Qdrant collection status.

    Returns 200 with status "healthy" when all systems are up, or "degraded"
    when one or more checks fail.  Useful for diagnosing "why isn't search
    working?" without tailing logs.
    """
    checks: dict[str, str] = {}
    overall = "healthy"

    # Database check
    try:
        with request.app.state.db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall = "degraded"

    # Qdrant check
    try:
        from .services.qdrant_service import get_qdrant_service

        info = get_qdrant_service().get_collection_info()
        if info:
            checks["qdrant"] = f"ok ({info.get('points_count', '?')} points)"
        else:
            checks["qdrant"] = "error: empty collection info"
            overall = "degraded"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc}"
        overall = "degraded"

    # Job runner status
    from .services.job_runner import get_job_runner

    checks["job_runner"] = get_job_runner().status

    return {"status": overall, "mode": settings.app_mode, "checks": checks}


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
        os.environ["DATA_DIR"] = args.data_dir
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
