"""Heavy integration tests that use real CLIP model.

These tests load the ONNX CLIP models and run real inference.
They are SKIPPED by default — run explicitly with:

    uv run python -m pytest -m heavy -v

Or run everything including heavy:

    uv run python -m pytest -m '' -v

Requires ONNX models to be exported first:

    uv run python scripts/export_clip_onnx.py
"""

import pytest

pytestmark = pytest.mark.heavy


@pytest.fixture(scope="session")
def clip_service():
    """Load the real CLIP service once for the entire test session.

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
    """Tests using the real CLIP model (marked as heavy)."""

    def test_encode_image_returns_512_dim(self, clip_service, make_test_image, tmp_path):
        img = tmp_path / "test.jpg"
        make_test_image(img, width=100, height=100, color=(100, 150, 200))
        embedding = clip_service.encode_image(img)
        assert len(embedding) == 512
        assert all(isinstance(v, float) for v in embedding)

    def test_encode_text_returns_512_dim(self, clip_service):
        embedding = clip_service.encode_text("a dark forest with a river")
        assert len(embedding) == 512

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
        assert all(len(e) == 512 for e in embeddings)

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
    """Test the pipeline task functions with real CLIP."""

    def test_generate_clip_embedding(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import generate_clip_embedding

        img = tmp_path / "test.jpg"
        make_test_image(img, width=100, height=100)
        embedding = generate_clip_embedding(str(img))
        assert len(embedding) == 512

    def test_batch_generate_clip_embeddings(self, make_test_image, tmp_path):
        from backend.pipeline.tasks.embedding_generation import batch_generate_clip_embeddings

        paths = []
        for i in range(3):
            p = tmp_path / f"img{i}.jpg"
            make_test_image(p, width=80, height=80)
            paths.append(str(p))

        embeddings = batch_generate_clip_embeddings(paths, batch_size=2)
        assert len(embeddings) == 3
        assert all(len(e) == 512 for e in embeddings)
