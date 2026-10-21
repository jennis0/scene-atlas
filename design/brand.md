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
| `electron/loading.html` | Inline SVG between `<!-- brand-mark -->` comments (generated) |
| `assets/brand/lockup-dark.png`, `lockup-light.png` | Mark and Cinzel wordmark for the README header, swapped by GitHub's light/dark theme |
| `assets/brand/social-preview.png` | 1280×640 social preview: lockup, tagline, platforms. GitHub has no API for it: upload by hand in **Settings → General → Social preview** |
| `docs/public/social-preview.png` | The same image, as the website's `og:image` for link previews |

`electron-builder.yml` already points at `assets/icon.{ico,icns,png}`.

## In the app: themed

The icons and favicons are fixed in the Navy palette: the OS shows app icons before the app runs, and a stable favicon is easier to find among tabs. Inside the app, the mark follows the theme:

- **Web UI:** `BrandMark` (`frontend/src/components/brand/`) sits beside the wordmark in the gallery header and the setup wizard. The pages use `fill-mark-page` and the band `fill-primary`, so the mark follows palette, light/dark and contrast level: on dark themes the pages are the text colour (parchment for navy), on light themes they are the palette's dark background (navy for the default palette). It is sized in `em` so it scales with the wordmark and the text size setting, and is `aria-hidden` because the wordmark next to it carries the name.
- **Electron storage and loading windows:** these are plain HTML before React loads. The script injects the same paths as inline SVG, coloured by each page's `--mark-page` (navy on light, `--fg` on dark) and `--primary` (classes `mark-page` and `mark-band`), so they follow the OS light/dark setting like the rest of those pages.
- **Website:** the landing page (`docs/.vitepress/theme/components/Landing.vue`, at <https://jennis0.github.io/scene-atlas/>) imports `markPaths.ts` and colours it with the VitePress tokens: `--sa-mark-page` (navy on light, parchment on dark, in `custom.css`) and `--vp-c-brand-1`. The docs workflow also redeploys when `markPaths.ts` changes.

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
- Thumbnails only, with one exception: a map under a licence that isn't ShareAlike (Fantasy Atlas, 2-Minute Tabletop) may be shown at viewer size when it's the only art in the shot and the caption names the map, the creator with a link, the licence with a link, and that it's shown in Scene Atlas (CC BY's "indicate changes"). The docs' viewer and group editor shots use Fantasy Atlas's *Campfire Stories* this way (user decision 2026-10-21). Moonlight maps stay thumbnail-sized, since a large one would put the whole shot under ShareAlike. Captures are at 1x.
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

### Docs screenshots

The guide's other screenshots come from one Playwright spec, `e2e/screenshots/docs.spec.ts`, run against a demo instance. Re-run it when the UI they show changes, and before a release (releasing.md).

Everything in them is the real app on the demo library except what only the desktop app provides: `window.electronAPI` (a stand-in with made-up `C:\Users\GM\…` and `D:\Battle Maps` paths) and `POST /library/inspect` for those paths, plus `setup-status` reporting setup unfinished for the library-step shot. The stand-in and the canned responses are typed with the frontend's own types (`ElectronAPI`, `InspectResult`, `SetupStatus`), and `e2e/` is type-checked in the pre-push hook and CI, so a change to the bridge or those responses fails the check rather than the screenshot. Elements are found by role and label, as in the E2E tests, so a renamed control fails the run.

The demo library (`scripts/demo/docs_library.py`): Moonlight Maps and most of 2-Minute Tabletop imported; Fantasy Atlas copied into a linked folder, "My Maps"; two 2-Minute Tabletop packs with Tokens folders held back, which the run imports through the dialog (so the progress and report shots are real, with tokens skipped by Auto) and then undoes, so the run can be repeated. The Small model is linked in rather than downloaded.

```bash
W=/tmp/docs-demo
uv run python -m scripts.demo.docs_library layout demo_maps $W [models dir]   # a worktree passes the main checkout's data/models
cd frontend && npm run build && cd ..
APP_DATA_DIR=$W/data IMAGE_LIBRARY_DIR=$W/images LINKED_LIBRARY_DIR="$W/linked/My Maps" \
  EMBEDDING_MODEL=small CHECK_FOR_UPDATES=false \
  uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8123 --no-proxy-headers
uv run python -m scripts.demo.docs_library setup http://127.0.0.1:8123
uv run python -m scripts.demo.import_library http://127.0.0.1:8123 $W/import $W/no-paintings   # ~15 min
DEMO_URL=http://127.0.0.1:8123 DEMO_HELD=$W/held npm run docs:screenshots
```

`docs:screenshots` writes PNGs to `e2e/test-results-screenshots/png/` and converts them to `docs/public/screenshots/*.webp`; check them before committing. Each page credits the art visible in its shot under the image.

## Directions tried and rejected

Recorded so they aren't re-explored without a new reason. The brief was a mark that says "tabletop RPG maps"; every literal tabletop symbol either cluttered the mark or looked like stock clip art, so the plain book won.

- **Dice** (a d20 as a hex-grid cell, a d20 shaded with map hachures, a d6 with a battlemap top): d20s are overdone; the hex cluster was off balance.
- **At the table** (a token on a perspective grid, an old-school dungeon floor plan, a GM screen, a fog-of-war light radius): the dungeon plan was the most RPG, but too much layout for an icon; the others read as other things (sunflower, brochure).
- **On the book:** a battle grid with a token, a hex grid (hexes can't follow the page curve), Cinzel's capital A as a pop-up peak, mountains rising from or behind the book, and dotted quest routes from simple to winding. None improved on the empty book.
- **A tapered base band** echoing Cinzel's thick-thin strokes: promising, but not in the form tried.

The quest route printed in ink on the pages (broken at the gutter, bending with the page, ending at a gold X) is the closest runner-up if a larger illustrative version is ever wanted, for example a landing-page hero.
