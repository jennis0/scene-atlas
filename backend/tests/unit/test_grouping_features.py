"""Tests for variant-grouping features (backend/pipeline/grouping_features.py, ADR-028).

Parity: ``phash256`` must be bit-identical to the research catalog's
``imagehash.phash(hash_size=16)``, and ``edge_descriptor`` equal to the research layout
descriptor, or the research thresholds don't transfer. The references were computed by
the research code in its own environment (``scripts/quality/grouping_feature_reference.py``)
on the fixtures in ``grouping_fixtures.py``.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from backend.app.models.database import ImageGroupingFeatures
from backend.pipeline import grouping_features as gf
from backend.pipeline.grouping_features import (
    EDGE_BYTES,
    EDGE_DIM,
    GROUPING_FEATURES_VERSION,
    PHASH256_BYTES,
    GroupingFeatures,
    compute_grouping_features,
    edge_descriptor,
    load_grouping_features,
    phash256,
    phash256_distance,
    store_grouping_features,
)

from .grouping_fixtures import FIXTURES, map_rgb, map_rgba

_REFERENCE = json.loads((Path(__file__).parent / "grouping_features_reference.json").read_text())

# imagehash.phash(img.convert("RGB"), hash_size=16), via the research thumbnail step
# (imagehash 4.3.2, Pillow 12.1.1, NumPy 2.4.3, SciPy 1.17.1)
PHASH256_REFERENCE = {
    "map_rgb": "d3c00ec666b1f8be19df6073c69689d3c86eb1321e96afb739129f29122c342d",
    "map_portrait": "979d89a649469c8339ddf22265a86231e81cb0a2fd16e6f124b65d5dbe283e7a",
    "map_wide": "85e850022d583e5617f8cae1494699e39247b7b2625db5b92f1de6d8b69cbc0e",
    "map_rgba": "ff807f087691807e7fc069c380fa7c906f4d82dd7d883e49a56a3a91e1a62f26",
    "map_gray": "8f44e620727867301b3ef39bbe560b211aa56d5eef176d60a1113dc21789f754",
    "map_palette": "bfc2ae8242d5698e06a4b19a849234fc2d46783a039c9b6c6ff7da11f685b5ea",
    "map_cmyk": "b94be259da1537ea3566e95d9e591c31e1dd60066bc375a6c69818d12e40e1fc",
    "tiny": "87002daa8cabd25f775c2db78de22cfbad6f2cc289d32e5d89962c70a80c2d71",
}


def _reference_edge(name: str) -> np.ndarray:
    blob = base64.b64decode(_REFERENCE["fixtures"][name]["edge_f16_base64"])
    return np.frombuffer(blob, dtype="<f2")


def _jpeg(image: Image.Image, quality: int = 85) -> Image.Image:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    reopened = Image.open(buf)
    reopened.load()
    return reopened


def _with_grid(image: Image.Image, cell: int = 40) -> Image.Image:
    gridded = image.convert("RGB")
    draw = ImageDraw.Draw(gridded)
    for x in range(0, gridded.width, cell):
        draw.line((x, 0, x, gridded.height), fill=(0, 0, 0))
    for y in range(0, gridded.height, cell):
        draw.line((0, y, gridded.width, y), fill=(0, 0, 0))
    return gridded


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    return float(a.astype(np.float32) @ b.astype(np.float32)) / EDGE_DIM


class TestResearchParity:
    def test_references_cover_every_fixture(self):
        assert set(_REFERENCE["fixtures"]) == set(FIXTURES) == set(PHASH256_REFERENCE)
        for name, expected in PHASH256_REFERENCE.items():
            assert _REFERENCE["fixtures"][name]["phash256"] == expected

    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_phash256_is_bit_identical_to_imagehash(self, name):
        assert phash256(FIXTURES[name]()).hex() == PHASH256_REFERENCE[name]

    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_edge_descriptor_matches_the_research_descriptor(self, name):
        ours = edge_descriptor(FIXTURES[name]())
        reference = _reference_edge(name)
        assert ours.dtype == np.dtype("<f2") and ours.shape == (EDGE_DIM,)
        # Within float16 rounding (measured: exactly equal)
        np.testing.assert_allclose(
            ours.astype(np.float32), reference.astype(np.float32), rtol=1e-3, atol=1e-3
        )


class TestPhash256:
    def test_is_32_bytes_msb_first_row_major(self):
        """The first byte holds the top row's first 8 coefficients, MSB first."""
        assert len(phash256(map_rgb())) == PHASH256_BYTES
        bits = np.unpackbits(np.frombuffer(phash256(map_rgb()), dtype=np.uint8))
        assert "".join(map(str, bits)) == bin(int(PHASH256_REFERENCE["map_rgb"], 16))[2:].zfill(256)

    def test_renditions_are_a_few_bits_apart(self):
        """Resized, re-encoded and gridded copies stay within the research's rendition
        threshold (12 of 256 bits); a different map doesn't."""
        original = map_rgb()
        base = phash256(original)
        smaller = original.resize((400, 300), Image.Resampling.LANCZOS)
        assert phash256_distance(base, phash256(_jpeg(smaller, quality=70))) <= 12
        assert phash256_distance(base, phash256(_with_grid(original))) <= 12
        assert phash256_distance(base, phash256(FIXTURES["map_portrait"]())) > 40

    def test_distance(self):
        a = phash256(map_rgb())
        assert phash256_distance(a, a) == 0
        assert phash256_distance(a, bytes(b ^ 0xFF for b in a)) == 256
        assert phash256_distance(bytes(32), bytes(31) + b"\x05") == 2


class TestEdgeDescriptor:
    def test_is_z_scored_so_its_dot_product_is_a_correlation(self):
        edge = edge_descriptor(map_rgb()).astype(np.float32)
        assert abs(edge.mean()) < 1e-3
        assert edge.std() == pytest.approx(1.0, abs=1e-3)
        assert _correlation(edge, edge) == pytest.approx(1.0, abs=1e-3)

    def test_layout_survives_recolouring(self):
        """A night version (darker, tinted) correlates with the day map; another map doesn't."""
        day = np.asarray(map_rgb()).astype(np.int32)
        night = Image.fromarray((day * (0.4, 0.45, 0.7)).astype(np.uint8), "RGB")
        assert _correlation(edge_descriptor(map_rgb()), edge_descriptor(night)) > 0.9
        other = Image.fromarray(np.asarray(FIXTURES["map_portrait"]()).copy()).resize((800, 600))
        assert _correlation(edge_descriptor(map_rgb()), edge_descriptor(other)) < 0.5

    def test_flat_image_is_all_zeros(self):
        edge = edge_descriptor(Image.new("RGB", (300, 200), (90, 120, 30)))
        assert not edge.any()


class TestInputs:
    @pytest.mark.parametrize(
        "image",
        [
            Image.new("RGB", (1, 1), (10, 20, 30)),
            Image.new("RGB", (3, 700), (10, 20, 30)),
            Image.new("LA", (40, 30), (128, 100)),
            Image.new("I;16", (40, 30), 30000),
            Image.new("RGBA", (40, 30), (0, 0, 0, 0)),
            Image.new("CMYK", (40, 30), (0, 128, 255, 10)),
            Image.new("1", (40, 30), 1),
        ],
        ids=["1x1", "sliver", "LA", "I16", "transparent", "CMYK", "bilevel"],
    )
    def test_any_mode_and_size_gives_well_formed_features(self, image):
        features = compute_grouping_features(image)
        assert features.phash256 is not None and len(features.phash256) == PHASH256_BYTES
        assert features.edge is not None and features.edge.shape == (EDGE_DIM,)
        assert np.isfinite(features.edge.astype(np.float32)).all()

    def test_colour_under_transparent_pixels_is_ignored(self):
        """Transparency is flattened onto white, as the research thumbnails were."""
        pixels = np.asarray(map_rgba()).copy()
        hidden = pixels[..., 3] == 0
        pixels[hidden, :3] = (0, 255, 0)
        recoloured = Image.fromarray(pixels, "RGBA")
        assert phash256(recoloured) == phash256(map_rgba())
        assert np.array_equal(edge_descriptor(recoloured), edge_descriptor(map_rgba()))

    def test_fully_transparent_image_is_white(self):
        white = compute_grouping_features(Image.new("RGB", (64, 64), (255, 255, 255)))
        clear = compute_grouping_features(Image.new("RGBA", (64, 64), (0, 0, 0, 0)))
        assert clear.phash256 == white.phash256

    def test_exif_orientation_is_applied(self, tmp_path):
        """A JPEG stored sideways with an orientation tag hashes as it is displayed."""
        upright = map_rgb()
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° clockwise to display
        path = tmp_path / "sideways.jpg"
        upright.transpose(Image.Transpose.ROTATE_90).save(path, quality=95, exif=exif)
        with Image.open(path) as sideways:
            assert phash256_distance(phash256(sideways), phash256(upright)) <= 6


class TestFailures:
    def test_a_failing_feature_is_none_and_the_other_is_kept(self, monkeypatch, caplog):
        def boom(_gray):
            raise ValueError("bad pixels")

        monkeypatch.setattr(gf, "_phash256", boom)
        with caplog.at_level(logging.WARNING, logger=gf.__name__):
            features = compute_grouping_features(map_rgb(), "A/Map.png")
        assert features.phash256 is None and features.edge is not None
        assert "A/Map.png" in caplog.text

    def test_an_unreadable_image_gives_no_features(self, monkeypatch):
        def boom(_image):
            raise OSError("truncated")

        monkeypatch.setattr(gf, "_flattened_rgb", boom)
        assert compute_grouping_features(map_rgb()) == GroupingFeatures(None, None)


class TestStorage:
    @pytest.fixture
    def image_ids(self, db_session):
        from backend.app.models import Image

        images = [Image(filename=f"{k}.png", storage_key=f"{k}.png", name=str(k)) for k in range(3)]
        db_session.add_all(images)
        db_session.flush()
        return [image.id for image in images]

    def test_round_trip(self, db_session, image_ids):
        features = compute_grouping_features(map_rgb())
        assert features.phash256 is not None and features.edge is not None
        store_grouping_features(db_session, {image_ids[0]: features})
        db_session.commit()

        row = db_session.get(ImageGroupingFeatures, image_ids[0])
        assert row is not None and row.version == GROUPING_FEATURES_VERSION
        assert len(row.phash256 or b"") == PHASH256_BYTES and len(row.edge or b"") == EDGE_BYTES

        loaded = load_grouping_features(db_session, image_ids)
        assert set(loaded) == {image_ids[0]}
        got = loaded[image_ids[0]]
        assert got.phash256 == features.phash256
        assert got.edge is not None and np.array_equal(got.edge, features.edge)

    def test_failed_features_are_stored_as_nulls(self, db_session, image_ids):
        store_grouping_features(db_session, {image_ids[0]: GroupingFeatures(None, None)})
        loaded = load_grouping_features(db_session, [image_ids[0]])[image_ids[0]]
        assert (loaded.phash256, loaded.edge) == (None, None)

    def test_store_replaces_and_none_removes(self, db_session, image_ids):
        first, second = image_ids[:2]
        store_grouping_features(
            db_session,
            {first: GroupingFeatures(bytes(32), None), second: GroupingFeatures(None, None)},
        )
        replaced = GroupingFeatures(b"\xff" * 32, None)
        store_grouping_features(db_session, {first: replaced, second: None})
        loaded = load_grouping_features(db_session, image_ids)
        assert set(loaded) == {first}
        assert loaded[first].phash256 == b"\xff" * 32

    def test_rows_of_another_version_are_ignored(self, db_session, image_ids):
        store_grouping_features(db_session, {image_ids[0]: GroupingFeatures(bytes(32), None)})
        db_session.query(ImageGroupingFeatures).update({"version": GROUPING_FEATURES_VERSION + 1})
        assert load_grouping_features(db_session, image_ids) == {}

    def test_malformed_blobs_are_ignored(self, db_session, image_ids):
        store_grouping_features(db_session, {image_ids[0]: GroupingFeatures(bytes(32), None)})
        db_session.query(ImageGroupingFeatures).update({"phash256": b"short", "edge": b"\x00" * 7})
        loaded = load_grouping_features(db_session, image_ids)[image_ids[0]]
        assert (loaded.phash256, loaded.edge) == (None, None)

    def test_load_reads_in_chunks(self, db_session, image_ids):
        """Ids beyond SQLite's parameter limits are read in chunks of 500."""
        store_grouping_features(
            db_session, {i: GroupingFeatures(bytes(32), None) for i in image_ids}
        )
        loaded = load_grouping_features(db_session, [*range(10_000, 11_200), *image_ids])
        assert set(loaded) == set(image_ids)
