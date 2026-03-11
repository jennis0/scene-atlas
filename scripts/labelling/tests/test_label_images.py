"""Tests for label_images.py — UUID anonymization, mapping, resolve, and cooldown."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from scripts.labelling.label_images import (
    COOLDOWN_SECONDS,
    _enforce_cooldown,
    cmd_resolve,
    generate_image_id,
    load_mapping,
)

# ---------------------------------------------------------------------------
# generate_image_id
# ---------------------------------------------------------------------------


def test_generate_image_id_is_32_hex_chars():
    image_id = generate_image_id()
    assert len(image_id) == 32
    assert all(c in "0123456789abcdef" for c in image_id)


def test_generate_image_id_is_unique():
    ids = {generate_image_id() for _ in range(100)}
    assert len(ids) == 100


# ---------------------------------------------------------------------------
# load_mapping
# ---------------------------------------------------------------------------


def test_load_mapping_returns_dict(tmp_path: Path):
    mapping = {"abc123.jpg": "folder/image.jpg", "def456.png": "other/pic.png"}
    (tmp_path / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")

    result = load_mapping(tmp_path)
    assert result == mapping


def test_load_mapping_returns_empty_when_no_file(tmp_path: Path):
    result = load_mapping(tmp_path)
    assert result == {}


# ---------------------------------------------------------------------------
# cmd_prepare — UUID anonymization
# ---------------------------------------------------------------------------


@pytest.fixture()
def source_dir_with_images(tmp_path: Path) -> Path:
    """Create a source directory with a few small test images."""
    source = tmp_path / "source"
    source.mkdir()

    # Create a simple 10x10 image in root
    img = Image.new("RGB", (10, 10), color="red")
    img.save(source / "red.jpg")

    # Create a subfolder image
    sub = source / "subfolder"
    sub.mkdir()
    img2 = Image.new("RGBA", (10, 10), color="blue")
    img2.save(sub / "blue.png")

    return source


def test_prepare_creates_uuid_thumbnails(source_dir_with_images: Path, tmp_path: Path):
    """Verify that prepare creates UUID-named thumbnails and mapping."""
    import argparse

    from scripts.labelling.label_images import cmd_prepare

    prep_dir = tmp_path / "prep"
    args = argparse.Namespace(
        source=str(source_dir_with_images),
        prep_dir=str(prep_dir),
        sample=None,
        force=False,
    )

    result = cmd_prepare(args)
    assert result == 0

    # Check mapping.json exists
    mapping_path = prep_dir / "mapping.json"
    assert mapping_path.exists()
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert len(mapping) == 2

    # All keys should be UUID-based filenames (hex + extension)
    for thumb_name, relpath in mapping.items():
        stem = Path(thumb_name).stem
        assert len(stem) == 32
        assert all(c in "0123456789abcdef" for c in stem)
        # relpath should be the real path
        assert "/" in relpath or relpath.endswith(".jpg")

    # Check thumbnails exist with UUID names
    thumb_dir = prep_dir / "thumbnails"
    thumbnails = list(thumb_dir.iterdir())
    assert len(thumbnails) == 2
    for thumb in thumbnails:
        assert thumb.name in mapping

    # Check batch files contain UUID thumbnail names, not relpaths
    batch_dir = prep_dir / "batches"
    batch_files = list(batch_dir.glob("batch-*.txt"))
    assert len(batch_files) >= 1
    all_entries = []
    for bf in batch_files:
        entries = [
            line.strip() for line in bf.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        all_entries.extend(entries)
    assert len(all_entries) == 2
    for entry in all_entries:
        assert entry in mapping

    # Config should have anonymized flag
    config = json.loads((prep_dir / "config.json").read_text(encoding="utf-8"))
    assert config["anonymized"] is True


# ---------------------------------------------------------------------------
# cmd_resolve
# ---------------------------------------------------------------------------


def test_resolve_replaces_uuids_with_relpaths(tmp_path: Path):
    """Verify resolve correctly maps UUIDs back to real paths."""
    prep_dir = tmp_path / "prep"
    prep_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Create mapping
    mapping = {"abc123def456.jpg": "folder/castle.jpg", "789012345678.png": "scenes/forest.png"}
    (prep_dir / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")

    # Create labels with UUID-based relpaths
    labels = [
        {
            "relpath": "abc123def456.jpg",
            "type": "battlemap",
            "grid": "square",
            "description_standard": "A castle",
            "description_alt": "A fortress",
            "description_search": "castle",
            "description_terse": "a castle",
        },
        {
            "relpath": "789012345678.png",
            "type": "scene",
            "grid": "none",
            "description_standard": "A forest",
            "description_alt": "A woodland",
            "description_search": "forest",
            "description_terse": "a forest",
        },
    ]
    (run_dir / "labels.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in labels) + "\n", encoding="utf-8"
    )

    import argparse

    args = argparse.Namespace(prep_dir=str(prep_dir), run_dir=str(run_dir))
    result = cmd_resolve(args)
    assert result == 0

    # Check resolved output
    resolved_path = run_dir / "labels-resolved.jsonl"
    assert resolved_path.exists()
    resolved = [
        json.loads(line)
        for line in resolved_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(resolved) == 2
    assert resolved[0]["relpath"] == "folder/castle.jpg"
    assert resolved[1]["relpath"] == "scenes/forest.png"
    # Other fields preserved
    assert resolved[0]["type"] == "battlemap"
    assert resolved[1]["description_alt"] == "A woodland"


def test_resolve_warns_on_missing_ids(tmp_path: Path):
    """Verify resolve handles missing IDs gracefully."""
    prep_dir = tmp_path / "prep"
    prep_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    (prep_dir / "mapping.json").write_text("{}", encoding="utf-8")
    (run_dir / "labels.jsonl").write_text(
        json.dumps({"relpath": "unknown.jpg", "type": "other", "grid": "none"}) + "\n",
        encoding="utf-8",
    )

    import argparse

    args = argparse.Namespace(prep_dir=str(prep_dir), run_dir=str(run_dir))
    result = cmd_resolve(args)
    assert result == 0  # Still succeeds, just warns

    resolved = json.loads((run_dir / "labels-resolved.jsonl").read_text(encoding="utf-8").strip())
    # relpath unchanged since it wasn't in mapping
    assert resolved["relpath"] == "unknown.jpg"


# ---------------------------------------------------------------------------
# _enforce_cooldown
# ---------------------------------------------------------------------------


def test_enforce_cooldown_creates_timestamp_file(tmp_path: Path):
    """First call should create the timestamp file without sleeping."""
    with patch("scripts.labelling.label_images.time.sleep") as mock_sleep:
        _enforce_cooldown(tmp_path)

    mock_sleep.assert_not_called()
    assert (tmp_path / ".last_status_time").exists()


def test_enforce_cooldown_sleeps_when_called_too_soon(tmp_path: Path):
    """Second call within cooldown period should sleep."""
    # Write a recent timestamp
    (tmp_path / ".last_status_time").write_text(str(time.monotonic()), encoding="utf-8")

    with patch("scripts.labelling.label_images.time.sleep") as mock_sleep:
        with patch(
            "scripts.labelling.label_images.time.monotonic",
            side_effect=[time.monotonic(), time.monotonic() + COOLDOWN_SECONDS],
        ):
            _enforce_cooldown(tmp_path)

    mock_sleep.assert_called_once()
    wait_time = mock_sleep.call_args[0][0]
    assert 0 < wait_time <= COOLDOWN_SECONDS


def test_enforce_cooldown_skips_sleep_after_cooldown(tmp_path: Path):
    """Call after cooldown has elapsed should not sleep."""
    # Write an old timestamp (well past cooldown)
    old_time = time.monotonic() - COOLDOWN_SECONDS - 10
    (tmp_path / ".last_status_time").write_text(str(old_time), encoding="utf-8")

    with patch("scripts.labelling.label_images.time.sleep") as mock_sleep:
        _enforce_cooldown(tmp_path)

    mock_sleep.assert_not_called()
