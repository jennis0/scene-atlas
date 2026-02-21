"""FastAPI application for Battlemap Explorer."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

# Set PREFECT_API_URL before any Prefect imports so the client connects to our server
os.environ.setdefault("PREFECT_API_URL", settings.prefect_api_url)

from .api import images, imports, search, tags, variant_groups
from .models import get_engine, init_db, seed_tag_categories, get_session_local

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

    # Seed tag categories
    SessionLocal = get_session_local(engine)
    session = SessionLocal()
    try:
        seed_tag_categories(session)
        logger.info("Tag categories seeded")
    finally:
        session.close()

    # Store engine in app state
    app.state.db_engine = engine

    # Pre-load CLIP model to avoid blocking on first request
    logger.info("Pre-loading CLIP model...")
    from .services.clip_service import get_clip_service

    clip_service = get_clip_service()
    logger.info("CLIP model loaded and ready")

    logger.info(f"Server ready on {settings.api_host}:{settings.api_port}")

    yield

    # Shutdown
    logger.info("Shutting down application")


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
app.include_router(
    variant_groups.router, prefix=f"{settings.api_prefix}/variant-groups", tags=["variant-groups"]
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
