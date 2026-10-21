# Groups & Variants

Battlemap artists often make several versions of one scene: day and night, seasons, gridded and gridless. Scene Atlas keeps these together in a **group**, so you browse by scene rather than by file.

A group has a **name**, an **author** and one or more images. It can contain both battlemaps and scenes.

Groups are made for you when you [import](/guide/importing#groups-and-names), from folders and shared filename prefixes. Most of this page is about fixing the ones it gets wrong.

## Subgroups

Subgroups split a large group into labelled parts, such as the rooms of a dungeon or the floors of a tower. Deeper folders become subgroups on import, and you can set them yourself. They show as sections in the viewer's scene panel; images without one are listed under *Other*.

## Editing Groups

### One Image

From an image tile's **…** menu or the viewer:

- **Move to group…** moves the image to another group, or to a new group of its own. Groups with names like the image's are listed first. There's no undo, but moving it back is the same action.
- **Edit group** opens the group editor.
- Rename the image, change its subgroup, type, grid or tags in the [viewer](/guide/gallery#image-viewer).

### The Group Editor

Open it with **Edit** on a group card, **Edit group** in the viewer, or **Review in editor** from an import report. The list on the left holds the groups you opened; the right side shows the selected group's images.

In the editor you can:

- rename the group and change its author;
- **drag images** onto another group in the list, or onto a subgroup;
- select images and use **Move selected to new group** to split them off;
- select images and set their type, grid, subgroup or tags all at once;
- mark images for deletion; they are deleted when the changes are saved, and can be restored until then;
- filter the images by name, type, grid or media to find the ones to change.

In the group list, `Ctrl`/`Cmd`-click selects several groups and `Shift`-click a range. With several selected you can **Merge Selected** into one, or delete them. **Merge All** combines every group in the list.

### Merging

To join two groups, use **Merge into…** on a group card and search for the group to merge it into. The images keep their tags and subgroups.

### Deleting

**Delete** on a group card deletes the group and all its images. Delete one image from its tile menu or the viewer. Files in [your own folder](/guide/library#using-your-own-folder) are never deleted; only Scene Atlas's record of them is.

## Bulk Editing

**Edit all** in the results bar opens every group in the current results in the group editor, so you can tag, type or regroup a whole search at once. For example, search for "snow", then set every result's Season tag to winter.

- It's available in the Groups view when the results hold at most 500 groups. Narrow the search or filters if there are more.
- With a search, only the images that matched are changed. The rest of each group is shown so you can add them one at a time.
- Changes to more than 500 images ask for confirmation first.
- After a bulk change, **Undo** in the notification puts the images back as they were.

Reviewing a very large import (more than 5,000 images) works the same way, but groups load as you scroll and **Everything** applies changes on the server.
