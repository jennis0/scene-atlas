"""Unit tests for scripts.quantisation.utils pure functions.

scripts/quantisation/ is internal tooling kept out of git (see .gitignore), so
these tests only run where it exists locally; clean checkouts and CI skip them.
"""

import json
from pathlib import Path

import numpy as np
import pytest

utils = pytest.importorskip("scripts.quantisation.utils")
ExperimentResult = utils.ExperimentResult
RunMeta = utils.RunMeta
collect_images = utils.collect_images
cosine_diffs = utils.cosine_diffs
rank_correlation = utils.rank_correlation
save_results = utils.save_results

# ── cosine_diffs ─────────────────────────────────────────────────────────────


class TestCosineDiffs:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0])
        diffs = cosine_diffs([v, v], [v, v])
        assert diffs.shape == (2,)
        assert np.allclose(diffs, 0.0, atol=1e-10)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        diffs = cosine_diffs([a], [b])
        assert np.isclose(diffs[0], 1.0, atol=1e-10)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])
        diffs = cosine_diffs([a], [b])
        assert np.isclose(diffs[0], 2.0, atol=1e-10)

    def test_small_diff(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.999, 0.001, 0.0])
        b = b / np.linalg.norm(b)  # normalise
        diffs = cosine_diffs([a], [b])
        assert 0 < diffs[0] < 0.01

    def test_empty_input(self):
        diffs = cosine_diffs([], [])
        assert len(diffs) == 0


# ── rank_correlation ─────────────────────────────────────────────────────────


class TestRankCorrelation:
    def test_perfect_agreement(self):
        """Identical embeddings should give perfect rank correlation."""
        rng = np.random.default_rng(42)
        img_embs = [rng.standard_normal(128).astype(np.float32) for _ in range(20)]
        # Normalise
        img_embs = [e / np.linalg.norm(e) for e in img_embs]
        txt_embs = [rng.standard_normal(128).astype(np.float32) for _ in range(10)]
        txt_embs = [e / np.linalg.norm(e) for e in txt_embs]

        stats = rank_correlation(img_embs, txt_embs, img_embs, txt_embs)
        assert stats["mean_rho"] == pytest.approx(1.0, abs=1e-6)
        assert stats["pct_top5_preserved"] == pytest.approx(1.0)

    def test_random_embeddings_low_correlation(self):
        """Unrelated ref and test should have low rank correlation."""
        rng = np.random.default_rng(42)
        ref_img = [rng.standard_normal(64).astype(np.float32) for _ in range(30)]
        ref_img = [e / np.linalg.norm(e) for e in ref_img]
        ref_txt = [rng.standard_normal(64).astype(np.float32) for _ in range(10)]
        ref_txt = [e / np.linalg.norm(e) for e in ref_txt]

        rng2 = np.random.default_rng(99)
        test_img = [rng2.standard_normal(64).astype(np.float32) for _ in range(30)]
        test_img = [e / np.linalg.norm(e) for e in test_img]
        test_txt = [rng2.standard_normal(64).astype(np.float32) for _ in range(10)]
        test_txt = [e / np.linalg.norm(e) for e in test_txt]

        stats = rank_correlation(ref_img, ref_txt, test_img, test_txt)
        # With totally random embeddings, rho should be low
        assert stats["mean_rho"] < 0.8

    def test_few_images_degrades_gracefully(self):
        """With fewer images than top_k, should not crash."""
        rng = np.random.default_rng(42)
        img_embs = [rng.standard_normal(32).astype(np.float32) for _ in range(3)]
        img_embs = [e / np.linalg.norm(e) for e in img_embs]
        txt_embs = [rng.standard_normal(32).astype(np.float32) for _ in range(2)]
        txt_embs = [e / np.linalg.norm(e) for e in txt_embs]

        stats = rank_correlation(img_embs, txt_embs, img_embs, txt_embs)
        assert "mean_rho" in stats
        assert "pct_top5_preserved" in stats

    def test_single_image(self):
        """With 1 image, should return perfect scores."""
        v = np.array([1.0, 0.0, 0.0])
        t = np.array([0.5, 0.5, 0.0])
        t = t / np.linalg.norm(t)
        stats = rank_correlation([v], [t], [v], [t])
        assert stats["mean_rho"] == 1.0
        assert stats["pct_top5_preserved"] == 1.0


# ── collect_images ───────────────────────────────────────────────────────────


class TestCollectImages:
    def test_collects_jpg_and_png(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"fake")
        (tmp_path / "b.png").write_bytes(b"fake")
        (tmp_path / "c.txt").write_text("not an image")
        # We create real-ish files just to test collection, not opening
        imgs = collect_images(tmp_path, max_count=10)
        assert len(imgs) == 2
        assert all(p.suffix in (".jpg", ".png") for p in imgs)

    def test_filters_macosx(self, tmp_path):
        macos_dir = tmp_path / "__MACOSX"
        macos_dir.mkdir()
        (macos_dir / "resource.jpg").write_bytes(b"fake")
        (tmp_path / "._hidden.png").write_bytes(b"fake")
        (tmp_path / "real.jpg").write_bytes(b"fake")
        imgs = collect_images(tmp_path, max_count=10)
        assert len(imgs) == 1
        assert imgs[0].name == "real.jpg"

    def test_deterministic_sampling(self, tmp_path):
        for i in range(20):
            (tmp_path / f"img_{i:03d}.jpg").write_bytes(b"fake")
        a = collect_images(tmp_path, max_count=5, seed=42)
        b = collect_images(tmp_path, max_count=5, seed=42)
        assert [p.name for p in a] == [p.name for p in b]

    def test_different_seeds_different_order(self, tmp_path):
        for i in range(20):
            (tmp_path / f"img_{i:03d}.jpg").write_bytes(b"fake")
        a = collect_images(tmp_path, max_count=5, seed=42)
        b = collect_images(tmp_path, max_count=5, seed=99)
        assert [p.name for p in a] != [p.name for p in b]

    def test_max_count_respected(self, tmp_path):
        for i in range(50):
            (tmp_path / f"img_{i:03d}.jpg").write_bytes(b"fake")
        imgs = collect_images(tmp_path, max_count=10)
        assert len(imgs) == 10

    def test_nonexistent_dir_raises(self):
        with pytest.raises(FileNotFoundError):
            collect_images(Path("/nonexistent/path"), max_count=10)

    def test_empty_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            collect_images(tmp_path, max_count=10)


# ── save_results / ExperimentResult ──────────────────────────────────────────


class TestSaveResults:
    def _make_result(self, name="test") -> ExperimentResult:
        return ExperimentResult(
            name=name,
            img_max=0.01,
            img_mean=0.003,
            txt_max=0.005,
            txt_mean=0.002,
            top5_preserved=0.95,
            top_k_rho=0.98,
            v_size_mb=100.0,
            t_size_mb=50.0,
            config={"weight_type": "QInt8"},
        )

    def _make_meta(self) -> RunMeta:
        return RunMeta(
            model_id="test-model",
            family="clip",
            git_commit="abc123",
            timestamp="2025-01-01T00:00:00Z",
            platform_info="test",
            ort_version="1.0",
            image_count=100,
            text_count=103,
            seed=42,
            image_dir="/tmp/images",
        )

    def test_round_trip(self, tmp_path):
        meta = self._make_meta()
        results = [self._make_result("exp1"), self._make_result("exp2")]
        path = save_results(meta, results, tmp_path, prefix="test")

        assert path.exists()
        data = json.loads(path.read_text())
        assert data["meta"]["model_id"] == "test-model"
        assert len(data["results"]) == 2
        assert data["results"][0]["name"] == "exp1"
        assert data["results"][1]["top5_preserved"] == 0.95

    def test_experiment_result_properties(self):
        r = self._make_result()
        assert r.total_mb == 150.0
        assert r.img_pass is True
        assert r.txt_pass is True

    def test_failing_result(self):
        r = self._make_result()
        r.img_max = 0.05  # above threshold
        assert r.img_pass is False
        assert r.txt_pass is True
