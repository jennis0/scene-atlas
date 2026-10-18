"""Tests for the bundled image-type heads and the classifier that applies them."""

import json

import numpy as np
import pytest
from PIL import Image

from backend.app.file_hash import file_sha256
from backend.app.services import image_type_classifier as itc
from backend.app.services.model_registry import MODELS


def _head(dim=4, features=None, min_confidence=0.0, **over) -> dict:
    """A tiny valid head: class k fires on embedding axis k."""
    classes = ["tactical_map", "environment", "token", "item"]
    n_in = dim + len(features or [])
    weight = np.zeros((4, n_in))
    weight[:, :4] = np.eye(4) * 10
    data = {
        "format": "scene-atlas-linear-head/2",
        "encoder_sha256": "a" * 64,
        "encoder_version": "test-v1",
        "embedding_dim": dim,
        "classes": classes,
        "groups": {
            "map": ["tactical_map"],
            "illustration": ["environment"],
            "token": ["token"],
            "other": ["item"],
        },
        "features": {"names": features, "spec": "..."} if features else None,
        "weight": weight.tolist(),
        "bias": [0.0] * 4,
        "fallback": {"group": "other", "min_confidence": min_confidence},
    }
    data.update(over)
    return data


def _contract_image() -> Image.Image:
    """Same pixels as the scene-atlas-learning contract image (see test below)."""
    a = np.zeros((90, 160, 4), np.uint8)
    a[..., 0] = np.arange(160)[None, :]
    a[..., 1] = np.arange(90)[:, None] * 2
    a[..., 2] = 200
    a[20:70, 30:130, 3] = 255
    a[40:50, 60:100, 3] = 128
    return Image.fromarray(a, "RGBA")


class TestImageFeatures:
    def test_matches_scene_atlas_learning(self):
        # Values from scene-atlas-learning's release.heads._features_one on the same image.
        # If this fails, the bundled heads see different features than they were trained on.
        f = itc.image_features(_contract_image())
        assert f["log_aspect"] == pytest.approx(0.5753641724586487, abs=1e-6)
        assert f["white_frac"] == pytest.approx(0.6407470703125, abs=1e-6)
        assert f["white_border_frac"] == pytest.approx(1.0, abs=1e-6)

    def test_transparent_counts_as_white(self):
        f = itc.image_features(Image.new("RGBA", (10, 20), (0, 0, 0, 0)))
        assert f["white_frac"] == 1.0
        assert f["log_aspect"] == pytest.approx(np.log(0.5))


class TestImageTypeHead:
    def test_classifies_and_groups(self):
        head = itc.ImageTypeHead(_head())
        r = head.classify([0, 0, 3, 0])  # unnormalised is fine
        assert r.group == "token" and not r.fell_back
        assert sum(r.probabilities.values()) == pytest.approx(1.0)

    def test_low_confidence_falls_back(self):
        head = itc.ImageTypeHead(_head(min_confidence=0.9))
        r = head.classify([1, 0.95, 0, 0])  # map vs illustration, neither confident
        assert r.group == "other" and r.fell_back

    def test_fallback_group_never_falls_back(self):
        head = itc.ImageTypeHead(_head(min_confidence=0.99))
        r = head.classify([0, 0, 0.1, 0.12])
        assert r.group == "other" and not r.fell_back

    def test_features_need_the_image(self):
        head = itc.ImageTypeHead(_head(features=["white_frac"]))
        with pytest.raises(ValueError):
            head.classify([1, 0, 0, 0])
        assert head.classify([1, 0, 0, 0], Image.new("RGB", (8, 8))).group == "map"

    def test_precomputed_features_match_the_image(self):
        """Ingest computes features on the prepare pool and classifies later."""
        head = itc.ImageTypeHead(_head(features=list(itc.KNOWN_FEATURES)))
        img = _contract_image()
        from_image = head.classify([1, 0.5, 0, 0], img)
        precomputed = head.classify([1, 0.5, 0, 0], features=itc.image_features(img))
        assert precomputed == from_image

    def test_wrong_embedding_size(self):
        with pytest.raises(ValueError):
            itc.ImageTypeHead(_head()).classify([1, 0, 0])

    @pytest.mark.parametrize(
        "over",
        [
            {"format": "scene-atlas-linear-head/1"},
            {"weight": np.zeros((4, 5)).tolist()},
            {"features": {"names": ["edge_density"]}},
            {  # a class in two groups
                "groups": {
                    "map": ["tactical_map", "environment"],
                    "illustration": ["environment"],
                    "token": ["token"],
                    "other": ["item"],
                }
            },
            {"groups": {"map": ["tactical_map"], "token": ["token"], "other": ["item"]}},  # none
            {  # a group ingest doesn't know how to act on
                "groups": {
                    "map": ["tactical_map"],
                    "illustration": ["environment"],
                    "token": ["token"],
                    "handout": ["item"],
                },
                "fallback": {"group": "handout", "min_confidence": 0.0},
            },
            {"fallback": {"group": "unsure", "min_confidence": 0.5}},  # not one of its groups
        ],
    )
    def test_rejects_malformed_heads(self, over):
        with pytest.raises((itc.ImageTypeHeadError, ValueError)):
            itc.ImageTypeHead(_head(**over))


class TestEncoderSha:
    def test_hashes_once_and_caches(self, tmp_path):
        (tmp_path / "manifest.json").write_text(json.dumps({"vision_encoder": "v.onnx"}))
        (tmp_path / "v.onnx").write_bytes(b"weights")
        (tmp_path / "version.json").write_text(json.dumps({"hf_commit_sha": "x"}))
        sha = itc.vision_encoder_sha256(tmp_path)
        assert sha == file_sha256(tmp_path / "v.onnx")
        assert json.loads((tmp_path / "version.json").read_text())["vision_sha256"] == sha
        (tmp_path / "v.onnx").write_bytes(b"changed")  # cached value wins
        assert itc.vision_encoder_sha256(tmp_path) == sha

    def test_none_when_not_installed(self, tmp_path):
        assert itc.vision_encoder_sha256(tmp_path) is None

    def test_caching_is_best_effort(self, tmp_path, monkeypatch):
        """A read-only install still gets its hash; it's just computed again next time."""
        (tmp_path / "manifest.json").write_text(json.dumps({"vision_encoder": "v.onnx"}))
        (tmp_path / "v.onnx").write_bytes(b"weights")
        (tmp_path / "version.json").write_text(json.dumps({"hf_commit_sha": "x"}))

        def read_only(self, *args, **kwargs):
            raise PermissionError("read-only file system")

        monkeypatch.setattr(itc.Path, "write_text", read_only)
        assert itc.vision_encoder_sha256(tmp_path) == file_sha256(tmp_path / "v.onnx")
        assert "vision_sha256" not in json.loads((tmp_path / "version.json").read_text())


class TestBundledHeads:
    @pytest.fixture
    def heads_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(itc, "HEADS_DIR", tmp_path)
        monkeypatch.setattr(itc, "_heads", None)
        yield tmp_path
        itc._heads = None  # the next caller loads the real bundled heads again

    def test_a_malformed_head_does_not_break_the_others(self, heads_dir):
        good = _head(encoder_sha256="b" * 64)
        (heads_dir / f"{'b' * 64}.json").write_text(json.dumps(good))
        (heads_dir / f"{'c' * 64}.json").write_text("{not json")
        bad_groups = _head(encoder_sha256="d" * 64, fallback={"group": "x", "min_confidence": 0})
        (heads_dir / f"{'d' * 64}.json").write_text(json.dumps(bad_groups))
        misnamed = _head(encoder_sha256="e" * 64)
        (heads_dir / f"{'f' * 64}.json").write_text(json.dumps(misnamed))

        assert set(itc.bundled_heads()) == {"b" * 64}
        (heads_dir / f"{'b' * 64}.json").unlink()
        assert set(itc.bundled_heads()) == {"b" * 64}  # loaded once, cached

    def test_all_bundled_heads_load(self):
        heads = itc.bundled_heads()
        for sha, head in heads.items():
            assert head.encoder_sha256 == sha

    @pytest.mark.parametrize("entry", MODELS, ids=[m["name"] for m in MODELS])
    def test_every_model_has_a_head(self, entry):
        """Each registry model pins a revision with exactly one bundled head trained for it,
        so a model bump can't silently ship without auto-classification."""
        if entry.get("image_type_head") is False:
            pytest.skip("model explicitly has no image-type head")
        matches = [
            h for h in itc.bundled_heads().values() if h.encoder_version == entry.get("hf_revision")
        ]
        assert len(matches) == 1, f"{entry['name']}: no bundled head for {entry.get('hf_revision')}"
        assert matches[0].embedding_dim == entry["embedding_dim"]
