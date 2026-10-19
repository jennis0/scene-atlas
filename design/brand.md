# Brand: the mark and app icons

**Decided:** 2026-10-19

## The mark

An open book: two curved parchment pages over a gold base band, on navy. It stands for the atlas in the name and pairs with the Cinzel wordmark ([visual-language.md](visual-language.md#typography)) without competing with it.

Construction, in a 512 box (see `scripts/build/build_icons.py`, the single source of truth):

- **Pages.** Each page's top edge rises from the outer corner and dips into the spine. The bottom edge is the same curve moved down, so both edges bend the same way and anything printed on a page can follow it (`y = top(x) + offset`). The curve depth is 70% of the first draft; flatter pages start to read as two cards at 16 px.
- **Gutter.** The pages stop 5 px short of the spine on each side.
- **Base band.** An even 32 px band, 14 px below the pages, following the same curve. It splits at the spine.
- **Colours.** Parchment `#ede8dc` and gold `#dda43c` on navy `#0e1118`: the Navy palette's foreground, accent and background. The gaps are real transparency, so the mark works on any background and in one colour.

Why the curves matter: an earlier draft drew the pages as flat panels meeting in a V, which reads just as easily as a tent or roof seen from below. Curved page edges are what make it read as an open book.

## Files

| File | Use |
|---|---|
| `assets/brand/mark.svg` | The mark alone, transparent background (README header, landing page, docs) |
| `assets/brand/icon.svg` | App icon: the mark on a navy rounded tile, on the macOS 824-in-1024 grid |
| `assets/brand/favicon.svg` | Small sizes: the mark on a full-bleed navy tile |
| `assets/icon.png`, `assets/icon.icns` | Linux and macOS app icons (1024 px), from `icon.svg` |
| `assets/icon.ico` | Windows app icon, 16–256 px, from the full-bleed tile (Windows shows icons small and without the macOS margin) |
| `frontend/public/favicon.svg`, `docs/public/favicon.svg` | Web UI and docs site favicons; the docs nav bar also uses it as its logo |
| `frontend/src/components/brand/markPaths.ts` | The mark's paths for `BrandMark` (generated) |
| `electron/setup.html`, `electron/loading.html` | Inline SVG between `<!-- brand-mark -->` comments (generated) |
| `assets/brand/lockup-dark.png`, `lockup-light.png` | Mark and Cinzel wordmark for the README header, swapped by GitHub's light/dark theme |
| `assets/brand/social-preview.png` | 1280×640 social preview: lockup, tagline, platforms. GitHub has no API for it: upload by hand in **Settings → General → Social preview** |

`electron-builder.yml` already points at `assets/icon.{ico,icns,png}`.

## In the app: themed

The icons and favicons are fixed in the Navy palette: the OS shows app icons before the app runs, and a stable favicon is easier to find among tabs. Inside the app, the mark follows the theme:

- **Web UI:** `BrandMark` (`frontend/src/components/brand/`) sits beside the wordmark in the gallery header and the setup wizard. The pages use `fill-foreground` and the band `fill-primary`, so the mark follows palette, light/dark and contrast level: parchment pages on dark themes, ink pages on light ones. It is sized in `em` so it scales with the wordmark and the text size setting, and is `aria-hidden` because the wordmark next to it carries the name.
- **Electron storage and loading windows:** these are plain HTML before React loads. The script injects the same paths as inline SVG, coloured by each page's `--fg` and `--primary` (classes `mark-page` and `mark-band`), so they follow the OS light/dark setting like the rest of those pages.

## Rebuilding

Change the geometry or colours in `scripts/build/build_icons.py`, then run:

```bash
uv run python scripts/build/build_icons.py
```

It rewrites every file above except the PNG lockups and social preview, which need the Cinzel and Figtree fonts and are built by a second script:

```bash
uv run python -m scripts.build.build_brand_images
```

Commit the outputs; nothing generates them at build time.

## Screenshots

The README screenshot (`docs/public/screenshots/search.webp`, dark and light themes split along a diagonal) is a search for "woodland path at night" in the grouped Maps view: maps from all three creators come up led by their night-time variants, which shows search by content and variant groups in one image. "snowy mountain pass" (all Moonlight) is the most striking alternative.

**Rules for the art in screenshots:**

- Only openly licensed art, credited under the screenshot for whatever is visible in it: Moonlight Maps (CC BY-NC-SA 4.0: their licence covers all their works, paid ones included, for non-commercial use), Fantasy Atlas's free maps (CC BY-NC 4.0) and 2-Minute Tabletop's free maps (CC BY-NC 4.0, credit "Map by 2-Minute Tabletop"). Because Moonlight's licence is ShareAlike, the screenshot is shared under CC BY-NC-SA 4.0. The non-commercial licences hold only while Scene Atlas and its promotion stay free.
- Thumbnails only: no screenshot shows an individual map at full size, so no screenshot works as a copy of a map. Captures are at 1x.
- Never commit the maps themselves.

Other creators' terms, checked 2026-10-19, are in the project's research notes. In short: Elven Tower's Creative Commons Collection is CC BY 4.0 and Manea Roliste's packs are CC BY-NC 4.0, both usable. Czepeku, Neutral Party, Domille, Venatus and Seafoot need permission. Forgotten Adventures is personal use only. Tom Cartos's open licence has an AI clause that needs his confirmation first.

**Regenerating:** put the maps in `demo_maps/`, with any zips unzipped into one folder each (gitignored locally; layout in `scripts/demo/import_library.py`), then:

```bash
uv run python -m scripts.demo.download_paintings /tmp/paintings     # CC0 scenes, optional
APP_DATA_DIR=/tmp/demo/data IMAGE_LIBRARY_DIR=/tmp/demo/images \
  uv run uvicorn backend.app.main:app --port 8123                   # a clean instance
# set it up: POST /api/v1/models/medium/download, PUT /api/v1/tags/packs {"packs": ["common", "fantasy"]},
# POST /api/v1/models/setup-complete, then restart so the model loads
uv run python -m scripts.demo.import_library http://127.0.0.1:8123 demo_maps /tmp/paintings
node scripts/demo/screenshots.mjs http://127.0.0.1:8123 /tmp/shots
uv run python -m scripts.demo.split_screenshot /tmp/shots/search-dark.png /tmp/shots/search-light.png \
  docs/public/screenshots/search.webp
```

## Directions tried and rejected

Recorded so they aren't re-explored without a new reason. The brief was a mark that says "tabletop RPG maps"; every literal tabletop symbol either cluttered the mark or looked like stock clip art, so the plain book won.

- **Dice** (a d20 as a hex-grid cell, a d20 shaded with map hachures, a d6 with a battlemap top): d20s are overdone; the hex cluster was off balance.
- **At the table** (a token on a perspective grid, an old-school dungeon floor plan, a GM screen, a fog-of-war light radius): the dungeon plan was the most RPG, but too much layout for an icon; the others read as other things (sunflower, brochure).
- **On the book:** a battle grid with a token, a hex grid (hexes can't follow the page curve), Cinzel's capital A as a pop-up peak, mountains rising from or behind the book, and dotted quest routes from simple to winding. None improved on the empty book.
- **A tapered base band** echoing Cinzel's thick-thin strokes: promising, but not in the form tried.

The quest route printed in ink on the pages (broken at the gutter, bending with the page, ending at a gold X) is the closest runner-up if a larger illustrative version is ever wanted, for example a landing-page hero.
