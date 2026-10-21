"""App settings API — GET and PATCH /api/v1/settings."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import settings as app_config
from ..models.schemas import AppSettings, AppSettingsPatch, RestartPending
from ..services.app_settings import get_settings, pending_restart, update_settings
from .dependencies import get_db
from .rate_limits import limiter

router = APIRouter()


@router.get("/", response_model=AppSettings)
def get_app_settings(db: Session = Depends(get_db)) -> AppSettings:
    """Return the current application settings."""
    return get_settings(db)


@router.get("/restart-pending", response_model=RestartPending)
def get_restart_pending(request: Request, db: Session = Depends(get_db)) -> RestartPending:
    """Settings saved since the backend started that it applies only on a restart."""
    running = getattr(request.app.state, "running_settings", None)
    if running is None:
        return RestartPending(keys=[])
    return RestartPending(keys=pending_restart(get_settings(db), running))


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
