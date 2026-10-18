"""Build the Scene Atlas mark, app icons and favicons from one set of geometry.

The mark is an open book: two curved pages over a gold base band. The geometry below is
the single source of truth; this script writes the SVGs and every raster from it.

Usage:
    uv run python scripts/build/build_icons.py

Writes:
    assets/brand/mark.svg      the mark alone, transparent background
    assets/brand/icon.svg      the app icon: mark on a navy tile with the macOS margin
    assets/brand/favicon.svg   the small-size icon: mark on a full-bleed navy tile
    assets/icon.png            1024 px app icon (Linux; electron-builder)
    assets/icon.icns           macOS app icon
    assets/icon.ico            Windows app icon, 16-256 px, from the full-bleed tile
    frontend/public/favicon.svg, docs/public/favicon.svg
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]

NAVY = "#0e1118"
PARCHMENT = "#ede8dc"
GOLD = "#dda43c"

Point = tuple[float, float]

# Left page, in a 512 box. The top edge rises from the outer corner and dips into the
# spine; the bottom edge is the same curve moved down, so both bend the same way.
OUTER_TOP: Point = (52.0, 140.1)
CTRL_1: Point = (112.0, 114.9)
CTRL_2: Point = (210.0, 123.3)
SPINE_TOP: Point = (251.0, 177.9)  # the pages stop 5 px short of the spine: the gutter
PAGE_DEPTH = 206.0
BAND_GAP = 14.0  # gap between the pages and the gold base band
BAND_DEPTH = 32.0
CURVE_SAMPLES = 64


@dataclass(frozen=True)
class Shape:
    fill: str
    svg_path: str
    polygon: list[Point]


def _bezier(t: float, p0: Point, p1: Point, p2: Point, p3: Point) -> Point:
    u = 1 - t
    x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
    return (x, y)


def _top_edge(drop: float) -> list[Point]:
    """The page's top curve moved down by `drop`, sampled from the outer edge to the spine."""
    return [
        (x, y + drop)
        for x, y in (
            _bezier(i / CURVE_SAMPLES, OUTER_TOP, CTRL_1, CTRL_2, SPINE_TOP)
            for i in range(CURVE_SAMPLES + 1)
        )
    ]


def _curve_cmd(drop: float, reverse: bool) -> str:
    """SVG cubic for the top curve moved down by `drop`, in either direction."""
    p = [OUTER_TOP, CTRL_1, CTRL_2, SPINE_TOP]
    p = [(x, y + drop) for x, y in p]
    if reverse:
        p = p[::-1]
    return f"M{_fmt(p[0])} C{_fmt(p[1])} {_fmt(p[2])} {_fmt(p[3])}"


def _band_cmds(top: float, bottom: float) -> str:
    """Closed band between two copies of the curve: along the top, back along the bottom."""
    a = _curve_cmd(top, reverse=False)
    b = _curve_cmd(bottom, reverse=True)
    return f"{a} L{b[1:]} Z"


def _fmt(p: Point) -> str:
    return f"{p[0]:.1f},{p[1]:.1f}"


def _mirror(points: list[Point]) -> list[Point]:
    return [(512 - x, y) for x, y in points]


def _mirror_path(path: str) -> str:
    """Mirror an SVG path made only of absolute x,y pairs across the spine."""
    out = []
    for token in path.split(" "):
        cmd = token[0] if token[0].isalpha() else ""
        body = token[len(cmd) :]
        if "," in body:
            x, y = body.split(",")
            body = f"{512 - float(x):.1f},{y}"
        out.append(cmd + body)
    return " ".join(out)


def mark_shapes() -> list[Shape]:
    """The mark as filled shapes, back to front, in a 512 box."""
    page_poly = _top_edge(0) + _top_edge(PAGE_DEPTH)[::-1]
    page_path = _band_cmds(0, PAGE_DEPTH)
    band_top = PAGE_DEPTH + BAND_GAP
    band_poly = _top_edge(band_top) + _top_edge(band_top + BAND_DEPTH)[::-1]
    band_path = _band_cmds(band_top, band_top + BAND_DEPTH)
    return [
        Shape(GOLD, band_path, band_poly),
        Shape(GOLD, _mirror_path(band_path), _mirror(band_poly)),
        Shape(PARCHMENT, page_path, page_poly),
        Shape(PARCHMENT, _mirror_path(page_path), _mirror(page_poly)),
    ]


def _bounds(shapes: list[Shape]) -> tuple[float, float, float, float]:
    xs = [x for s in shapes for x, _ in s.polygon]
    ys = [y for s in shapes for _, y in s.polygon]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class Layout:
    """A square canvas with an optional rounded navy tile and the mark fitted inside it."""

    size: float
    tile_inset: float | None  # None: no tile (transparent)
    tile_radius: float
    mark_width: float  # as a fraction of the canvas


# macOS app icon grid: an 824 px tile with a 100 px margin on a 1024 canvas
ICON = Layout(size=1024, tile_inset=100, tile_radius=185, mark_width=0.6)
FAVICON = Layout(size=512, tile_inset=0, tile_radius=96, mark_width=0.82)
MARK = Layout(size=512, tile_inset=None, tile_radius=0, mark_width=0.92)


def _placement(layout: Layout, shapes: list[Shape]) -> tuple[float, float, float]:
    """Scale and offset that centre the mark on the canvas at the layout's width."""
    x0, y0, x1, y1 = _bounds(shapes)
    scale = layout.size * layout.mark_width / (x1 - x0)
    dx = layout.size / 2 - (x0 + x1) / 2 * scale
    dy = layout.size / 2 - (y0 + y1) / 2 * scale
    return scale, dx, dy


def to_svg(layout: Layout) -> str:
    shapes = mark_shapes()
    scale, dx, dy = _placement(layout, shapes)
    size = f"{layout.size:g}"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">']
    if layout.tile_inset is not None:
        inset = layout.tile_inset
        side = layout.size - 2 * inset
        parts.append(
            f'<rect x="{inset:g}" y="{inset:g}" width="{side:g}" height="{side:g}" '
            f'rx="{layout.tile_radius:g}" fill="{NAVY}"/>'
        )
    parts.append(f'<g transform="translate({dx:.2f} {dy:.2f}) scale({scale:.4f})">')
    parts += [f'<path d="{s.svg_path}" fill="{s.fill}"/>' for s in shapes]
    parts.append("</g></svg>\n")
    return "".join(parts)


def render(layout: Layout, px: int, supersample: int = 8) -> Image.Image:
    """Rasterise a layout at `px` pixels, drawing large and scaling down for smooth edges."""
    big = px * supersample
    k = big / layout.size
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if layout.tile_inset is not None:
        a = layout.tile_inset * k
        b = big - a
        draw.rounded_rectangle((a, a, b, b), radius=layout.tile_radius * k, fill=NAVY)
    shapes = mark_shapes()
    scale, dx, dy = _placement(layout, shapes)
    for s in shapes:
        pts = [((x * scale + dx) * k, (y * scale + dy) * k) for x, y in s.polygon]
        draw.polygon(pts, fill=s.fill)
    return img.resize((px, px), Image.Resampling.LANCZOS)


ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    brand = ROOT / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    favicon = to_svg(FAVICON)
    (brand / "mark.svg").write_text(to_svg(MARK))
    (brand / "icon.svg").write_text(to_svg(ICON))
    (brand / "favicon.svg").write_text(favicon)
    for target in (ROOT / "frontend" / "public", ROOT / "docs" / "public"):
        target.mkdir(parents=True, exist_ok=True)
        (target / "favicon.svg").write_text(favicon)

    icon = render(ICON, 1024)
    icon.save(ROOT / "assets" / "icon.png")
    icon.save(ROOT / "assets" / "icon.icns")
    # Windows shows icons small and without the macOS margin, so use the full-bleed tile
    ico = [render(FAVICON, s) for s in ICO_SIZES]
    ico[-1].save(
        ROOT / "assets" / "icon.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=ico[:-1],
    )
    print(f"Wrote icons to {brand.relative_to(ROOT)} and assets/")


if __name__ == "__main__":
    main()
