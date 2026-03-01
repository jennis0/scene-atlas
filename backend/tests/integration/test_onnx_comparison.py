"""Comparison tests: torch CLIP vs ONNX CLIPService.

Loads the original torch implementation directly alongside the ONNX-based
CLIPService and asserts that their outputs are numerically equivalent
(dot product difference < threshold) for the same inputs.

These tests require:
1. Dev deps: torch, transformers (for the reference implementation)
2. The ONNX models exported to backend/models/ (run scripts/export_clip_onnx.py)
3. Real images in data/store/images/

Run with:
    uv run --extra dev --group dev python -m pytest -m heavy \
        backend/tests/integration/test_onnx_comparison.py -v
"""

import logging
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.heavy

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "backend" / "models"
IMAGES_DIR = PROJECT_ROOT / "data" / "store" / "images"

# Thresholds: abs(1.0 - dot(torch_emb, onnx_emb))
THRESHOLD_FP32 = 0.001
THRESHOLD_FP16 = 0.001
THRESHOLD_INT8 = 0.01

TEXT_QUERIES = [
    "a dark forest with a river",
    "bright sunny beach with palm trees",
    "underground dungeon with torches",
    "medieval castle on a hill",
    "dark cave entrance",
    "snowy mountain pass",
    "underwater coral reef",
    "city streets at night",
    "ancient temple ruins",
    "peaceful meadow with flowers",
    # Edge cases
    "a",  # single word
    "the quick brown fox jumps over the lazy dog " * 5,  # long text (truncation)
    "UPPERCASE TEXT WITH NUMBERS 123",  # mixed case + numbers
]

MODEL_NAME = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dot(a: list[float], b: list[float]) -> float:
    """Dot product of two vectors."""
    return float(np.dot(np.array(a), np.array(b)))


def _diff(a: list[float], b: list[float]) -> float:
    """abs(1.0 - dot(a, b)) -- measures deviation for L2-normalised vectors."""
    return abs(1.0 - _dot(a, b))


def _collect_real_images(max_count: int = 50) -> list[Path]:
    """Collect real images from the image store."""
    images: list[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        images.extend(IMAGES_DIR.rglob(ext))
        if len(images) >= max_count * 2:
            break
    return sorted(images)[:max_count]


# ── Torch reference implementation ───────────────────────────────────────────
# This wraps the original torch+transformers model directly, independent of
# CLIPService (which is now ONNX-based).


class _TorchCLIPReference:
    """Torch-based CLIP reference for comparison testing."""

    def __init__(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        self.model = CLIPModel.from_pretrained(MODEL_NAME, local_files_only=True)
        self.model.eval()
        self.processor = CLIPProcessor.from_pretrained(MODEL_NAME, local_files_only=True)

    def encode_image(self, image_path) -> list[float]:
        from PIL import Image

        with Image.open(image_path) as img:
            image = img.convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt")
        del image
        with self._torch.no_grad():
            vo = self.model.vision_model(**inputs)
            features = self.model.visual_projection(vo.pooler_output)
            features = self._torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().flatten().tolist()

    def encode_text(self, text: str) -> list[float]:
        inputs = self.processor(text=text, return_tensors="pt", padding=True)
        with self._torch.no_grad():
            to = self.model.text_model(**inputs)
            features = self.model.text_projection(to.pooler_output)
            features = self._torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().flatten().tolist()

    def batch_encode_images(self, image_paths) -> list[list[float]]:
        from PIL import Image

        images = []
        for p in image_paths:
            with Image.open(p) as img:
                images.append(img.convert("RGB"))
        inputs = self.processor(images=images, return_tensors="pt", padding=True)
        del images
        with self._torch.no_grad():
            vo = self.model.vision_model(**inputs)
            features = self.model.visual_projection(vo.pooler_output)
            features = self._torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def torch_service():
    """Load the torch-based CLIP reference (dev env only)."""
    try:
        import torch  # noqa: F401
        from transformers import CLIPModel  # noqa: F401
    except ImportError:
        pytest.skip("torch/transformers not available (production env)")
    return _TorchCLIPReference()


@pytest.fixture(scope="session")
def onnx_fp32_service():
    """Load ONNX CLIPService with fp32 models."""
    fp32_dir = MODELS_DIR / "fp32"
    if not fp32_dir.exists():
        pytest.skip(f"fp32 ONNX models not found at {fp32_dir}")
    from backend.app.services.clip_service import CLIPService

    return CLIPService(models_dir=fp32_dir)


@pytest.fixture(scope="session")
def onnx_fp16_service():
    """Load ONNX CLIPService with fp16 models."""
    fp16_dir = MODELS_DIR / "fp16"
    if not fp16_dir.exists():
        pytest.skip(f"fp16 ONNX models not found at {fp16_dir}")
    from backend.app.services.clip_service import CLIPService

    return CLIPService(models_dir=fp16_dir)


@pytest.fixture(scope="session")
def onnx_int8_service():
    """Load ONNX CLIPService with int8 models."""
    int8_dir = MODELS_DIR / "int8"
    if not int8_dir.exists():
        pytest.skip(f"int8 ONNX models not found at {int8_dir}")
    from backend.app.services.clip_service import CLIPService

    return CLIPService(models_dir=int8_dir)


@pytest.fixture(scope="session")
def real_images():
    """Collect real images for comparison testing."""
    images = _collect_real_images(max_count=50)
    if len(images) < 5:
        pytest.skip(f"Need at least 5 real images, found {len(images)}")
    return images


# ── Parametrised variant helper ──────────────────────────────────────────────

VARIANTS = ["fp32", "fp16", "int8"]
VARIANT_THRESHOLDS = {
    "fp32": THRESHOLD_FP32,
    "fp16": THRESHOLD_FP16,
    "int8": THRESHOLD_INT8,
}


@pytest.fixture(params=VARIANTS)
def onnx_variant(request, onnx_fp32_service, onnx_fp16_service, onnx_int8_service):
    """Parametrised fixture yielding (variant_name, service, threshold)."""
    services = {
        "fp32": onnx_fp32_service,
        "fp16": onnx_fp16_service,
        "int8": onnx_int8_service,
    }
    name = request.param
    return name, services[name], VARIANT_THRESHOLDS[name]


# ── Image Encoding Tests ────────────────────────────────────────────────────


class TestImageEncoding:
    """Compare single image encoding between torch and ONNX variants."""

    def test_synthetic_image(self, torch_service, onnx_variant, make_test_image, tmp_path):
        """Synthetic test image: dot product within threshold."""
        name, onnx_svc, threshold = onnx_variant
        img = tmp_path / f"synth_{name}.jpg"
        make_test_image(img, width=300, height=200, color=(100, 150, 200))

        torch_emb = torch_service.encode_image(img)
        onnx_emb = onnx_svc.encode_image(img)

        diff = _diff(torch_emb, onnx_emb)
        assert diff < threshold, (
            f"[{name}] Dot product diff {diff:.6f} exceeds {threshold} for synthetic image"
        )

    def test_embedding_dimensions_and_norm(
        self, torch_service, onnx_variant, make_test_image, tmp_path
    ):
        """Both services produce 512-dim L2-normalised embeddings."""
        name, onnx_svc, _ = onnx_variant
        img = tmp_path / f"dim_{name}.jpg"
        make_test_image(img, width=100, height=100)

        torch_emb = torch_service.encode_image(img)
        onnx_emb = onnx_svc.encode_image(img)

        assert len(torch_emb) == 512
        assert len(onnx_emb) == 512
        assert abs(float(np.linalg.norm(torch_emb)) - 1.0) < 0.001
        assert abs(float(np.linalg.norm(onnx_emb)) - 1.0) < 0.001

    @pytest.mark.parametrize("image_idx", range(20))
    def test_real_images(self, torch_service, onnx_variant, real_images, image_idx):
        """Real images from the store: dot product within threshold."""
        if image_idx >= len(real_images):
            pytest.skip(f"Only {len(real_images)} images available")

        name, onnx_svc, threshold = onnx_variant
        img = real_images[image_idx]

        torch_emb = torch_service.encode_image(img)
        onnx_emb = onnx_svc.encode_image(img)

        diff = _diff(torch_emb, onnx_emb)
        assert diff < threshold, (
            f"[{name}] Dot product diff {diff:.6f} exceeds {threshold} for {img.name}"
        )

    def test_worst_case_across_50_images(self, torch_service, onnx_variant, real_images):
        """Aggregate: worst-case dot product diff across all real images."""
        name, onnx_svc, threshold = onnx_variant
        max_diff = 0.0
        worst_image = None

        for img in real_images:
            torch_emb = torch_service.encode_image(img)
            onnx_emb = onnx_svc.encode_image(img)
            diff = _diff(torch_emb, onnx_emb)
            if diff > max_diff:
                max_diff = diff
                worst_image = img.name

        logger.info(
            "[%s] Image encoding worst diff: %.6f (%s) across %d images",
            name,
            max_diff,
            worst_image,
            len(real_images),
        )
        assert max_diff < threshold, (
            f"[{name}] Worst diff {max_diff:.6f} exceeds {threshold} (image: {worst_image})"
        )

    @pytest.mark.parametrize(
        "size",
        [
            (50, 50),  # smaller than 224
            (224, 224),  # exactly 224
            (300, 200),  # landscape
            (200, 300),  # portrait
            (1000, 1000),  # large square
            (1920, 1080),  # 1080p
            (100, 800),  # extreme aspect ratio
        ],
        ids=lambda s: f"{s[0]}x{s[1]}",
    )
    def test_varied_aspect_ratios(
        self, torch_service, onnx_variant, make_test_image, tmp_path, size
    ):
        """Various image sizes exercise different resize/crop paths."""
        name, onnx_svc, threshold = onnx_variant
        w, h = size
        img = tmp_path / f"aspect_{name}_{w}x{h}.jpg"
        make_test_image(img, width=w, height=h, color=(80, 120, 160))

        torch_emb = torch_service.encode_image(img)
        onnx_emb = onnx_svc.encode_image(img)

        diff = _diff(torch_emb, onnx_emb)
        assert diff < threshold, (
            f"[{name}] Dot product diff {diff:.6f} for {w}x{h} image"
        )


# ── Text Encoding Tests ─────────────────────────────────────────────────────


class TestTextEncoding:
    """Compare text encoding between torch and ONNX variants."""

    @pytest.mark.parametrize("text", TEXT_QUERIES, ids=lambda t: t[:30])
    def test_text_dot_product(self, torch_service, onnx_variant, text):
        """Text queries: dot product within threshold."""
        name, onnx_svc, threshold = onnx_variant

        torch_emb = torch_service.encode_text(text)
        onnx_emb = onnx_svc.encode_text(text)

        diff = _diff(torch_emb, onnx_emb)
        assert diff < threshold, (
            f"[{name}] Dot product diff {diff:.6f} for text: '{text[:40]}...'"
        )

    def test_text_dimensions_and_norm(self, torch_service, onnx_variant):
        """Both services produce 512-dim L2-normalised text embeddings."""
        name, onnx_svc, _ = onnx_variant
        text = "forest cave with water"

        torch_emb = torch_service.encode_text(text)
        onnx_emb = onnx_svc.encode_text(text)

        assert len(torch_emb) == 512
        assert len(onnx_emb) == 512
        assert abs(float(np.linalg.norm(torch_emb)) - 1.0) < 0.001
        assert abs(float(np.linalg.norm(onnx_emb)) - 1.0) < 0.001


# ── Batch Encoding Tests ────────────────────────────────────────────────────


class TestBatchEncoding:
    """Compare batch image encoding between torch and ONNX variants."""

    def test_batch_dot_products(
        self, torch_service, onnx_variant, make_test_image, tmp_path
    ):
        """Batch encoding: every image within threshold."""
        name, onnx_svc, threshold = onnx_variant
        paths = []
        for i in range(8):
            p = tmp_path / f"batch_{name}_{i}.jpg"
            make_test_image(p, width=150, height=150, color=(30 * i, 100, 200 - 20 * i))
            paths.append(p)

        torch_embs = torch_service.batch_encode_images(paths)
        onnx_embs = onnx_svc.batch_encode_images(paths)

        assert len(torch_embs) == len(onnx_embs) == 8
        for i, (t, o) in enumerate(zip(torch_embs, onnx_embs, strict=True)):
            diff = _diff(t, o)
            assert diff < threshold, f"[{name}] Batch image {i}: diff {diff:.6f}"

    def test_batch_vs_single_consistency(self, onnx_variant, make_test_image, tmp_path):
        """ONNX batch encoding matches ONNX single encoding."""
        name, onnx_svc, _ = onnx_variant
        paths = []
        for i in range(4):
            p = tmp_path / f"consist_{name}_{i}.jpg"
            make_test_image(p, width=100, height=100, color=(50 * i, 80, 160))
            paths.append(p)

        batch_embs = onnx_svc.batch_encode_images(paths)
        single_embs = [onnx_svc.encode_image(p) for p in paths]

        # fp16 accumulates differently in batch vs single, so relax threshold
        batch_threshold = 0.001 if name == "fp16" else 0.0001
        for i, (batch, single) in enumerate(zip(batch_embs, single_embs, strict=True)):
            diff = _diff(batch, single)
            assert diff < batch_threshold, (
                f"[{name}] Batch vs single diff {diff:.6f} for image {i}"
            )

    def test_batch_real_images(self, torch_service, onnx_variant, real_images):
        """Batch encode real images and compare."""
        name, onnx_svc, threshold = onnx_variant
        batch = real_images[:8]

        torch_embs = torch_service.batch_encode_images(batch)
        onnx_embs = onnx_svc.batch_encode_images(batch)

        for i, (t, o) in enumerate(zip(torch_embs, onnx_embs, strict=True)):
            diff = _diff(t, o)
            assert diff < threshold, (
                f"[{name}] Batch real image {i} ({batch[i].name}): diff {diff:.6f}"
            )


# ── Cross-modal Consistency ──────────────────────────────────────────────────


class TestCrossModalConsistency:
    """Verify that text-image similarity rankings are preserved."""

    def test_search_ranking_preserved(
        self, torch_service, onnx_variant, make_test_image, tmp_path
    ):
        """Same query should rank images in the same order across implementations."""
        name, onnx_svc, _ = onnx_variant
        colors = {
            "green": (20, 150, 30),
            "blue": (30, 30, 200),
            "red": (220, 20, 20),
            "yellow": (220, 220, 30),
        }
        paths = {}
        for cname, color in colors.items():
            p = tmp_path / f"rank_{name}_{cname}.jpg"
            make_test_image(p, width=100, height=100, color=color)
            paths[cname] = p

        query = "lush green forest"

        torch_text = np.array(torch_service.encode_text(query))
        onnx_text = np.array(onnx_svc.encode_text(query))

        torch_scores = {}
        onnx_scores = {}
        for cname, path in paths.items():
            t_img = np.array(torch_service.encode_image(path))
            o_img = np.array(onnx_svc.encode_image(path))
            torch_scores[cname] = float(np.dot(torch_text, t_img))
            onnx_scores[cname] = float(np.dot(onnx_text, o_img))

        torch_ranking = sorted(torch_scores, key=torch_scores.get, reverse=True)
        onnx_ranking = sorted(onnx_scores, key=onnx_scores.get, reverse=True)

        assert torch_ranking == onnx_ranking, (
            f"[{name}] Rankings differ: torch={torch_ranking}, onnx={onnx_ranking}"
        )


# ── Quantisation Summary Report ──────────────────────────────────────────────


class TestQuantisationReport:
    """Aggregate accuracy/size report across all quantisation levels.

    This test always passes -- it prints a summary table for human review.
    """

    def test_print_report(
        self,
        torch_service,
        onnx_fp32_service,
        onnx_fp16_service,
        onnx_int8_service,
        real_images,
    ):
        """Print quantisation accuracy and size report."""
        services = {
            "fp32": onnx_fp32_service,
            "fp16": onnx_fp16_service,
            "int8": onnx_int8_service,
        }

        # Collect image diffs
        image_diffs: dict[str, list[float]] = {v: [] for v in VARIANTS}
        for img in real_images[:50]:
            torch_emb = torch_service.encode_image(img)
            for variant, svc in services.items():
                onnx_emb = svc.encode_image(img)
                image_diffs[variant].append(_diff(torch_emb, onnx_emb))

        # Collect text diffs
        text_diffs: dict[str, list[float]] = {v: [] for v in VARIANTS}
        for text in TEXT_QUERIES:
            torch_emb = torch_service.encode_text(text)
            for variant, svc in services.items():
                onnx_emb = svc.encode_text(text)
                text_diffs[variant].append(_diff(torch_emb, onnx_emb))

        # Model sizes
        sizes: dict[str, float] = {}
        for variant in VARIANTS:
            vdir = MODELS_DIR / variant
            if vdir.exists():
                total = sum(f.stat().st_size for f in vdir.rglob("*") if f.is_file())
                sizes[variant] = total / (1024 * 1024)
            else:
                sizes[variant] = 0.0

        # Print report
        header = (
            f"\n{'=' * 90}\n"
            f"Quantisation Report ({len(real_images)} images, {len(TEXT_QUERIES)} text queries)\n"
            f"{'=' * 90}\n"
            f"{'Variant':<8} | {'Img Max':>10} | {'Img Mean':>10} | {'Img P99':>10} "
            f"| {'Txt Max':>10} | {'Txt Mean':>10} | {'Size':>10}\n"
            f"{'-' * 90}"
        )
        print(header)
        logger.info(header)

        for variant in VARIANTS:
            i_arr = np.array(image_diffs[variant])
            t_arr = np.array(text_diffs[variant])
            row = (
                f"{variant:<8} | {i_arr.max():>10.6f} | {i_arr.mean():>10.6f} "
                f"| {np.percentile(i_arr, 99):>10.6f} "
                f"| {t_arr.max():>10.6f} | {t_arr.mean():>10.6f} "
                f"| {sizes[variant]:>8.1f} MB"
            )
            print(row)
            logger.info(row)

        print("=" * 90)
