"""Synthetic test fixture generation for stress tests.

All generators use deterministic seeds for reproducibility — the same seed
always produces the same bytes, which means the same SHA-256 hash.  This is
critical because the pipeline's /check-hashes deduplication will silently
skip re-uploads of identical files; each concurrent import must use a
distinct seed range to avoid false deduplication.
"""

from __future__ import annotations

import random
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover
    PILImage = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# FixturePaths — returned by ensure_fixtures, passed to scenario functions
# ---------------------------------------------------------------------------


@dataclass
class FixturePaths:
    """Paths to all generated fixtures."""

    # Single sample images (used where one file is enough)
    jpeg_small: Path
    png_small: Path
    webp_small: Path

    # ZIP archives
    zip_small: Path  # ~10 images
    zip_large: Path  # 100 images default, 1000 with --large
    zip_near_bomb: Path  # triggers check_zip_safety() uncompressed-size guard

    # Malformed files (valid magic bytes, corrupted body)
    malformed_jpeg: Path
    malformed_png: Path
    malformed_webp: Path
    malformed_mp4: Path
    malformed_webm: Path
    malformed_zip: Path

    # Video fixtures (None when ffmpeg is absent)
    video_mp4: Path | None
    video_webm: Path | None

    # Mode flags — forwarded so scenarios can skip gracefully
    large_mode: bool
    has_ffmpeg: bool


# ---------------------------------------------------------------------------
# Individual fixture generators
# ---------------------------------------------------------------------------


def generate_random_noise_jpeg(path: Path, seed: int, width: int = 640, height: int = 480) -> Path:
    """Random RGB noise JPEG — unique SHA-256 per seed."""
    assert PILImage is not None, "Pillow is required"
    rng = random.Random(seed)
    data = bytes(rng.randint(0, 255) for _ in range(width * height * 3))
    img = PILImage.frombytes("RGB", (width, height), data)
    quality = 70 + (seed % 25)  # 70–94, deterministic
    img.save(path, format="JPEG", quality=quality)
    return path


def generate_random_noise_png(path: Path, seed: int, width: int = 640, height: int = 480) -> Path:
    """Random RGBA noise PNG — unique SHA-256 per seed."""
    assert PILImage is not None, "Pillow is required"
    rng = random.Random(seed)
    data = bytes(rng.randint(0, 255) for _ in range(width * height * 4))
    img = PILImage.frombytes("RGBA", (width, height), data)
    img.save(path, format="PNG")
    return path


def generate_random_noise_webp(path: Path, seed: int, width: int = 640, height: int = 480) -> Path:
    """Random RGB noise WebP (lossy) — unique SHA-256 per seed."""
    assert PILImage is not None, "Pillow is required"
    rng = random.Random(seed)
    data = bytes(rng.randint(0, 255) for _ in range(width * height * 3))
    img = PILImage.frombytes("RGB", (width, height), data)
    quality = 70 + (seed % 25)
    img.save(path, format="WebP", quality=quality)
    return path


def generate_zip(images: list[Path], output_path: Path) -> Path:
    """Pack image files into a ZIP using DEFLATE compression.

    Random-noise JPEGs are already entropy-coded so ZIP compression ratio
    will be near 1.0 — exactly what we want for realistic testing.
    """
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for img_path in images:
            zf.write(img_path, arcname=f"StressAuthor/StressMap/{img_path.name}")
    return output_path


def generate_near_zip_bomb(output_path: Path) -> Path:
    """ZIP that triggers check_zip_safety()'s uncompressed-size guard.

    Technique: 800 entries of 3 MB zeros each, stored with DEFLATE.
    - Uncompressed size metadata: 800 × 3 MB = 2 400 MB  →  exceeds 2 048 MB limit
    - Actual ZIP size: ~800 × 2 KB  ≈  1.6 MB (zeros compress extremely well)

    The check_zip_safety() function sums e.file_size (uncompressed sizes
    from the central directory) BEFORE any extraction, so this will be
    rejected cleanly with a 413 before any bytes are written to disk.
    """
    zero_block = b"\x00" * (3 * 1024 * 1024)  # 3 MB of zeros
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(800):
            zf.writestr(f"file_{i:04d}.dat", zero_block)
    return output_path


def generate_malformed_jpeg(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid JFIF header (FFD8 FFE0 …) + random garbage body."""
    rng = random.Random(42)
    # Minimal JFIF marker + APP0 header
    header = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01])
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(header))))
    output_path.write_bytes(header + body)
    return output_path


def generate_malformed_png(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid PNG signature + IHDR chunk + corrupted data."""
    rng = random.Random(43)
    png_sig = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    # IHDR: length=13, type, width=100, height=100, bit_depth=8, color_type=2 (RGB)
    ihdr_data = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", 0)
    header = png_sig + ihdr_chunk
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(header))))
    output_path.write_bytes(header + body)
    return output_path


def generate_malformed_webp(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid RIFF/WEBP header + corrupted VP8 data."""
    rng = random.Random(44)
    riff_size = max(4, size_bytes - 8)
    header = b"RIFF" + struct.pack("<I", riff_size) + b"WEBP"
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(header))))
    output_path.write_bytes(header + body)
    return output_path


def generate_malformed_mp4(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid ftyp box + corrupted moov/mdat data."""
    rng = random.Random(45)
    # ftyp box: size=28, type='ftyp', major_brand='isom', minor=0x200, compat brands
    ftyp = struct.pack(">I", 28) + b"ftyp" + b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41"
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(ftyp))))
    output_path.write_bytes(ftyp + body)
    return output_path


def generate_malformed_webm(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid EBML header (1A 45 DF A3) + corrupted data."""
    rng = random.Random(46)
    header = bytes([0x1A, 0x45, 0xDF, 0xA3])
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(header))))
    output_path.write_bytes(header + body)
    return output_path


def generate_malformed_zip(output_path: Path, size_bytes: int = 5 * 1024 * 1024) -> Path:
    """Valid ZIP local file header signature (PK\\x03\\x04) + corrupted entries."""
    rng = random.Random(47)
    header = bytes([0x50, 0x4B, 0x03, 0x04])  # Local file header signature
    body = bytes(rng.randint(0, 255) for _ in range(max(0, size_bytes - len(header))))
    output_path.write_bytes(header + body)
    return output_path


def generate_video_mp4(
    output_path: Path, duration_seconds: int = 1, resolution: str = "720p"
) -> Path:
    """Generate MP4 with color bars using ffmpeg (H.264)."""
    width, height = (1920, 1080) if resolution == "1080p" else (1280, 720)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_seconds}:size={width}x{height}:rate=30",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "51",  # Lowest quality = smallest file
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg MP4 generation failed: {result.stderr.decode(errors='replace')}"
        )
    return output_path


def generate_video_webm(
    output_path: Path, duration_seconds: int = 1, resolution: str = "720p"
) -> Path:
    """Generate WebM with color bars using ffmpeg (VP9)."""
    width, height = (1920, 1080) if resolution == "1080p" else (1280, 720)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_seconds}:size={width}x{height}:rate=30",
        "-c:v",
        "libvpx-vp9",
        "-b:v",
        "0",
        "-crf",
        "63",  # Low quality = small file
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg WebM generation failed: {result.stderr.decode(errors='replace')}"
        )
    return output_path


# ---------------------------------------------------------------------------
# ensure_fixtures — idempotent, cache on disk
# ---------------------------------------------------------------------------


def _make_zip_images(
    fixtures_dir: Path, count: int, seed_base: int, size: tuple[int, int] = (320, 240)
) -> list[Path]:
    """Generate `count` JPEGs into a _zip_imgs subdir, return their paths."""
    img_dir = fixtures_dir / "_zip_imgs"
    img_dir.mkdir(exist_ok=True)
    paths: list[Path] = []
    for i in range(count):
        p = img_dir / f"img_{seed_base + i:06d}.jpg"
        if not p.exists():
            generate_random_noise_jpeg(p, seed=seed_base + i, width=size[0], height=size[1])
        paths.append(p)
    return paths


def ensure_fixtures(fixtures_dir: Path, large_mode: bool, has_ffmpeg: bool) -> FixturePaths:
    """Generate all fixtures if they don't already exist.  Returns FixturePaths.

    Uses simple "if file exists, skip" caching — no manifest.  Delete the
    .fixtures/ directory to force regeneration.
    """
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    malformed_mb = 500 if large_mode else 5
    malformed_size = malformed_mb * 1024 * 1024

    def _needs_regen(p: Path, min_bytes: int = 1) -> bool:
        """Return True if the fixture file is missing or suspiciously small (partial write)."""
        return not p.exists() or p.stat().st_size < min_bytes

    # --- Single sample images -----------------------------------------------
    jpeg_small = fixtures_dir / "sample.jpg"
    if _needs_regen(jpeg_small):
        print(f"    Generating {jpeg_small.name}...")
        generate_random_noise_jpeg(jpeg_small, seed=0)

    png_small = fixtures_dir / "sample.png"
    if _needs_regen(png_small):
        print(f"    Generating {png_small.name}...")
        generate_random_noise_png(png_small, seed=1)

    webp_small = fixtures_dir / "sample.webp"
    if _needs_regen(webp_small):
        print(f"    Generating {webp_small.name}...")
        generate_random_noise_webp(webp_small, seed=2)

    # --- ZIP archives --------------------------------------------------------
    zip_small = fixtures_dir / "small.zip"
    if _needs_regen(zip_small):
        print(f"    Generating {zip_small.name} (10 images)...")
        imgs = _make_zip_images(fixtures_dir, 10, seed_base=100)
        generate_zip(imgs, zip_small)

    large_count = 1000 if large_mode else 100
    zip_large = fixtures_dir / f"large_{large_count}.zip"
    if _needs_regen(zip_large):
        print(f"    Generating {zip_large.name} ({large_count} images)...")
        imgs = _make_zip_images(fixtures_dir, large_count, seed_base=200)
        generate_zip(imgs, zip_large)

    zip_near_bomb = fixtures_dir / "near_bomb.zip"
    if _needs_regen(zip_near_bomb):
        print(f"    Generating {zip_near_bomb.name} (near-zip-bomb, ~1.6 MB compressed)...")
        generate_near_zip_bomb(zip_near_bomb)

    # --- Malformed files -----------------------------------------------------
    for fmt, gen_fn in [
        ("jpg", generate_malformed_jpeg),
        ("png", generate_malformed_png),
        ("webp", generate_malformed_webp),
        ("mp4", generate_malformed_mp4),
        ("webm", generate_malformed_webm),
        ("zip", generate_malformed_zip),
    ]:
        path = fixtures_dir / f"malformed_{malformed_mb}mb.{fmt}"
        # Regenerate if missing or truncated (e.g. interrupted write)
        if not path.exists() or path.stat().st_size < malformed_size * 0.9:
            print(f"    Generating {path.name} ({malformed_mb} MB)...")
            gen_fn(path, malformed_size)  # type: ignore[call-arg]

    malformed_jpeg = fixtures_dir / f"malformed_{malformed_mb}mb.jpg"
    malformed_png = fixtures_dir / f"malformed_{malformed_mb}mb.png"
    malformed_webp = fixtures_dir / f"malformed_{malformed_mb}mb.webp"
    malformed_mp4 = fixtures_dir / f"malformed_{malformed_mb}mb.mp4"
    malformed_webm = fixtures_dir / f"malformed_{malformed_mb}mb.webm"
    malformed_zip = fixtures_dir / f"malformed_{malformed_mb}mb.zip"

    # --- Video fixtures (optional) ------------------------------------------
    video_mp4: Path | None = None
    video_webm: Path | None = None
    if has_ffmpeg:
        resolution = "1080p" if large_mode else "720p"
        duration = 60 if large_mode else 1
        video_mp4 = fixtures_dir / f"video_{resolution}_{duration}s.mp4"
        if not video_mp4.exists():
            print(f"    Generating {video_mp4.name}...")
            generate_video_mp4(video_mp4, duration, resolution)
        video_webm = fixtures_dir / f"video_{resolution}_{duration}s.webm"
        if not video_webm.exists():
            print(f"    Generating {video_webm.name}...")
            generate_video_webm(video_webm, duration, resolution)

    total_mb = sum(p.stat().st_size for p in fixtures_dir.rglob("*") if p.is_file()) // (
        1024 * 1024
    )
    print(f"    Fixtures total: ~{total_mb} MB in {fixtures_dir}")

    return FixturePaths(
        jpeg_small=jpeg_small,
        png_small=png_small,
        webp_small=webp_small,
        zip_small=zip_small,
        zip_large=zip_large,
        zip_near_bomb=zip_near_bomb,
        malformed_jpeg=malformed_jpeg,
        malformed_png=malformed_png,
        malformed_webp=malformed_webp,
        malformed_mp4=malformed_mp4,
        malformed_webm=malformed_webm,
        malformed_zip=malformed_zip,
        video_mp4=video_mp4,
        video_webm=video_webm,
        large_mode=large_mode,
        has_ffmpeg=has_ffmpeg,
    )
