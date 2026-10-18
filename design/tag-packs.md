# Tag Packs

## Overview

Tag packs are curated vocabularies of tag values grouped by genre. They allow users to install only the tags relevant to their content -- a fantasy-focused library does not need cyberpunk or sci-fi tags cluttering its filters and auto-detection.

Packs exist because Scene Atlas supports a wide range of tabletop RPG genres. Rather than seeding every possible tag at first boot, the system ships a single canonical vocabulary file where each tag value declares which packs it belongs to. First boot installs only the `common` pack (see [First-Boot Seeding](#first-boot-seeding)); genre packs are added from the setup wizard or Settings.

## Vocabulary File

All tag data lives in a single JSON file: `backend/app/data/tag_vocabulary.json`.

### Structure

```json
{
  "version": 1,
  "packs": {
    "common": { "label": "Common", "description": "Core tags for any genre" },
    "fantasy": { "label": "Fantasy", "description": "Medieval fantasy settings" }
  },
  "categories": [
    {
      "name": "lighting",
      "description": "Time of day and lighting conditions",
      "color": "amber",
      "icon": "sun",
      "display_order": 0,
      "tags": [
        { "value": "day", "aliases": ["daytime", "daylight"], "packs": ["common"] },
        { "value": "neon", "aliases": ["neon-lit"], "packs": ["cyberpunk"] }
      ]
    }
  ]
}
```

Each tag entry has:

| Field | Purpose |
|-------|---------|
| `value` | Canonical tag value stored in the DB |
| `aliases` | Synonyms used for search alias expansion and auto-tagging |
| `packs` | Which pack(s) include this tag (a tag can belong to multiple packs) |

Categories define the grouping axis (lighting, season, weather, environment, etc.) with display metadata (color, icon, order).

## Available Packs

| Pack | Label | Description |
|------|-------|-------------|
| `common` | Common | Core tags for any genre (lighting, season, weather, terrain) |
| `fantasy` | Fantasy | Medieval fantasy settings |
| `scifi` | Sci-Fi | Science fiction settings |
| `cyberpunk` | Cyberpunk | Dystopian neon-lit settings |
| `horror` | Horror | Dark and unsettling settings |
| `historical` | Historical | Real-world historical periods |

## Import Mechanics

Importing a pack merges its tags into the database. The process is handled by `import_tag_pack()` in `tag_packs.py`:

1. **Filter vocabulary** -- `get_tags_for_packs([pack_name])` returns only categories and tags belonging to the requested pack.
2. **For each category in the pack:**
   - If the category does not exist in DB: create it with only this pack's tags as `common_values`.
   - If it exists: merge new tag values into the existing `common_values` JSON.
3. **Merge rules:**
   - Existing tag values are preserved unchanged.
   - New values are appended.
   - Aliases are unioned -- if a tag already exists and the pack adds new aliases, they are merged into the existing alias list.
4. **Post-import:** The FTS alias cache is invalidated so the search system immediately picks up new vocabulary.
5. **Return counts:** `categories_created`, `tags_added`, `tags_existing`.

Import is idempotent -- importing the same pack twice produces zero changes on the second run.

### Pack Status Detection

`get_pack_status()` checks whether a pack is fully imported by comparing every tag value in the pack against the DB category's `common_values`. A pack is marked `imported: true` only when all its tags are present. The `new_tags` count tells the user how many tags would be added.

## Database Storage

Tags are stored in two tables:

| Table | Role |
|-------|------|
| `tag_categories` | Defines categories with `common_values` (JSON array of tag values/aliases) |
| `tags` | Per-image tag assignments (category + value + confidence + source) |

The `common_values` column uses a compact JSON format: bare strings for tags without aliases, objects for tags with aliases:

```json
["day", {"value": "night", "aliases": ["nighttime"]}, "dusk"]
```

### First-Boot Seeding

`seed_tag_categories()` in `backend/app/models/database.py` runs at every startup (`main.py` lifespan) but only acts when `tag_categories` is empty. It creates every category with the `common` pack's tags (every category has common tags), so a fresh library starts with only `common` installed and the genre packs opt-in. `POST /api/v1/system/tags/reset` deletes all tags and categories and calls the same function, so after a reset only `common` is installed again. Existing libraries are unaffected: seeding never runs once categories exist.

## API Endpoints

All under `/api/v1/tags`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/packs` | List all packs with import status (`imported`, `new_tags`, `tag_count`) |
| POST | `/packs/{name}/import` | Import/merge a single pack. 404 for an unknown pack. Rate-limited (`rate_limit_expensive`, default 2/minute) |
| POST | `/packs/import-multiple` | Body `{"packs": [...]}`. Imports each pack in turn (a failed pack is rolled back without affecting the others); returns `{"imported": [...], "errors": ["name: message", ...]}` with HTTP 200 even when some fail. Rate-limited (`rate_limit_expensive`). Used by the setup wizard |

## Frontend Integration

### Settings Dialog

`TagPacksSection` in `components/settings/SettingsTabContent.tsx` lists all packs in a 2-column grid of `TagPackCard`s (`components/setup/TagPackCard.tsx`). Each card shows:

- Pack label and description
- Total tag count and number of new tags (if not fully imported)
- Import button (disabled when already imported, shows "Added" with checkmark)

Import calls `tagApi.importTagPack(packName)`, invalidates the tag-pack and tag queries, and shows a toast with the result.

### Setup Wizard

`components/setup/TagPackStep.tsx` is the third step of the setup wizard ([first-run.md](first-run.md)). It lists packs, pre-selects every pack not yet `imported` (already-imported packs, normally just `common`, are shown checked and disabled as "included"), and on Continue sends the selection to `POST /tags/packs/import-multiple`. If the response lists `errors` (or the request fails, e.g. 429), the step stays open with an alert listing them, refreshes the pack list and keeps only the failed packs selected; the user can "Try again" or "Skip for now". Packs imported earlier in the wizard (e.g. before Back) show as "added". When the wizard finishes it calls `POST /api/v1/models/setup-complete`, which writes the `setup_completed_at` app setting.

`GET /api/v1/models/setup-status` returns `setup_completed: false` until `setup_completed_at` exists, and `App.tsx` shows the wizard until then. The wizard runs in every mode, desktop included.

**Interaction with seeding.** Seeding runs before the wizard and installs only `common`, so the wizard's defaults (all genre packs selected) give the same vocabulary as before, while deselecting packs or skipping leaves them out. Packs cannot be removed once imported.

## Key Files

| File | Responsibility |
|------|---------------|
| `backend/app/data/tag_vocabulary.json` | Canonical vocabulary -- all packs, categories, tags, and aliases |
| `backend/app/data/vocabulary.py` | Vocabulary loader -- `load_vocabulary()`, `get_tags_for_packs()`, `build_common_values_json()` |
| `backend/app/services/tag_packs.py` | Pack import logic -- `get_pack_status()`, `import_tag_pack()` |
| `backend/app/api/tags.py` | API endpoints -- `GET /packs`, `POST /packs/{name}/import`, `POST /packs/import-multiple` |
| `backend/app/api/models.py` | `GET /models/setup-status` (`setup_completed`), `POST /models/setup-complete` |
| `backend/app/models/database.py` | `TagCategory` model, `seed_tag_categories()` first-boot seeding |
| `frontend/src/components/settings/SettingsTabContent.tsx` | `TagPacksSection` (Settings) |
| `frontend/src/components/setup/TagPackCard.tsx` | Pack card used in Settings |
| `frontend/src/components/setup/TagPackStep.tsx` | Setup wizard pack selection step |
| `frontend/src/lib/api/tagApi.ts` | Frontend API client -- `getTagPacks()`, `importTagPack()`, `importMultipleTagPacks()` |
| `frontend/src/types/index.ts` | `TagPack` TypeScript interface |
