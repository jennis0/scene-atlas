# Plan: User-Configurable Tag System

## Current State

**What already exists:**
- `TagCategory` table stores vocabulary as JSON (`common_values`) — categories like "lighting", "weather", etc.
- `Tag` table stores actual tags on images (category string, value string, confidence, source)
- Tags link to categories by **name string**, not FK — `Tag.category = "lighting"` matches `TagCategory.name = "lighting"`
- Tag API has basic endpoints: list categories, add/delete tag values within categories, CRUD tags on images
- Parser loads vocabulary from DB at import time, matches filename words → canonical values via aliases
- Frontend colors are **hardcoded** in `tagColors.ts` — a static map from category name → Tailwind classes

**Key design constraint:** Tags on images store plain strings (`category`, `value`), not foreign keys to TagCategory. Simple queries, no joins needed for search — but renames require bulk updates.

---

## What Needs to Change

### Phase 1: Backend — Schema & API

#### 1a. Add `color` column to `TagCategory`

Store a Tailwind color name (e.g. `"amber"`, `"sky"`, `"emerald"`). The frontend already has the infrastructure to map these to class strings.

```python
# database.py — TagCategory
color = Column(String, nullable=True)  # Tailwind color name, e.g. "amber"
display_order = Column(Integer, default=0)
```

Migration: `ALTER TABLE tag_categories ADD COLUMN color TEXT; ALTER TABLE tag_categories ADD COLUMN display_order INTEGER DEFAULT 0;`

Backfill existing categories with their current colors from the hardcoded map:
- lighting → amber, weather → sky, season → orange, terrain → emerald, biome → green, environment → teal, structure → stone, feature → violet, mood → rose

#### 1b. New/Updated API Endpoints

| Endpoint | Method | Purpose | Cascading |
|----------|--------|---------|-----------|
| `/tags/categories` | POST | **Create** category (name, description, color) | — |
| `/tags/categories/{name}` | PATCH | **Update** category (rename, description, color, display_order) | If renamed: `UPDATE tags SET category = :new WHERE category = :old` |
| `/tags/categories/{name}` | DELETE | **Delete** category | `DELETE FROM tags WHERE category = :name`, then delete the `TagCategory` row |
| `/tags/categories/{name}/tags/{value}` | PUT | Add/update tag value + aliases (exists, minor cleanup) | — |
| `/tags/categories/{name}/tags/{value}` | PATCH | **Rename** a tag value | `UPDATE tags SET value = :new WHERE category = :name AND value = :old` |
| `/tags/categories/{name}/tags/{value}` | DELETE | **Delete** a tag value (exists but doesn't cascade) | Add: `DELETE FROM tags WHERE category = :name AND value = :value` |

All mutating endpoints return `{ affected_images: number }` so the frontend can confirm the impact.

**Cascade performance:** A rename of "terrain" could touch thousands of Tag rows. For SQLite with ~100k images this is sub-second (single `UPDATE` statement). No background job needed.

---

### Phase 2: Frontend — Color System (Small effort)

**No refactoring needed.** The existing `tagColors.ts` pattern stays. Changes:

1. Expand `CATEGORY_COLORS` from a hardcoded map of 9 categories to a **palette of ~25 Tailwind color presets** keyed by color name:

```typescript
// tagColors.ts
export const COLOR_PALETTE: Record<string, TagColor> = {
  amber:   { bg: 'bg-amber-400/10',   text: 'text-amber-300',   border: 'border-amber-400/30',   dot: 'bg-amber-400' },
  sky:     { bg: 'bg-sky-400/10',     text: 'text-sky-300',     border: 'border-sky-400/30',     dot: 'bg-sky-400' },
  // ... ~25 total presets
}
```

2. `getTagColor()` changes from `category name → color` to `color name → TagColor`:

```typescript
export function getTagColor(colorName: string | null): TagColor {
  if (!colorName) return DEFAULT_TAG_COLOR
  return COLOR_PALETTE[colorName] ?? DEFAULT_TAG_COLOR
}
```

3. **Call sites** need a minor change: instead of `getTagColor("lighting")` they need `getTagColor(category.color)`. This means components that render tags need access to the category-to-color mapping.

**Approach:** A lightweight `useTagColors()` hook or a module-level map built from the categories query:

```typescript
// Existing: tagApi.getCategories() already fetched in multiple places
// New: build Map<categoryName, colorName> from response
// getTagColor() call sites: getTagColor(colorMap.get(category))
```

**Files affected:** `tagColors.ts` (expand palette, change lookup), `FilterMenuContent.tsx`, `GalleryFilterPanel.tsx`, `FileCard.tsx`, `ImageViewer.tsx` — anywhere `getTagColor(category)` is called with a category name. Each is a small change (look up color name from map first).

---

### Phase 3: Frontend — Tag Management UI

A dialog accessible from the gallery toolbar (e.g. a "Tags" or gear icon).

**Layout:**
- Left panel: category list with colored dots, reorderable
- Right panel: selected category detail
  - Name (editable), description
  - Color picker: grid of ~25 Tailwind preset swatches
  - Tag values list: each row shows value + aliases (editable), with rename/delete
  - "Add value" input at bottom

**Components:**
1. `TagManagementDialog.tsx` — main dialog, fetches categories, manages state
2. `CategoryEditor.tsx` — right panel for editing a single category
3. `ColorSwatchPicker.tsx` — grid of ~25 preset color swatches (simple, no custom hex)
4. Inline confirmation for destructive actions (rename/delete show affected count)

**Preset palette (~25 colors):**
```
red, orange, amber, yellow, lime, green, emerald, teal,
cyan, sky, blue, indigo, violet, purple, fuchsia, pink, rose,
stone, slate, zinc, neutral
```

Each is a Tailwind shade name. The swatch grid renders each as a colored circle. Click to select.

---

### Phase 4: Wire DB Colors into Existing Views (Small effort)

1. Gallery page already fetches tag categories for filters
2. Build `Map<categoryName, colorName>` from response
3. Thread it through to components (context or prop drilling — context is cleaner)
4. All existing tag rendering automatically picks up DB-driven colors

---

### Stretch: Discarded Token Saving

Save unmatched filename tokens during import for potential future use. No UI for now — just data collection.

#### Schema
```python
class UnmatchedToken(Base):
    __tablename__ = "unmatched_tokens"
    id = Column(Integer, primary_key=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    token = Column(String, nullable=False, index=True)
    source = Column(String)  # "filename" or "path"
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### Changes
1. **Parser** (`image_parser.py`): return `unmatched_tokens` alongside `tags`
2. **Ingestion** (`ingestion.py`): save unmatched tokens during `batch_save_to_database()`

That's it for V1. Auto-apply UI deferred.

---

## Effort Estimate & Build Order

| Step | Phase | Effort |
|------|-------|--------|
| 1 | Schema: add `color` + `display_order` to TagCategory, backfill | Small (30 min) |
| 2 | API: CRUD + cascade endpoints for categories and tag values | Medium (3-4 hours) |
| 3 | `tagColors.ts`: expand to ~25 preset palette, change lookup signature | Small (1 hour) |
| 4 | Wire DB colors: update call sites + add category color context | Small (1-2 hours) |
| 5 | Tag Management dialog + sub-components | Large (6-8 hours) |
| 6 | Stretch: unmatched token saving (schema + parser + ingestion) | Small (2-3 hours) |

**Total core (steps 1-5): ~2 days. With stretch: ~2.5 days.**

## Key Decisions Made

1. **Pure Tailwind presets** — no hex fallback. ~25 named colors stored in DB. Zero refactoring to style system. If a 26th color is ever needed, hex support is a trivial upgrade.

2. **Stretch scoped to data collection only** — save unmatched tokens during import, defer auto-apply UI.

3. **Dialog not page** — tag management lives in a dialog, consistent with import/edit patterns.

4. **Cascade in-request** — rename/delete operations run synchronous SQL updates. Fast enough for SQLite scale. Response includes affected count for user feedback.
