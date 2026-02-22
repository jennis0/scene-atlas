# Visual Language & Component Design

A comprehensive reference for the Scene Atlas UI. All new components must conform to these principles. When in doubt, follow existing patterns rather than introduce new ones.

---

## Aesthetic Direction

**Theme:** Dark cartographic / archival. Think a scholar's map room at night — deep navy surfaces, warm parchment text, amber gold accents used sparingly for wayfinding.

**NOT:** generic dark mode, purple gradients, high-contrast tech aesthetics.

### Core Adjectives
- Precise and measured (tight spacing, clean alignment)
- Warm but serious (amber over blue, parchment over white)
- Informational density done tastefully (show more, never clutter)

---

## Design Tokens

All values sourced from CSS custom properties defined in `frontend/src/index.css`. **Never use raw hex/rgb values** — always use token names.

### Surface Hierarchy (darkest → lightest)
| Token | Approx. hex | Role |
|-------|-------------|------|
| `--background` | `#0e1118` | Page base, dot-grid applied |
| `--popover` | `#12171f` | Dropdowns, popovers |
| `--card` | `#161c28` | Card surfaces, panel backgrounds |
| `--muted` | `#181f2e` | Muted/recessed surfaces |
| `--secondary` | `#1c2231` | Inputs, hover states, raised elements |

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
- Micro badges / counts: `text-[10px]` or `text-[9px]`
- Category labels: `text-[10px] uppercase tracking-wider text-muted-foreground/60`

---

## Amber Accent — Rules of Use

Amber (`primary`) is the single accent colour. It draws the eye, so it must be used intentionally and sparingly.

| Use | Pattern |
|-----|---------|
| Top-of-viewport stripe | `body::before` in index.css — always present |
| Top of modal/panel | Split gradient: canvas side `from-transparent to-primary/80`, sidebar side `from-primary/80 to-transparent` — brightest at the join line |
| Active/selected states | `bg-primary/20 text-primary border border-primary/40` |
| Focus rings | `focus:ring-1 focus:ring-primary/40` |
| Hover on interactive text | `hover:text-primary` |
| Decorative rule | `border-primary/60` |

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
```
bg-secondary border border-border rounded
text-foreground placeholder:text-muted-foreground
focus:outline-none focus:ring-1 focus:ring-primary/40
```
For inline editing (no box, just underline): `bg-transparent border-b border-primary/70 focus:outline-none`

### Number inputs — always hide native spinners
```
[appearance:textfield]
[&::-webkit-outer-spin-button]:appearance-none
[&::-webkit-inner-spin-button]:appearance-none
```

---

## Tag / Category Colour System

Tags are coloured by category. The colour replaces any need for a text category label. Defined in `frontend/src/components/import/tagColors.ts`.

### Colour pattern (dark-mode opacity tints)
```typescript
{ bg: 'bg-{colour}-400/10', text: 'text-{colour}-300', border: 'border-{colour}-400/30', dot: 'bg-{colour}-400' }
```
- `bg-*-400/10` — very subtle tint, doesn't dominate
- `text-*-300` — lighter shade readable on dark backgrounds
- `border-*-400/30` — 30% opacity border, cohesive with bg tint
- `dot` — solid colour for small dot indicators (2×2 in category nav lists)

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
- Canvas background: `hsl(222 22% 6%)` + `radial-gradient(circle, rgba(255,255,255,0.045) 1px, transparent 1px)` at 24px
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
  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 w-[72px] shrink-0">Subgroup</span>
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

---

## Component-Level Rules

### Borders and separators
- Between major sections: `border-b border-border/30`
- Between items in a list: `border-border/50`
- Very subtle internal structure: `border-border/20`
- Never use `border-border` at full opacity for internal dividers

### Scrollbars
Styled globally in index.css: 5px wide, `bg-border` thumb, transparent track. Do not override per-component.

### Shadows
- Elevation for floating panels/modals: `shadow-2xl shadow-black/70`
- Dropdowns: `shadow-2xl shadow-black/40`
- Card hover: `shadow-lg shadow-primary/15` (amber tinted)

### Popovers
Use Radix `<Popover>` with `<PopoverContent className="p-0 ...">` — do not add internal padding at the content level, let child components define their own spacing.

### Z-index conventions
- Sticky variant header inside scroll container: `z-10`
- ImageViewer overlay: `z-50`
- Tag picker / subgroup picker dropdowns: `z-50`
- Global amber top stripe (body::before): `z-1000`

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
