# Visual Language & Component Design

A comprehensive reference for the Scene Atlas UI. All new components must conform to these principles. When in doubt, follow existing patterns rather than introduce new ones.

---

## Aesthetic Direction

**Theme:** Cartographic / archival, carried by the maps themselves rather than by ornament. Surfaces are quiet so the art leads; character comes from type (a book serif for names, the Cinzel wordmark) and a single accent colour.

**Palettes.** Five, each with light and dark mode, chosen in the Library dialog's Appearance tab and stored per device (`scene-atlas-palette` in localStorage, applied as `data-palette` on `<html>` before first paint; navy, the default, sets no attribute):
- **Navy & gold** (default): deep navy and warm parchment, gold accent. Base tokens in `:root` / `.dark`.
- **Ink & verdigris**: green-black ink and pale paper, aged-copper green accent.
- **Slate & lapis**: near-neutral cool grey stone, cobalt accent (hue 214: lapis's own ~224 read as periwinkle).
- **Walnut & sienna**: oiled-wood browns and sand, burnt-sienna accent. Overrides `--destructive` to crimson so it stays distinct from the orange-red accent.
- **Nightshade & amethyst**: dusky plum greys, muted violet accent.

Every palette is a pair of blocks in `index.css`: `[data-palette='x']` (light) and `.dark[data-palette='x'], .dark [data-palette='x']` (dark). The selectors match any element, not only `<html>`, so the Appearance palette picker (`components/settings/PalettePicker.tsx`) renders each option's preview in that palette's real tokens. No colour values are duplicated. Rules for a new palette:
- Add the two blocks, the two high-contrast blocks (see Contrast below), an entry in `PALETTES` (`lib/palette.ts`), and one in the accessibility spec's `VARIANTS`.
- The dark block must set every token the light block sets. The light block also matches `<html>` in dark mode, so anything left out leaks a light value into dark. The same holds for the high-contrast pair.
- **Fill vs ink.** Accent and status colours come in pairs: a fill (`--primary`, `--destructive`, `--success`, `--warning`) for backgrounds, tints, buttons and outlines, and an ink (`--primary-ink`, `--destructive-ink`, `--success-ink`, `--warning-ink`) for text and icons. `text-primary`, `text-destructive`, `text-success` and `text-warning` resolve to the inks (`textColor` in `tailwind.config.js`). In dark mode keep fills saturated and lighten only the inks as far as text needs: one light value for both makes fills pastel, and text on its own tint drags its tint lighter.
- Keep accent hues away from the destructive red (hue 0), or override `--destructive` as sienna does.
- `lib/paletteContrast.test.ts` parses `index.css` and, per palette, mode and contrast level, enforces text contrast for every ink on every surface and on its own tint up to /20, labels on filled buttons, and the focus ring. It rounds colours to 8 bits as browsers render them, so it agrees with axe to the decimal. It runs as a unit test, ahead of the e2e axe scan.

**Contrast (Standard / High).** Appearance → Contrast: Auto (default; follows the system's `prefers-contrast: more`), Standard, High. Stored as `scene-atlas-contrast`; the effective result is `data-contrast="high"` on `<html>` (`lib/contrast.ts`), and components can style it with the `hc:` Tailwind variant. It works with every palette, so nobody trades their palette for legibility.

| | Standard (WCAG AA) | High (WCAG AAA text) |
|---|---|---|
| Text, every ink, every surface and own tint | ≥ 4.5:1 | ≥ 7:1 |
| Labels on filled accent buttons | ≥ 4.5:1 | ≥ 7:1 |
| Control outlines (`--input`) | not guaranteed | ≥ 3:1 (1.4.11) |
| Dividers (`--border`) | — | ≥ 2:1 |
| Names on images, over a pure-white map | ≥ 4.5:1 | ≥ 7:1, full white with a shadow |
| Tag chips (on chip and bare) | ≥ 4.5:1 | ≥ 7:1 |
| Focus ring | ≥ 3:1, 2px | ≥ 3:1, 3px |

How High is built, so it still looks like the same app:
- **Tokens:** per palette and mode, the high-contrast blocks move only lightness (hue and saturation kept), and only as far as each check needs. The values were computed against the tests, not picked by eye; if you retune a palette, nudge lightness until `paletteContrast.test.ts` passes rather than replacing hues.
- **Text dimmed with opacity** (`text-foreground/80`, `text-primary/70`, …) gets an `hc:` full-strength twin at the same site. Disabled states stay dim (WCAG exempts them). New dimmed text should do the same.
- **Tag chips** keep their tint; High swaps the text to the least extreme shade of that hue that reaches 7:1 everywhere (`HIGH_CONTRAST_SHADE` in `components/import/tagColors.ts`) and adds a solid outline. Dark mode mostly keeps its standard shade; light mode needs the deep ones. The classes are built at runtime, so they're safelisted in `tailwind.config.js`; `tagContrast.test.ts` checks the safelist matches the hues. Other categorical badges (hardware CPU/GPU/Any) use the tag hues via `useHueColor()` and inherit all of this.
- **Status colours** are tokens (`success`, `warning`, plus `destructive`), never raw Tailwind colours, so High can lift them.
- **Captions on images** use `.caption-scrim` / `.caption-band` (`index.css`), whose darkness behind the text is a known minimum (`--scrim-text`, `--band`), checked over pure white by `lib/captionContrast.test.ts`.
- **Axe:** `e2e/tests/accessibility.spec.ts` scans every palette × theme × contrast level; High also runs axe's AAA `color-contrast-enhanced` rule.

Not covered yet: reflow at 400% zoom (1.4.10), text-spacing overrides (1.4.12), and Windows forced-colors mode.

**NOT:** decorative ornament — glowing stripes, fading underline rules, dot-grid backgrounds, header washes, blur on surfaces that don't overlap anything, hover zoom on artwork, tiny uppercase letter-spaced labels. These were removed in the 2026-10 refresh because they read as generic generated UI and competed with the maps.

### Core Adjectives
- Precise and measured (tight spacing, clean alignment)
- Warm but serious (amber over blue, parchment over white)
- Informational density done tastefully (show more, never clutter)

---

## Design Tokens

All values sourced from CSS custom properties defined in `frontend/src/index.css`. **Never use raw hex/rgb/hsl values** — always use `hsl(var(--token))` or Tailwind token classes. For opacity variants, use `hsl(var(--token) / 0.N)`.

**Theme switching:** Light mode values are in `:root`, dark mode values in `.dark`. The `dark` class on `<html>` activates dark mode (Tailwind `darkMode: ["class"]`). Default theme is dark; toggled via `ThemeContext` (stored in localStorage as `scene-atlas-theme`).

### Surface Hierarchy — Dark Mode (darkest → lightest)
| Token | Approx. hex | Role |
|-------|-------------|------|
| `--surface-canvas` | `#0b0e14` | ImageViewer deep canvas bg |
| `--background` | `#0e1118` | Page base |
| `--popover` | `#12171f` | Dropdowns, popovers, panel headers/footers |
| `--card` | `#161c28` | Card surfaces, panel backgrounds |
| `--muted` | `#181f2e` | Muted/recessed surfaces, hover backgrounds |
| `--secondary` | `#1c2231` | Inputs, hover states, raised elements |

### Surface Hierarchy — Light Mode (warm parchment)
| Token | Approx. hex | Role |
|-------|-------------|------|
| `--secondary` | `#e5ddd0` | Subtle warm recessed surface |
| `--muted` | `#ece6dc` | Muted surfaces |
| `--surface-canvas` | `#ece5db` | ImageViewer canvas bg |
| `--background` | `#f3ede5` | Warm parchment base |
| `--card` | `#f8f5f0` | Card surfaces (slightly lighter than bg) |
| `--popover` | `#faf7f3` | Lightest surface for floating layers |

### Accent / Semantic
| Token | Approx. hex | Role |
|-------|-------------|------|
| `--primary` | `#dda43c` | Amber gold — active states, focus rings, decorative accents |
| `--primary-foreground` | near-black | Text on amber backgrounds |
| `--destructive` | `#e04e4e` | Destructive actions, excluded filter chips |
| `--border` | `#222a38` | Dividers — use `/50` or `/30` for very subtle |
| `--ring` | same as primary | Focus ring colour |

### Text
| Token | Role |
|-------|------|
| `text-foreground` | `#ede8dc` warm parchment — primary body text |
| `text-muted-foreground` | dimmed parchment — secondary text, labels |
| `text-white/85` or brighter | for text overlaid directly on images (on the bottom scrim) |

Never fade text with an opacity modifier (`text-muted-foreground/60`, `opacity-50`): `muted-foreground` is already the lowest-contrast text that passes AA. See [Accessibility](#accessibility).

---

## Typography

Three font families, used in distinct roles. **Never mix roles.**

| Family | Tailwind class | Role |
|--------|---------------|------|
| **Newsreader** (book serif) | `font-display` | Map/group names, viewer and dialog titles. Real lowercase, readable at any size. |
| **Cinzel** (capitals serif) | `font-wordmark` | The "Scene Atlas" wordmark only. |
| **Figtree** (geometric sans) | `font-sans` (default) | All body text, labels, controls, metadata. |
| **JetBrains Mono** | `font-mono` | Filenames, UUIDs, dimensions, file sizes. `text-3xs` usually. |

### Size Scale in Practice
- Wordmark: `font-wordmark text-2xl font-medium tracking-wide` (GalleryHeader)
- Viewer heading (image name): `font-display text-2xl font-semibold`
- Card name: `text-xs font-medium` (gradient overlay) or `text-sm font-semibold`
- Metadata / labels: `text-2xs` or `text-xs text-muted-foreground`
- Micro badges / counts: `text-3xs`
- Section labels: `.section-label` utility — `text-xs font-medium text-muted-foreground`, sentence case

### Text size setting and rem-only sizing
The Appearance tab offers Small / Default / Large / Larger, set as `data-text-size` on `<html>` (`lib/textSize.ts`), which changes the root font size: 16, 17 (default), 19, 21px, as percentages so a larger browser default still scales up. Everything in rem follows: text, spacing, icons, and the panels that hold text. Images and thumbnails keep their size, so the gallery's density is unchanged, unlike browser zoom.

That only works if sizes are in rem, so:
- **No pixel font sizes.** Use the scale: `text-3xs` (11px at default), `text-2xs` (11.5px), then Tailwind's `text-xs` (12.75px), `text-sm`, `text-base`. The two small steps are CSS variables (`--text-3xs`, `--text-2xs` in `index.css`) with no line height, so they inherit one as the old pixel sizes did.
- **The floor rises faster than the root.** Large and Larger lift the two small steps more than everything else: small text is at least 12.5px at Large and 14px at Larger, and never below 10.5px at Small. `lib/textScale.test.ts` enforces these floors.
- **200% zoom is a tested guarantee** (WCAG 1.4.4). `e2e/tests/zoom.spec.ts` runs at 960×480 (200% zoom on 1080p) with Larger text: no horizontal scroll, header controls on screen, and every dialog's controls reachable. Dialogs cap at the window height and scroll their body; use `max-h-[calc(100dvh-1rem)]` plus a `min-h-0` scrolling body rather than a fixed height alone.
- **Containers that hold text are sized in rem** (dialogs, the viewer's side panel, pickers, sidebars): px ÷ 17, e.g. the Library dialog is `max-w-[28.24rem]` (480px at default). Keep pixels only for things sized to images or the screen: thumbnails, the viewer stage (`max-w-[1600px]`), the gallery page width (`max-w-[1400px]`).
- Check new dense UI at **Larger** as well as Default.

### Short windows and the compact header
Browser zoom and the text size setting both cut how many lines of text fit vertically. `lib/compactLayout.ts` measures the window height **in rem** (a media query sees only px, so it misses the text size setting) and sets `data-short` on `<html>` below 44rem (~750px at default text).
- **Image viewer:** on short windows the details panel scrolls together with the group's scenes instead of pinning the details above them. The toolbar stays pinned and the Scenes bar is sticky. Styled with the `short:` Tailwind variant (`tailwind.config.js`). This is automatic, with no setting: it's a fallback that keeps the group reachable, not a preference.
- **Gallery header:** compact is two rows instead of four. The type tabs join the wordmark row, and the count/sort/size/Edit all controls join the search row (wrapping if the width runs out). It's a preference: Appearance → Compact header, **Auto** (default: follows `data-short`) / **On** / **Off**, saved as `scene-atlas-compact-header` and set as `data-compact-header`. Components read it with `useCompactHeader()`.

---

## Amber Accent — Rules of Use

Amber (`primary`) is the single accent colour. It draws the eye, so it must be used intentionally and sparingly.

| Use | Pattern |
|-----|---------|
| Active/selected states | `bg-primary/10 text-primary border border-primary/40` |
| Focus | The global `:focus-visible` outline in `index.css` — components don't set their own |
| Hover on interactive text | `hover:text-primary` |
| The one primary action (Import) | `Button` default variant (`bg-primary text-primary-foreground`) — every other button is secondary, outline or ghost |

The accent is never decoration: no stripes, glows or underline rules.

---

## Interaction States

Applied consistently across all interactive elements:

### Buttons and clickable items
| State | Classes |
|-------|---------|
| Default (muted) | `text-muted-foreground` |
| Hover | `hover:text-foreground hover:bg-secondary` |
| Active / selected | `bg-primary/10 text-primary border border-primary/40` |
| Disabled | `opacity-30 cursor-not-allowed` (not `disabled:` if using native button disabled) |
| Destructive hover | `hover:text-destructive hover:bg-destructive/10` |

### Inputs and text fields

Use the `<Input>` component from `ui/input.tsx` which supports CVA variants:

| Variant | Height | Size | Used for |
|---------|--------|------|----------|
| `default` | h-10 | text-sm | Gallery search, forms |
| `compact` | h-[30px] | text-xs | Filter search, panel inputs |
| `sm` | h-6 | text-xs | Scene search, grid W×H inputs |

Shared base: `bg-secondary border-border rounded-md` (focus comes from the global outline)

```tsx
<Input inputSize="compact" placeholder="Search filters…" />
```

For inline editing (no box, just underline): `bg-transparent border-b border-primary/70 focus:outline-none`

### Number inputs — always hide native spinners
```
[appearance:textfield]
[&::-webkit-outer-spin-button]:appearance-none
[&::-webkit-inner-spin-button]:appearance-none
```

### Count badges

Two tiers:

| Tier | Classes | Used for |
|------|---------|----------|
| **Solid** (button overlays) | `h-4 min-w-4 px-1 rounded-full bg-primary text-3xs font-bold text-primary-foreground flex items-center justify-center tabular-nums` | Gallery filter button, ImageViewer filter badge |
| **Tinted** (inline context) | `px-1.5 py-px rounded-full bg-primary/15 text-3xs font-medium text-primary tabular-nums` | Tab counts, "N active" badges |

### Close buttons

Standard close button (used in dialogs and panels):
```tsx
<button className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
  <X className="h-3.5 w-3.5" />
  <span className="sr-only">Close</span>
</button>
```

### Create / add buttons (standalone)

Ghost text only — no border, no background. Subtle default, brightens on hover:
```tsx
<button className="flex items-center gap-1.5 text-2xs text-muted-foreground/70 hover:text-muted-foreground transition-colors">
  <Plus className="h-[11px] w-[11px]" />
  New category
</button>
```

Use for standalone "add to list" actions (new category, add tag value, etc.). The `+ Tag` dashed pill in TagPicker is a different pattern — it's an inline popover trigger in a tag flow.

### Color swatch pickers

Circles (`rounded-full`), 26×26px in an 8-col grid with 6px gap. No default ring — let the color speak. Selected: `outline: 2px solid hsl(var(--foreground))` with `outlineOffset: 3` (3px prevents overlap with neighbors at current gap). Unselected: `opacity-70 hover:opacity-100 hover:scale-110`.

### Icon grid pickers

32×32px cells in an 8-col grid, 2px gap. Selected: `bg-secondary text-foreground` + `outline: 2px solid hsl(var(--foreground) / 0.5)` with `outlineOffset: 1`. Unselected: `text-muted-foreground hover:text-foreground hover:bg-secondary`. Icons at 17×17px inside cells.

When an element has both icon and color pickers, combine them into a single **appearance popover** — one trigger button (icon in category color, `bg-secondary/60` background), opening a single `PopoverContent` with icon grid on top, `h-px bg-border/50` divider, color grid below.

### Conditional action buttons

For actions that only become relevant when state changes (e.g. "Regenerate" after vocabulary edits), use ghost text by default and highlight only when dirty:
- **Clean state:** `text-muted-foreground hover:text-foreground`, transparent border
- **Dirty state:** `text-primary`, `bg-primary/12`, `border-primary/35`

### Icon strokeWidth

All Lucide icons use the **default strokeWidth (2)**. Never override to 1.5 — it creates visual inconsistency with other components.

---

## Tag / Category Colour System

Tags are coloured by category. The colour replaces any need for a text category label. Defined in `frontend/src/components/import/tagColors.ts`.

### Colour pattern (theme-aware)

Each palette entry has both dark and light variants. The `useGetTagColor()` hook automatically selects the correct variant based on the current theme.

**Dark mode:**
```typescript
{ bg: 'bg-{colour}-400/10', text: 'text-{colour}-300', border: 'border-{colour}-400/30', dot: 'bg-{colour}-400' }
```

**Light mode:**
```typescript
{ bg: 'bg-{colour}-50', text: 'text-{colour}-700', border: 'border-{colour}-200', dot: 'bg-{colour}-400' }
```

The colour identity (hue) stays the same — red is always red, teal is always teal. Only the shade shifts to suit the background. The `dot` colour is theme-independent since solid dots work on both backgrounds.

### Assigned categories
| Category | Colour family |
|----------|--------------|
| lighting | amber |
| season | orange |
| weather | sky |
| environment | emerald |
| features | stone |
| state | red |
| theme | purple |
| population | cyan |
| perspective | violet |
| style | rose |
| (unknown) | zinc |

### Tag pill rendering
Show **capitalised value only** — the colour already encodes the category:
```tsx
<span className={`inline-flex items-center gap-1 text-2xs rounded-full border px-2 py-px ${colors.bg} ${colors.text} ${colors.border}`}
  title={tag.category}>
  <span className="capitalize">{tag.value}</span>
</span>
```
Add `title={tag.category}` on the outer element for discoverability on hover.

---

## Card Pattern

All image cards (`GroupCard`, `SceneTile`) share a **gradient overlay** structure — NO separate metadata bar below the image.

```
┌─────────────────────────┐
│                         │
│      Image area         │ ← object-cover, lazy loaded
│      (thumbnail)        │
│                         │
│ ░░░░░░░░░░░░░░░░░░░░░   │ ← gradient overlay: from-black/85 via-black/55 to-transparent
│  Group                   │ ← font-display text-sm font-semibold text-white, wraps to 2 lines
│  Subgroup · Variant      │ ← font-display text-xs text-white/85, wraps to 2 lines
│  Author                  │ ← text-2xs text-white/85 (sans)
└─────────────────────────┘
```

**Overlay gradient:** `bg-gradient-to-t from-black/85 via-black/55 to-transparent pt-10 pb-2.5 px-3`

**Hover:** nothing moves — the card gains a border tint and shadow only. The thumbnail sits on a `transparency-backdrop` checkerboard so transparent images (stored as RGBA WebP thumbnails) read as transparent rather than black.

**Gallery tile caption (`SceneTile` in `ImageGrid`):** three lines, set like the viewer — the group in the serif at semibold, then `{subgroup} · {image name}` in the serif at regular weight (each only when present and distinct), then the author in the sans. Names wrap (up to two lines each) rather than truncating. Standalone images show their name, then the author.

**Tile size:** the individual view has a size slider (small-grid icon · `range` slider · large-grid icon) in the results row, 160–360px in 40px steps (`TILE_WIDTH`, `useTileSize`, remembered per device).

**Border on cards:**
- Default: `border border-border/30`
- Hover: `hover:border-primary/40 hover:shadow-xl hover:shadow-black/40`
- Active / selected (SceneTile): `border-primary/60 ring-2 ring-primary/70 shadow-lg shadow-primary/15`

---

## Gallery Page Structure

### Header
```
[Title (font-display)]                    [Import button] [Toggle segmented control]
─────────────────── amber rule ──────────────────────────────────────────────────────
```

**Amber rule:** `h-px bg-gradient-to-r from-primary/70 via-primary/30 to-transparent`

**Segmented view toggle:** Native `<button>` elements inside a shared `div.flex.rounded-md.overflow-hidden.border.border-border`:
```tsx
<div className="flex rounded-md overflow-hidden border border-border">
  <button className={`h-10 w-10 flex items-center justify-center border-r border-border transition-colors ${
    active ? 'bg-secondary text-foreground' : 'text-foreground/50 hover:text-foreground hover:bg-secondary/50'
  }`}>
```

### Filter panel
Filter chips use `bg-primary/10 border border-primary/40 text-primary` for active state. Clear-all uses plain `text-muted-foreground`.

---

## FilterMenuContent Component

Shared two-column filter panel used in GalleryFilterPanel (full-page sidebar) and ImageViewer (variant filter popover).

### Structure
- Left 112px: scrollable category nav with coloured dot indicators
- Right: `flex-1` pill grid, wraps, with search bar at top

### Active states
| State | Classes |
|-------|---------|
| Include (active) | `bg-primary/10 border border-primary/40 text-primary` |
| Exclude (active) | `bg-destructive/10 border border-destructive/30 text-destructive` |
| Category nav active | Uses category's `colors.bg colors.text colors.border` (left border stripe) |

### Truncation — mandatory for all label text
Filter chips (active filter rows below search inputs): `max-w-[130px] truncate` with `title={filter.label}` on outer element.
Option pills (inside popover): `max-w-[160px] truncate` with `title={label}` on outer element.

### Filter button states (for variant filter trigger in ImageViewer)
```tsx
hasActiveFilters     → 'bg-primary/10 text-primary border border-primary/40'
hasFilterableData    → 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
no filterable data   → 'text-muted-foreground/25 border border-transparent cursor-not-allowed'
```
**Always render the button** — never hide it just because there's nothing to filter. Grey it out instead. This maintains layout stability and teaches the user what feature is present.

---

## ImageViewer Layout

Full-screen overlay with fixed image canvas + structured sidebar:

```
┌──────────────────────────────────────────────────────────────────────┐
├──────────────────────────────────┬───────────────────────────────────┤
│                                  │  [Edit group]            [✕]      │  ← controls row
│         Image canvas             ├───────────────────────────────────┤
│         plain canvas             │  Map Name (font-display, xl)      │  ← fixed info section
│                                  │  by Author                        │    (shrink-0, border-b)
│                                  │  Variant  [current value] [✎] [✕] │
│                                  │  [Grid][Gridless][?]  W × H       │
│    [◀]                   [▶]    │  ● ● ● ●  1920×1080 · 4.2MB      │
│                                  │  [tag] [tag] [+ Tag]              │
│                                  ├───────────────────────────────────┤
│                                  │  Variants (23)  [search] [⧉]    │  ← sticky within scroll area
│                                  ├───────────────────────────────────┤
│                                  │  [tile] [tile]  ← scrollable      │
│                                  │  [tile] [tile]                    │
│                                  │  [tile] [tile]                    │
└──────────────────────────────────┴───────────────────────────────────┘
```

### Key layout rules
- Container: `max-width: 1600px; height: 88vh` — fixed size, image fits within canvas
- Canvas: `flex-1 relative`, `min-w-0` (allows flex shrink)
- Canvas background: plain `hsl(var(--surface-canvas))`
- Grid overlay: when the image has a detected square grid, a "Grid W×H" toggle (bottom-left of the canvas, also the `G` key, remembered per device) draws `GridOverlay` — an SVG sized to the image's rendered box with one line per detected column/row, dark under light so it shows on any map
- Sidebar: `w-[440px] shrink-0 flex flex-col` — **does not grow or shrink**

### Sidebar sections (top to bottom)
1. Controls row: `shrink-0` — edit group link (left), close × (right)
2. **Image info**: `shrink-0 border-b border-border/30 px-4 pb-4` — **fixed, never scrolls away**
3. **Variants**: `flex-1 min-h-0 overflow-y-auto` — only this section scrolls

### Inline editing pattern (name field)
```tsx
// Display mode — group hover reveals pencil icon
<div className="group/name flex items-start gap-2">
  <h2 className="cursor-text" onClick={() => setEditing(true)}>{value}</h2>
  <button className="opacity-0 group-hover/name:opacity-60 hover:!opacity-100 transition-opacity">
    <Pencil className="h-3.5 w-3.5" />
  </button>
</div>

// Edit mode — underline input, Enter/Escape/blur to save/cancel
<input className="bg-transparent border-b border-primary/70 focus:outline-none" onBlur={save} />
```

### Subgroup field
Displayed as a labeled property row, **not** a tag pill. Uses inline editing:
```tsx
<div className="group/sv flex items-center gap-2 mb-2 min-w-0">
  <span className="section-label w-[72px] shrink-0">Subgroup</span>
  {/* editing: underline input with datalist suggestions from sibling scenes */}
  {/* display: current value text (or italic "none"), hover reveals ✎ and ✕ */}
</div>
```
The datalist is populated from `existingSubgroups` — unique non-null `subgroup` values across the loaded image group.

### Grid toggle pattern (GridToggle component)
Segmented button group: `[Grid | Gridless | ?]` — saves immediately on click via `patchMutation`. When `gridded === true`, shows W × H number inputs inline (spinners hidden, saves on blur/Enter).

### Scene scroll preservation
When navigating to a scene within the same group (sidebar click), sidebar scroll position must be maintained. Implementation:
- Set `preserveStateRef.current = true` **before** calling `onImageChange`
- In the `useEffect([image.id])`, guard with `lastProcessedIdRef.current === image.id` to prevent React Strict Mode double-invocation from consuming the flag prematurely
- Only `scrollContainerRef` (the scenes section) is reset to 0; image info state is always reset on cross-group navigation

---

## Shared Interactive Components

### TagPicker (`frontend/src/components/import/TagPicker.tsx`)
Two-level dropdown: category → value. Used in both import flow and ImageViewer.

Trigger: `border-dashed border-border/50 text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary/50`
Dropdown: `bg-card border-border shadow-2xl shadow-black/40 rounded-xl`
Category dot: `color.dot` (solid), not `color.bg` (tinted)

### GridToggle (`frontend/src/components/import/GridToggle.tsx`)
Three-option segmented control: Grid / Gridless / ?

Active: `bg-primary/20 text-primary`
Inactive: `text-muted-foreground hover:text-foreground hover:bg-secondary/50`
Container: `inline-flex rounded-md overflow-hidden border border-border`

### ActivityDock (`frontend/src/components/ActivityDock.tsx`)
Floating bottom-right card for imports (from the ImportManager) and background jobs.
**Collapsed pill:** `bg-card/95 backdrop-blur-sm border border-border/40 rounded-full shadow-lg shadow-black/40`. Hover: `bg-secondary hover:-translate-y-px`. Shows Loader2 (spinning) when active, PauseCircle when imports are system-paused, WifiOff when offline, Package when idle. Active count badge uses the solid tier.
**Expanded card:** `w-[320px] max-h-[min(520px,65vh)] bg-card rounded-xl border border-border/30 shadow-2xl shadow-black/60`. Header follows the panel header pattern (`PanelTitle`). A tinted amber notice row explains a system pause, with "Try again".
**Import rows (`components/imports/ImportJobRow.tsx`):** `rounded-md border-border/30 bg-secondary/20 hover:bg-secondary/40`. Finished: `opacity-80 hover:opacity-100`. Progress: 3px track. Status text stays muted; failures are signalled by the icon, not by colouring the whole line. Hover reveals Pause/Resume, or Undo import (confirmed) and Dismiss (no confirm: dismiss never deletes) once finished.
**Visibility:** Hidden when no jobs exist. No auto-expand — user clicks pill to open.

### Import ledger (`components/imports/GroupLedger.tsx`)
The import's groups as ruled rows. Virtualised: a folder can plan thousands of groups. Clickable rows (groups with imported images) extend 8px into the gutter and use `hover:bg-muted/30`. Two variants:
- **progress** (import dialog, and the report while still running): rows fill in as images land. Group name `font-display text-sm`, author `text-2xs`, counts `font-mono text-2xs tabular-nums` in the margin (`done/total`, failed in `text-destructive`), one hairline progress bar per row (`bg-primary/80` while open, `/35` finished). 48px rows.
- **report** (the import dialog's finished view): 44px rows, ruled `border-border/40`. A 40×30 cover thumbnail (`cover_image_id` from the job detail, on the transparency backdrop), group name `font-display text-sm`, author only when the groups' authors differ (otherwise it's in the dialog's status line), then on the right only the exceptions worth reading — `N failed` (destructive), `N already in library`, `added to an existing group` — and `N images`. No progress bar.

### Import notices (`components/imports/ImportFrame.tsx`)
One-line notices inside import dialogs: `rounded-lg border px-3 py-2.5`, attention `border-primary/25 bg-primary/[0.06]` (amber icon), problem `border-destructive/30 bg-destructive/[0.07]` (red icon). Actions go on a row beneath the text, never squeezed beside it.

---

## Component-Level Rules

### Borders and separators

**Structural frame borders** (header/footer edges, sidebar/content splits, panel outlines): `border-border` at full opacity is fine — these define the skeleton.

**Content dividers** (within a section or list):
- Between major content sections: `border-border/30`
- Between items in a dense list: `border-border/40` to `border-border/50`
- Very subtle internal structure: `border-border/20`
- Never use `border-border` at full opacity for content-area dividers

### Scrollbars
Styled globally in index.css: 5px wide, `bg-border` thumb, transparent track. Do not override per-component.

### Shadows
- Elevation for floating panels/modals: `shadow-2xl shadow-black/70`
- Dropdowns: `shadow-2xl shadow-black/40`
- Card hover: `shadow-lg shadow-primary/15` (amber tinted)

### Popovers
Use Radix `<Popover>` with `<PopoverContent className="p-0 ...">` — do not add internal padding at the content level, let child components define their own spacing.

### Confirm overlays

Inline confirmation (displayed over parent container, not a separate dialog):
```tsx
<div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-sm">
  <div className="bg-card border border-border rounded-xl p-5 max-w-sm mx-4 shadow-2xl shadow-black/70">
    {/* AlertTriangle icon (text-primary) + title + detail */}
    {/* Cancel (ghost) + Confirm (tinted: primary for warning, destructive for danger) */}
  </div>
</div>
```

Confirm button styles:
- Warning: `text-primary bg-primary/10 hover:bg-primary/20 border-primary/20`
- Danger: `text-destructive bg-destructive/10 hover:bg-destructive/20 border-destructive/20`

### Z-index conventions
- Sticky variant header inside scroll container: `z-10`
- ImageViewer overlay: `z-50`
- Tag picker / subgroup picker dropdowns: `z-50`

---

## Dense Editing Lists (Ledger Style)

For management dialogs with editable lists (tag values, vocabulary entries), use the ledger row pattern:

```tsx
<div className={`group/valrow flex items-stretch border-b border-border/40 transition-colors last:border-b-0 ${
  isEditing ? 'bg-muted/50' : 'hover:bg-muted/30'
}`}>
  {/* Content area — click to enter edit mode */}
  <div className="flex-1 min-w-0 py-[7px] px-[10px] cursor-text" onClick={...}>
    <span className={`text-xs font-medium capitalize ${colors.text}`}>{value}</span>
    <button className="text-2xs text-muted-foreground italic ...">aliases or "No aliases"</button>
  </div>
  {/* Margin column — count + actions */}
  <div className="w-[54px] shrink-0 flex items-center justify-end gap-1 px-2">
    <Pencil /> <span className="tabular-nums">{count}</span> <Trash2 />
  </div>
</div>
```

Key rules:
- `group/valrow` on the entire row — hover effects are row-level, not per-element
- Ruled lines: `border-b border-border/40`, remove on last row
- Editing state: `bg-muted/50` replaces hover bg
- Pencil appears in margin on row hover: `opacity-0 group-hover/valrow:opacity-50`

### Blur-safe inline editing

When click-to-edit rows contain their own click handler, use a cooldown ref to prevent blur → click re-entry:

```tsx
const editEndedAt = useRef(0)
// On blur/escape/done: editEndedAt.current = Date.now()
// On row click: if (Date.now() - editEndedAt.current > 150) setEditMode('name')
```

This prevents the row click from immediately re-opening the editor when the user clicks outside the input to dismiss it.

---

## Accessibility

Target: WCAG 2.2 AA in both themes. `e2e/tests/accessibility.spec.ts` runs axe over the main surfaces in dark and light and walks the keyboard path through the gallery; keep it passing.

- **Contrast.** The tokens are tuned so `foreground`, `muted-foreground`, `primary` (as text) and `destructive` all reach 4.5:1 as text on every surface, and on their own `/10` tint. Opacity modifiers on text break that, so don't use them; tints for selected states stay at `/10` or lighter.
- **Two ambers.** `--primary` is the fill (buttons, tints, borders); `--primary-ink` is amber as text, icons and the focus ring. `text-primary` resolves to the ink (see `tailwind.config.js`). In dark mode they're the same gold; in light mode the fill is bright gold with dark `primary-foreground` text on it, and the ink is a deeper gold, because bright gold is only ~2:1 on parchment.
- **Focus.** One indicator for everything: the 2px `--ring` outline set on `:focus-visible` in `index.css`. Don't add `outline-none` or per-component rings. Inside a clipping parent (`overflow-hidden`, segmented controls), use `focus-visible:outline-offset-[-2px]`. Menu items are the exception: Radix menus show focus as the highlighted row.
- **Clickable cards** (`SceneTile`, `GroupCard`): the container is plain; a full-cover `<button>` (`absolute inset-0`) is the click and keyboard target and carries the spoken name. Its focus outline is drawn outside the card by `focus-ring-within` (an outline over the artwork has no reliable contrast). Joined fields like search input + button use `focus-ring-within-input` the same way. Secondary actions (the card menu) are sibling buttons above it, never nested inside. Caption and thumbnail are `aria-hidden` / `alt=""` so the name isn't read twice.
- **Hover-revealed controls** must also show on keyboard focus and on touch: `opacity-0 group-hover/x:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100` (or `group-focus-within/x:` for a cluster).
- **Names and state.** Icon-only buttons get an `aria-label`. Toggles and segmented controls set `aria-pressed`; real panel switchers use `role="tablist"`/`tab`/`tabpanel`. Counts and outcomes that change after an action live in a `role="status"` element that stays mounted.
- **Target size.** Controls are at least 24×24px. For small icons use the `target-24` utility, which grows the hit area with an invisible `::after` (the element must be positioned).
- **Dialogs** are named by their `DialogTitle` / `PanelTitle` automatically; see [dialog-focus-management.md](dialog-focus-management.md) for the modal layer.
- **Sliders** use the `range` class: a quiet track filled to `--fill`, and a knob that grows on hover and carries the focus outline.
- **Shortcuts.** `/` focuses search from anywhere (not while typing or with a dialog open; the empty search box shows a `/` hint). In the viewer: ←/→ change image, Esc closes, `G` toggles the grid overlay. Declare them with `aria-keyshortcuts`.
- **Motion.** `prefers-reduced-motion` collapses transitions and stops looping animations globally.
- **Reflow.** No fixed widths that exceed the viewport: popovers use `w-[min(400px,calc(100vw-2rem))]`, the header wraps, and the image viewer stacks below `lg`.

---

## Anti-Patterns

The following patterns appear in older code (especially FileCard and import-flow components) and should **not** be used in new work or extended to viewer/gallery components:

| Old pattern | Correct replacement |
|-------------|---------------------|
| `bg-white`, `bg-slate-50` | `bg-card`, `bg-secondary` |
| `text-slate-700`, `text-slate-400` | `text-foreground`, `text-muted-foreground` |
| `border-slate-200` | `border-border` |
| `hover:bg-emerald-50 hover:text-emerald-700` | `hover:bg-primary/10 hover:text-primary` |
| `bg-emerald-600 text-white` (active) | `bg-primary/20 text-primary` |
| `border-emerald-300` (focus) | `focus:ring-primary/40` |
| Separate metadata bar below image | Gradient overlay (bottom of image) |
| Showing `category: value` in tag pills | Value only, capitalised; category in `title` attribute |
| Hiding filter button when no filterable data | Show it greyed out (`opacity-25 cursor-not-allowed`) |
| Metadata bar with fixed height below card | Remove; use gradient overlay on card |
| `rounded-lg border bg-white shadow-black/5` for dropdowns | `rounded-xl border border-border bg-card shadow-2xl shadow-black/40` |

---

## Open Items (Low Priority)

Remaining items from the design language audit (2026-02-25) that have not yet been addressed:

1. **Hover state implementation** — Some components use hardcoded hover colors instead of token-based `hover:bg-muted` or `hover:bg-primary/10`
2. **Font weight consistency** — Mixed usage of `font-medium` vs `font-semibold` for section labels across FilterMenuContent and ImageViewer
