# Groups & Variants

Many battlemap artists create multiple versions of the same scene: day/night, seasonal, gridded/gridless. Scene Atlas groups these variants together so you can browse by scene concept.

## What is a Group?

A group is a collection of related images representing the same scene. Each group has:

- A **name** (usually the base scene name)
- An **author**
- One or more **images** (the variants)
- Optional **subgroups** for further organisation (e.g., "Main Chamber", "Entrance", "Treasure Room")

## Auto-Grouping During Import

Scene Atlas detects groups when you [import](/guide/importing#_2-grouping-and-upload) using two passes:

1. **Folder-based** grouping: if your files are in folders per scene (e.g., `Forest Clearing/summer.jpg`, `Forest Clearing/winter.jpg`), each folder becomes a group.

2. **Prefix-based** grouping: files with a shared naming prefix are grouped together. `TavernBrawl_Grid.jpg`, `TavernBrawl_Gridless.jpg`, and `TavernBrawl_Night.jpg` all share the prefix "TavernBrawl".

Imports start straight away, so groups are reviewed afterwards: open them from the import report (**Review in editor**) and drag images between groups to fix any misdetections, or edit them as described below.

## Subgroups

Subgroups add an extra layer of organisation within a group. A group called "Dragon's Lair" might have subgroups for different rooms. These show as labelled sections in the image viewer sidebar.

## Editing Groups

### From the Gallery

Click the edit icon on any group card to open the edit dialog, where you can:

- Rename the group or change the author
- Move images between subgroups
- Merge the group into another group (search for the target group by name)
- Delete the group and all its images

### From the Image Viewer

The image viewer sidebar supports inline editing:

- Click the group name to rename it
- Edit the subgroup assignment for the current image
- Add or remove tags
- Change grid settings (for battlemaps)
