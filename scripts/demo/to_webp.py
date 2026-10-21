"""Convert the docs screenshot PNGs (e2e/screenshots) to WebP for docs/public/screenshots.

Usage:
    uv run python -m scripts.demo.to_webp e2e/test-results-screenshots/png docs/public/screenshots
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    pngs = sorted(src.glob("*.png"))
    if not pngs:
        sys.exit(f"No screenshots in {src}")
    for png in pngs:
        out = dest / f"{png.stem}.webp"
        Image.open(png).convert("RGB").save(out, "WEBP", quality=88, method=6)
        print(f"{out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
