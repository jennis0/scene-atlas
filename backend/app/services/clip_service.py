"""CLIP model service for generating image and text embeddings.

Uses ONNX Runtime for inference with fp16-quantised CLIP models.
The ONNX models are exported from the torch model using
``scripts/export_clip_onnx.py`` and bundled into the sidecar.
"""

import logging
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# CLIP image preprocessing constants (from preprocessor_config.json)
_CLIP_IMAGE_SIZE = 224
_CLIP_IMAGE_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_IMAGE_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def _default_models_dir() -> Path:
    """Resolve the ONNX models directory.

    In a frozen PyInstaller sidecar the models are bundled at
    ``_MEIPASS/models/``.  In development they live under
    ``backend/models/fp16/`` (or whichever quantisation variant is active).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "models"
    return Path(__file__).parent.parent.parent / "models" / "fp16"


class CLIPService:
    """Service for generating CLIP embeddings via ONNX Runtime.

    Parameters
    ----------
    device : str
        Ignored (kept for backward compatibility with existing callers).
    model_name : str
        Ignored (kept for backward compatibility).
    models_dir : path, optional
        Directory containing ``clip_vision_encoder.onnx``,
        ``clip_text_encoder.onnx``, and a ``tokenizer/`` sub-directory.
    """

    def __init__(
        self,
        device: str = "cpu",
        model_name: str = "",
        models_dir: str | Path | None = None,
        tokenizer_dir: str | Path | None = None,
    ):
        # Deferred imports — mirrors the Windows-safe pattern that prevented
        # directory-scan OSErrors with transformers.  onnxruntime and tokenizers
        # are lightweight by comparison, but the pattern costs nothing.
        import onnxruntime as ort
        from tokenizers import Tokenizer as HFTokenizer

        if models_dir is None:
            models_dir = _default_models_dir()
        models_dir = Path(models_dir)

        if tokenizer_dir is None:
            # Tokenizer lives as a sibling of the quantisation subdirectory
            # in dev mode, or directly under models/ in the frozen sidecar.
            candidate = models_dir.parent / "tokenizer"
            if candidate.exists():
                tokenizer_dir = candidate
            else:
                tokenizer_dir = models_dir / "tokenizer"
        tokenizer_dir = Path(tokenizer_dir)

        logger.info("Loading ONNX CLIP models from %s", models_dir)

        # Session options — limit threads to avoid contention with uvicorn
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 2
        sess_opts.inter_op_num_threads = 1
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        providers = ["CPUExecutionProvider"]

        self._vision_session = ort.InferenceSession(
            str(models_dir / "clip_vision_encoder.onnx"), sess_opts, providers=providers
        )
        self._text_session = ort.InferenceSession(
            str(models_dir / "clip_text_encoder.onnx"), sess_opts, providers=providers
        )

        # Tokenizer
        tok_path = tokenizer_dir / "tokenizer.json"
        self._tokenizer = HFTokenizer.from_file(str(tok_path))
        self._tokenizer.enable_truncation(max_length=77)
        self._tokenizer.enable_padding(length=77, pad_id=49407)

        logger.info("ONNX CLIP models loaded")

    # ── Image preprocessing ──────────────────────────────────────────────

    @staticmethod
    def _preprocess_image(image: Image.Image) -> np.ndarray:
        """Replicate CLIPImageProcessor: resize → centre-crop → normalise → CHW.

        Returns a float32 array of shape ``[3, 224, 224]``.
        """
        # 1. Resize shortest side to 224 with BICUBIC
        w, h = image.size
        if h < w:
            new_h = _CLIP_IMAGE_SIZE
            new_w = int(w * _CLIP_IMAGE_SIZE / h)
        else:
            new_w = _CLIP_IMAGE_SIZE
            new_h = int(h * _CLIP_IMAGE_SIZE / w)
        image = image.resize((new_w, new_h), Image.BICUBIC)

        # 2. Centre crop to 224×224
        w, h = image.size
        left = (w - _CLIP_IMAGE_SIZE) // 2
        top = (h - _CLIP_IMAGE_SIZE) // 2
        image = image.crop((left, top, left + _CLIP_IMAGE_SIZE, top + _CLIP_IMAGE_SIZE))

        # 3. Scale to [0, 1]
        pixels = np.array(image, dtype=np.float32) / 255.0

        # 4. Normalise with CLIP mean / std
        pixels = (pixels - _CLIP_IMAGE_MEAN) / _CLIP_IMAGE_STD

        # 5. HWC → CHW
        return np.transpose(pixels, (2, 0, 1))

    # ── Public interface ─────────────────────────────────────────────────

    def encode_image(self, image_path: str | Path) -> list[float]:
        """Generate embedding for an image.

        Args:
            image_path: Path to the image file.

        Returns:
            Embedding vector as list of floats (512-d, L2-normalised).
        """
        try:
            with Image.open(image_path) as img:
                pixel_values = self._preprocess_image(img.convert("RGB"))

            pixel_values = pixel_values[np.newaxis, ...]  # [1, 3, 224, 224]

            (embeddings,) = self._vision_session.run(
                ["embeddings"], {"pixel_values": pixel_values}
            )
            embedding = embeddings[0].tolist()
            logger.debug("Generated embedding for %s, size: %s", image_path, len(embedding))
            return embedding

        except Exception as e:
            logger.error("Error encoding image %s: %s", image_path, e)
            raise

    def encode_text(self, text: str) -> list[float]:
        """Generate embedding for text query.

        Args:
            text: Text query (e.g., "dark forest cave with water").

        Returns:
            Embedding vector as list of floats (512-d, L2-normalised).
        """
        try:
            encoding = self._tokenizer.encode(text)

            input_ids = np.array([encoding.ids], dtype=np.int64)
            attention_mask = np.array([encoding.attention_mask], dtype=np.int64)

            (embeddings,) = self._text_session.run(
                ["embeddings"],
                {"input_ids": input_ids, "attention_mask": attention_mask},
            )
            embedding = embeddings[0].tolist()
            logger.debug("Generated text embedding for '%s', size: %s", text, len(embedding))
            return embedding

        except Exception as e:
            logger.error("Error encoding text '%s': %s", text, e)
            raise

    def batch_encode_images(self, image_paths: list[str | Path]) -> list[list[float]]:
        """Generate embeddings for multiple images in batch.

        Args:
            image_paths: List of paths to image files.

        Returns:
            List of embedding vectors.
        """
        try:
            pixel_batch = []
            for path in image_paths:
                with Image.open(path) as img:
                    pixel_batch.append(self._preprocess_image(img.convert("RGB")))

            pixel_values = np.stack(pixel_batch, axis=0)  # [N, 3, 224, 224]
            del pixel_batch

            (embeddings,) = self._vision_session.run(
                ["embeddings"], {"pixel_values": pixel_values}
            )
            result = embeddings.tolist()
            logger.debug("Generated batch embeddings for %s images", len(image_paths))
            return result

        except Exception as e:
            logger.error("Error batch encoding images: %s", e)
            raise


# ── Singleton with background-load support ───────────────────────────────────
# start_clip_background_load() is called from the FastAPI lifespan so CLIP
# begins loading without blocking server startup.  get_clip_service() blocks
# until loading completes (via the Event), so callers that arrive before the
# model is ready wait rather than triggering a second load.

_clip_service: CLIPService | None = None
_clip_lock = threading.Lock()
_clip_ready = threading.Event()
_clip_error: Exception | None = None


def _load_clip() -> None:
    global _clip_service, _clip_error
    try:
        service = CLIPService()
        with _clip_lock:
            _clip_service = service
        logger.info("CLIP model ready")
    except Exception as exc:
        with _clip_lock:
            _clip_error = exc
        logger.exception("CLIP model load failed")
    finally:
        _clip_ready.set()  # Always unblock waiters, even on failure


def start_clip_background_load() -> threading.Thread:
    """Kick off CLIP loading in a daemon thread.  Idempotent — safe to call twice."""
    if _clip_ready.is_set():
        # Already loaded (or failed) — nothing to do; return a harmless sentinel.
        t = threading.Thread(target=lambda: None, daemon=True, name="clip-loader-noop")
        t.start()
        return t
    t = threading.Thread(target=_load_clip, daemon=True, name="clip-loader")
    t.start()
    return t


def get_clip_service() -> CLIPService:
    """Return the CLIP singleton, waiting for the background load if needed."""
    _clip_ready.wait()  # no-op once set; blocks briefly if still loading
    if _clip_service is None:
        raise RuntimeError(f"CLIP service unavailable: {_clip_error}")
    return _clip_service
