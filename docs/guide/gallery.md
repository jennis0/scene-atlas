# Gallery Views

The gallery is your primary way to browse and discover scenes in Scene Atlas. Two view modes serve different browsing needs, and a full-screen image viewer provides detailed scene information.

## View Modes

Toggle between views using the segmented control in the gallery header.

### Flat Grid

Shows every image as an individual card in a responsive grid. Each card displays:
- Thumbnail image
- Scene name and author overlaid with a gradient
- Scene count badge (if part of a group)

Best for: scanning across your full library, finding specific individual images.

### Grouped (Hero + Mosaic)

Shows each group as a larger card with:
- A hero image (60% width) showing the best-matching or first scene
- A mosaic area (40% width) with 1–4 additional variants
- Group name, author, scene count, and tag badges

Best for: browsing by scene concept, seeing what variants exist at a glance.

<!-- TODO: screenshot — flat vs grouped gallery comparison -->

## Sorting and Type Tabs

**Sort options:**
- **Relevance** — available when a search query is active; ranked by hybrid search score
- **Name** — alphabetical by group or image name
- **Date** — most recently imported first

**Type tabs:**
- **All** — every image in your library
- **Battlemaps** — only images with type "battlemap"
- **Scenes** — only images with type "scene"

## Image Viewer

Click any image or group card to open the full-screen image viewer.

### Canvas

The left side shows the full-resolution image on a dot-grid background. Navigate between images in the group with arrow buttons or keyboard arrow keys.

### Sidebar

The right sidebar (440px fixed width) is divided into two sections:

**Image Info** (fixed, always visible):
- Group name (click to edit) in Cinzel display font
- Author
- Subgroup label (click to edit)
- Grid toggle: Grid / Gridless / Unknown — with width × height inputs for gridded images
- Dominant colour dots with dimensions and file size
- Tag pills with a + Tag picker

**Variants** (scrollable):
- All other images in the group, partitioned by subgroup
- Search bar to filter within the group
- Click any variant thumbnail to navigate to it
- Filter button for tag-based filtering within the group

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / next image in group |
| `Escape` | Close the image viewer |
