"""Models API — list, download, and switch HuggingFace embedding models."""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models.database import AppSetting
from ..services import clip_service as _clip_module
from ..services.clip_service import (
    get_effective_model_name,
    reload_clip_service,
    wait_for_clip_ready,
)
from ..services.job_runner import get_job_runner
from ..services.lancedb_service import get_lancedb_service, reload_lancedb_service
from ..services.model_download_service import (
    check_disk_space,
    download_model,
    get_all_model_statuses,
    get_collection_name,
    is_model_downloaded,
)
from ..services.model_registry import (
    GPU_PROVIDER_PRIORITY,
    GPU_PROVIDERS,
    MODEL_NAMES,
    get_default_model,
    get_model,
)
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ModelInfo(BaseModel):
    name: str
    label: str
    description: str
    description_technical: str
    recommended_hardware: str
    approx_size_mb: int
    downloaded: bool
    version_info: dict | None
    active: bool


class ModelListResponse(BaseModel):
    models: list[ModelInfo]


class SetupStatusResponse(BaseModel):
    needs_model: bool
    needs_tag_packs: bool
    recommended: str
    has_gpu: bool
    gpu_provider: str | None


class EmbeddingStatsResponse(BaseModel):
    collection_name: str
    vectors_count: int
    exists: bool


class ActiveModelRequest(BaseModel):
    model_name: str


class ActiveModelResponse(BaseModel):
    status: str
    job_id: str | None


class EmbeddingStatusResponse(BaseModel):
    status: str  # "loading" | "ready" | "error"
    error: str | None


# ---------------------------------------------------------------------------
# Background job helpers
# ---------------------------------------------------------------------------


def _download_only(name: str, progress_fn=None) -> None:
    """Background job: download model files only (does not activate)."""
    download_model(name, progress_fn=progress_fn)


def _download_and_activate(name: str, progress_fn=None) -> None:
    """Sequenced job: download (if needed) → reload clip → reload lancedb → re-embed.

    If this job fails, active_model in the DB will point to `name` but the model
    will not be loaded. The frontend should check job status and offer a retry.
    """
    try:
        from backend.pipeline.write_new_embeddings import rebuild_all_embeddings

        steps = 3 if not is_model_downloaded(name) else 2

        if not is_model_downloaded(name):
            if progress_fn:
                progress_fn(0, steps, "Downloading model...")
            download_model(
                name,
                progress_fn=lambda c, t, m: progress_fn(c, t * steps, m) if progress_fn else None,
            )

        # Imports pause (rather than being refused) while the model and its vector
        # table change underneath them; no batch spans the switch.
        from backend.pipeline.ingest_worker import get_ingest_worker

        with get_ingest_worker().held("Paused while the AI model changes"):
            if progress_fn:
                progress_fn(steps - 2, steps, "Loading model...")
            reload_clip_service()
            wait_for_clip_ready()

            model_meta = get_model(name)
            embedding_dim = model_meta["embedding_dim"] if model_meta else None
            reload_lancedb_service(get_collection_name(name), vector_size=embedding_dim)

            if progress_fn:
                progress_fn(steps - 1, steps, "Re-building embeddings...")
            rebuild_all_embeddings(force=True)

        if progress_fn:
            progress_fn(steps, steps, "Done")
    except Exception:
        logger.exception(
            "Model activation failed for '%s'. DB active_model may be out of sync. "
            "Retry via POST /api/v1/models/active to recover.",
            name,
        )
        raise  # re-raise so JobRunner marks job as failed


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=ModelListResponse)
def list_models() -> ModelListResponse:
    """List all models with download status and active flag."""
    statuses = get_all_model_statuses()
    active_name = get_effective_model_name()

    model_infos = []
    for s in statuses:
        model_infos.append(
            ModelInfo(
                name=s["name"],
                label=s["label"],
                description=s["description"],
                description_technical=s["description_technical"],
                recommended_hardware=s["recommended_hardware"],
                approx_size_mb=s["approx_size_mb"],
                downloaded=s["downloaded"],
                version_info=s["version_info"],
                active=(s["name"] == active_name),
            )
        )

    return ModelListResponse(models=model_infos)


@router.get("/embedding-status", response_model=EmbeddingStatusResponse)
def get_embedding_status() -> EmbeddingStatusResponse:
    """Return the current status of the embedding model (CLIP service).

    - "loading": model is still initialising in the background
    - "ready": model is loaded and available for inference
    - "error": model failed to load
    """
    if _clip_module._clip_service is not None:
        return EmbeddingStatusResponse(status="ready", error=None)
    if _clip_module._clip_error is not None:
        return EmbeddingStatusResponse(status="error", error=str(_clip_module._clip_error))
    # No service and no error: either still loading, or no model configured yet.
    # Both cases show "loading" to the frontend — the setup wizard handles model selection.
    return EmbeddingStatusResponse(status="loading", error=None)


@router.get("/setup-status", response_model=SetupStatusResponse)
def get_setup_status(db: Session = Depends(get_db)) -> SetupStatusResponse:
    """Return setup status: whether a model is needed and GPU detection results."""
    from ..services.ort_providers import resolve_providers

    providers = resolve_providers("auto")
    has_gpu = any(p in GPU_PROVIDERS for p in providers)

    # Find the best GPU provider
    providers_set = set(providers)
    gpu_provider: str | None = None
    for candidate in GPU_PROVIDER_PRIORITY:
        if candidate in providers_set:
            gpu_provider = candidate
            break

    effective_name = get_effective_model_name()
    if effective_name:
        needs_model = not is_model_downloaded(effective_name)
    else:
        # Auto-detect hasn't run yet — needs_model is True only if NO model is downloaded
        needs_model = not any(is_model_downloaded(n) for n in MODEL_NAMES)

    recommended = get_default_model(has_gpu)

    # Tag packs are needed if setup has never been completed
    setup_completed = db.query(AppSetting).filter(AppSetting.key == "setup_completed_at").first()
    needs_tag_packs = setup_completed is None

    return SetupStatusResponse(
        needs_model=needs_model,
        needs_tag_packs=needs_tag_packs,
        recommended=recommended,
        has_gpu=has_gpu,
        gpu_provider=gpu_provider,
    )


@router.post("/{name}/download", response_model=ActiveModelResponse)
def download_model_endpoint(name: str) -> ActiveModelResponse:
    """Trigger a background download job for the named model."""
    if get_model(name) is None:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    if is_model_downloaded(name):
        return ActiveModelResponse(job_id=None, status="already_downloaded")

    # Pre-flight: check disk space before downloading
    ok, needed_mb, available_mb = check_disk_space(name)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient disk space. Need approximately {needed_mb} MB "
                f"but only {available_mb} MB free."
            ),
        )

    runner = get_job_runner()
    job_id = runner.submit(_download_only, name, name=f"Download model: {name}")
    return ActiveModelResponse(job_id=job_id, status="downloading")


@router.get("/{name}/embeddings", response_model=EmbeddingStatsResponse)
def get_embeddings_stats(name: str) -> EmbeddingStatsResponse:
    """Return LanceDB table stats for the named model's embedding collection."""
    if get_model(name) is None:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    collection_name = get_collection_name(name)
    svc = get_lancedb_service()

    try:
        if not svc.table_exists(collection_name):
            return EmbeddingStatsResponse(
                collection_name=collection_name,
                vectors_count=0,
                exists=False,
            )
        table = svc.db.open_table(collection_name)
        return EmbeddingStatsResponse(
            collection_name=collection_name,
            vectors_count=table.count_rows(),
            exists=True,
        )
    except Exception:
        return EmbeddingStatsResponse(
            collection_name=collection_name,
            vectors_count=0,
            exists=False,
        )


@router.delete("/{name}/embeddings", status_code=204)
def delete_embeddings(name: str) -> None:
    """Delete the LanceDB embedding table for a non-active model."""
    if get_model(name) is None:
        raise HTTPException(status_code=404, detail=f"Model '{name}' not found")

    active_name = get_effective_model_name()
    if name == active_name:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete embeddings for the active model '{name}'. Switch models first.",
        )

    svc = get_lancedb_service()
    try:
        svc.delete_collection_by_name(get_collection_name(name))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/active", response_model=ActiveModelResponse)
def set_active_model(
    body: ActiveModelRequest,
    db: Session = Depends(get_db),
) -> ActiveModelResponse:
    """Change the active embedding model, triggering download + re-embed if needed."""
    model_name = body.model_name

    if model_name not in MODEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown model '{model_name}'. Valid names: {MODEL_NAMES}",
        )

    if model_name == get_effective_model_name() and is_model_downloaded(model_name):
        return ActiveModelResponse(status="already_active", job_id=None)

    # Guard: reject if a model activation job is already running
    runner = get_job_runner()
    existing_job_id = runner.get_active_job_id(f"Activate model: {model_name}")
    if existing_job_id is not None:
        return ActiveModelResponse(status="already_downloading", job_id=existing_job_id)

    # Pre-flight: check disk space before downloading
    if not is_model_downloaded(model_name):
        ok, needed_mb, available_mb = check_disk_space(model_name)
        if not ok:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Insufficient disk space. Need approximately {needed_mb} MB "
                    f"but only {available_mb} MB free."
                ),
            )

    # Persist the active model to DB directly (bypass update_settings to avoid side-effects)
    db.merge(AppSetting(key="active_model", value_json=json.dumps(model_name)))
    db.commit()

    already_downloaded = is_model_downloaded(model_name)
    job_id = runner.submit(
        _download_and_activate,
        model_name,
        name=f"Activate model: {model_name}",
    )

    status = "rebuilding" if already_downloaded else "downloading"
    return ActiveModelResponse(status=status, job_id=job_id)


@router.post("/setup-complete", status_code=200)
def mark_setup_complete(db: Session = Depends(get_db)) -> dict:
    """Mark the initial setup wizard as completed.

    Creates an AppSetting with key ``setup_completed_at`` so the setup
    wizard is not shown again on subsequent visits.
    """
    now_iso = datetime.now(UTC).isoformat()
    db.merge(AppSetting(key="setup_completed_at", value_json=json.dumps(now_iso)))
    db.commit()
    return {"status": "ok", "setup_completed_at": now_iso}
