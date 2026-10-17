"""Model download service — fetch ONNX model files from HuggingFace Hub.

Downloads to DATA_DIR/models/{name}/ using an atomic temp-dir → rename pattern.
version.json is the completion marker (written last, checked by is_model_downloaded).
"""

import errno
import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from backend.app.config import settings as _settings
from backend.app.services.model_registry import MODEL_BY_NAME, get_model

logger = logging.getLogger(__name__)

# Multiplier applied to model size to account for temp download + final copy
_DISK_SPACE_MULTIPLIER = 1.5


class ModelDownloadError(Exception):
    """Raised when a model download fails with a user-readable message."""


def get_model_dir(name: str) -> Path:
    """Return the target directory for a downloaded model: DATA_DIR/models/{name}/"""
    return _settings.app_data_dir / "models" / name


def get_version_info(name: str) -> dict | None:
    """Read version.json for a downloaded model, or None if not present."""
    version_path = get_model_dir(name) / "version.json"
    if not version_path.exists():
        return None
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read version.json for model '%s'", name)
        return None


def is_model_downloaded(name: str) -> bool:
    """Return True only if the model has been fully downloaded (version.json exists)."""
    return (get_model_dir(name) / "version.json").exists()


def get_collection_name(name: str) -> str:
    """Return the LanceDB table name for a model.

    Currently uses the plain model name.  A future version may incorporate the
    HF commit SHA so that re-downloading an updated model produces a distinct
    collection — but this requires a migration strategy for existing installs.
    """
    return f"embeddings_{name}"


def check_disk_space(model_name: str) -> tuple[bool, int, int]:
    """Check whether there is enough disk space to download a model.

    Uses ``shutil.disk_usage()`` on the models directory and the model's
    ``approx_size_mb`` from the registry, applying a 1.5x safety multiplier
    to account for the temp download directory plus the final copy.

    Returns
    -------
    (ok, needed_mb, available_mb)
        *ok* is True when available space exceeds the requirement.
    """
    entry = get_model(model_name)
    if entry is None:
        raise ModelDownloadError(
            f"Unknown model '{model_name}'. Valid names: {list(MODEL_BY_NAME)}"
        )

    needed_mb = int(entry["approx_size_mb"] * _DISK_SPACE_MULTIPLIER)
    models_dir = _settings.app_data_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(models_dir)
    available_mb = int(usage.free / (1024 * 1024))
    return (available_mb >= needed_mb, needed_mb, available_mb)


def get_all_model_statuses() -> list[dict]:
    """Return status dicts for all registered models."""
    from backend.app.services.model_registry import MODELS

    statuses = []
    for entry in MODELS:
        n = entry["name"]
        statuses.append(
            {
                **entry,
                "downloaded": is_model_downloaded(n),
                "version_info": get_version_info(n),
            }
        )
    return statuses


def download_model(name: str, progress_fn=None) -> dict:
    """Download a model from HuggingFace Hub to DATA_DIR/models/{name}/.

    Uses an atomic temp-dir → rename pattern to prevent corrupt model directories.
    version.json is written last as the completion marker.

    Parameters
    ----------
    name:
        Model name (must exist in MODEL_BY_NAME).
    progress_fn:
        Optional callback ``(current, total, message)`` for progress reporting.

    Returns
    -------
    dict with keys: name, hf_commit_sha, downloaded_at

    Raises
    ------
    ModelDownloadError:
        On network failure, invalid model name, or missing files after download.
    """
    entry = get_model(name)
    if entry is None:
        raise ModelDownloadError(f"Unknown model '{name}'. Valid names: {list(MODEL_BY_NAME)}")

    # Pre-flight: check disk space before attempting download
    ok, needed_mb, available_mb = check_disk_space(name)
    if not ok:
        raise ModelDownloadError(
            f"Insufficient disk space to download model '{name}'. "
            f"Need approximately {needed_mb} MB but only {available_mb} MB free."
        )

    repo_id = entry["hf_repo"]
    model_dir = get_model_dir(name)
    tmp_dir = _settings.app_data_dir / "models" / ".tmp" / name

    # Phase 1: get commit SHA before download (avoids post-download race condition)
    if progress_fn:
        progress_fn(0, 100, "Fetching model info...")
    subfolder: str | None = entry.get("hf_subfolder")
    revision: str | None = entry.get("hf_revision")
    try:
        from huggingface_hub import model_info as hf_model_info

        info = hf_model_info(repo_id, revision=revision)
        commit_sha: str = info.sha or "unknown"
    except Exception as exc:
        raise ModelDownloadError(f"Could not reach HuggingFace to fetch model info: {exc}") from exc

    logger.info("Downloading model '%s' (repo: %s, sha: %s)", name, repo_id, commit_sha[:8])

    # Phase 2: download into temp directory
    if progress_fn:
        progress_fn(
            5,
            100,
            f"Downloading {entry['label']} model (~{entry['approx_size_mb']} MB)...",
        )

    tmp_dir.parent.mkdir(parents=True, exist_ok=True)
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)  # Clean any previous partial download

    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=str(tmp_dir),
            # Repos with a subfolder also hold the full training checkpoint at the root;
            # fetch only the ONNX bundle.
            allow_patterns=[f"{subfolder}/*"] if subfolder else None,
            ignore_patterns=["*.md", "*.txt"],
        )
    except Exception as exc:
        # Clean up partial temp dir
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        _raise_download_error(exc, repo_id)

    # Phase 3: verify required files exist in tmp dir
    if progress_fn:
        progress_fn(90, 100, "Verifying download...")

    bundle_dir = tmp_dir / subfolder if subfolder else tmp_dir
    required = ["manifest.json", "clip_vision_encoder.onnx", "clip_text_encoder.onnx"]
    missing = [f for f in required if not (bundle_dir / f).exists()]
    if missing:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ModelDownloadError(
            f"Download of '{name}' appears incomplete — missing files: {missing}"
        )

    # Phase 4: atomic rename to final location
    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    bundle_dir.rename(model_dir)
    if subfolder:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # snapshot leftovers (.cache etc.)

    # Phase 5: write version.json (completion marker — written last)
    downloaded_at = datetime.now(UTC).isoformat()
    version_data = {
        "hf_commit_sha": commit_sha,
        "hf_revision": revision,
        "downloaded_at": downloaded_at,
        # Keys the bundled image-type head (services/image_type_classifier.py).
        "vision_sha256": _file_sha256(model_dir / "clip_vision_encoder.onnx"),
    }
    (model_dir / "version.json").write_text(json.dumps(version_data, indent=2), encoding="utf-8")

    if progress_fn:
        progress_fn(100, 100, "Download complete")

    logger.info("Model '%s' downloaded successfully (sha: %s)", name, commit_sha[:8])
    return {"name": name, "hf_commit_sha": commit_sha, "downloaded_at": downloaded_at}


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _raise_download_error(exc: Exception, repo_id: str) -> NoReturn:
    """Convert various HuggingFace/network exceptions into ModelDownloadError."""
    exc_str = str(exc)

    # ── Timeout errors (check before generic ConnectionError) ──
    try:
        import requests

        if isinstance(exc, requests.exceptions.Timeout):
            raise ModelDownloadError(
                "Download timed out. Check your internet connection and try again."
            ) from exc
        if isinstance(exc, requests.exceptions.ConnectionError):
            raise ModelDownloadError(
                "Could not connect to download server. Check your internet connection."
            ) from exc
    except ImportError:
        pass

    try:
        import urllib3.exceptions

        if isinstance(exc, urllib3.exceptions.TimeoutError):
            raise ModelDownloadError(
                "Download timed out. Check your internet connection and try again."
            ) from exc
    except ImportError:
        pass

    try:
        from huggingface_hub.errors import HfHubHTTPError

        if isinstance(exc, HfHubHTTPError):
            raise ModelDownloadError(
                f"HuggingFace returned an error downloading '{repo_id}': {exc_str}"
            ) from exc
    except ImportError:
        pass

    # ── Permission errors ──
    if isinstance(exc, PermissionError):
        raise ModelDownloadError(
            "Cannot write to the models directory. Check file permissions."
        ) from exc

    # ── Disk-space errors ──
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        raise ModelDownloadError(
            "Not enough disk space to download the model. Free up space and try again."
        ) from exc

    # ── Generic OS errors ──
    if isinstance(exc, OSError):
        raise ModelDownloadError(
            f"File system error while downloading '{repo_id}': {exc_str}"
        ) from exc

    raise ModelDownloadError(f"Unexpected error downloading '{repo_id}': {exc_str}") from exc
