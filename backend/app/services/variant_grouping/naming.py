"""Display names, authors and sub-group labels for walk groups, via ``ImageParser``.

A group is named, in order of preference (design/variant-grouping-algorithm.md §8):

1. after the **effective folder it occupies** (its members' deepest common folder) when that
   folder is named after its files, or is a meaningful folder holding exactly this group (below
   the top level, or whose child folders the group joined; see ``GroupNamer._naming_folder``);
2. otherwise after its members' **common identity name**, mapped back onto the original text of
   a file name and cleaned as the parser cleans group names;
3. otherwise (no identity: a numbering) after the first member's own cleaned file stem, so such
   groups stay distinguishable; these names are flagged ``is_identity = False``.

The author is the majority of the members' authors: a folder named after a known author, else a
folder named by a stripped house prefix, else a ``by<Author>`` marker, else the top folder (see
``GroupNamer._file_author``). Every choice breaks ties by sorted order, so names are
deterministic. Names are cleaned, and ``by<Author>`` markers read, by ``ImageParser``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import names as N
from . import vocab as V
from .names import Folder, Token
from .schema import SubLabel, WalkFiles, WalkResult
from .vocab import PART_WORDS

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser


def _most_common(values: Iterable[str]) -> str | None:
    """The most frequent value; ties go to the smallest. None for no values."""
    counts = Counter(values)
    if not counts:
        return None
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _is_rendition_folder_name(name: str) -> bool:
    """A folder named only with rendition / variant words (``Gridded``, ``VTT``, ``Night``):
    a packaging folder, never a creator. A one-letter folder (``A``) does not count."""
    words = [t for t in N.name_tokens(name) if not t.isdigit() and t != V.DIMS and len(t) > 1]
    return bool(words) and all(t in V.REND or t in V.AXIS for t in words)


def _matches(token: str, target: str) -> bool:
    return token == target or (token.isdigit() and target.isdigit() and int(token) == int(target))


def _expand(identity: N.Seq) -> list[str]:
    """Identity tokens as raw tokens: a series token ``vol#4`` is the two tokens ``vol 4``."""
    out: list[str] = []
    for t in identity:
        out.extend(t.split("#") if "#" in t else [t])
    return out


def _identity_span(tokens: Sequence[Token], identity: N.Seq) -> tuple[int, int] | None:
    """Character span of the tightest match of ``identity`` (in order) among ``tokens``."""
    targets = _expand(identity)
    best: tuple[int, int] | None = None
    for s, first in enumerate(tokens):
        if not _matches(first.text, targets[0]):
            continue
        k, end = 1, first.end
        for tok in tokens[s + 1 :]:
            if k == len(targets):
                break
            if _matches(tok.text, targets[k]):
                k, end = k + 1, tok.end
        if k == len(targets) and (best is None or end - first.start < best[1] - best[0]):
            best = (first.start, end)
    return best


def _without_by_author(identity: N.Seq, author: str | None) -> N.Seq:
    """Drop a ``by <Author>`` marker: "Arena_byUpsetti" names the map "Arena"."""
    if not author:
        return identity
    marker = ("by", *N.tokenize(author))
    for k in range(len(identity) - len(marker) + 1):
        if identity[k : k + len(marker)] == marker:
            return identity[:k] + identity[k + len(marker) :]
    return identity


def _without_trailing_parts(identity: N.Seq) -> N.Seq:
    """Drop trailing part words: floors of one map share "Inn Floor", but the map is "Inn"."""
    end = len(identity)
    while end > 1 and identity[end - 1] in PART_WORDS:
        end -= 1
    return identity[:end]


def _level_label(tag: str) -> str:
    """``floor#2`` -> "Floor 2", ``roof`` -> "Roof"."""
    word, _, number = tag.partition("#")
    return f"{word.capitalize()} {number}" if number else word.capitalize()


@dataclass(frozen=True)
class GroupName:
    """A group's display name and author.

    ``is_identity`` is True when the name came from a folder or from identity tokens, False for
    a fallback (a numbering such as ``IMG_0001``): only identity names should be matched against
    existing gallery groups.
    """

    name: str
    author: str | None
    is_identity: bool


class GroupNamer:
    """Names, authors and sub-group labels for the groups of one walk."""

    def __init__(
        self,
        parser: ImageParser,
        result: WalkResult,
        files: WalkFiles,
        paths: Sequence[str],
        known_authors: Mapping[str, str],
    ):
        """``known_authors``: creators already in the library, by ``names.name_key``."""
        self._parser = parser
        self._result = result
        self._files = files
        self._paths = paths
        self._known = known_authors

    def _clean(self, raw: str, author: str | None = None) -> str:
        """A folder or name fragment cleaned exactly as the parser cleans group names."""
        return self._parser.clean_group_name(raw, author)

    def _known_author(self, folder_name: str) -> str | None:
        """The known author a folder is named after, if any."""
        return self._known.get(N.name_key(folder_name)) or self._known.get(
            N.name_key(self._clean(folder_name))
        )

    def _naming_folder(self, members: Sequence[int]) -> Folder | None:
        """Rule 1: the effective folder that names the group, if any.

        The folder the members share names the group when it is named after its files, when
        it is a variant-only folder (a6) holding exactly this group, or when it is a meaningful
        folder holding exactly this group *and* is either below the top level or the parent whose
        child folders the group joined. A top-level folder holding a single map is usually its
        creator's (``2mtt/Grand Inn - Floor 1.png``), so there the file names (rule 2) name the
        group.
        """
        eff = self._result.effective
        folder = N.common_prefix(eff[i] for i in members)
        verdict = self._result.folders.get(folder)
        if not folder or verdict is None:
            return None
        raw = self._result.tree.raw_names.get(folder, set())
        if any(self._known_author(name) for name in raw):
            return None  # a creator's folder, never a map's name
        if verdict.named_after_files:
            return folder
        if verdict.variant_only and verdict.files == len(members):
            return folder  # a6: the folder is the map and its files have no names
        holds_only_this = not verdict.container and verdict.files == len(members)
        if holds_only_this and (len(folder) >= 2 or self._joined_children(members, folder)):
            return folder
        return None

    def _joined_children(self, members: Sequence[int], folder: Folder) -> bool:
        """Whether the group's sub-groups are child folders of ``folder`` (it joined them)."""
        labels = (self._result.sublabel[i] for i in members)
        return any(
            label is not None and label.kind == "folder" and label.value[:-1] == folder
            for label in labels
        )

    def _folder_display(self, folder: Folder, author: str | None) -> str:
        raw = sorted(self._result.tree.raw_names.get(folder, ())) or [folder[-1]]
        return _most_common(self._clean(r, author) for r in raw) or folder[-1]

    def _author(self, members: Sequence[int], folder: Folder | None, name: str) -> str | None:
        """Majority of the members' authors (ties: a named author, then the smallest)."""
        counts = Counter(self._file_author(i, folder, name) for i in members)
        return min(counts.items(), key=lambda kv: (-kv[1], kv[0] is None, kv[0] or ""))[0]

    def _file_author(self, i: int, folder: Folder | None, name: str) -> str | None:
        """One file's author, in order of preference:

        1. an enclosing folder named after a known author (as ``compute_plan`` passes them);
        2. an enclosing folder named by a house prefix stripped from the file's name
           (``Woods/Moonlight Maps/…/Moonlight_Maps_…`` -> "Moonlight Maps", not "Woods");
        3. a ``by<Author>`` marker in the file name;
        4. the top folder (today's parser), skipping leading rendition folders (``Gridded/``).

        The folder that names the group (``folder``, or a folder whose cleaned name is the
        group's ``name``) is the map's, never its author: then there is none. A file at the
        root has no folder author.
        """
        tree = self._result.tree
        raw = self._files.folders[i]
        # the file's folders that are not transparent (each starts a new effective folder)
        kept = [
            raw[d - 1]
            for d in range(1, len(raw) + 1)
            if tree.effective_of[raw[:d]] != tree.effective_of[raw[: d - 1]]
        ]
        for folder_name in kept:
            known = self._known_author(folder_name)
            if known is not None:
                return known
        stripped = self._result.names.stripped[i]
        for folder_name in kept:
            tokens = set(N.name_identity(folder_name))
            if tokens and tokens <= stripped:
                return folder_name
        _, file_name = N.split_path(self._paths[i])
        by_author = self._parser.author_from_stem(N.file_stem(file_name))
        if by_author is not None:
            return by_author
        top = 0
        while top < len(raw) and _is_rendition_folder_name(raw[top]):
            top += 1
        if top == len(raw):
            return None
        names_group = (folder is not None and tree.effective_of[raw[: top + 1]] == folder) or (
            N.name_key(self._clean(raw[top])) == N.name_key(name)
        )
        return None if names_group else raw[top]

    def _identity_name(self, members: Sequence[int], author: str | None) -> str | None:
        """Rule 2: the members' common identity, in a file name's own spelling, cleaned."""
        full = self._result.names.full
        named = [i for i in members if full[i] is not None]
        if not named:
            return None
        prefix = N.common_prefix(full[i] or () for i in named)
        prefix = _without_trailing_parts(_without_by_author(prefix, author))
        if not prefix:
            return None
        fragments: Counter[str] = Counter()
        for i in named:
            stem = self._files.stems[i]
            span = _identity_span(N.tokenize_spans(stem, split_glued=True), prefix)
            if span is not None:
                fragments[stem[span[0] : span[1]]] += 1
        cleaned: Counter[str] = Counter()
        for fragment, count in fragments.items():  # members mostly share one spelling
            name = self._clean(fragment, author)
            if name:
                cleaned[name] += count
        return _most_common(cleaned.elements())

    def _display(
        self, members: Sequence[int], folder: Folder | None, author: str | None
    ) -> tuple[str, bool]:
        """(display name, is it an identity name) by rules 1-3."""
        if folder is not None:
            return self._folder_display(folder, author), True
        name = self._identity_name(members, author)
        if name is not None:
            return name, True
        # No identity (a numbering): the first file's own cleaned stem keeps groups apart.
        stem = self._files.stems[members[0]]
        return self._clean(stem, author) or stem, False

    def name(self, members: Sequence[int]) -> GroupName:
        """Display name and author of a group given its members (walk indices, path order).

        The author is chosen against the name (a folder naming the group is not its author),
        and the name is then cleaned with the author (a leading author prefix is dropped).
        """
        folder = self._naming_folder(members)
        provisional, _ = self._display(members, folder, None)
        author = self._author(members, folder, provisional)
        name, is_identity = self._display(members, folder, author)
        return GroupName(name, author, is_identity)

    def subgroup_label(self, label: SubLabel) -> str:
        """Display text of a sub-group label."""
        if isinstance(label.value, tuple):
            return self._folder_display(label.value, None)
        return _level_label(label.value)
