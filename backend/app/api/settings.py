"""App settings API — GET and PATCH /api/v1/settings."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..models import get_session_local
from ..models.schemas import AppSettings, AppSettingsPatch
from ..services.app_settings import get_settings, update_settings

router = APIRouter()


def get_db(request: Request):
    """Dependency to get database session."""
    SessionLocal = get_session_local(request.app.state.db_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=AppSettings)
async def get_app_settings(db: Session = Depends(get_db)) -> AppSettings:
    """Return the current application settings."""
    return get_settings(db)


@router.patch("/", response_model=AppSettings)
async def patch_app_settings(
    patch: AppSettingsPatch,
    db: Session = Depends(get_db),
) -> AppSettings:
    """Update one or more application settings.

    Only include the fields you want to change — unset fields are left as-is.
    Returns the full updated settings after the write.
    """
    return update_settings(db, patch)
