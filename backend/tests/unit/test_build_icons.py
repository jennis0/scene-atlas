"""The icon builder: SVGs parse, the mark is centred, rasters come out at the asked size."""

import xml.etree.ElementTree as ET

import pytest

from scripts.build.build_icons import (
    FAVICON,
    ICON,
    MARK,
    _bounds,
    _placement,
    inject_inline_svg,
    mark_shapes,
    render,
    to_svg,
    to_typescript,
)

SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("layout", [MARK, ICON, FAVICON])
def test_svg_parses_with_two_pages_and_two_bands(layout):
    root = ET.fromstring(to_svg(layout))  # noqa: S314 - parses our own generated SVG, not untrusted input
    assert len(root.findall(f".//{SVG_NS}path")) == 4
    assert (root.find(f"{SVG_NS}rect") is None) == (layout.tile_inset is None)


@pytest.mark.parametrize("layout", [MARK, ICON, FAVICON])
def test_mark_is_centred_and_fits_inside_the_tile(layout):
    shapes = mark_shapes()
    scale, dx, dy = _placement(layout, shapes)
    x0, y0, x1, y1 = _bounds(shapes)
    left, top, right, bottom = x0 * scale + dx, y0 * scale + dy, x1 * scale + dx, y1 * scale + dy
    assert left + right == pytest.approx(layout.size)
    assert top + bottom == pytest.approx(layout.size)
    inset = layout.tile_inset or 0
    assert left > inset and top > inset
    assert right < layout.size - inset and bottom < layout.size - inset


def test_pages_mirror_across_the_spine():
    left_page, right_page = mark_shapes()[2:]
    for (lx, ly), (rx, ry) in zip(left_page.polygon, right_page.polygon, strict=True):
        assert lx + rx == pytest.approx(512)
        assert ly == pytest.approx(ry)


@pytest.mark.parametrize("px", [16, 256])
def test_render_size_and_transparent_corners(px):
    img = render(FAVICON, px)
    assert img.size == (px, px)
    # the full-bleed tile has rounded corners, so the very corner pixel is transparent
    alpha = img.getpixel((0, 0))
    assert isinstance(alpha, tuple) and alpha[3] < 64


def test_typescript_has_the_tight_viewbox_and_two_of_each_path():
    ts = to_typescript()
    assert "export const MARK_VIEWBOX = '52 " in ts
    bands = ts.split("MARK_BANDS = [")[1].split("]")[0]
    pages = ts.split("MARK_PAGES = [")[1].split("]")[0]
    assert bands.count("'M") == 2
    assert pages.count("'M") == 2


def test_inject_replaces_the_marked_block_and_is_repeatable(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<h1><!-- brand-mark -->old<!-- /brand-mark -->Scene Atlas</h1>")
    inject_inline_svg(page)
    once = page.read_text()
    inject_inline_svg(page)
    assert page.read_text() == once
    assert "old" not in once
    assert once.count('class="mark-band"') == 2
    assert once.count('class="mark-page"') == 2


@pytest.mark.parametrize(
    "html", ["<h1>Scene Atlas</h1>", "<!-- brand-mark --><!-- /brand-mark -->" * 2]
)
def test_inject_refuses_a_page_without_exactly_one_block(tmp_path, html):
    page = tmp_path / "page.html"
    page.write_text(html)
    with pytest.raises(SystemExit):
        inject_inline_svg(page)
