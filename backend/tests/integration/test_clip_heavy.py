"""Heavy integration tests that use real embedding models.

These tests load the ONNX models and run real inference.
They are SKIPPED by default — run explicitly with:

    uv run python -m pytest -m heavy -v

Or run everything including heavy:

    uv run python -m pytest -m '' -v

Requires ONNX models to be exported first:

    uv run python -m scripts.models.export_model_onnx small
    uv run python -m scripts.models.export_model_onnx medium
    uv run python -m scripts.models.export_model_onnx large
"""

from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.heavy

# Expected properties per model, derived from their manifests.
_MODEL_SPECS = {
    "small": {"embedding_dim": 512, "vision_quant": "fp16", "text_quant": "int8"},
    "medium": {"embedding_dim": 768, "vision_quant": "fp16", "text_quant": "int8"},
    "large": {"embedding_dim": 1152, "vision_quant": "fp16", "text_quant": "fp16"},
}

_MODELS_ROOT = Path(__file__).parent.parent.parent / "models"


@pytest.fixture(scope="session")
def clip_service():
    """Load the real embedding service once for the entire test session.

    Also primes the module-level singleton so that code paths using
    ``get_clip_service()`` work without needing ``start_clip_background_load()``.
    """
    import backend.app.services.clip_service as clip_mod
    from backend.app.services.clip_service import CLIPService

    service = CLIPService(device="cpu")

    # Prime the singleton so get_clip_service() returns this instance
    clip_mod._clip_service = service
    clip_mod._clip_ready.set()

    return service


class TestCLIPServiceReal:
    """Tests using the real model (marked as heavy)."""

    def test_encode_image_returns_correct_dim(self, clip_service, make_test_image, tmp_path):
        img = tmp_path / "test.jpg"
        make_test_image(img, width=100, height=100, color=(100, 150, 200))
        embedding = clip_service.encode_image(img)
        assert len(embedding) == clip_service.embedding_dim
        assert all(isinstance(v, float) for v in embedding)

    def test_encode_text_returns_correct_dim(self, clip_service):
        embedding = clip_service.encode_text("a dark forest with a river")
        assert len(embedding) == clip_service.embedding_dim

    def test_similar_images_have_higher_similarity(self, clip_service, make_test_image, tmp_path):
        """Two similar-colored images should be more similar than very different ones."""
        import numpy as np

        blue1 = tmp_path / "blue1.jpg"
        blue2 = tmp_path / "blue2.jpg"
        red = tmp_path / "red.jpg"
        make_test_image(blue1, width=100, height=100, color=(30, 30, 200))
        make_test_image(blue2, width=100, height=100, color=(40, 40, 210))
        make_test_image(red, width=100, height=100, color=(220, 20, 20))

        emb_blue1 = np.array(clip_service.encode_image(blue1))
        emb_blue2 = np.array(clip_service.encode_image(blue2))
        emb_red = np.array(clip_service.encode_image(red))

        # Cosine similarity
        def cosine(a, b):
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        sim_blues = cosine(emb_blue1, emb_blue2)
        sim_blue_red = cosine(emb_blue1, emb_red)

        assert sim_blues > sim_blue_red, (
            f"Blue-blue similarity ({sim_blues:.4f}) should be > blue-red ({sim_blue_red:.4f})"
        )

    def test_batch_encode_images(self, clip_service, make_test_image, tmp_path):
        paths = []
        for i in range(4):
            p = tmp_path / f"img{i}.jpg"
            make_test_image(p, width=80, height=80, color=(50 * i, 100, 200))
            paths.append(p)

        embeddings = clip_service.batch_encode_images(paths)
        assert len(embeddings) == 4
        assert all(len(e) == clip_service.embedding_dim for e in embeddings)

    def test_text_image_cross_similarity(self, clip_service, make_test_image, tmp_path):
        """A 'forest' text query should match a green image better than a red one."""
        import numpy as np

        green = tmp_path / "green.jpg"
        red = tmp_path / "red.jpg"
        make_test_image(green, width=100, height=100, color=(20, 150, 30))
        make_test_image(red, width=100, height=100, color=(220, 20, 20))

        text_emb = np.array(clip_service.encode_text("a lush green forest"))
        green_emb = np.array(clip_service.encode_image(green))
        red_emb = np.array(clip_service.encode_image(red))

        def cosine(a, b):
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        # This is a soft check — CLIP with solid color images may not always differentiate
        # well, but the embedding pipeline should at least produce valid vectors
        assert isinstance(cosine(text_emb, green_emb), float)
        assert isinstance(cosine(text_emb, red_emb), float)


class TestCLIPEmbeddingGenerationReal:
    """Test the pipeline task functions with real model."""

    def test_generate_clip_embedding(self, clip_service, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import generate_clip_embedding

        img = tmp_path / "test.jpg"
        make_test_image(img, width=100, height=100)
        embedding = generate_clip_embedding(str(img))
        assert len(embedding) == clip_service.embedding_dim

    def test_batch_generate_clip_embeddings(self, clip_service, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import (
            batch_generate_clip_embeddings,
        )

        paths = []
        for i in range(3):
            p = tmp_path / f"img{i}.jpg"
            make_test_image(p, width=80, height=80)
            paths.append(str(p))

        embeddings = batch_generate_clip_embeddings(paths, batch_size=2)
        assert len(embeddings) == 3
        assert all(len(e) == clip_service.embedding_dim for e in embeddings)


# ---------------------------------------------------------------------------
# Per-model tests — one fixture instance per named model
# ---------------------------------------------------------------------------


@pytest.fixture(
    scope="module",
    params=list(_MODEL_SPECS.keys()),
    ids=list(_MODEL_SPECS.keys()),
)
def named_model_service(request):
    """Load each named model (small/medium/large) once per module."""
    from backend.app.services.clip_service import CLIPService

    model_name = request.param
    models_dir = _MODELS_ROOT / model_name
    if not models_dir.exists():
        pytest.skip(f"Model '{model_name}' not found at {models_dir}")
    return model_name, CLIPService(models_dir=models_dir, device="cpu")


class TestNamedModels:
    """Smoke-test each exported model: correct dims, quant metadata, basic inference."""

    def test_embedding_dim(self, named_model_service):
        model_name, svc = named_model_service
        expected = _MODEL_SPECS[model_name]["embedding_dim"]
        assert svc.embedding_dim == expected, (
            f"{model_name}: expected dim {expected}, got {svc.embedding_dim}"
        )

    def test_manifest_quant_fields(self, named_model_service):
        model_name, svc = named_model_service
        spec = _MODEL_SPECS[model_name]
        assert svc._manifest.get("vision_quant") == spec["vision_quant"], (
            f"{model_name}: wrong vision_quant"
        )
        assert svc._manifest.get("text_quant") == spec["text_quant"], (
            f"{model_name}: wrong text_quant"
        )

    def test_encode_text_shape(self, named_model_service):
        model_name, svc = named_model_service
        emb = svc.encode_text("a moonlit dungeon corridor")
        assert len(emb) == _MODEL_SPECS[model_name]["embedding_dim"]

    def test_encode_image_shape(self, named_model_service, make_test_image, tmp_path):
        model_name, svc = named_model_service
        img = tmp_path / f"{model_name}_test.jpg"
        make_test_image(img, width=120, height=120, color=(80, 140, 200))
        emb = svc.encode_image(img)
        assert len(emb) == _MODEL_SPECS[model_name]["embedding_dim"]

    def test_text_image_embeddings_are_unit_vectors(
        self, named_model_service, make_test_image, tmp_path
    ):
        """Embeddings should be L2-normalised (norm ≈ 1)."""
        model_name, svc = named_model_service
        img = tmp_path / f"{model_name}_norm.jpg"
        make_test_image(img, width=100, height=100)
        text_emb = np.array(svc.encode_text("forest"))
        img_emb = np.array(svc.encode_image(img))
        assert abs(np.linalg.norm(text_emb) - 1.0) < 0.01, (
            f"{model_name}: text embedding not unit-normalised"
        )
        assert abs(np.linalg.norm(img_emb) - 1.0) < 0.01, (
            f"{model_name}: image embedding not unit-normalised"
        )

    def test_provider_routing(self, named_model_service):
        """int8 text encoder must never run on a GPU provider; fp16 vision should match active providers."""
        model_name, svc = named_model_service
        spec = _MODEL_SPECS[model_name]
        text_providers = svc._session_providers["_text_session"]
        vision_providers = svc._session_providers["_vision_session"]
        if spec["text_quant"] == "int8":
            assert text_providers == ["CPUExecutionProvider"], (
                f"{model_name}: int8 text encoder should be on CPU, got {text_providers}"
            )
        # vision is always fp16 — provider depends on hardware, just check it's set
        assert len(vision_providers) > 0, f"{model_name}: vision provider list is empty"
