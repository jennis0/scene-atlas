"""Tests for manifest-driven CLIPService configuration.

Verifies that CLIPService correctly reads manifest.json and falls back
to hardcoded CLIP ViT-B/32 defaults when no manifest is present.
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image as PILImage


@pytest.fixture()
def manifest_clip():
    """A valid CLIP ViT-B/32 manifest dict."""
    return {
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


class TestLoadManifest:
    """Tests for _load_manifest helper."""

    def test_loads_manifest_from_file(self, tmp_path, manifest_clip):
        from backend.app.services.clip_service import _load_manifest

        (tmp_path / "manifest.json").write_text(json.dumps(manifest_clip), encoding="utf-8")
        result = _load_manifest(tmp_path)
        assert result["model_id"] == "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
        assert result["embedding_dim"] == 512

    def test_fallback_when_no_manifest(self, tmp_path):
        from backend.app.services.clip_service import (
            _FALLBACK_MANIFEST,
            _load_manifest,
        )

        result = _load_manifest(tmp_path)
        assert result == _FALLBACK_MANIFEST

    def test_fallback_is_independent_copy(self, tmp_path):
        """Mutating the returned fallback must not affect the module constant."""
        from backend.app.services.clip_service import (
            _FALLBACK_MANIFEST,
            _load_manifest,
        )

        result = _load_manifest(tmp_path)
        result["embedding_dim"] = 9999
        assert _FALLBACK_MANIFEST["embedding_dim"] == 512


class TestManifestPreprocessing:
    """Tests that manifest values are correctly applied to preprocessing."""

    def _make_service_with_manifest(self, tmp_path, manifest):
        """Create a CLIPService with mocked ONNX sessions and a real manifest."""
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Create dummy ONNX files (CLIPService tries to load them)
        # We'll mock the onnxruntime import instead
        tok_dir = tmp_path / "tokenizer"
        tok_dir.mkdir()
        # Create a minimal tokenizer.json (enough for the Tokenizer constructor)
        (tok_dir / "tokenizer.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "model": {"type": "BPE", "vocab": {}, "merges": []},
                    "added_tokens": [],
                    "normalizer": None,
                    "pre_tokenizer": None,
                    "post_processor": None,
                    "decoder": None,
                }
            ),
            encoding="utf-8",
        )

        mock_session = MagicMock()
        mock_session.run.return_value = [np.zeros((1, manifest["embedding_dim"]))]

        with patch("onnxruntime.InferenceSession", return_value=mock_session):
            from backend.app.services.clip_service import CLIPService

            return CLIPService(models_dir=tmp_path, tokenizer_dir=tok_dir)

    def test_image_size_from_manifest(self, tmp_path, manifest_clip):
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc._image_size == 224

    def test_embedding_dim_property(self, tmp_path, manifest_clip):
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc.embedding_dim == 512

    def test_model_id_property(self, tmp_path, manifest_clip):
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc.model_id == "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"

    def test_interpolation_bicubic(self, tmp_path, manifest_clip):
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc._interpolation == PILImage.BICUBIC

    def test_interpolation_bilinear(self, tmp_path, manifest_clip):
        manifest_clip["interpolation"] = "bilinear"
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc._interpolation == PILImage.BILINEAR

    def test_resize_mode_from_manifest(self, tmp_path, manifest_clip):
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc._resize_mode == "shortest_edge_then_crop"

    def test_direct_resize_mode(self, tmp_path, manifest_clip):
        manifest_clip["resize_mode"] = "direct_resize"
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc._resize_mode == "direct_resize"

    def test_different_embedding_dim(self, tmp_path, manifest_clip):
        manifest_clip["embedding_dim"] = 768
        manifest_clip["model_id"] = "google/siglip2-base-patch16-224"
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        assert svc.embedding_dim == 768

    def test_preprocessing_shortest_edge_then_crop(self, tmp_path, manifest_clip):
        """Verify shortest-side-resize + centre-crop produces correct shape."""
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        # Non-square image
        img = PILImage.new("RGB", (400, 300), color=(128, 128, 128))
        result = svc._preprocess_image(img)
        assert result.shape == (3, 224, 224)

    def test_preprocessing_direct_resize(self, tmp_path, manifest_clip):
        """Verify direct resize produces correct shape."""
        manifest_clip["resize_mode"] = "direct_resize"
        manifest_clip["image_size"] = 384
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)
        img = PILImage.new("RGB", (400, 300), color=(128, 128, 128))
        result = svc._preprocess_image(img)
        assert result.shape == (3, 384, 384)

    def test_preprocessing_regression_clip_defaults(self, tmp_path, manifest_clip):
        """Manifest-driven preprocessing must produce identical output to the
        old hardcoded CLIP preprocessing for the same input image."""
        svc = self._make_service_with_manifest(tmp_path, manifest_clip)

        # Replicate the old hardcoded preprocessing
        old_mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
        old_std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
        old_size = 224

        img = PILImage.new("RGB", (320, 240), color=(100, 150, 200))

        # New manifest-driven path
        new_result = svc._preprocess_image(img.copy())

        # Old hardcoded path (replicated)
        w, h = img.size
        if h < w:
            new_h = old_size
            new_w = int(w * old_size / h)
        else:
            new_w = old_size
            new_h = int(h * old_size / w)
        old_img = img.resize((new_w, new_h), PILImage.BICUBIC)
        w, h = old_img.size
        left = (w - old_size) // 2
        top = (h - old_size) // 2
        old_img = old_img.crop((left, top, left + old_size, top + old_size))
        pixels = np.array(old_img, dtype=np.float32) / 255.0
        pixels = (pixels - old_mean) / old_std
        old_result = np.transpose(pixels, (2, 0, 1))

        np.testing.assert_array_equal(new_result, old_result)
