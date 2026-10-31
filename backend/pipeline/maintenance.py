"""Maintenance tasks: the pre-migration snapshot and the orphaned store file sweep.

Functions:
    backup_before_migration    — Snapshot SQLite before init_db() applies pending migrations.
    sweep_orphaned_store_files — Delete store files no image refers to. Runs daily.

Ingest-related maintenance lives in ``ingest_maintenance``; vector index repair
in ``vector_reconcile``. Scheduled by the Scheduler (started in the FastAPI
lifespan).
"""

import logging
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import settings

# Pre-migration snapshot

# Snapshot directories are named with this timestamp, so name order is chronological.
BACKUP_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
_TIMESTAMP_LEN = len("YYYYmmdd_HHMMSS")
# Inside backups/.
PRE_MIGRATION_DIRNAME = "pre-migration"
PRE_MIGRATION_KEEP = 5


def _backup_timestamp(name: str) -> datetime | None:
    """The timestamp a backup directory is named with, or None if it isn't one."""
    try:
        return datetime.strptime(name, BACKUP_TIMESTAMP_FORMAT)
    except ValueError:
        return None


def backup_sqlite(backup_dir: Path, db_path: Path | None = None) -> Path:
    """Write a consistent snapshot of the SQLite database into *backup_dir*.

    Uses the sqlite3 backup API rather than a file copy so the snapshot is
    consistent even while the database is being written to. *db_path*
    defaults to the application database.
    """
    logger = logging.getLogger(__name__)
    if db_path is None:
        db_path = settings.data_dir / "battlemap.db"
    backup_path = backup_dir / db_path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as src, sqlite3.connect(str(backup_path)) as dst:
        src.backup(dst)

    size_kb = backup_path.stat().st_size // 1024
    logger.info("SQLite backed up to %s (%s KB)", backup_path, size_kb)
    return backup_path


def backup_before_migration(
    db_path: Path, from_rev: str, to_rev: str, backups_root: Path | None = None
) -> Path:
    """Snapshot the SQLite database before init_db() migrates it from *from_rev*.

    Migrations are one-way, so this is the only way back to the previous app
    version with its data. Writes ``backups/pre-migration/{timestamp}_{from_rev}/``
    and keeps the ``PRE_MIGRATION_KEEP`` most recent. SQLite only: no migration
    touches LanceDB. Raises if the snapshot can't be written (nothing partial is
    left behind); a rotation failure is only logged.
    """
    logger = logging.getLogger(__name__)
    root = (backups_root or settings.backups_dir) / PRE_MIGRATION_DIRNAME
    timestamp = datetime.now(UTC).strftime(BACKUP_TIMESTAMP_FORMAT)
    snapshot_dir = root / f"{timestamp}_{from_rev}"
    try:
        snapshot = backup_sqlite(snapshot_dir, db_path)
    except BaseException:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    logger.info(
        "Pre-migration snapshot written to %s (revision %s -> %s)", snapshot, from_rev, to_rev
    )
    try:
        rotate_pre_migration_backups(root)
    except OSError as e:
        logger.warning("Could not rotate pre-migration snapshots in %s: %s", root, e)
    return snapshot


def rotate_pre_migration_backups(root: Path, keep: int = PRE_MIGRATION_KEEP) -> int:
    """Keep the *keep* most recent pre-migration snapshots in *root*; delete the rest.

    Only directories named ``{timestamp}_{revision}`` are considered. Returns the
    number deleted.
    """
    logger = logging.getLogger(__name__)
    if not root.exists():
        return 0
    snapshots = sorted(
        (
            d
            for d in root.iterdir()
            if d.is_dir()
            and d.name[_TIMESTAMP_LEN : _TIMESTAMP_LEN + 1] == "_"
            and _backup_timestamp(d.name[:_TIMESTAMP_LEN]) is not None
        ),
        key=lambda d: d.name,
        reverse=True,  # most recent first
    )
    for d in snapshots[keep:]:
        shutil.rmtree(d, ignore_errors=True)
        logger.info("Rotated old pre-migration snapshot: %s", d.name)
    return len(snapshots[keep:])


# Only files in the store's shard layout (ab/cd/<key>) are ever considered;
# anything else under the library root (backups/, .incoming/) is left alone.
_SHARD_HEX = set("0123456789abcdef")
ORPHAN_MIN_AGE_SECONDS = 3600
# If more than this fraction of files look orphaned, something is wrong (wrong
# database, unmounted drive): refuse to delete anything.
ORPHAN_SANITY_FRACTION = 0.25


def _is_shard_dir(name: str) -> bool:
    return len(name) == 2 and set(name) <= _SHARD_HEX


def _store_files(base_dir: Path) -> list[Path]:
    """Files at <base>/<xx>/<yy>/<name> where xx and yy are shard directories."""
    files: list[Path] = []
    if not base_dir.exists():
        return files
    for first in base_dir.iterdir():
        if not (first.is_dir() and _is_shard_dir(first.name)):
            continue
        for second in first.iterdir():
            if not (second.is_dir() and _is_shard_dir(second.name)):
                continue
            files.extend(p for p in second.iterdir() if p.is_file())
    return files


def _thumbnail_stem(name: str) -> str:
    """'abc123_400x400.jpg' -> 'abc123' (all sizes of one image share the stem)."""
    return Path(name).stem.rsplit("_", 1)[0]


def sweep_orphaned_store_files(delete: bool = True) -> dict:
    """Find, and delete, store files that no image row refers to.

    Files become orphaned when a crash lands between placing a file and
    committing its row, or when a deletion commits but file removal fails.
    Files younger than an hour are skipped (they may belong to a batch that is
    committing right now). If an implausibly large share of the store looks
    orphaned, nothing is deleted and an error is logged instead.

    Scheduled daily.
    """
    logger = logging.getLogger(__name__)

    from backend.app.models import Image
    from backend.app.services import get_image_store, get_thumbnail_store
    from backend.app.services.shutdown import raise_if_shutting_down
    from backend.pipeline.db import pipeline_db

    with pipeline_db() as db:
        image_keys = {key for (key,) in db.query(Image.storage_key) if key}
        thumbnail_stems = {_thumbnail_stem(key) for (key,) in db.query(Image.thumbnail_key) if key}

    now = time.time()
    results: dict[str, int] = {}
    for label, store, is_known in (
        ("images", get_image_store(), lambda p: p.name in image_keys),
        ("thumbnails", get_thumbnail_store(), lambda p: _thumbnail_stem(p.name) in thumbnail_stems),
    ):
        raise_if_shutting_down()
        files = _store_files(store.base_dir)
        orphans = [
            p for p in files if not is_known(p) and now - p.stat().st_mtime > ORPHAN_MIN_AGE_SECONDS
        ]
        deleted = 0
        if orphans and len(orphans) > ORPHAN_SANITY_FRACTION * len(files) and len(orphans) > 20:
            logger.error(
                "Orphan sweep: %d of %d %s files look orphaned; refusing to delete. "
                "Is the right database / library folder in use?",
                len(orphans),
                len(files),
                label,
            )
        elif delete:
            for path in orphans:
                path.unlink(missing_ok=True)
                deleted += 1
        if orphans:
            logger.warning(
                "Orphan sweep: %d orphaned %s file(s), %d deleted", len(orphans), label, deleted
            )
        results[f"orphaned_{label}"] = len(orphans)
        results[f"deleted_{label}"] = deleted
    return results
