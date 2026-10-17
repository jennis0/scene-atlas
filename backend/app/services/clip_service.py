"""Embedding model service for generating image and text embeddings.

Uses ONNX Runtime for inference with quantised models (CLIP, SigLIP2, etc.).
The ONNX models are exported using ``scripts/models/export_model_onnx.py``
and bundled into the sidecar.

Model-specific parameters (image size, normalization, tokenizer config,
embedding dimension) are read from a ``manifest.json`` file co-located
with the ONNX models.  If no manifest is found, hardcoded CLIP ViT-B/32
defaults are used for backward compatibility.
"""

import copy
import json
import logging
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from backend.app.config import settings as _settings
from backend.app.services.model_registry import GPU_PROVIDERS
from backend.app.services.ort_providers import (
    create_session_with_fallback,
    get_session_options,
    is_gpu_provider,
    resolve_providers,
)

logger = logging.getLogger(__name__)

# Hardcoded CLIP ViT-B/32 defaults — used as fallback when no manifest.json
# exists (backward compatibility for deployments that haven't re-exported).
_FALLBACK_MANIFEST: dict = {
    "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
    "model_family": "clip",
    "embedding_dim": 512,
    "image_size": 224,
    "image_mean": [0.48145466, 0.4578275, 0.40821073],
    "image_std": [0.26862954, 0.26130258, 0.27577711],
    "interpolation": "bicubic",
    "resize_mode": "shortest_edge_then_crop",
    "tokenizer_type": "huggingface",
    "tokenizer_max_length": 77,
    "tokenizer_pad_id": 49407,
    "vision_encoder": "clip_vision_encoder.onnx",
    "text_encoder": "clip_text_encoder.onnx",
}

_INTERPOLATION_MAP = {
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
}


# SentencePiece tokenizer wrapper
# Provides the same interface as tokenizers.Tokenizer so CLIPService can use
# either backend transparently.


class _TokenizerOutput:
    """Minimal output mimicking tokenizers.Encoding."""

    def __init__(self, ids: list[int], attention_mask: list[int]):
        self.ids = ids
        self.attention_mask = attention_mask


class _SentencePieceTokenizerWrapper:
    """Thin wrapper around sentencepiece to match the tokenizers.Tokenizer API.

    SigLIP2's HF tokenizer appends an EOS token after the text tokens
    (with attention_mask=1).  We replicate that here when ``eos_id`` is
    provided, so ONNX inference produces identical embeddings to the
    original torch model.
    """

    def __init__(
        self,
        model_path: str,
        max_length: int,
        pad_id: int,
        lowercase: bool = True,
        eos_id: int | None = None,
    ):
        import sentencepiece as spm

        self._sp = spm.SentencePieceProcessor(model_file=model_path)  # pyright: ignore[reportCallIssue]
        self._max_length = max_length
        self._pad_id = pad_id
        self._lowercase = lowercase
        self._eos_id = eos_id

    def encode(self, text: str) -> _TokenizerOutput:
        if self._lowercase:
            text = text.lower()
        ids = self._sp.encode(text, out_type=int)  # pyright: ignore[reportAttributeAccessIssue]
        # Append EOS if configured (SigLIP2 convention)
        if self._eos_id is not None:
            ids = ids + [self._eos_id]
        # Truncate to max_length
        ids = ids[: self._max_length]
        # Pad to max_length
        ids = ids + [self._pad_id] * (self._max_length - len(ids))
        # SigLIP2 does NOT use attention masking for padding — the HF
        # processor never returns an attention_mask.  Passing all-ones
        # is required; zeroing out pad positions destroys embeddings.
        attention_mask = [1] * self._max_length
        return _TokenizerOutput(ids=ids, attention_mask=attention_mask)


_REQUIRED_MANIFEST_KEYS = {
    "embedding_dim": int,
    "image_size": int,
    "image_mean": list,
    "image_std": list,
}


def _validate_manifest(manifest: dict, source: str) -> None:
    """Check that required manifest keys exist and have correct types."""
    for key, expected_type in _REQUIRED_MANIFEST_KEYS.items():
        if key not in manifest:
            raise ValueError(f"Manifest from {source} is missing required key '{key}'")
        if not isinstance(manifest[key], expected_type):
            raise TypeError(
                f"Manifest key '{key}' should be {expected_type.__name__}, "
                f"got {type(manifest[key]).__name__}"
            )


def _load_manifest(models_dir: Path) -> dict:
    """Load manifest.json from models_dir, falling back to hardcoded defaults."""
    manifest_path = models_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest, str(manifest_path))
        logger.info("Loaded model manifest: %s", manifest.get("model_id", "unknown"))
        return manifest
    logger.info("No manifest.json in %s — using CLIP ViT-B/32 fallback defaults", models_dir)
    return copy.deepcopy(_FALLBACK_MANIFEST)


def _default_models_dir() -> Path:
    """Resolve the ONNX models directory.

    Search order:
    1. DATA_DIR/models/{name}/ — user data dir (HF downloads)
    2. backend/models/{name}/ — dev fallback (local exports, non-frozen only)
    """
    model_name = _get_active_model_name()
    # 1. User data dir (HF downloads) — primary path for both frozen and dev
    data_models = _settings.app_data_dir / "models" / model_name
    if data_models.exists() and (data_models / "manifest.json").exists():
        return data_models
    # 2. Dev fallback (local exports in backend/models/) — not available in frozen builds
    if not getattr(sys, "frozen", False):
        return Path(__file__).parent.parent.parent / "models" / model_name
    # Frozen build with no downloaded model — return the expected HF download path.
    # The model setup screen will prompt the user to download before CLIP loads.
    return data_models


def _get_active_model_name() -> str:
    """Resolve the active model name from env var → DB → auto-detect.

    1. EMBEDDING_MODEL env var (operator override)
    2. active_model key in app_settings DB
    3. Auto-detect: GPU present → medium, CPU-only → small

    The deferred database import must remain inside this function to avoid
    circular imports (database.py imports nothing from clip_service.py, but
    module-level cross-imports between services can still cause issues at
    startup).  The bare except is intentional — if the DB is locked or not
    yet initialised, auto-detect silently activates.
    """
    # 1. Env var override
    env = os.environ.get("EMBEDDING_MODEL", "")
    if env:
        return env

    # 2. DB setting (deferred import — must stay local)
    try:
        from backend.app.models import get_engine, get_session_local
        from backend.app.models.database import AppSetting

        engine = get_engine(_settings.database_url)
        Session = get_session_local(engine)
        with Session() as db:
            row = db.query(AppSetting).filter_by(key="active_model").first()
            if row and row.value_json:
                return json.loads(row.value_json)
    except Exception:
        logger.debug("Could not read active_model setting; using defaults", exc_info=True)

    # 3. Auto-detect based on ORT provider availability
    providers = resolve_providers("auto")
    return "medium" if _has_real_gpu_provider(providers) else "small"


def _has_real_gpu_provider(providers: list[str]) -> bool:
    """Return True only if a real GPU provider (CUDA/DirectML/CoreML) is available."""
    return bool(set(providers) & GPU_PROVIDERS)


_ORT_FLOAT_TYPES = {"tensor(float)": np.float32, "tensor(float16)": np.float16}


def _cast_feed_to_inputs(session, feed: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Cast float inputs to the dtype each graph input declares.

    Exports differ: some keep float32 I/O around an fp16 graph, others take
    float16 pixel_values directly, and ORT rejects a mismatched dtype.
    """
    declared = {i.name: _ORT_FLOAT_TYPES.get(i.type) for i in session.get_inputs()}
    return {
        name: arr.astype(declared[name])
        if declared.get(name) is not None and arr.dtype != declared[name]
        else arr
        for name, arr in feed.items()
    }


def _to_rgb(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white, as the models were trained.

    scene-atlas-learning embeds thumbnails that composite alpha onto white. A plain
    ``convert("RGB")`` drops alpha instead, exposing whatever colour the transparent
    pixels store (usually black), which moves embeddings of transparent tokens and
    cut-outs far enough to misclassify most of them.
    """
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA", "PA"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


# Module-level LRU cache for text embeddings (avoids lru_cache-on-method leak).
# Keys are query strings; values are tuple[float, ...].
# lru_cache maxsize is baked at decoration time — restart required to change.
_TEXT_CACHE_MAX = _settings.clip_text_cache_max
_text_embedding_cache: dict[str, tuple[float, ...]] = {}

# DirectML leaks GPU memory on each .run() call with no public API to
# flush/sync (ORT issues #975, #25996).  Session recreation is the only
# way to release resources.  Counted in items processed, not .run() calls,
# because larger batches consume more GPU memory per call.
_DML_SESSION_RECREATION_INTERVAL = 75


class CLIPService:
    """Service for generating embeddings via ONNX Runtime.

    Reads a ``manifest.json`` from the models directory to configure itself
    for the active model (image preprocessing, tokenizer, ONNX filenames).
    Falls back to CLIP ViT-B/32 defaults if no manifest is present.

    Parameters
    ----------
    device : str
        Ignored (kept for backward compatibility with existing callers).
    model_name : str
        Ignored (kept for backward compatibility).
    models_dir : path, optional
        Directory containing ONNX vision/text encoders, a ``manifest.json``,
        and a ``tokenizer/`` sub-directory.
    """

    def __init__(
        self,
        device: str | None = None,
        model_name: str = "",
        models_dir: str | Path | None = None,
        tokenizer_dir: str | Path | None = None,
    ):
        # Record the exact model name resolved at construction time so that
        # _load_clip() can record what was actually loaded (not a later re-resolution).
        self.model_name: str = _get_active_model_name()

        # Clear stale text embedding cache — different model instances may
        # produce different-dimensional embeddings.
        _text_embedding_cache.clear()

        if models_dir is None:
            models_dir = _default_models_dir()
        models_dir = Path(models_dir)

        # Load manifest (or fall back to hardcoded CLIP defaults)
        manifest = _load_manifest(models_dir)
        self._manifest = manifest
        self._image_size: int = manifest["image_size"]
        self._image_mean = np.array(manifest["image_mean"], dtype=np.float32)
        self._image_std = np.array(manifest["image_std"], dtype=np.float32)
        self._interpolation = _INTERPOLATION_MAP.get(
            manifest.get("interpolation", "bicubic"), Image.Resampling.BICUBIC
        )
        self._resize_mode: str = manifest.get("resize_mode", "shortest_edge_then_crop")

        if tokenizer_dir is None:
            # Tokenizer lives directly under the model directory in the flat
            # layout, or under models/ in the frozen sidecar.
            candidate = models_dir / "tokenizer"
            if not candidate.exists():
                candidate = models_dir.parent / "tokenizer"
            tokenizer_dir = candidate
        tokenizer_dir = Path(tokenizer_dir)

        logger.info("Loading ONNX models from %s", models_dir)

        # Resolve execution providers — explicit device param takes priority
        # over the global INFERENCE_DEVICE setting (used by scripts that pass
        # device directly).
        inference_device = device if device is not None else _settings.inference_device
        gpu_providers = resolve_providers(inference_device)
        cpu_providers = ["CPUExecutionProvider"]

        vision_file = manifest.get("vision_encoder", "clip_vision_encoder.onnx")
        text_file = manifest.get("text_encoder", "clip_text_encoder.onnx")

        self._vision_model_path = str(models_dir / vision_file)
        self._text_model_path = str(models_dir / text_file)
        self._inference_count = 0

        # INT8 quantised encoders have no CUDA kernels — all quantised ops fall
        # back to CPU, generating expensive PCIe memcpy nodes at every boundary.
        # Force CPU for int8 encoders; use the configured GPU provider for fp16.
        vision_quant = manifest.get("vision_quant", "fp16")
        text_quant = manifest.get("text_quant", "fp16")
        vision_providers_req = gpu_providers if vision_quant != "int8" else cpu_providers
        text_providers_req = gpu_providers if text_quant != "int8" else cpu_providers

        self._vision_session, vision_actual = create_session_with_fallback(
            models_dir / vision_file,
            vision_providers_req,
            get_session_options(vision_providers_req),
        )
        self._text_session, text_actual = create_session_with_fallback(
            models_dir / text_file,
            text_providers_req,
            get_session_options(text_providers_req),
        )

        # Per-session provider tracking — used by _run_with_fallback and DML recreation.
        self._session_providers: dict[str, list[str]] = {
            "_vision_session": vision_actual,
            "_text_session": text_actual,
        }

        logger.info(
            "ONNX providers — vision (%s): %s, text (%s): %s",
            vision_quant,
            vision_actual[0],
            text_quant,
            text_actual[0],
        )

        # Tokenizer — branch on type (huggingface fast tokenizer vs sentencepiece)
        tokenizer_type = manifest.get("tokenizer_type", "huggingface")
        tok_max_length = manifest.get("tokenizer_max_length", 77)
        tok_pad_id = manifest.get("tokenizer_pad_id", 49407)

        if tokenizer_type == "sentencepiece":
            # SigLIP2 uses SentencePiece tokenizer
            sp_model_path = tokenizer_dir / "spiece.model"
            if not sp_model_path.exists():
                # Try alternative name
                sp_model_path = tokenizer_dir / "sentencepiece.bpe.model"
            tok_eos_id = manifest.get("tokenizer_eos_id")
            self._tokenizer = _SentencePieceTokenizerWrapper(
                str(sp_model_path), tok_max_length, tok_pad_id, eos_id=tok_eos_id
            )
        else:
            # CLIP uses HuggingFace fast tokenizer
            from tokenizers import Tokenizer as HFTokenizer

            tok_path = tokenizer_dir / "tokenizer.json"
            self._tokenizer = HFTokenizer.from_file(str(tok_path))
            self._tokenizer.enable_truncation(max_length=tok_max_length)
            self._tokenizer.enable_padding(length=tok_max_length, pad_id=tok_pad_id)

        logger.info("ONNX models loaded (%s)", manifest.get("model_id", "unknown"))

    # Properties

    @property
    def embedding_dim(self) -> int:
        """Embedding vector dimensionality for the active model."""
        return self._manifest.get("embedding_dim", 512)

    @property
    def model_id(self) -> str:
        """HuggingFace model ID for the active model."""
        return self._manifest.get("model_id", "unknown")

    # Image preprocessing

    def _preprocess_image(self, image: Image.Image) -> np.ndarray:
        """Resize, optionally crop, normalise, and transpose to CHW.

        Returns a float32 array of shape ``[3, size, size]``.
        """
        size = self._image_size

        if self._resize_mode == "shortest_edge_then_crop":
            # Resize shortest side to target, then centre-crop
            w, h = image.size
            if h < w:
                new_h = size
                new_w = int(w * size / h)
            else:
                new_w = size
                new_h = int(h * size / w)
            image = image.resize((new_w, new_h), self._interpolation)

            w, h = image.size
            left = (w - size) // 2
            top = (h - size) // 2
            image = image.crop((left, top, left + size, top + size))
        else:
            # direct_resize — resize directly to (size, size)
            image = image.resize((size, size), self._interpolation)

        pixels = np.array(image, dtype=np.float32) / 255.0
        pixels = (pixels - self._image_mean) / self._image_std
        return np.transpose(pixels, (2, 0, 1))

    # GPU resilience

    def _maybe_recreate_dml_session(
        self, session_attr: str, model_path: str, item_count: int = 1
    ) -> None:
        """Recreate a DirectML session periodically to prevent command buffer exhaustion.

        DirectML leaks GPU memory on each ``.run()`` call with no public API
        to flush/sync (ORT issues #975, #25996).  Session recreation is the
        only way to release resources.  No-op for non-DML providers.
        ``item_count`` is the number of images or texts in this inference.
        """
        session_providers = self._session_providers[session_attr]
        if session_providers[0] != "DmlExecutionProvider":
            return
        self._inference_count += item_count
        if self._inference_count < _DML_SESSION_RECREATION_INTERVAL:
            return
        logger.debug(
            "Recreating %s DML session after %d items processed",
            session_attr,
            self._inference_count,
        )
        sess_opts = get_session_options(session_providers)
        new_session, actual = create_session_with_fallback(model_path, session_providers, sess_opts)
        setattr(self, session_attr, new_session)
        self._session_providers[session_attr] = actual
        self._inference_count = 0

    def _run_with_fallback(
        self,
        session_attr: str,
        model_path: str,
        output_names: list[str],
        feed: dict[str, np.ndarray],
    ) -> list[np.ndarray]:
        """Run inference, falling back to CPU if GPU provider crashes."""
        session = getattr(self, session_attr)
        feed = _cast_feed_to_inputs(session, feed)
        try:
            return session.run(output_names, feed)
        except Exception as exc:
            session_providers = self._session_providers[session_attr]
            if not is_gpu_provider(session_providers):
                raise
            logger.warning(
                "GPU inference failed (%s), falling back to CPU: %s",
                session_providers[0],
                exc,
            )
            cpu_providers = ["CPUExecutionProvider"]
            cpu_opts = get_session_options(cpu_providers)
            new_session = ort.InferenceSession(model_path, cpu_opts, providers=cpu_providers)
            setattr(self, session_attr, new_session)
            self._session_providers[session_attr] = cpu_providers
            self._inference_count = 0
            return new_session.run(output_names, feed)  # pyright: ignore[reportReturnType]

    # Public interface

    def encode_image(self, image_path: str | Path) -> list[float]:
        """L2-normalised embedding for one image."""
        with Image.open(image_path) as img:
            pixel_values = self._preprocess_image(_to_rgb(img))

        pixel_values = pixel_values[np.newaxis, ...]

        self._maybe_recreate_dml_session("_vision_session", self._vision_model_path)
        (embeddings,) = self._run_with_fallback(
            "_vision_session",
            self._vision_model_path,
            ["embeddings"],
            {"pixel_values": pixel_values},
        )
        embedding = embeddings[0].tolist()
        logger.debug("Generated embedding for %s, size: %s", image_path, len(embedding))
        return embedding

    def encode_text(self, text: str) -> list[float]:
        """L2-normalised embedding for a text query.

        Results are cached in a module-level LRU dict keyed on the query
        string to avoid repeated ONNX inference for common queries.
        """
        cached = _text_embedding_cache.get(text)
        if cached is not None:
            return list(cached)

        encoding = self._tokenizer.encode(text)

        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

        self._maybe_recreate_dml_session("_text_session", self._text_model_path)
        (embeddings,) = self._run_with_fallback(
            "_text_session",
            self._text_model_path,
            ["embeddings"],
            {"input_ids": input_ids, "attention_mask": attention_mask},
        )
        embedding = embeddings[0].tolist()
        logger.debug("Generated text embedding for '%s', size: %s", text, len(embedding))

        # Store as tuple to save memory; evict oldest if full
        if len(_text_embedding_cache) >= _TEXT_CACHE_MAX:
            _text_embedding_cache.pop(next(iter(_text_embedding_cache)))
        _text_embedding_cache[text] = tuple(embedding)

        return embedding

    def batch_encode_images(self, image_paths: Sequence[str | Path]) -> list[list[float]]:
        """L2-normalised embeddings for several images in one forward pass."""
        pixel_batch = []
        for path in image_paths:
            with Image.open(path) as img:
                pixel_batch.append(self._preprocess_image(_to_rgb(img)))

        pixel_values = np.stack(pixel_batch, axis=0)
        del pixel_batch

        self._maybe_recreate_dml_session(
            "_vision_session",
            self._vision_model_path,
            item_count=len(image_paths),
        )
        (embeddings,) = self._run_with_fallback(
            "_vision_session",
            self._vision_model_path,
            ["embeddings"],
            {"pixel_values": pixel_values},
        )
        result = embeddings.tolist()
        logger.debug("Generated batch embeddings for %s images", len(image_paths))
        return result


# Singleton with background-load support
# start_clip_background_load() is called from the FastAPI lifespan so CLIP
# begins loading without blocking server startup.  get_clip_service() blocks
# until loading completes (via the Event), so callers that arrive before the
# model is ready wait rather than triggering a second load.

_clip_service: CLIPService | None = None
_clip_lock = threading.Lock()
_clip_ready = threading.Event()
_clip_error: Exception | None = None
_active_model_name: str | None = None  # Set by _load_clip(); read by get_effective_model_name()
_reload_lock = threading.Lock()


def _load_clip() -> None:
    global _clip_service, _clip_error, _active_model_name
    try:
        service = CLIPService()
        with _clip_lock:
            _clip_service = service
            _active_model_name = service.model_name  # Record what was actually loaded
        logger.info("Embedding model ready")
    except FileNotFoundError:
        # No model downloaded yet — expected on first launch.
        # The user will select and download a model via the setup wizard,
        # which calls reload_clip_service() after download completes.
        with _clip_lock:
            _clip_error = None  # Not an error — just not configured yet
        logger.info(
            "No embedding model found — waiting for model setup. "
            "Semantic search will be available after a model is downloaded."
        )
    except Exception as exc:
        with _clip_lock:
            _clip_error = exc
        logger.exception(
            "Embedding model load failed: %s. "
            "The app will run but semantic search will not work until the model is available.",
            exc,
        )
    finally:
        _clip_ready.set()  # Always unblock waiters, even on failure


def start_clip_background_load() -> threading.Thread:
    """Kick off model loading in a daemon thread.

    Idempotent for the initial load — safe to call twice before first load completes.
    After reload_clip_service() clears the ready event, calling this again
    starts a fresh load (intended behaviour — not a duplicate).
    """
    if _clip_ready.is_set():
        # Already loaded (or failed) — nothing to do; return a harmless sentinel.
        t = threading.Thread(target=lambda: None, daemon=True, name="clip-loader-noop")
        t.start()
        return t
    t = threading.Thread(target=_load_clip, daemon=True, name="clip-loader")
    t.start()
    return t


def get_effective_model_name() -> str:
    """Return the currently active model name (set during last successful load).

    Falls back to _get_active_model_name() if the service hasn't loaded yet.
    """
    # CPython: str assignment is atomic at bytecode level, so reading _active_model_name
    # without _clip_lock is safe in practice. The write happens under _clip_lock in
    # _load_clip(), so the value is either None (not loaded) or a complete string.
    if _active_model_name is not None:
        return _active_model_name
    return _get_active_model_name()


def get_clip_service() -> CLIPService:
    """Return the embedding model singleton, waiting for background load if needed."""
    _clip_ready.wait()  # no-op once set; blocks briefly if still loading
    if _clip_service is None:
        raise RuntimeError(f"Embedding service unavailable: {_clip_error}")
    return _clip_service


def get_clip_unavailable_reason() -> str | None:
    """Why embeddings can't be generated right now, or None if the model is ready.

    Never blocks, unlike ``get_clip_service()``. Used by the ingest worker to
    pause the queue instead of failing images while a model loads or is missing.
    """
    if not _clip_ready.is_set():
        return "Waiting for the AI model to load"
    if _clip_service is None:
        return "No AI model is available"
    return None


def wait_for_clip_ready() -> None:
    """Block until the CLIPService has finished loading (or failed).

    Safe to call from any thread, including JobRunner worker threads.
    Use this instead of joining the thread returned by reload_clip_service().
    """
    _clip_ready.wait()


def reload_clip_service() -> threading.Thread:
    """Reload the CLIPService singleton with the currently active model.

    Thread-safe: uses _reload_lock to prevent concurrent reloads.
    If a reload is already in progress (event is cleared), waits for it
    to complete and returns the current thread as a no-op sentinel.

    Returns the loader thread (callers can .join() to wait for completion).
    """
    with _reload_lock:
        if not _clip_ready.is_set():
            # Reload already in progress — wait for it instead of double-loading
            _clip_ready.wait()
            return threading.current_thread()
        global _clip_service, _clip_error
        _clip_ready.clear()
        with _clip_lock:
            _clip_service = None
            _clip_error = None
    return start_clip_background_load()
