# Visual Language & Component Design

A comprehensive reference for the Scene Atlas UI. All new components must conform to these principles. When in doubt, follow existing patterns rather than introduce new ones.

---

## Aesthetic Direction

**Theme:** Cartographic / archival. The dark mode evokes a scholar's map room at night — deep navy surfaces, warm parchment text, amber gold accents used sparingly for wayfinding. The light mode uses warm parchment tones reminiscent of aged paper, with the same amber accent adapted for readability.

**NOT:** generic dark/light mode, purple gradients, cold whites/greys, high-contrast tech aesthetics.

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
| `--background` | `#0e1118` | Page base, dot-grid applied |
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
| `--background` | `#f3ede5` | Warm parchment base, dot-grid applied |
| `--card` | `#f8f5f0` | Card surfaces (slightly lighter than bg) |
| `--popover` | `#faf7f3` | Lightest surface for floating layers |

### Accent / Semantic
| Token | Approx. hex | Role |
|-------|-------------|------|
| `--primary` | `#d4a853` | Amber gold — active states, focus rings, decorative accents |
| `--primary-foreground` | near-black | Text on amber backgrounds |
| `--destructive` | `#e04e4e` | Destructive actions, excluded filter chips |
| `--border` | `#222a38` | Dividers — use `/50` or `/30` for very subtle |
| `--ring` | same as primary | Focus ring colour |

### Text
| Token | Role |
|-------|------|
| `text-foreground` | `#ede8dc` warm parchment — primary body text |
| `text-muted-foreground` | dimmed parchment — secondary text, labels |
| `text-muted-foreground/60` | very subtle — hints, placeholders, tertiary info |
| `text-white` with opacity | for text overlaid directly on images |

---

## Typography

Three font families, used in distinct roles. **Never mix roles.**

| Family | Tailwind class | Role |
|--------|---------------|------|
| **Cinzel** (display serif) | `font-display` | Page titles, map/group names, modal headings. Conveys gravitas. |
| **Figtree** (geometric sans) | `font-sans` (default) | All body text, labels, controls, metadata. |
| **JetBrains Mono** | `font-mono` | Filenames, UUIDs, dimensions, file sizes. `text-[10px]` usually. |

### Size Scale in Practice
- Page title: `font-display text-3xl font-semibold`
- Section heading (e.g. viewer name): `font-display text-xl font-semibold`
- Card name: `text-[13px] font-medium` (gradient overlay) or `text-sm font-semibold`
- Metadata / labels: `text-[11px]` or `text-xs text-muted-foreground`
- Micro badges / counts: `text-[10px]`
- Section labels: `.section-label` utility — `text-[10px] font-semibold tracking-[0.1em] uppercase text-muted-foreground`

---

## Amber Accent — Rules of Use

Amber (`primary`) is the single accent colour. It draws the eye, so it must be used intentionally and sparingly.

| Use | Pattern |
|-----|---------|
| Top-of-viewport stripe | `body::before` in index.css — always present |
| Top of modal/panel | Split gradient: canvas side `from-transparent to-primary/80`, sidebar side `from-primary/80 to-transparent` — brightest at the join line |
| Active/selected states | `bg-primary/20 text-primary border border-primary/40` |
| Focus rings | `focus-visible:ring-1 focus-visible:ring-primary/40` (unified across all components) |
| Hover on interactive text | `hover:text-primary` |
| Page-level decorative rule | `h-[1.5px] w-16 bg-gradient-to-r from-primary/70 to-transparent` |
| Panel-level decorative rule | `h-px w-7 bg-gradient-to-r from-primary to-transparent` |

**Never use amber as a background fill** (except `bg-primary` for the tiny count badge on filter buttons, where text-primary-foreground ensures contrast).

---

## Interaction States

Applied consistently across all interactive elements:

### Buttons and clickable items
| State | Classes |
|-------|---------|
| Default (muted) | `text-muted-foreground` |
| Hover | `hover:text-foreground hover:bg-secondary` |
| Active / selected | `bg-primary/20 text-primary border border-primary/40` |
| Disabled | `opacity-30 cursor-not-allowed` (not `disabled:` if using native button disabled) |
| Destructive hover | `hover:text-destructive hover:bg-destructive/10` |

### Inputs and text fields

Use the `<Input>` component from `ui/input.tsx` which supports CVA variants:

| Variant | Height | Size | Used for |
|---------|--------|------|----------|
| `default` | h-10 | text-sm | Gallery search, forms |
| `compact` | h-[30px] | text-[12px] | Filter search, panel inputs |
| `sm` | h-6 | text-xs | Scene search, grid W×H inputs |

Shared base: `bg-secondary border-border rounded-md focus-visible:ring-1 focus-visible:ring-primary/40`

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
| **Solid** (button overlays) | `h-4 min-w-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center tabular-nums` | Gallery filter button, ImageViewer filter badge |
| **Tinted** (inline context) | `px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary tabular-nums` | Tab counts, "N active" badges |

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
<button className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground/70 hover:text-muted-foreground transition-colors">
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
| weather | sky |
| season | orange |
| terrain | emerald |
| biome | green |
| environment | teal |
| structure | stone |
| feature | violet |
| mood | rose |
| (unknown) | zinc |

### Tag pill rendering
Show **capitalised value only** — the colour already encodes the category:
```tsx
<span className={`inline-flex items-center gap-1 text-[11px] rounded-full border px-2 py-px ${colors.bg} ${colors.text} ${colors.border}`}
  title={tag.category}>
  <span className="capitalize">{tag.value}</span>
</span>
```
Add `title={tag.category}` on the outer element for discoverability on hover.

---

## Card Pattern

All image cards (ImageCard, GroupCard, VariantTile) share a **gradient overlay** structure — NO separate metadata bar below the image.

```
┌─────────────────────────┐
│                         │
│      Image area         │ ← object-cover, lazy loaded
│      (thumbnail)        │
│                         │
│ ░░░░░░░░░░░░░░░░░░░░░   │ ← gradient overlay: from-black/85 via-black/55 to-transparent
│  Name           [N]  │   │ ← text-[13px] font-medium text-white
│  Author              │   │ ← text-[11px] text-white/60
└─────────────────────────┘
```

**Overlay gradient:** `bg-gradient-to-t from-black/85 via-black/55 to-transparent pt-10 pb-2.5 px-3`

**Hover animation:** `transition-all duration-200 hover:scale-[1.03]` — subtle scale only, no border animation on cards with overlays.

**Ring/border on cards:**
- Default: `ring-1 ring-border/40`
- Hover: `hover:ring-primary/40`
- Active / selected: `ring-2 ring-primary/70 shadow-lg shadow-primary/15`

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
Filter chips use `bg-primary/20 border border-primary/40 text-primary` for active state. Clear-all uses plain `text-muted-foreground`.

---

## FilterMenuContent Component

Shared two-column filter panel used in GalleryFilterPanel (full-page sidebar) and ImageViewer (variant filter popover).

### Structure
- Left 112px: scrollable category nav with coloured dot indicators
- Right: `flex-1` pill grid, wraps, with search bar at top

### Active states
| State | Classes |
|-------|---------|
| Include (active) | `bg-primary/20 border border-primary/40 text-primary` |
| Exclude (active) | `bg-destructive/10 border border-destructive/30 text-destructive` |
| Category nav active | Uses category's `colors.bg colors.text colors.border` (left border stripe) |

### Truncation — mandatory for all label text
Filter chips (active filter rows below search inputs): `max-w-[130px] truncate` with `title={filter.label}` on outer element.
Option pills (inside popover): `max-w-[160px] truncate` with `title={label}` on outer element.

### Filter button states (for variant filter trigger in ImageViewer)
```tsx
hasActiveFilters     → 'bg-primary/20 text-primary border border-primary/40'
hasFilterableData    → 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
no filterable data   → 'text-muted-foreground/25 border border-transparent cursor-not-allowed'
```
**Always render the button** — never hide it just because there's nothing to filter. Grey it out instead. This maintains layout stability and teaches the user what feature is present.

---

## ImageViewer Layout

Full-screen overlay with fixed image canvas + structured sidebar:

```
┌──────────────────────────────────────────────────────────────────────┐
│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  ← amber stripe: bright at join, transparent at edges
├──────────────────────────────────┬───────────────────────────────────┤
│                                  │  [Edit group]            [✕]      │  ← controls row
│         Image canvas             ├───────────────────────────────────┤
│         dot-grid background      │  Map Name (font-display, xl)      │  ← fixed info section
│         (dark navy + subtle      │  by Author                        │    (shrink-0, border-b)
│          white dots at 24px)     │  Variant  [current value] [✎] [✕] │
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
- Canvas background: `hsl(var(--surface-canvas))` + `radial-gradient(circle, hsl(var(--foreground) / 0.045) 1px, transparent 1px)` at 24px
- Sidebar: `w-[440px] shrink-0 flex flex-col` — **does not grow or shrink**

### Sidebar sections (top to bottom)
1. `h-0.5 shrink-0 bg-gradient-to-l from-transparent to-primary/80` — amber stripe (sidebar half)
2. Controls row: `shrink-0` — edit group link (left), close × (right)
3. **Image info**: `shrink-0 border-b border-border/30 px-4 pb-4` — **fixed, never scrolls away**
4. **Variants**: `flex-1 min-h-0 overflow-y-auto` — only this section scrolls

### Amber stripe implementation
The stripe spans the full viewer top but is **brightest at the canvas/sidebar join**, fading to transparent at both outer rounded corners:
- Canvas: `absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent to-primary/80`
- Sidebar: first child `h-0.5 shrink-0 bg-gradient-to-l from-transparent to-primary/80`

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

### SubgroupPicker (`frontend/src/components/import/SubgroupPicker.tsx`)
Popup picker showing existing subgroups from the group as quick-select options, plus a free-text input. Used in the import/edit flow (not in ImageViewer — ImageViewer uses inline editing instead).

Trigger: `text-muted-foreground hover:text-primary`
Dropdown: `bg-card border-border shadow-2xl shadow-black/40`

### ActivityDock (`frontend/src/components/ActivityDock.tsx`)
Floating bottom-right card for viewing background job status.

**Collapsed pill:** `bg-card/95 backdrop-blur-sm border border-border/40 rounded-full shadow-lg shadow-black/40`. Hover: `bg-secondary hover:-translate-y-px`. Shows Loader2 (spinning) when active, Package when idle. Active count badge uses the solid tier.

**Expanded card:** `w-[320px] max-h-[min(520px,65vh)] bg-card rounded-xl border border-border/30 shadow-2xl shadow-black/60`. Amber stripe at top. Header follows panel header pattern (Cinzel title + amber rule). Footer uses `bg-popover`.

**Job cards:** `rounded-md border-border/30 bg-secondary/20 hover:bg-secondary/40`. Terminal: `opacity-75 hover:opacity-100`. Progress: 3px track.

**Visibility:** Hidden when no jobs exist. No auto-expand — user clicks pill to open.

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
- Global amber top stripe (body::before): `z-1000`

---

## Dense Editing Lists (Ledger Style)

For management dialogs with editable lists (tag values, vocabulary entries), use the ledger row pattern:

```tsx
<div className={`group/valrow flex items-stretch border-b border-border/40 transition-colors last:border-b-0 ${
  isEditing ? 'bg-muted/50' : 'hover:bg-muted/30'
}`}>
  {/* Content area — click to enter edit mode */}
  <div className="flex-1 min-w-0 py-[7px] px-[10px] cursor-text" onClick={...}>
    <span className={`text-[13px] font-medium capitalize ${colors.text}`}>{value}</span>
    <button className="text-[10.5px] text-muted-foreground italic ...">aliases or "No aliases"</button>
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

1. **Confirm dialogs** — `ConfirmDialog` component uses default Radix styling rather than the documented token-based patterns (low visual impact since it's rarely seen)
2. **Hover state implementation** — Some components use hardcoded hover colors instead of token-based `hover:bg-muted` or `hover:bg-primary/10`
3. **Card scale on hover** — GroupCard uses `hover:scale-[1.01]` which is inconsistent with ImageGrid cards that have no scale transform
4. **Font weight consistency** — Mixed usage of `font-medium` vs `font-semibold` for section labels across FilterMenuContent and ImageViewer
