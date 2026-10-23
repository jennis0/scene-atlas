"""Per-encoder grouping calibrations (ADR-028, design/variant-grouping.md §5)."""

from __future__ import annotations

import json
import logging

import pytest

from backend.app.services import grouping_calibration as gc
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


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    """A temp calibrations folder, loaded afresh, with the active model's encoder ``SHA``."""
    monkeypatch.setattr(gc, "CALIBRATIONS_DIR", tmp_path)
    monkeypatch.setattr(gc, "_calibrations", None)
    monkeypatch.setattr(gc, "_warned", set())
    monkeypatch.setattr(
        "backend.app.services.image_type_classifier.vision_encoder_sha256", lambda _dir: SHA
    )
    monkeypatch.setattr(
        "backend.app.services.clip_service.get_effective_model_name", lambda: "medium"
    )

    def write(name: str, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (tmp_path / f"{name}.json").write_text(text, encoding="utf-8")

    return write


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
        {"encoder_sha256": ""},
        {"embedding_dim": 0},
        {"embedding_dim": "768"},
        {"embedding_dim": True},
        {"thresholds": None},
        {"thresholds": {k: v for k, v in THRESHOLDS.items() if k != "coh"}},
        {"thresholds": {**THRESHOLDS, "coh_extra": 0.5}},
        {"thresholds": {**THRESHOLDS, "coh": 1.5}},
        {"thresholds": {**THRESHOLDS, "coh": "high"}},
        {"thresholds": {**THRESHOLDS, "coh": float("nan")}},
    ],
)
def test_malformed_documents_are_rejected(overrides):
    with pytest.raises(gc.GroupingCalibrationError):
        gc.parse_calibration(document(**overrides))


def test_a_document_must_be_an_object():
    with pytest.raises(gc.GroupingCalibrationError):
        gc.parse_calibration([1, 2])


def test_the_active_models_calibration_is_used(bundled):
    bundled(SHA, document())
    assert gc.active_calibration() is not None
    assert gc.active_thresholds(768) == gc.parse_calibration(document()).thresholds


def test_no_calibration_for_the_encoder_switches_embeddings_off(bundled, caplog):
    other = "cd" * 32
    bundled(other, document(encoder_sha256=other))
    with caplog.at_level(logging.WARNING):
        assert gc.active_thresholds(768) is None
        assert gc.active_thresholds(768) is None
    assert sum("No grouping calibration" in r.getMessage() for r in caplog.records) == 1


def test_embeddings_of_another_dimension_switch_embeddings_off(bundled, caplog):
    bundled(SHA, document())
    with caplog.at_level(logging.WARNING):
        assert gc.active_thresholds(512) is None
        assert gc.active_thresholds(512) is None
    assert sum("expects 768-dim" in r.getMessage() for r in caplog.records) == 1
    assert gc.active_thresholds(None) is None


def test_malformed_files_are_logged_and_skipped(bundled, caplog):
    other = "cd" * 32
    bundled(SHA, document())
    bundled(other, "{ not json")
    bundled("ef" * 32, document(encoder_sha256="ef" * 32, embedding_dim=-1))
    with caplog.at_level(logging.ERROR):
        found = gc.bundled_calibrations()
    assert set(found) == {SHA}
    assert (
        sum("Skipping malformed grouping calibration" in r.getMessage() for r in caplog.records)
        == 2
    )


def test_the_file_name_must_be_the_encoder_hash(bundled):
    bundled("not-the-sha", document())
    assert gc.bundled_calibrations() == {}


def test_calibrations_are_loaded_once(bundled):
    bundled(SHA, document())
    first = gc.bundled_calibrations()
    bundled("cd" * 32, document(encoder_sha256="cd" * 32))
    assert gc.bundled_calibrations() is first


def test_an_uninstalled_model_has_no_calibration(bundled, monkeypatch):
    bundled(SHA, document())
    monkeypatch.setattr(
        "backend.app.services.image_type_classifier.vision_encoder_sha256", lambda _dir: None
    )
    assert gc.active_calibration() is None


def test_every_bundled_calibration_loads_one_per_shipped_model(monkeypatch):
    """The real files: each loads, and there is one for every encoder an image-type head
    ships for (the models Scene Atlas downloads), and none for another."""
    from backend.app.services.image_type_classifier import HEADS_DIR

    monkeypatch.setattr(gc, "_calibrations", None)
    files = sorted(gc.CALIBRATIONS_DIR.glob("*.json"))
    loaded = gc.bundled_calibrations()
    assert len(loaded) == len(files) > 0  # none skipped as malformed
    assert set(loaded) == {path.stem for path in HEADS_DIR.glob("*.json")}
    for sha, calibration in loaded.items():
        assert calibration.encoder_sha256 == sha
        assert calibration.embedding_dim > 0
        head = json.loads((HEADS_DIR / f"{sha}.json").read_text(encoding="utf-8"))
        assert calibration.embedding_dim == head["embedding_dim"]
