# Visual Language & Component Patterns

A reference for consistent styling across all gallery components.

## Card Pattern

All image-displaying cards (ImageCard, GroupCard, VariantTile) share a common visual structure:

```
┌─────────────────────────┐
│                         │
│      Image area         │  ← object-cover, lazy loaded
│      (thumbnail)        │
│                         │
├─────────────────────────┤
│  Name / label           │  ← always visible, not hover-only
│  Author / secondary     │
│  [tag] [tag] [+N]       │  ← outline badges, text-[10px]
└─────────────────────────┘
```

### Shared Classes

| Property | Classes |
|----------|---------|
| Container | `cursor-pointer overflow-hidden rounded-lg border bg-card` |
| Hover | `transition-all duration-200 hover:scale-[1.03] hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5` |
| Metadata bar | `bg-card border-t border-border/50` + padding |
| Name text | `font-semibold text-sm text-foreground truncate` |
| Secondary text | `text-xs text-muted-foreground truncate` |
| Tag badges | `Badge variant="outline"` with `text-[10px] text-muted-foreground` |
| Tiny badges | `text-[8px] px-1 py-0 text-muted-foreground/60 leading-tight` (variant tiles) |

### Key Principle: Always-Visible Metadata

Metadata (name, author, tags) is shown in a permanent bar below the image, **not** hidden behind a hover overlay. This ensures:
- Users can scan content without mousing over every card
- Touch/mobile users see the same information
- The grid reads as an informative catalogue, not a photo wall

## Card Variants

### ImageCard (individual grid)
- 200px wide, square image area + metadata bar
- Shows: name, author, up to 3 tag values + overflow count

### GroupCard (grouped grid)
- 420px wide, 160px image area + metadata bar
- Left 60%: hero image, right 40%: mosaic of variant thumbnails
- Mosaic uses **even tile counts only** (1, 2, or 4) to avoid empty grid cells
- Last mosaic tile shows "+N more" overlay when overflow
- Metadata: group name, author, variant count badge (shows "3/23" when filtered), up to 3 tags

### VariantTile (ImageViewer sidebar)
- Small tile in 2-column scrollable grid
- 4:3 aspect ratio image
- Shows: filename (without extension), grid info badge, up to 2 tag values
- Active state: `border-primary ring-1 ring-primary/30`

## ImageViewer Layout

Full-screen overlay (`bg-black/95`) with image + sidebar:

```
┌────────────────────────────────────────────────────┐
│                                    ┌──────────┐    │
│                                    │ Metadata │    │
│         Main Image                 │ header   │    │
│         (object-contain)           ├──────────┤    │
│                                    │ Variants │    │
│                                    │ (scroll) │    │
│                                    └──────────┘    │
└────────────────────────────────────────────────────┘
```

- Both sides constrained to `max-height: 85vh` via `items-stretch` on the container
- Sidebar: fixed metadata header (name, author, sub-variant badge, grid badge, filename, tags, colors, dimensions) + scrollable variant area

### Variant Organisation in ImageViewer

Variants are **partitioned by `sub_variant` value** into labelled sections:

```
Variants (23)

SNOWY
  [tile] [tile]
  [tile] [tile]

FEY
  [tile] [tile]

SUMMER
  [tile] [tile]
  [tile]
```

- Each unique `sub_variant` becomes an uppercase section header
- Tiles within a section show the **filename** (not sub_variant, since the header already shows it)
- If all variants share the same `sub_variant` or none have one, renders as a single flat list with no section header
- Variants without `sub_variant` go into an "Other" section

## Badge Usage

| Context | Variant | Size | Content |
|---------|---------|------|---------|
| Gallery cards (tags) | `outline` | `text-[10px]` | Tag value only (no category prefix) |
| Gallery cards (variant count) | `secondary` | `text-[10px]` | "23" or "3/23" |
| ImageViewer header (tags) | `outline` | `text-[10px]` | "category: value" |
| ImageViewer header (sub-variant) | `outline` | `text-xs` | Sub-variant label |
| ImageViewer header (grid) | `outline` | `text-xs` | "Grid 30×20" or "Gridded" |
| Variant tiles (tags/grid) | `outline` | `text-[8px]` | Compact, muted |

## Color & Theme

- Dark mode is primary (`dark` class on root)
- Card backgrounds: `bg-card` (maps to dark blue-grey)
- Borders: `border-border` (subtle), `border-border/50` (very subtle, used for internal separators)
- Hover accent: `border-primary/40` + `shadow-primary/5`
- Active/selected: `border-primary ring-1 ring-primary/30`
- Muted text: `text-muted-foreground` (main secondary), `text-muted-foreground/60` (very subtle)
- Overlay text: white with opacity variants (`text-white`, `text-white/70`, `text-white/90`)
