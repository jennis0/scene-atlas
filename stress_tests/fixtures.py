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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image as PILImage


def _noise_image(seed: int, width: int, height: int, **save_args) -> bytes:
    pixels = np.random.default_rng(seed).integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    buf = io.BytesIO()
    PILImage.fromarray(pixels, "RGB").save(buf, **save_args)
    return buf.getvalue()


def noise_jpeg(seed: int, width: int = 96, height: int = 72, quality: int | None = None) -> bytes:
    """A random-noise JPEG whose bytes and pixels are unique per seed."""
    q = quality if quality is not None else 70 + seed % 25
    return _noise_image(seed, width, height, format="JPEG", quality=q)


def noise_png(seed: int, width: int = 96, height: int = 72, compress_level: int = 6) -> bytes:
    """Same seed at different compression levels: different bytes, identical pixels."""
    return _noise_image(seed, width, height, format="PNG", compress_level=compress_level)


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


@dataclass
class FixturePaths:
    zip_small: Path  # 10 images
    zip_large: Path  # large_zip_count images
    large_zip_count: int
    zip_near_bomb: Path  # declared uncompressed size beyond the archive limit

    # Valid magic bytes, corrupt body
    malformed_jpeg: Path
    malformed_png: Path
    malformed_webp: Path
    malformed_mp4: Path
    malformed_webm: Path
    malformed_zip: Path

    big_jpegs: list[Path]
    video_mp4: Path | None  # None without ffmpeg
    video_webm: Path | None
    large_mode: bool


def _random_bytes(seed: int, size: int) -> bytes:
    return np.random.default_rng(seed).integers(0, 256, size=size, dtype=np.uint8).tobytes()


def _near_zip_bomb() -> bytes:
    """800 × 3 MB of zeros: ~2.4 GB declared, ~2.5 MB compressed.

    The archive guard sums the declared uncompressed sizes before extracting,
    so this must become one failed ``archive`` item without writing 2.4 GB.
    """
    zero_block = b"\x00" * (3 * 1024 * 1024)
    return zip_bytes([(f"file_{i:04d}.jpg", zero_block) for i in range(800)])


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

    def cached(name: str, build: Callable[[], bytes], min_bytes: int = 1) -> Path:
        path = fixtures_dir / name
        if not path.exists() or path.stat().st_size < min_bytes:
            print(f"    Generating {name}...")
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(build())
            tmp.replace(path)
        return path

    large_count = 1000 if large_mode else 100
    zip_small = cached(
        "small_10.zip", lambda: zip_bytes(image_set(10, 10_000, folder="ZipAuthor/Small Pack"))
    )
    zip_large = cached(
        f"large_{large_count}.zip",
        lambda: zip_bytes(image_set(large_count, 20_000, folder="ZipAuthor/Large Pack")),
    )
    zip_near_bomb = cached("near_bomb.zip", _near_zip_bomb)

    malformed_mb = 200 if large_mode else 5
    size = malformed_mb * 1024 * 1024
    malformed = {
        kind: cached(
            f"malformed_{malformed_mb}mb.{kind}",
            lambda k=kind: _malformed(k, size),
            int(size * 0.9),
        )
        for kind in ("jpg", "png", "webp", "mp4", "webm", "zip")
    }

    big_side = 12_000 if large_mode else 4_000
    big_jpegs = [
        cached(
            f"big_{big_side}px_{i}.jpg",
            lambda i=i: noise_jpeg(30_000 + i, big_side, big_side, quality=90),
        )
        for i in range(4)
    ]

    video_mp4 = video_webm = None
    if has_ffmpeg:
        seconds, dims = (30, "1920x1080") if large_mode else (1, "640x360")
        video_mp4 = fixtures_dir / f"video_{dims}_{seconds}s.mp4"
        video_webm = fixtures_dir / f"video_{dims}_{seconds}s.webm"
        for path, codec in (
            (video_mp4, ["-c:v", "libx264", "-preset", "ultrafast"]),
            (video_webm, ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "63"]),
        ):
            if not path.exists():
                print(f"    Generating {path.name}...")
                _ffmpeg_video(path, codec, seconds, dims)

    total_mb = sum(p.stat().st_size for p in fixtures_dir.rglob("*") if p.is_file()) >> 20
    print(f"    Fixtures total: ~{total_mb} MB in {fixtures_dir}")

    return FixturePaths(
        zip_small=zip_small,
        zip_large=zip_large,
        large_zip_count=large_count,
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
    )
