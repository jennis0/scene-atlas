"""DB-backed application settings service.

Reads and writes AppSetting rows (key-value JSON store).
The in-memory representation is the AppSettings Pydantic model.
No cache is kept — SQLite reads are fast enough and this avoids
stale-read issues between the API process and any background jobs.
"""

import json
import logging

from sqlalchemy.orm import Session

from ..models.database import AppSetting
from ..models.schemas import AppSettings, AppSettingsPatch

logger = logging.getLogger(__name__)

_KNOWN_KEYS: frozenset[str] = frozenset(AppSettings.model_fields.keys())

# Read once at startup (main.lifespan), so a saved change applies only after a restart
RESTART_SETTINGS: tuple[str, ...] = (
    "max_concurrent_prepare",
    "max_concurrent_heavy_requests",
    "scheduler_enabled",
)


def restart_values(current: AppSettings) -> dict[str, object]:
    """The restart-only settings as the backend starts with them."""
    return {key: getattr(current, key) for key in RESTART_SETTINGS}


def pending_restart(stored: AppSettings, running: dict[str, object]) -> list[str]:
    """Restart-only settings saved since startup that the running backend hasn't applied."""
    return [key for key, value in running.items() if getattr(stored, key) != value]


# NOTE: active_model is intentionally NOT auto-seeded into the DB on first boot.
# It defaults to "" in AppSettings, and get_settings() will use that default if the
# key is absent from the DB. This allows _get_active_model_name() in clip_service.py
# to detect that the key is missing and trigger auto-detection at startup.


def get_settings(db: Session) -> AppSettings:
    """Read all setting rows and merge with schema defaults.

    Unknown keys are ignored. Missing keys fall back to the Pydantic defaults
    defined on AppSettings so this is always safe to call on a fresh DB.
    """
    rows = db.query(AppSetting).all()
    data: dict = {}
    for row in rows:
        if row.key not in _KNOWN_KEYS:
            continue
        try:
            data[row.key] = json.loads(row.value_json) if row.value_json is not None else None
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not decode setting '%s' — using default", row.key)
    return AppSettings(**data)


def update_settings(db: Session, patch: AppSettingsPatch) -> AppSettings:
    """Apply a partial update and return the full updated settings.

    Only keys explicitly included in the patch (non-None) are written.
    """
    patch_dict = patch.model_dump(exclude_none=True)

    for key, value in patch_dict.items():
        if key not in _KNOWN_KEYS:
            continue
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value_json = json.dumps(value)
        else:
            db.add(AppSetting(key=key, value_json=json.dumps(value)))

    db.commit()
    return get_settings(db)
