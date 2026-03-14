"""App settings API — GET and PATCH /api/v1/settings."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import settings as app_config
from ..models.schemas import AppSettings, AppSettingsPatch
from ..services.app_settings import get_settings, update_settings
from .dependencies import get_db
from .rate_limits import limiter

router = APIRouter()


@router.get("/", response_model=AppSettings)
def get_app_settings(db: Session = Depends(get_db)) -> AppSettings:
    """Return the current application settings."""
    return get_settings(db)


@router.patch("/", response_model=AppSettings)
@limiter.limit(lambda: app_config.rate_limit_expensive)
def patch_app_settings(
    request: Request,
    patch: AppSettingsPatch,
    db: Session = Depends(get_db),
) -> AppSettings:
    """Update one or more application settings.

    Only include the fields you want to change — unset fields are left as-is.
    Returns the full updated settings after the write.
    """
    return update_settings(db, patch)
