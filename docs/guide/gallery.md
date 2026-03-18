# Gallery & Image Viewer

The gallery is the main interface for browsing your collection. It has two view modes, sorting and filtering controls, and a full-screen image viewer.

## View Modes

Toggle between views using the segmented control in the gallery header.

### Flat Grid

Shows every image as an individual card in a responsive grid. Cards display a thumbnail, scene name, author, and a badge if the image belongs to a group.

Good for scanning your full library or finding a specific individual image.

### Grouped (Hero + Mosaic)

Shows each group as a larger card: a hero image (60% width) next to a mosaic of 1-4 additional variants. The card includes group name, author, scene count, and tag badges. A "+N more" overlay appears when there are more variants than fit.

Good for browsing by scene concept and seeing what variants are available at a glance.

<!-- TODO: screenshot — flat vs grouped gallery comparison -->

## Sorting and Type Tabs

**Sort options:**
- **Relevance** — only available when a search query is active
- **Name** — alphabetical by group or image name
- **Date** — most recently imported first

**Type tabs:**
- **All** — everything in your library
- **Battlemaps** — images with type "battlemap"
- **Scenes** — images with type "scene"

## Image Viewer

Click any image or group card to open the full-screen viewer.

### Canvas

The left side shows the full-resolution image on a dot-grid background. Navigate between images in the group with arrow buttons or keyboard arrow keys.

### Sidebar

The right sidebar has two sections:

**Image Info** (fixed, always visible):
- Group name (click to edit)
- Author
- Subgroup label (click to edit)
- Grid toggle: Gridded / Gridless / Unknown, with width x height inputs for gridded images
- Dominant colour dots, dimensions, and file size
- Tag pills with a + Tag picker

**Variants** (scrollable):
- All other images in the group, partitioned by subgroup
- Search bar to filter within the group
- Click any variant thumbnail to navigate to it

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / next image in group |
| `Escape` | Close the image viewer |
