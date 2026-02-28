# Import Dialog Simplification

## Decision

The import dialog is being split into a focused group management tool. Per-file metadata editing (tags, grid, name, subgroup) is deferred to post-import, where the existing `ImageViewer` and `EditGroupDialog` (import-review mode) already provide full editing capabilities.

**Rationale:**
- Per-file editing doesn't scale to hundreds/thousands of images
- Grid detection, CLIP, and future ML enrichments run *after* confirmation — users were editing metadata blind
- The import dialog's core value is group management (merge, split, skip, exclude), not per-file editing
- Post-import editing shows enriched metadata (grid detection results, ML tags) — better informed decisions

## What the Import Dialog Shows Per-File

- Thumbnail (clickable for lightbox)
- Parsed name (read-only)
- Subgroup badge (read-only)
- Image type toggle (battlemap/scene — needed to gate grid detection)
- Duplicate indicator (with skip/import toggle)
- Selection checkbox + exclude toggle

## What Moved to Post-Import

- Tag editing (add/remove tags)
- Grid status editing (gridded/gridless/unknown, grid dimensions)
- Name editing
- Subgroup editing per-file
- Subgroup heading rename/clear

## Data Flow

Unchanged. `analyse_upload` still produces tags/grid hints from filename parsing (negligible cost, same parsing pass). These auto-detected values flow through `buildConfirmFiles` to the backend confirm endpoint unchanged. The UI just doesn't expose editors for them during import.

## Post-Import Review

Already implemented:
1. Import completes → ImportTray shows completed job
2. User clicks completed job → Gallery fetches created group IDs from status endpoint
3. Opens `EditGroupDialog` in import-review mode with full editing capabilities

## Future Work

- **Async analysis for scale:** `analyse_upload` runs synchronously with 120s timeout. At 1000+ images, thumbnail generation will exceed this. Needs async flow (upload → job ID → poll for analysis). Separate concern from dialog simplification.
