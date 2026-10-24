"""Per-encoder grouping calibrations (ADR-028, design/variant-grouping.md §5)."""

from __future__ import annotations

import json

import pytest

from backend.app.services import grouping_calibration as gc
from backend.app.services.image_type_classifier import HEADS_DIR, BundledHeads
from backend.app.services.variant_grouping import EmbeddingThresholds

SHA = "ab" * 32
THRESHOLDS = {
    "agree_emb": 0.71,
    "coh": 0.83,
    "coh_all": 0.79,
    "coh_key": 0.67,
    "coh_suggest": 0.6,
    "leaf_diff": 0.5,
    "leaf_same_prod": 0.78,
    "leaf_same": 0.82,
    "scene_agree_emb": 0.86,
}


def document(**overrides) -> dict:
    return {
        "format": "scene-atlas-grouping-calibration/2",
        "encoder_sha256": SHA,
        "embedding_dim": 768,
        "thresholds": dict(THRESHOLDS),
        **overrides,
    }


def test_thresholds_map_onto_the_walk():
    calibration = gc.parse_calibration(document())
    assert calibration.encoder_sha256 == SHA and calibration.embedding_dim == 768
    assert calibration.thresholds == EmbeddingThresholds(
        agree=0.71,
        parent=0.83,
        whole_folder=0.79,
        shared_base=0.67,
        suggest=0.6,
        leaf_different=0.5,
        leaf_same_production=0.78,
        leaf_same=0.82,
        scene_agree=0.86,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"format": "scene-atlas-grouping-calibration/1"},
        {"thresholds": {k: v for k, v in THRESHOLDS.items() if k != "coh"}},
        {"thresholds": {**THRESHOLDS, "coh_extra": 0.5}},
    ],
)
def test_another_format_or_other_thresholds_are_rejected(overrides):
    with pytest.raises(ValueError):
        gc.parse_calibration(document(**overrides))


def test_the_active_models_calibration_is_used_and_a_malformed_file_skipped(tmp_path, monkeypatch):
    (tmp_path / f"{SHA}.json").write_text(json.dumps(document()))
    (tmp_path / f"{'cd' * 32}.json").write_text("{ not json")
    (tmp_path / "not-the-sha.json").write_text(json.dumps(document()))
    monkeypatch.setattr(gc, "CALIBRATIONS", BundledHeads(tmp_path, gc.parse_calibration, "x"))
    monkeypatch.setattr(
        "backend.app.services.image_type_classifier.vision_encoder_sha256", lambda _dir: SHA
    )
    monkeypatch.setattr(
        "backend.app.services.clip_service.get_effective_model_name", lambda: "medium"
    )
    assert set(gc.CALIBRATIONS.all()) == {SHA}
    assert gc.active_calibration() == gc.parse_calibration(document())


def test_every_bundled_calibration_loads_one_per_shipped_model():
    """The real files: each loads, and there is one for every encoder an image-type head
    ships for (the models Scene Atlas downloads), and none for another."""
    files = sorted(gc.CALIBRATIONS_DIR.glob("*.json"))
    loaded = BundledHeads(gc.CALIBRATIONS_DIR, gc.parse_calibration, "calibration").all()
    assert len(loaded) == len(files) > 0  # none skipped as malformed
    assert set(loaded) == {path.stem for path in HEADS_DIR.glob("*.json")}
    for sha, calibration in loaded.items():
        head = json.loads((HEADS_DIR / f"{sha}.json").read_text(encoding="utf-8"))
        assert calibration.embedding_dim == head["embedding_dim"]
