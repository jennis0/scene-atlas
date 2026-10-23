"""Per-encoder embedding thresholds for variant grouping (ADR-028, design/variant-grouping.md §5).

The walk's embedding rules (probable joins by layout *and* embedding agreement, the
cohesion gates of meaningful parents, whole folders and large families) compare cosine
similarities against thresholds that depend on the encoder. They are calibrated by
scene-atlas-learning (``grouping/e5/calibrate.py``; the ``leaf_*`` thresholds
``grouping/e6/calibrate_leaf.py``) on Scene Atlas–style ONNX embeddings of
one exact vision encoder, and bundled here as ``data/heads/grouping/<sha256>.json``, keyed
by the sha256 of that encoder, like the image-type heads (``image_type_classifier``).

Format ``scene-atlas-grouping-calibration/2`` (``/1`` lacked the ``leaf_*`` thresholds)::

    {
      "format": "scene-atlas-grouping-calibration/2",
      "encoder_sha256": "<sha256 of clip_vision_encoder.onnx>",
      "embedding_dim": 768,
      "thresholds": {"agree_emb": 0.70, "coh": 0.82, "coh_all": 0.80,
                     "coh_key": 0.68, "coh_suggest": 0.66,
                     "leaf_diff": 0.55, "leaf_same_prod": 0.80, "leaf_same": 0.84}
    }

The threshold names are the research's (``grouping/e5/walk.py``, ``grouping/e6``). A model with no
calibration (or a file whose ``embedding_dim`` doesn't match its vectors) groups without
the embedding rules: pHash renditions, names and folders still work.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.variant_grouping import EmbeddingThresholds

logger = logging.getLogger(__name__)

CALIBRATIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "heads" / "grouping"
SUPPORTED_FORMATS = frozenset({"scene-atlas-grouping-calibration/2"})

# Research threshold name -> EmbeddingThresholds field
_THRESHOLD_FIELDS = {
    "agree_emb": "agree",  # a3 / b3 agreement (with the edge map)
    "coh": "parent",  # c1 meaningful parent
    "coh_all": "whole_folder",  # c0 whole folder
    "coh_key": "shared_base",  # a4 / b4 gated shared base
    "coh_suggest": "suggest",  # near-miss suggestions
    "leaf_diff": "leaf_different",  # a7 leaf default: different maps below this
    "leaf_same_prod": "leaf_same_production",  # ... the same with one weak cue + one production
    "leaf_same": "leaf_same",  # ... the same with one weak cue
}


class GroupingCalibrationError(ValueError):
    """A bundled calibration is malformed."""


@dataclass(frozen=True)
class GroupingCalibration:
    encoder_sha256: str
    embedding_dim: int
    thresholds: EmbeddingThresholds


def parse_calibration(data: object, source: str = "<dict>") -> GroupingCalibration:
    """Validate one calibration document. Raises ``GroupingCalibrationError``."""
    if not isinstance(data, dict):
        raise GroupingCalibrationError(f"{source}: not a JSON object")
    if data.get("format") not in SUPPORTED_FORMATS:
        raise GroupingCalibrationError(f"{source}: unsupported format {data.get('format')!r}")
    sha = data.get("encoder_sha256")
    if not isinstance(sha, str) or not sha:
        raise GroupingCalibrationError(f"{source}: missing encoder_sha256")
    dim = data.get("embedding_dim")
    if not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0:
        raise GroupingCalibrationError(f"{source}: embedding_dim must be a positive integer")
    raw = data.get("thresholds")
    if not isinstance(raw, dict):
        raise GroupingCalibrationError(f"{source}: missing thresholds")
    unknown = sorted(set(raw) - set(_THRESHOLD_FIELDS))
    missing = sorted(set(_THRESHOLD_FIELDS) - set(raw))
    if unknown or missing:
        raise GroupingCalibrationError(
            f"{source}: thresholds must be exactly {sorted(_THRESHOLD_FIELDS)} "
            f"(unknown {unknown}, missing {missing})"
        )
    values: dict[str, float] = {}
    for name, value in raw.items():
        # A cosine threshold: a number in [-1, 1]
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not -1.0 <= value <= 1.0
        ):
            raise GroupingCalibrationError(f"{source}: threshold {name} must be in [-1, 1]")
        values[_THRESHOLD_FIELDS[name]] = float(value)
    return GroupingCalibration(sha, dim, EmbeddingThresholds(**values))


def _load(path: Path) -> GroupingCalibration:
    calibration = parse_calibration(json.loads(path.read_text(encoding="utf-8")), str(path))
    if path.stem != calibration.encoder_sha256:
        raise GroupingCalibrationError(f"{path}: file name doesn't match encoder_sha256")
    return calibration


_lock = threading.Lock()
_calibrations: dict[str, GroupingCalibration] | None = None


def bundled_calibrations() -> dict[str, GroupingCalibration]:
    """{encoder sha256: calibration} for every bundled file (loaded once). A malformed file
    is logged and skipped, so it only costs its own model the embedding rules."""
    global _calibrations
    with _lock:
        if _calibrations is None:
            found: dict[str, GroupingCalibration] = {}
            for path in sorted(CALIBRATIONS_DIR.glob("*.json")):
                try:
                    calibration = _load(path)
                except (GroupingCalibrationError, OSError, ValueError):
                    logger.exception("Skipping malformed grouping calibration %s", path.name)
                    continue
                found[calibration.encoder_sha256] = calibration
            _calibrations = found
        return _calibrations


_warned: set[tuple[str, str]] = set()


def _warn_once(key: tuple[str, str], message: str, *args: object) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def calibration_for_model(name: str) -> GroupingCalibration | None:
    """The bundled calibration for an installed model's vision encoder, or None (not
    installed, or not calibrated for this exact encoder)."""
    from backend.app.services.image_type_classifier import vision_encoder_sha256
    from backend.app.services.model_download_service import get_model_dir

    sha = vision_encoder_sha256(get_model_dir(name))
    if sha is None:
        return None
    calibration = bundled_calibrations().get(sha)
    if calibration is None:
        _warn_once(
            ("missing", sha),
            "No grouping calibration for model '%s' (encoder %s): grouping without embeddings",
            name,
            sha[:12],
        )
    return calibration


def active_calibration() -> GroupingCalibration | None:
    """The calibration for the model producing embeddings now, or None."""
    from backend.app.services.clip_service import get_effective_model_name

    return calibration_for_model(get_effective_model_name())


def active_thresholds(embedding_dim: int | None) -> EmbeddingThresholds | None:
    """The embedding thresholds for the model producing embeddings now, if it is calibrated
    and its calibration is for embeddings of ``embedding_dim`` (the vectors in hand). None
    switches the walk's embedding rules off."""
    if embedding_dim is None:
        return None
    calibration = active_calibration()
    if calibration is None:
        return None
    if calibration.embedding_dim != embedding_dim:
        _warn_once(
            ("dim", calibration.encoder_sha256),
            "Grouping calibration %s expects %d-dim embeddings, got %d: grouping without "
            "embeddings",
            calibration.encoder_sha256[:12],
            calibration.embedding_dim,
            embedding_dim,
        )
        return None
    return calibration.thresholds
