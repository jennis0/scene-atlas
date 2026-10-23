# Groups & Variants

Battlemap artists often make several versions of one scene: day and night, seasons, gridded and gridless. Scene Atlas keeps these together in a **group**, so you browse by scene rather than by file.

A group has a **name**, an **author** and one or more images. It can contain both battlemaps and scenes.

Groups are made for you when you [import](/guide/importing#groups-and-names). Scene Atlas looks at your folders, your file names and the pictures themselves. Most of this page is about fixing the groups it gets wrong.

## How Groups Are Made

When an import's images have all been processed, Scene Atlas spends a moment **identifying groups**. It works up from the deepest folders and asks, at each level, whether the files belong to one map. Groups appear once this is done and aren't changed by the import afterwards.

It uses three kinds of evidence:

- **The pictures.** Two files showing the same picture, such as a gridded and a gridless copy, or the same map at two sizes, always end up together, wherever they are in the import. Versions with the same layout but different lighting, season or props are joined when they're in the same folder.
- **File names.** Files whose names differ only by version words belong together: `Tavern_Night_Gridded.jpg` and `Tavern_Day.jpg`. Words like *night*, *winter*, *gridless*, *VTT*, *300dpi* or *22x30* are ignored when comparing names. A prefix that every file in a collection shares, such as `MyCollection_`, is ignored too, so it doesn't merge different maps.
- **Folders.**
  - A folder named after a map, or full of files named only `Day`, `Night` and so on, is one group.
  - Folders such as `Gridded`, `No Grid`, `VTT`, `Print` or `70 DPI` are treated as versions of what's around them, not as groups of their own.
  - Folders inside a map's folder, like the rooms of a tower or the floors of an inn, become **subgroups** of one group, as long as they look like they belong to the same place.
  - Folders for an author, a topic (`Forests`, `Taverns`) or a download (`Maps`, `Pack 03`) are never treated as one map, and groups are never merged across them, except for identical copies. An author already in your library is recognised by name.
  - A folder holding only map folders, drawn at different sizes, is a collection of separate maps.
  - In a folder named after something specific, files belong together unless their names or pictures say they're different maps.

Floors and rooms are only joined when a folder or their names say they belong together. Two maps that merely look alike are kept apart.

### How your folders affect the result

- **One folder per map gives the best groups.** Anything inside a map's folder, including subfolders for grid versions, sizes or rooms, ends up in that group.
- **It doesn't matter how much you import at once.** A folder is grouped the same whether you import it on its own or as part of your whole library.
- **Many maps in one folder works** when their file names tell them apart. Very large flat folders take a little longer to sort out.
- **Splitting a map's versions across distant folders** (for example `Forests/Hut/` and `Swamps/Hut/`) only rejoins identical copies. Other versions stay separate groups; move them together before importing, or merge them afterwards.
- **Renaming files to numbers** (`IMG_0012.jpg`) leaves only the pictures to go on. Identical copies and close versions still join, but different floors of one map won't.
- **Reorganising files after an import doesn't regroup them.** Grouping happens when files are imported; existing groups only change when you edit them.

## Subgroups

Subgroups split a large group into labelled parts, such as the rooms of a dungeon or the floors of a tower. Deeper folders become subgroups on import, and you can set them yourself. They show as sections in the viewer's scene panel; images without one are listed under *Other*.

## Editing Groups

### One Image

From an image tile's **…** menu or the viewer:

- **Move to group…** moves the image to another group, or to a new group of its own. Groups with names like the image's are listed first. There's no undo, but moving it back is the same action.
- **Edit group** opens the group editor.
- Rename the image, change its subgroup, type, grid or tags in the [viewer](/guide/gallery#image-viewer).

### The Group Editor

Open it with **Edit** on a group card, **Edit group** in the viewer, or **Review in editor** from an import report (see [Reviewing an Import](/guide/importing#reviewing-an-import)). When you open several groups, the list on the left holds them and the right side shows the selected group's images.

![The group editor for one group: its author and name, and each variant with its subgroup, type, grid and tags](/screenshots/group-editor.webp)

*"Campfire Stories" by [Fantasy Atlas](https://www.patreon.com/fantasy_atlas), [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), shown in the Scene Atlas group editor.*

In the editor you can:

- rename the group and change its author;
- rename an image by clicking its name;
- **drag images** onto another group in the list, or onto a subgroup;
- select images and use **Move selected to new group** to split them off;
- select images and set their type, grid, subgroup or tags all at once;
- mark images for deletion; they are deleted when the changes are saved, and can be restored until then;
- filter the images by name, type, grid or media to find the ones to change.

In the group list, `Ctrl`/`Cmd`-click selects several groups and `Shift`-click a range. With several selected you can **Merge Selected** into one, or delete them. **Merge All** combines every group in the list.

![The group editor with several groups: the list on the left, and the images of all of them on the right](/screenshots/import-review.webp)

*Map thumbnails by [2-Minute Tabletop](https://2minutetabletop.com), [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).*

### Merging

To join two groups, use **Merge into…** on a group card and search for the group to merge it into. The images keep their tags and subgroups.

### Deleting

**Delete** on a group card deletes the group and all its images. Delete one image from its tile menu or the viewer. Files in a [linked library](/guide/library#linked-library) are never deleted; only Scene Atlas's record of them is.

## Bulk Editing

**Edit all** in the results bar opens every group in the current results in the group editor, so you can tag, type or regroup a whole search at once. For example, search for "snow", then set every result's Season tag to winter.

- It's available in the Groups view when the results hold at most 500 groups. Narrow the search or filters if there are more.
- With a search, only the images that matched are changed. The rest of each group is shown so you can add them one at a time.
- Changes to more than 500 images ask for confirmation first.
- After a bulk change, **Undo** in the notification puts the images back as they were.

Reviewing a very large import (more than 5,000 images) works the same way, but groups load as you scroll and **Everything** applies changes on the server.
