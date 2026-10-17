"""Grid detection v3 on synthetic images.

No real maps are used: they are commercial artwork and can't be committed. Each image is
a seeded noise texture with a grid drawn on top, so the expected answer is exact.
"""

import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.app.services.grid import detect_grid
from backend.app.services.grid import detector as grid_detector_module
from backend.app.services.grid.analysis import AnalysisParams, is_jpeg, reduction_factor
from backend.app.services.grid.detector import tile_counts
from backend.app.services.grid.features import feature_vector, measure
from backend.app.services.grid.models import MODEL_DIR, GridModelError, get_models, load_models

W, H = 1600, 1200

# ---------------------------------------------------------------------------
# Synthetic images
# ---------------------------------------------------------------------------


def texture(w: int = W, h: int = H, seed: int = 0) -> np.ndarray:
    """Smooth mottled background with fine grain, like a painted floor."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, (h // 8 + 1, w // 8 + 1)).astype(np.float32)
    base = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    fine = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 1.5)
    return np.clip(140 + 35 * base + 12 * fine, 0, 255)


def square_grid(img, cell, thick=2, alpha=0.5, offset=(0, 0)):
    h, w = img.shape
    mask = np.zeros_like(img)
    for x in np.arange(offset[0], w, cell):
        cv2.line(mask, (round(x), 0), (round(x), h - 1), 1.0, thick)
    for y in np.arange(offset[1], h, cell):
        cv2.line(mask, (0, round(y)), (w - 1, round(y)), 1.0, thick)
    return img * (1 - alpha * mask) + 20 * alpha * mask


def hex_grid(img, size, pointy=True, thick=2, alpha=0.5):
    """Hex outlines with flat-to-flat distance ``size``."""
    h, w = img.shape
    mask = np.zeros_like(img)
    r = size / math.sqrt(3)
    start = 30 if pointy else 0
    corners = [math.radians(start + 60 * k) for k in range(6)]
    step_x, step_y = (size, 1.5 * r) if pointy else (1.5 * r, size)
    for j, cy in enumerate(np.arange(0, h + step_y, step_y)):
        for i, cx in enumerate(np.arange(0, w + step_x, step_x)):
            x = cx + (size / 2 if pointy and j % 2 else 0)
            y = cy + (size / 2 if not pointy and i % 2 else 0)
            pts = np.array([[x + r * math.cos(a), y + r * math.sin(a)] for a in corners], np.int32)
            cv2.polylines(mask, [pts], True, 1.0, thick)
    return img * (1 - alpha * mask) + 20 * alpha * mask


def planks(img, spacing=45):
    """Vertical lines only: a one-directional pattern, not a grid."""
    out = img.copy()
    for x in range(0, img.shape[1], spacing):
        cv2.line(out, (x, 0), (x, img.shape[0] - 1), 60, 2)
    return out


def write(img, path: Path, quality: int = 90) -> Path:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if path.suffix == ".jpg" else []
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8), params)
    return path


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def test_reduction_factor():
    assert reduction_factor(30000, None) == 1  # default: always full resolution
    assert reduction_factor(4000, 4096) == 1
    assert reduction_factor(5000, 4096) == 2
    assert reduction_factor(16000, 4096) == 4
    assert reduction_factor(100000, 4096) == 8  # never more than 8x


def test_jpeg_detection_uses_content_not_extension(tmp_path):
    png_named_jpg = write(texture(64, 64), tmp_path / "a.png").rename(tmp_path / "a.jpg")
    assert not is_jpeg(png_named_jpg)
    assert is_jpeg(write(texture(64, 64), tmp_path / "b.jpg"))


def test_max_analysis_dim_reduces_large_images(tmp_path):
    path = write(square_grid(texture(), 100), tmp_path / "g.jpg")
    assert measure(path, W, H, AnalysisParams())["factor"] == 1
    assert measure(path, W, H, AnalysisParams(max_analysis_dim=1000))["factor"] == 2


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "kwargs"),
    [
        (100, {}),
        (70, {"thick": 1, "alpha": 0.3}),  # faint, non-integer count
        (100, {"offset": (37, 61)}),  # grid not aligned to the image edge
    ],
)
def test_square_grid_found_with_counts(tmp_path, cell, kwargs):
    path = write(square_grid(texture(seed=cell + len(kwargs)), cell, **kwargs), tmp_path / "g.jpg")
    result = detect_grid(path, W, H)
    assert result["gridded"] is True
    assert result["grid_type"] == "square"
    assert (result["grid_width"], result["grid_height"]) == (round(W / cell), round(H / cell))
    assert result["confidence"] >= 0.9


def test_plain_texture_is_not_gridded(tmp_path):
    result = detect_grid(write(texture(seed=3), tmp_path / "p.jpg"), W, H)
    assert result["gridded"] is False
    assert result["grid_type"] is None


@pytest.mark.xfail(
    strict=True,
    reason="Known limitation: perfectly regular one-directional lines can pass as a grid; "
    "the models never saw such patterns in training (design/grid-detection-v3.md §6)",
)
def test_one_directional_lines_are_not_a_grid(tmp_path):
    result = detect_grid(write(planks(texture(seed=4)), tmp_path / "planks.jpg"), W, H)
    assert result["gridded"] is False


@pytest.mark.parametrize("pointy", [True, False])
def test_hex_grid_found(tmp_path, pointy):
    path = write(hex_grid(texture(seed=5), 90, pointy=pointy), tmp_path / "h.jpg")
    result = detect_grid(path, W, H)
    assert result["gridded"] is True
    assert result["grid_type"] == "hex"


def test_png_input(tmp_path):
    result = detect_grid(write(square_grid(texture(seed=6), 100), tmp_path / "g.png"), W, H)
    assert (result["grid_width"], result["grid_height"]) == (16, 12)


def test_size_only_returns_counts_even_when_unsure(tmp_path):
    faint = square_grid(texture(seed=7), 100, thick=1, alpha=0.15)
    result = detect_grid(write(faint, tmp_path / "f.jpg"), W, H, size_only=True)
    assert result["gridded"] is True
    assert (result["grid_width"], result["grid_height"]) == (16, 12)


def test_size_only_accepts_a_matching_sibling_size(tmp_path):
    path = write(square_grid(texture(seed=8), 100), tmp_path / "g.jpg")
    result = detect_grid(path, W, H, size_only=True, sibling_counts=[(16, 12), (30, 20)])
    assert (result["grid_width"], result["grid_height"]) == (16, 12)


def test_unreadable_file_gives_unknown(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xff" + b"not really a jpeg" * 100)
    result = detect_grid(bad, 2000, 1500)
    assert result["gridded"] is None
    assert result["confidence"] == 0.0


def test_small_images_use_the_legacy_detector(tmp_path, monkeypatch):
    calls = []

    class FakeLegacy:
        def detect(self, path, w, h):
            calls.append(("detect", w, h))
            return {"gridded": False, "grid_type": None, "grid_width": None, "grid_height": None,
                    "confidence": 0.0}  # fmt: skip

        def detect_size_only(self, path, w, h):
            calls.append(("size", w, h))
            return {"gridded": True, "grid_type": "square", "grid_width": 8, "grid_height": 6,
                    "confidence": 0.5}  # fmt: skip

    monkeypatch.setattr(grid_detector_module, "GridDetector", FakeLegacy)
    path = write(texture(800, 600), tmp_path / "small.jpg")
    detect_grid(path, 800, 600)
    detect_grid(path, 800, 600, size_only=True)
    assert calls == [("detect", 800, 600), ("size", 800, 600)]


# ---------------------------------------------------------------------------
# Sibling prior
# ---------------------------------------------------------------------------


def _m(**extra):
    return {"ok": True, "nx": 24.4, "ny": 17.6, **extra}


def test_tile_counts_without_prior_is_the_comb_pick():
    assert tile_counts(_m()) == (24, 18)
    assert tile_counts(_m(sibling_scores={(50, 30): 9.0}, own_score=1.0)) == (24, 18)


def test_tile_counts_prior_takes_a_good_enough_candidate():
    m = _m(sibling_scores={(12, 9): 0.5, (25, 18): 0.9}, own_score=1.0)
    assert tile_counts(m, sibling_beta=0.3) == (25, 18)


def test_tile_counts_prior_ignores_weak_candidates():
    m = _m(sibling_scores={(40, 30): 0.2}, own_score=1.0)
    assert tile_counts(m, sibling_beta=0.3) == (24, 18)


def test_tile_counts_missing_when_analysis_failed():
    assert tile_counts({"ok": False, "nx": None, "ny": None}) is None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_bundled_models_load_and_match_the_features():
    models = get_models()
    assert len(models.presence_features) == 27
    assert len(models.hex_features) == 8
    assert models.threshold == 0.5


def test_model_outputs_are_stable_for_a_fixed_input():
    """Pins the shipped model files: any retrain must update these numbers on purpose."""
    models = get_models()
    m = {
        "ok": True, "joint": 2.0, "sx": 1.9, "sy": 2.1, "odd": 1.8, "width": 4000,
        "height": 3000, "cell": 100.0, "z_joint": 5.0, "z_x": 4.0, "z_y": 4.5,
        "z_self": 6.0, "null_mean": 0.3, "null_sd": 0.25, "hex": 0.3, "hex_edges": 0.6,
        "hex_pointy": 0.2, "hex_flat": 0.3, "hex2d": 0.8, "hex2d_both": 0.5, "sq2d": 2.0,
        "sq2d_both": 1.5, "contrast_x": 5.0, "contrast_y": 4.5, "block_contrast_med": 4.0,
        "block_contrast_min": 2.0, "coverage_1.15": 1.0, "coverage_1.3": 1.0,
        "coverage_1.6": 0.9, "polarity": 0.9, "sign_agree": 1.0,
    }  # fmt: skip
    presence = models.presence_probability(feature_vector(m, models.presence_features))
    hex_p = models.hex_probability(feature_vector(m, models.hex_features))
    assert presence == pytest.approx(PINNED_PRESENCE, abs=1e-5)
    assert hex_p == pytest.approx(PINNED_HEX, abs=1e-5)


def _model_copy(tmp_path: Path) -> Path:
    target = tmp_path / "models"
    shutil.copytree(MODEL_DIR, target)
    return target


def test_unknown_feature_in_meta_is_rejected(tmp_path):
    target = _model_copy(tmp_path)
    meta = json.loads((target / "meta.json").read_text())
    meta["presence_features"][0] = "not_a_feature"
    (target / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(GridModelError, match="not_a_feature"):
        load_models(target)


def test_missing_model_file_is_reported(tmp_path):
    target = _model_copy(tmp_path)
    (target / "hex_lr.onnx").unlink()
    with pytest.raises(GridModelError, match="missing"):
        load_models(target)


PINNED_PRESENCE = 0.9949530
PINNED_HEX = 0.0049351
