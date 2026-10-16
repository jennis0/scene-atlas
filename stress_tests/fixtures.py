"""Synthetic fixtures for the stress tests.

Everything here is generated: random-noise images, zips of them, and
deliberately corrupt files. Never point the stress tests at real maps (they are
commercial content, and the tests must be reproducible on any machine).

Generators are deterministic per seed, so the same seed always produces the
same bytes and therefore the same SHA-256. That matters: the pipeline skips
files whose bytes (or decoded pixels) are already in the library, so callers
must use distinct seed ranges whenever they want distinct images.
"""

from __future__ import annotations

import io
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# In-memory image generation (used by most scenarios)
# ---------------------------------------------------------------------------


def noise_pixels(seed: int, width: int, height: int, channels: int = 3) -> np.ndarray:
    """Deterministic random pixels for ``seed``."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, channels), dtype=np.uint8)


def noise_jpeg(seed: int, width: int = 96, height: int = 72) -> bytes:
    """A random-noise JPEG whose bytes and pixels are unique per seed."""
    img = PILImage.fromarray(noise_pixels(seed, width, height), "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70 + (seed % 25))
    return buf.getvalue()


def noise_png(seed: int, width: int = 96, height: int = 72, compress_level: int = 6) -> bytes:
    """A random-noise PNG. The same seed at different compression levels gives
    different bytes but identical pixels (exercises the pixel-hash tier)."""
    img = PILImage.fromarray(noise_pixels(seed, width, height), "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=compress_level)
    return buf.getvalue()


def image_set(
    count: int,
    base_seed: int,
    *,
    folder: str = "StressAuthor/StressMap",
    width: int = 96,
    height: int = 72,
) -> list[tuple[str, bytes]]:
    """``count`` unique ``(relative_path, bytes)`` JPEGs under one folder (one group)."""
    return [
        (f"{folder}/image_{i:05d}.jpg", noise_jpeg(base_seed + i, width, height))
        for i in range(count)
    ]


def zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# On-disk fixtures (larger or slower to build; cached between runs)
# ---------------------------------------------------------------------------


@dataclass
class FixturePaths:
    """Paths to the cached on-disk fixtures."""

    zip_small: Path  # 10 images
    zip_large: Path  # 100 images (1000 with --large)
    zip_near_bomb: Path  # declared uncompressed size beyond the archive limit

    # Valid magic bytes, corrupt body
    malformed_jpeg: Path
    malformed_png: Path
    malformed_webp: Path
    malformed_mp4: Path
    malformed_webm: Path
    malformed_zip: Path

    # Large but valid images (for concurrent big uploads)
    big_jpegs: list[Path]

    # Real videos (None without ffmpeg)
    video_mp4: Path | None
    video_webm: Path | None

    large_mode: bool
    has_ffmpeg: bool


def _random_bytes(seed: int, size: int) -> bytes:
    return np.random.default_rng(seed).integers(0, 256, size=size, dtype=np.uint8).tobytes()


def generate_near_zip_bomb(output_path: Path) -> Path:
    """800 × 3 MB of zeros: ~2.4 GB declared, ~2.5 MB on disk.

    The archive guard sums the declared uncompressed sizes before extracting,
    so this must become one failed ``archive`` item without writing 2.4 GB.
    """
    zero_block = b"\x00" * (3 * 1024 * 1024)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(800):
            zf.writestr(f"file_{i:04d}.jpg", zero_block)
    return output_path


def _malformed(kind: str, size: int) -> bytes:
    """Correct magic bytes for ``kind`` followed by random garbage."""
    seed = {"jpg": 42, "png": 43, "webp": 44, "mp4": 45, "webm": 46, "zip": 47}[kind]
    if kind == "jpg":
        header = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10]) + b"JFIF\x00\x01"
    elif kind == "png":
        ihdr = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
        header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00" * 4
    elif kind == "webp":
        header = b"RIFF" + struct.pack("<I", max(4, size - 8)) + b"WEBPVP8 "
    elif kind == "mp4":
        header = struct.pack(">I", 28) + b"ftypisom" + struct.pack(">I", 0x200) + b"isomiso2mp41"
    elif kind == "webm":
        header = bytes([0x1A, 0x45, 0xDF, 0xA3])
    else:
        header = b"PK\x03\x04"
    return header + _random_bytes(seed, max(0, size - len(header)))


def _ffmpeg_video(output_path: Path, codec_args: list[str], seconds: int, size: str) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size={size}:rate=30",
        *codec_args,
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode(errors='replace')}")


def ensure_fixtures(fixtures_dir: Path, large_mode: bool, has_ffmpeg: bool) -> FixturePaths:
    """Generate any missing fixtures (cached by file name; delete the dir to rebuild)."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    def missing(p: Path, min_bytes: int = 1) -> bool:
        return not p.exists() or p.stat().st_size < min_bytes

    def write(p: Path, data: bytes) -> None:
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)

    zip_small = fixtures_dir / "small_10.zip"
    if missing(zip_small):
        print(f"    Generating {zip_small.name}...")
        write(zip_small, zip_bytes(image_set(10, 10_000, folder="ZipAuthor/Small Pack")))

    large_count = 1000 if large_mode else 100
    zip_large = fixtures_dir / f"large_{large_count}.zip"
    if missing(zip_large):
        print(f"    Generating {zip_large.name}...")
        write(
            zip_large,
            zip_bytes(image_set(large_count, 20_000, folder="ZipAuthor/Large Pack")),
        )

    zip_near_bomb = fixtures_dir / "near_bomb.zip"
    if missing(zip_near_bomb):
        print(f"    Generating {zip_near_bomb.name}...")
        generate_near_zip_bomb(zip_near_bomb)

    malformed_mb = 200 if large_mode else 5
    malformed: dict[str, Path] = {}
    for kind in ("jpg", "png", "webp", "mp4", "webm", "zip"):
        path = fixtures_dir / f"malformed_{malformed_mb}mb.{kind}"
        if missing(path, int(malformed_mb * 1024 * 1024 * 0.9)):
            print(f"    Generating {path.name}...")
            write(path, _malformed(kind, malformed_mb * 1024 * 1024))
        malformed[kind] = path

    # Big valid images: noise JPEGs compress poorly, so ~3 bytes/px at q95.
    big_side = 12_000 if large_mode else 4_000
    big_jpegs: list[Path] = []
    for i in range(4):
        path = fixtures_dir / f"big_{big_side}px_{i}.jpg"
        if missing(path):
            print(f"    Generating {path.name}...")
            img = PILImage.fromarray(noise_pixels(30_000 + i, big_side, big_side), "RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            write(path, buf.getvalue())
        big_jpegs.append(path)

    video_mp4 = video_webm = None
    if has_ffmpeg:
        seconds, size = (30, "1920x1080") if large_mode else (1, "640x360")
        video_mp4 = fixtures_dir / f"video_{size}_{seconds}s.mp4"
        if missing(video_mp4):
            print(f"    Generating {video_mp4.name}...")
            _ffmpeg_video(video_mp4, ["-c:v", "libx264", "-preset", "ultrafast"], seconds, size)
        video_webm = fixtures_dir / f"video_{size}_{seconds}s.webm"
        if missing(video_webm):
            print(f"    Generating {video_webm.name}...")
            _ffmpeg_video(
                video_webm, ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "63"], seconds, size
            )

    total_mb = sum(p.stat().st_size for p in fixtures_dir.rglob("*") if p.is_file()) >> 20
    print(f"    Fixtures total: ~{total_mb} MB in {fixtures_dir}")

    return FixturePaths(
        zip_small=zip_small,
        zip_large=zip_large,
        zip_near_bomb=zip_near_bomb,
        malformed_jpeg=malformed["jpg"],
        malformed_png=malformed["png"],
        malformed_webp=malformed["webp"],
        malformed_mp4=malformed["mp4"],
        malformed_webm=malformed["webm"],
        malformed_zip=malformed["zip"],
        big_jpegs=big_jpegs,
        video_mp4=video_mp4,
        video_webm=video_webm,
        large_mode=large_mode,
        has_ffmpeg=has_ffmpeg,
    )
