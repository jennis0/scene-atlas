"""Per-encoder embedding thresholds for variant grouping (ADR-028, design/variant-grouping.md §5).

The walk's embedding rules (probable joins by layout *and* embedding agreement, the
cohesion gates of meaningful parents, whole folders and large families) compare cosine
similarities against thresholds that depend on the encoder. They are calibrated by
scene-atlas-learning (``grouping/e5/calibrate.py``; the ``leaf_*`` thresholds
``grouping/e6/calibrate_leaf.py``, ``scene_agree_emb`` ``grouping/e7/calibrate_encoders.py``) on
Scene Atlas–style ONNX embeddings of one exact vision encoder, and bundled here as
``data/heads/grouping/<sha256>.json``, keyed by the sha256 of that encoder and loaded like the
image-type heads (``image_type_classifier.BundledHeads``).

Format ``scene-atlas-grouping-calibration/2`` (``/1`` lacked the ``leaf_*`` thresholds)::

    {
      "format": "scene-atlas-grouping-calibration/2",
      "encoder_sha256": "<sha256 of clip_vision_encoder.onnx>",
      "embedding_dim": 768,
      "thresholds": {"agree_emb": 0.70, "coh": 0.82, "coh_all": 0.80,
                     "coh_key": 0.68, "coh_suggest": 0.66,
                     "leaf_diff": 0.55, "leaf_same_prod": 0.80, "leaf_same": 0.84,
                     "scene_agree_emb": 0.85}
    }

The threshold names are the research's (``grouping/e5/walk.py``, ``grouping/e6``). A model with no
calibration groups without the embedding rules: pHash renditions, names and folders still work.
The files ship in the repo, and a test loads every one, so parsing checks only the keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.services.image_type_classifier import BundledHeads
from backend.app.services.variant_grouping import EmbeddingThresholds

CALIBRATIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "heads" / "grouping"
FORMAT = "scene-atlas-grouping-calibration/2"

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
    "scene_agree_emb": "scene_agree",  # scenes: embedding cosine of an agreeing pair
}


@dataclass(frozen=True)
class GroupingCalibration:
    encoder_sha256: str
    embedding_dim: int
    thresholds: EmbeddingThresholds


def parse_calibration(data: dict, source: str = "<dict>") -> GroupingCalibration:
    """One calibration document. Raises ``ValueError`` if its format or threshold names are
    not this code's (or ``KeyError``, ``TypeError`` for a malformed one)."""
    if data["format"] != FORMAT:
        raise ValueError(f"{source}: unsupported format {data['format']!r}")
    raw = data["thresholds"]
    if set(raw) != set(_THRESHOLD_FIELDS):
        raise ValueError(f"{source}: thresholds must be exactly {sorted(_THRESHOLD_FIELDS)}")
    return GroupingCalibration(
        data["encoder_sha256"],
        int(data["embedding_dim"]),
        EmbeddingThresholds(**{_THRESHOLD_FIELDS[k]: float(v) for k, v in raw.items()}),
    )


CALIBRATIONS = BundledHeads(CALIBRATIONS_DIR, parse_calibration, "grouping calibration")


def active_calibration() -> GroupingCalibration | None:
    """The calibration for the model producing embeddings now, or None (embedding rules
    off)."""
    return CALIBRATIONS.active()
