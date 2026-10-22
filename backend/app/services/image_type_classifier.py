"""Image-type classification from CLIP embeddings: map / illustration / token / asset / other.

Heads are small linear layers trained by scene-atlas-learning (``uv run release heads``) on
one exact vision encoder, and bundled here as ``data/heads/image_type/<sha256>.json``, keyed
by the sha256 of the ``clip_vision_encoder.onnx`` they were trained against. A head can be
improved without a model re-download, and a model with no matching head simply has no
auto-classification.

Head format ``scene-atlas-linear-head/2`` (see the file's ``usage``):
    x = L2-normalised image embedding [+ image features, if the head lists any]
    p = softmax(x @ weight.T + bias) over ``classes``
    group probability = sum of p over ``groups[g]``
    predict the argmax group; if it is not ``fallback.group`` and its probability is below
    ``fallback.min_confidence``, predict ``fallback.group``

Export a head with ``uv run release export-heads --release <name>`` in scene-atlas-learning.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from backend.app.file_hash import file_sha256
from backend.app.services.clip_service import _to_rgb
from backend.app.services.model_download_service import get_model_dir

logger = logging.getLogger(__name__)

HEADS_DIR = Path(__file__).resolve().parents[1] / "data" / "heads" / "image_type"
SUPPORTED_FORMATS = frozenset({"scene-atlas-linear-head/2"})
# Features this code can compute; a head asking for anything else is rejected at load.
KNOWN_FEATURES = ("log_aspect", "white_frac", "white_border_frac")
# The groups ingest knows how to act on (design/ingestion.md §5.6)
KNOWN_GROUPS = frozenset({"map", "illustration", "token", "asset", "other"})
_FEATURE_SIZE = 128
_FEATURE_BORDER = 8
_WHITE_MIN = 245


class ImageTypeHeadError(RuntimeError):
    """A bundled head is malformed or asks for something this code can't provide."""


@dataclass(frozen=True)
class ImageTypeResult:
    group: str  # map | illustration | token | asset | other
    probabilities: dict[str, float]  # per group, sums to 1
    fell_back: bool  # True when a low-confidence prediction was sent to the fallback group


def image_features(img: Image.Image) -> dict[str, float]:
    """The head's image statistics, computed after flattening transparency onto white.

    Must match scene-atlas-learning's ``release.heads._features_one`` exactly.
    """
    img = _to_rgb(img)
    w, h = img.size
    small = img.resize((_FEATURE_SIZE, _FEATURE_SIZE), Image.Resampling.BILINEAR)
    white = np.asarray(small).min(axis=2) >= _WHITE_MIN
    border = np.ones((_FEATURE_SIZE, _FEATURE_SIZE), bool)
    border[_FEATURE_BORDER:-_FEATURE_BORDER, _FEATURE_BORDER:-_FEATURE_BORDER] = False
    return {
        "log_aspect": float(np.log(w / h)),
        "white_frac": float(white.mean()),
        "white_border_frac": float(white[border].mean()),
    }


def _reject_unknown(source: str, kind: str, names, known) -> None:
    unknown = set(names) - set(known)
    if unknown:
        raise ImageTypeHeadError(f"{source}: unknown {kind} {sorted(unknown)}")


class ImageTypeHead:
    """One bundled head, validated at construction."""

    def __init__(self, data: dict, source: str = "<dict>") -> None:
        if data.get("format") not in SUPPORTED_FORMATS:
            raise ImageTypeHeadError(f"{source}: unsupported head format {data.get('format')!r}")
        self.encoder_sha256: str = data["encoder_sha256"]
        self.encoder_version: str = data.get("encoder_version", "")
        self.embedding_dim: int = data["embedding_dim"]
        self.classes: list[str] = data["classes"]
        self.groups: dict[str, list[str]] = data["groups"]
        _reject_unknown(source, "groups", self.groups, KNOWN_GROUPS)
        self.features: list[str] = list((data.get("features") or {}).get("names", []))
        _reject_unknown(source, "features", self.features, KNOWN_FEATURES)
        self.weight = np.asarray(data["weight"], dtype=np.float32)
        self.bias = np.asarray(data["bias"], dtype=np.float32)
        self._check_shapes(source)
        self.group_names = list(self.groups)
        self._group_matrix = self._class_to_group_matrix(source)
        fallback = data["fallback"]
        self.fallback_group: str = fallback["group"]
        if self.fallback_group not in self.groups:
            raise ImageTypeHeadError(
                f"{source}: fallback group {self.fallback_group!r} is not one of its groups"
            )
        self.min_confidence: float = float(fallback["min_confidence"])

    def _check_shapes(self, source: str) -> None:
        n_in = self.embedding_dim + len(self.features)
        if self.weight.shape != (len(self.classes), n_in) or self.bias.shape != (
            len(self.classes),
        ):
            raise ImageTypeHeadError(
                f"{source}: weight {self.weight.shape} / bias {self.bias.shape} don't fit "
                f"{len(self.classes)} classes x {n_in} inputs"
            )

    def _class_to_group_matrix(self, source: str) -> np.ndarray:
        """classes x groups, 1 where the class belongs to the group (exactly one each)."""
        matrix = np.zeros((len(self.classes), len(self.group_names)), np.float32)
        for g, members in self.groups.items():
            for c in members:
                matrix[self.classes.index(c), self.group_names.index(g)] = 1.0
        if not np.all(matrix.sum(axis=1) == 1):
            raise ImageTypeHeadError(f"{source}: every class must belong to exactly one group")
        return matrix

    @property
    def needs_image(self) -> bool:
        return bool(self.features)

    def classify(
        self,
        embedding,
        image: Image.Image | None = None,
        *,
        features: dict[str, float] | None = None,
    ) -> ImageTypeResult:
        """Classify one image from its embedding, plus the image itself or its precomputed
        ``image_features`` if the head uses features. The embedding is L2-normalised here,
        so raw or normalised both work."""
        x = np.asarray(embedding, dtype=np.float32).ravel()
        if x.shape[0] != self.embedding_dim:
            raise ValueError(f"embedding has {x.shape[0]} dims, head expects {self.embedding_dim}")
        x = x / max(float(np.linalg.norm(x)), 1e-12)
        if self.features:
            if features is None:
                if image is None:
                    raise ValueError("this head uses image features; pass the image or features")
                features = image_features(image)
            feats = features
            x = np.concatenate([x, np.array([feats[f] for f in self.features], np.float32)])
        logits = self.weight @ x + self.bias
        p = np.exp(logits - logits.max())
        p /= p.sum()
        gp = p @ self._group_matrix
        top = int(gp.argmax())
        group = self.group_names[top]
        fell_back = group != self.fallback_group and float(gp[top]) < self.min_confidence
        return ImageTypeResult(
            group=self.fallback_group if fell_back else group,
            probabilities={g: float(v) for g, v in zip(self.group_names, gp, strict=True)},
            fell_back=fell_back,
        )


_lock = threading.Lock()
_heads: dict[str, ImageTypeHead] | None = None


def _load_head(path: Path) -> ImageTypeHead:
    head = ImageTypeHead(json.loads(path.read_text(encoding="utf-8")), str(path))
    if path.stem != head.encoder_sha256:
        raise ImageTypeHeadError(f"{path}: file name doesn't match encoder_sha256")
    return head


def bundled_heads() -> dict[str, ImageTypeHead]:
    """{encoder sha256: head} for every bundled head (loaded once). A malformed file is
    logged and skipped, so it only costs its own model auto-classification."""
    global _heads
    with _lock:
        if _heads is None:
            heads = {}
            for path in sorted(HEADS_DIR.glob("*.json")):
                try:
                    head = _load_head(path)
                except (ImageTypeHeadError, OSError, ValueError, KeyError, TypeError):
                    logger.exception("Skipping malformed image-type head %s", path.name)
                    continue
                heads[head.encoder_sha256] = head
            _heads = heads
        return _heads


def vision_encoder_sha256(model_dir: Path) -> str | None:
    """sha256 of an installed model's vision encoder. Read from version.json, where the
    download records it; installs that predate that are hashed once and cached there."""
    version_path = model_dir / "version.json"
    if not version_path.exists():
        return None
    try:
        version = json.loads(version_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if version.get("vision_sha256"):
        return version["vision_sha256"]
    try:
        manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        sha = file_sha256(model_dir / manifest.get("vision_encoder", "clip_vision_encoder.onnx"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not hash vision encoder in %s: %s", model_dir, exc)
        return None
    version["vision_sha256"] = sha
    tmp = version_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(version, indent=2), encoding="utf-8")
        tmp.replace(version_path)
    except OSError as exc:  # a read-only install: hash again next time
        logger.warning("Could not cache the vision encoder hash in %s: %s", version_path, exc)
    return sha


_missing_logged: set[str] = set()


def head_for_model(name: str) -> ImageTypeHead | None:
    """The bundled head for an installed model, or None (not installed, or no head trained
    for this exact encoder)."""
    sha = vision_encoder_sha256(get_model_dir(name))
    if sha is None:
        return None
    head = bundled_heads().get(sha)
    if head is None and sha not in _missing_logged:
        _missing_logged.add(sha)
        logger.warning("No image-type head for model '%s' (encoder %s)", name, sha[:12])
    return head


def active_head() -> ImageTypeHead | None:
    """The head for the model currently producing embeddings, or None."""
    from backend.app.services.clip_service import get_effective_model_name

    return head_for_model(get_effective_model_name())
