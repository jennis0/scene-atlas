# Groups & Variants

Many battlemap artists create multiple versions of the same scene — day and night, snowy and summer, gridded and gridless. Scene Atlas groups these variants together so you can browse by scene concept rather than scrolling through hundreds of individual files.

## What is a Group?

A group is a collection of related images that represent the same scene. Typically these are lighting variants, seasonal variants, or grid/no-grid pairs from the same artist.

Each group has:
- A **name** (usually the base scene name)
- An **author**
- One or more **images** (the variants)
- Optional **subgroups** for further organisation within the group

## Auto-Grouping During Import

Scene Atlas automatically detects groups during the [import analysis step](/guide/importing#_2-analysis) using a two-pass algorithm:

1. **Folder-based grouping** — if your files are organised into folders per scene (e.g., `Forest Clearing/summer.jpg`, `Forest Clearing/winter.jpg`), each folder becomes a group.

2. **Prefix-based grouping** — files with a shared naming prefix are grouped together. For example, `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, and `TavernBrawl_Night.jpg` all share the prefix "TavernBrawl" and are grouped automatically.

You can review and adjust groups before confirming the import.

## Gallery Views

### Grouped View (Hero + Mosaic)

The grouped gallery shows each group as a card with:
- A **hero image** (the largest or most relevant variant) taking 60% of the card width
- A **mosaic area** showing 1–4 additional variants
- A "+N more" overlay when a group has more variants than fit in the mosaic
- Metadata: group name, author, scene count, and tag badges

<!-- TODO: screenshot — grouped gallery view -->

### Flat View

The flat gallery shows every image individually, regardless of grouping. Useful when you want to browse across all variants without the grouping layer.

Toggle between views using the segmented control in the gallery header.

## Image Viewer

Click any image to open the full-screen image viewer. The sidebar shows:

- **Image info** — name, author, dimensions, grid info, tags, dominant colours
- **All variants in the group** — partitioned by subgroup, with the current image highlighted
- Click any variant in the sidebar to navigate to it without closing the viewer

<!-- TODO: screenshot — image viewer with sidebar -->

## Subgroups

Subgroups provide an optional layer of organisation within a group. For example, a group called "Dragon's Lair" might have subgroups for "Main Chamber", "Entrance", and "Treasure Room".

Subgroups are displayed as labelled sections in the image viewer sidebar, making it easy to find the right variant.

## Editing Groups

### From the Gallery

Click the edit icon on any group card to:
- Rename the group
- Change the author
- Delete the group (and all its images)

### From the Image Viewer

The image viewer sidebar supports inline editing:
- Click the group name to rename it
- Edit the subgroup assignment for the current image
- Add or remove tags
- Change grid settings (for battlemaps)

### Merging Groups

If auto-grouping split a scene across multiple groups, you can merge them. Select multiple groups in the gallery and use the merge action to combine them into one.

### Moving Images

Drag and drop images between groups to reorganise. Images can be moved individually or in bulk.
