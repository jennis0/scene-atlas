"""Name evidence: tokens, identity names, house prefixes and level tags (design/variant-grouping-algorithm.md §4).

A file's *identity* is the part of its name that says which map it is: its tokens minus variant,
rendition and size words, numbers and stopwords. Before identities are compared, tokens that
carry no identity in this input are stripped:

- **globally**, tokens in nearly every file when many different names remain without them (a
  collection prefix such as ``myvaultMaps_…``), and house "hubs": a leading token run followed
  by many different maps (``moonlight maps …``);
- **per folder** (folder IDF), tokens in >= 80% of a folder's files are judged: a *house
  prefix* when many distinct multi-token names remain after them (strip), or *the map's name*
  when only variant words remain (keep, as evidence that the folder is one map).

Families of numbered files with no name (``IMG_0012``, ``NumberedGLMaps_52``) carry no identity.
"""

from __future__ import annotations

import functools
import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from . import vocab as V

# A name as identity tokens, and a folder as its path components.
Seq = tuple[str, ...]
Folder = tuple[str, ...]

_COPY_SUFFIX_RE = re.compile(r"\s*\((\d+)\)$")  # OS copy suffix: "name (2)"
_BRACKET_RE = re.compile(r"\[[^\]]*\]")  # "[forest,road]" tag lists carry no identity
_DIMS_RE = re.compile(r"(?<![0-9])(\d{1,3})[ _\-]?[xX×][ _\-]?(\d{1,3})(?![0-9])")
# One token: an upper-case run (not followed by lower case), a capitalised or lower-case word, or
# digits: a split at case changes, letter/digit boundaries and punctuation.
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_NXM_RE = re.compile(r"(?<![0-9])(\d{1,3})\s*[xX×]\s*(\d{1,3})(?![0-9])")
_DIGITS_RE = re.compile(r"\d+")
# Distinct folder names whose tokens are cached (a library has a few thousand).
_NAME_CACHE = 1 << 16

# Folder-IDF: a token in >= this share of a scope's named files is "common" there.
COMMON_SHARE = 0.8
# Global strip only runs on inputs this large (a small import has no house prefix to learn).
GLOBAL_MIN_NAMED = 20
# Global strip: at least this many distinct 2-token residual keys must remain.
GLOBAL_MIN_RESIDUAL_KEYS = 10
# House-vs-map-name test: share of files whose residual is itself a multi-token name.
MULTI_TOKEN_SHARE = 0.5
# Per-folder house test: at least this many distinct residual keys.
FOLDER_MIN_KEYS = 2
# A global house hub must span this many effective folders: a single multi-part map
# (``modular caves …``) lives in one folder, a house prefix spans many.
HUB_MIN_FOLDERS = 3
# find_hubs: a continuation is "heavy" (a map with variants, not a single rendition) with this many
# distinct names below it, and a hub needs this many heavy continuations.
HUB_HEAVY_NAMES = 4
HUB_FANOUT = 6
# One-token lead hubs over the whole input: first token of >= 25% of files, >= 10 continuations,
# spanning >= 5 folders (a bundle's prefix inside folders that mix makers).
GLOBAL_LEAD_COVER = 0.25
GLOBAL_LEAD_FANOUT = 10
GLOBAL_LEAD_MIN_FOLDERS = 5
# Per-folder hub stripping only in folders this large, with lead hubs at 40% cover, fan-out 6.
FOLDER_HUB_MIN_FILES = 20
FOLDER_LEAD_COVER = 0.4
FOLDER_LEAD_FANOUT = 6
# A lead hub's continuation counts when it starts at least this many files.
LEAD_MIN_FILES = 2
# Generic numbered families: >= 6 files sharing a key whose names differ only by numbers.
GENERIC_FAMILY_MIN = 6
GENERIC_FAMILY_SHARE = 0.8


# ----------------------------------------------------------------------------- tokens


class Token(NamedTuple):
    """A lower-case token and its character span in the source text."""

    text: str
    start: int
    end: int


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group(0))


# Shortest vocabulary word a glued token may be split into
_GLUE_MIN = 2


@functools.lru_cache(maxsize=_NAME_CACHE)
def _glued_parts(tok: str) -> tuple[str, ...] | None:
    """A lower-case run glued from rendition and variant words (``ungriddedprint``,
    ``printgridless``, ``vttgrid``): its parts, when the whole token is a sequence of such words
    with at least one rendition word, else None. Only whole decompositions count, so map names
    keep their letters, and the rendition word keeps variant compounds (``firelight``) whole."""
    if tok in V.REND or tok in V.AXIS or len(tok) < 2 * _GLUE_MIN:
        return None
    vocab = V.REND | V.AXIS
    best: dict[int, tuple[str, ...]] = {0: ()}  # end -> fewest words spelling tok[:end]
    for end in range(1, len(tok) + 1):
        for start in range(max(0, end - 12), end - _GLUE_MIN + 1):
            if start in best and tok[start:end] in vocab:
                candidate = (*best[start], tok[start:end])
                if end not in best or len(candidate) < len(best[end]):
                    best[end] = candidate
    parts = best.get(len(tok))
    if not parts or len(parts) < 2 or not any(t in V.REND for t in parts):
        return None
    return parts


def _split_glued(tokens: list[Token], text: str) -> list[Token]:
    """Split glued rendition suffixes (``_glued_parts``), and re-split an upper-case rendition
    run glued to a lower-case word: the word pattern reads ``GDprint`` as ``g`` + ``dprint``;
    it is ``gd`` + ``print`` when ``gd`` is a rendition word and ``print`` is one or decomposes
    into them."""
    out: list[Token] = []
    k = 0
    while k < len(tokens):
        t = tokens[k]
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if (
            nxt is not None
            and t.end == nxt.start
            and text[t.start : t.end].isupper()
            and text[t.start : t.end].isalpha()
            and len(nxt.text) > 2
            and text[nxt.start].isupper()
            and text[nxt.start + 1 : nxt.end].islower()
        ):
            head, rest = t.text + nxt.text[0], nxt.text[1:]
            if head in V.REND and (rest in V.REND or rest in V.AXIS or _glued_parts(rest)):
                out.append(Token(head, t.start, nxt.start + 1))
                t = Token(rest, nxt.start + 1, nxt.end)
                k += 1
        parts = _glued_parts(t.text) if t.text.isalpha() else None
        if parts:
            pos = t.start
            for part in parts:
                out.append(Token(part, pos, pos + len(part)))
                pos += len(part)
        else:
            out.append(t)
        k += 1
    return out


def tokenize_spans(text: str, split_glued: bool = False) -> list[Token]:
    """Tokens of a file stem or folder name, with spans.

    Bracketed tag lists are ignored, an ``NxM`` size becomes the ``DIMS`` marker, words split at
    case changes and letter/digit boundaries, ordinal suffixes are dropped after a number
    ("1st" -> "1") and split platform names are glued back ("Roll20"). ``split_glued`` (file
    stems) also splits rendition suffixes glued onto words (``GDprint``, ``Ungriddedvtt``). Spans
    let naming map identity tokens back to the original text.
    """
    masked = _BRACKET_RE.sub(_blank, text) if "[" in text else text
    found = [(m.start(), m.end(), V.DIMS) for m in _DIMS_RE.finditer(masked)]
    if found:
        masked = _DIMS_RE.sub(_blank, masked)
    found.extend((m.start(), m.end(), m.group(0).lower()) for m in _WORD_RE.finditer(masked))
    found.sort()
    out: list[Token] = []
    for start, end, tok in found:
        if out and out[-1].text.isdigit() and tok in V.ORDINAL_SUFFIXES:
            out[-1] = Token(out[-1].text, out[-1].start, end)
            continue
        if out and tok.isdigit() and (out[-1].text, tok) in V.GLUED_PAIRS:
            out[-1] = Token(out[-1].text + tok, out[-1].start, end)
            continue
        out.append(Token(tok, start, end))
    return _split_glued(out, text) if split_glued else out


def tokenize(text: str, split_glued: bool = False) -> list[str]:
    """Lower-case tokens of ``text`` (see ``tokenize_spans``)."""
    return [t.text for t in tokenize_spans(text, split_glued)]


@functools.lru_cache(maxsize=_NAME_CACHE)
def name_tokens(name: str) -> tuple[str, ...]:
    """Tokens of a folder name, cached: the tree and the walk ask for the same names often."""
    return tuple(tokenize(name))


@functools.lru_cache(maxsize=_NAME_CACHE)
def name_identity(name: str) -> Seq:
    """Identity tokens of a folder name, cached."""
    return identity_tokens(name_tokens(name))


def is_rendition_folder_name(name: str) -> bool:
    """A folder named only with rendition / variant words (``Gridded``, ``VTT``, ``Night``):
    a packaging folder, never a creator. A one-letter folder (``A``) does not count."""
    words = [t for t in name_tokens(name) if not t.isdigit() and t != V.DIMS and len(t) > 1]
    return bool(words) and all(t in V.REND or t in V.AXIS for t in words)


def file_stem(file_name: str) -> str:
    """A file name without its extension and OS copy suffix ("Map (2).jpg" -> "Map")."""
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    m = _COPY_SUFFIX_RE.search(stem)
    return stem[: m.start()] if m else stem


def split_path(path: str) -> tuple[Folder, str]:
    """(folder components, file name) of a "/"-separated relative path ("" and "." dropped)."""
    parts = [p for p in path.split("/") if p and p != "."]
    return tuple(parts[:-1]), parts[-1] if parts else ""


def name_key(text: str) -> str:
    """Letters and digits only, case-folded: "Moonlight Maps" matches "moonlightmaps" (as
    ``ImageParser`` compares creators)."""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def common_prefix(seqs: Iterable[Sequence[str]]) -> tuple[str, ...]:
    """The longest common prefix of one or more token sequences or folders."""
    it = iter(seqs)
    prefix = tuple(next(it))
    for seq in it:
        k = 0
        while k < min(len(prefix), len(seq)) and prefix[k] == seq[k]:
            k += 1
        prefix = prefix[:k]
    return prefix


def nxm_of(stem: str) -> tuple[int, int] | None:
    """The ``NxM`` size named in a stem, sorted (12x18 == 18x12), for the production fingerprint."""
    m = _NXM_RE.search(stem)
    if not m:
        return None
    a, b = sorted((int(m.group(1)), int(m.group(2))))
    return (a, b)


# ----------------------------------------------------------------------------- identity


def drop_grid_phrases(toks: Sequence[str]) -> list[str]:
    """Drop the function word of a grid phrase ("no grid", "with lines")."""
    return [
        t
        for k, t in enumerate(toks)
        if not (t in V.PHRASE_HEADS and k + 1 < len(toks) and toks[k + 1] in V.GRID_WORDS)
    ]


def _drop_library_words(toks: list[str]) -> list[str]:
    """Drop "battlemaps" and the pair "battle maps": library words, not identity."""
    out = []
    for k, t in enumerate(toks):
        if t in V.NOID:
            continue
        if t == "battle" and k + 1 < len(toks) and toks[k + 1] in ("maps", "map"):
            continue
        if t in ("maps", "map") and k and toks[k - 1] == "battle":
            continue
        out.append(t)
    return out


def identity_tokens(toks: Sequence[str]) -> Seq:
    """Identity-bearing tokens of a name, in order.

    Axis, rendition and size words, numbers, stopwords and one-letter tokens are dropped, and a
    repeated token is kept once ("leasealair maps leasealair maps"). A number after a series word
    is glued to it (``vol#4``): different volumes are different maps.
    """
    words = _drop_library_words(drop_grid_phrases(toks))
    out: list[str] = []
    for k, t in enumerate(words):
        prev = words[k - 1] if k else None
        if t.isdigit() and prev in V.SERIES and out and out[-1] == prev:
            out[-1] = f"{prev}#{int(t)}"
            continue
        if (
            t == V.DIMS
            or t.isdigit()
            or t in V.STOPWORDS
            or t in V.AXIS
            or t in V.REND
            or len(t) < 2
            or t in out
        ):
            continue
        out.append(t)
    return tuple(out)


def strip_level_suffix(seq: Seq) -> Seq:
    """Cut a trailing level designator from a file's identity ("inn basement" -> "inn",
    "heather house upper level" -> "heather house"): it names a floor of the map, not the map.

    Only a trailing run that holds a level noun is cut, so "hill top" stays. Floors of a one-word
    map ("Inn_Basement", "Inn_Roof") so share an identity and join by name, with level
    sub-groups; 1-token keys still never join as a shared base.
    """
    end = len(seq)
    has_noun = False
    while end > 0 and (seq[end - 1] in V.LEVEL_NOUNS or seq[end - 1] in V.LEVEL_QUALIFIERS):
        has_noun |= seq[end - 1] in V.LEVEL_NOUNS
        end -= 1
    return seq[:end] if has_noun else seq


def series_of(seq: Seq) -> frozenset[str]:
    """The series tokens (``vol#4``) of an identity: different series are different maps."""
    return frozenset(t for t in seq if "#" in t)


def collapse_repeats(seq: Iterable[str]) -> Seq:
    """Collapse consecutive repeats, left behind when tokens between them were stripped."""
    out: list[str] = []
    for t in seq:
        if not out or out[-1] != t:
            out.append(t)
    return tuple(out)


def level_numbers(toks: Sequence[str]) -> tuple[str, ...]:
    """Numbers that name a floor, level or part (``Floor 2`` -> ``floor#2``).

    Names that agree apart from these are layouts of one map: they join as different levels.
    """
    return tuple(
        f"{toks[k - 1]}#{int(t)}"
        for k, t in enumerate(toks)
        if t.isdigit() and k and toks[k - 1] in V.LEVEL
    )


def level_tag(toks: Sequence[str]) -> str | None:
    """The floor, level or part a file name names (``floor#2``, ``roof``), else None.

    Sub-group labels come from these when no joined child folder gives one.
    """
    numbered = level_numbers(toks)
    if numbered:
        return numbered[0]
    for k, t in enumerate(toks):
        if t in ("floor", "level") and k and toks[k - 1] in V.ORDINALS:
            return f"floor#{V.ORDINALS[toks[k - 1]]}"
        if t.isdigit() and k + 1 < len(toks) and toks[k + 1] in ("floor", "level"):
            return f"floor#{int(t)}"
    return next((t for t in toks if t in V.LEVEL_WORDS), None)


# ----------------------------------------------------------------------------- folder classes


class FolderClass(Enum):
    """How a folder's name relates to the maps below it."""

    RENDITION = "rendition"  # grid / format / size / platform words, or parent name + such words
    VARIANT = "variant"  # variant-axis words only ("Night", "Gridded Winter")
    GENERIC = "generic"  # library words only ("Maps", "Pack 03", "New folder (2)")
    SPECIFIC = "specific"  # anything else: may name a map, a maker or a topic


def folder_class(name: str, parent_tokens: set[str]) -> tuple[FolderClass, Seq]:
    """(class, core identity tokens) of a folder name.

    ``parent_tokens`` are the identity tokens of its parent and grandparent: a folder repeating
    its parent's name plus rendition words (``Beast Prison 12x12`` under ``Beast Prison``) is a
    rendition folder. The core is the name's identity tokens minus the parent's.
    """
    core = tuple(
        t
        for t in drop_grid_phrases(name_tokens(name))
        if t != V.DIMS
        and not t.isdigit()
        and t not in V.STOPWORDS
        and len(t) > 1
        and t not in parent_tokens
    )
    if all(t in V.REND for t in core):  # also an empty core
        return FolderClass.RENDITION, ()
    if all(t in V.REND or t in V.AXIS for t in core):
        return FolderClass.VARIANT, ()
    ident = tuple(t for t in core if t not in V.REND and t not in V.AXIS)
    if all(t in V.GENERIC for t in ident):
        return FolderClass.GENERIC, ident
    return FolderClass.SPECIFIC, ident


# ----------------------------------------------------------------------------- hubs


def strip_hub(seq: Seq, hubs: set[Seq]) -> Seq:
    """Remove the shortest hub prefix (up to 3 tokens), never the whole name."""
    for k in range(1, min(len(seq) - 1, 3) + 1):
        if seq[:k] in hubs:
            return seq[k:]
    return seq


def find_hubs(seqs: Sequence[Seq]) -> set[Seq]:
    """Multi-token leading runs followed by many different *heavy* continuations.

    A house prefix (``moonlight maps …``) precedes dozens of different maps; a map's own name
    precedes a handful of variant words. A continuation is heavy when >= ``HUB_HEAVY_NAMES``
    distinct names sit below it (a map with variants, not a single rendition). One-token
    prefixes are ``lead_hubs``'.
    """
    below: dict[Seq, dict[str, set[Seq]]] = defaultdict(lambda: defaultdict(set))
    for seq in seqs:
        for k in range(2, min(len(seq) - 1, 3) + 1):
            below[seq[:k]][seq[k]].add(seq)
    return {
        prefix
        for prefix, conts in below.items()
        if sum(len(names) >= HUB_HEAVY_NAMES for names in conts.values()) >= HUB_FANOUT
    }


def lead_hubs(seqs: Sequence[Seq], cover: float, fanout: int) -> set[Seq]:
    """One-token house prefixes (``czepeku city streets …``, ``tc forest …``).

    The first token of >= ``cover`` of the multi-token names, followed by >= ``fanout``
    different next tokens that each start >= ``LEAD_MIN_FILES`` files. A family word
    (``forest``) leads too few files to qualify.
    """
    named = [s for s in seqs if len(s) >= 2]
    first = Counter(s[0] for s in named)
    out: set[Seq] = set()
    for tok, count in first.items():
        if count < cover * len(named):
            continue
        nxt = Counter(s[1] for s in named if s[0] == tok)
        if sum(v >= LEAD_MIN_FILES for v in nxt.values()) >= fanout:
            out.add((tok,))
    return out


def common_tokens(named: Sequence[Seq]) -> set[str]:
    """Tokens in >= ``COMMON_SHARE`` of ``named`` (folder IDF)."""
    df = Counter(t for s in named for t in set(s))
    return {t for t, c in df.items() if c >= COMMON_SHARE * len(named)}


def _without(seqs: Sequence[Seq], tokens: Collection[str]) -> list[Seq]:
    return [tuple(t for t in s if t not in tokens) for s in seqs]


def _is_house_prefix(residuals: Sequence[Seq], min_keys: int, min_key_tokens: int = 1) -> bool:
    """Whether the tokens just removed from some names are a house prefix: at least
    ``min_keys`` distinct 2-token keys remain (counting residuals of >= ``min_key_tokens``
    tokens), and most residuals are multi-token names (identities, not variant words)."""
    keys = {r[:2] for r in residuals if len(r) >= min_key_tokens}
    multi = sum(len(r) >= 2 for r in residuals) / max(1, len(residuals))
    return len(keys) >= min_keys and multi >= MULTI_TOKEN_SHARE


def global_strip(seqs: list[Seq], folders: list[Folder]) -> tuple[list[Seq], set[str], set[Seq]]:
    """Strip input-wide house tokens: (new identities, removed tokens, hubs).

    Tokens in >= 80% of all named files go only when many multi-token names remain without them:
    a single imported map (``young adventurers hideout …`` in every file) must keep its name.
    House hubs must span >= ``HUB_MIN_FOLDERS`` folders.
    """
    named = [s for s in seqs if s]
    removed: set[str] = set()
    if len(named) >= GLOBAL_MIN_NAMED:
        cand = common_tokens(named)
        if cand and _is_house_prefix(_without(named, cand), GLOBAL_MIN_RESIDUAL_KEYS):
            removed = cand
    seqs = [collapse_repeats(t for t in s if t not in removed) for s in seqs]
    hubs = find_hubs(seqs)
    span: dict[Seq, set[Folder]] = defaultdict(set)
    for seq, folder in zip(seqs, folders, strict=True):
        for k in range(1, min(len(seq), 3) + 1):
            if seq[:k] in hubs:
                span[seq[:k]].add(folder)
    hubs = {h for h in hubs if len(span[h]) >= HUB_MIN_FOLDERS}
    return [strip_hub(s, hubs) for s in seqs], removed, hubs


@dataclass
class FolderNames:
    """Folder-IDF verdict on one effective folder's own files."""

    common: Seq = ()  # tokens in >= 80% of the named files, in name order
    house: bool = False  # ``common`` is a house / collection prefix: stripped
    named_map: bool = False  # ``common`` (>= 2 tokens) is the map's name: folder-is-one-map

    def describe(self) -> str:
        """Short text for the decision log."""
        if not self.common:
            return "common -"
        verdict = " = house prefix" if self.house else " = map name" if self.named_map else ""
        return "common " + " ".join(self.common) + verdict


def folder_names(seqs: list[Seq]) -> tuple[list[Seq], FolderNames]:
    """Folder-IDF stripping for one folder's own files: (new identities, verdict).

    With C the tokens common to >= 80% of the named files: if the residuals are several
    multi-token names, C is a house prefix and is stripped; if they are empty or one variant-like
    word, C (>= 2 tokens) is the map's name and is kept as positive evidence. Files with an empty
    residual count against "house" (a one-map folder with two floor names).
    """
    named = [s for s in seqs if s]
    info = FolderNames()
    if len(named) < 3:
        return seqs, info
    common = common_tokens(named)
    if not common:
        return seqs, info
    position: Counter[str] = Counter()
    for seq in named:
        for k, t in enumerate(seq):
            if t in common:
                position[t] += k
    info.common = tuple(sorted(common, key=lambda t: (position[t], t)))
    if _is_house_prefix(_without(named, common), FOLDER_MIN_KEYS):
        info.house = True
        return [collapse_repeats(s) for s in _without(seqs, common)], info
    info.named_map = len(info.common) >= 2
    return seqs, info


def folder_hubs(seqs: list[Seq], common: Seq) -> set[Seq]:
    """House hubs inside one folder (``moonlight maps`` in a flat dump of many makers), never the
    folder's own common name."""
    keep = set(common)
    return {h for h in find_hubs(seqs) if not set(h) <= keep}


def generic_keys(keys: Sequence[Seq | None], stems: Sequence[str]) -> set[Seq]:
    """Keys that carry no identity: a numbering, not a map name.

    Shared by >= ``GENERIC_FAMILY_MIN`` files whose names are the same apart from numbers
    (``NumberedGLMaps_52``, ``IMG_00012``), and mostly distinct.
    """
    family: dict[Seq, list[int]] = defaultdict(list)
    for k, key in enumerate(keys):
        if key:
            family[key].append(k)
    out: set[Seq] = set()
    for key, idx in family.items():
        if len(idx) < GENERIC_FAMILY_MIN:
            continue
        numbered = Counter(_DIGITS_RE.sub("#", stems[i].lower()) for i in idx)
        distinct = len({stems[i] for i in idx})
        need = GENERIC_FAMILY_SHARE * len(idx)
        if numbered.most_common(1)[0][1] >= need and distinct >= need:
            out.add(key)
    return out


# ----------------------------------------------------------------------------- per-file evidence


@dataclass
class NameEvidence:
    """Name evidence for every file of one grouping run, indexed like the walk's files.

    ``full`` is a file's identity after global and folder stripping (None: no usable name, or a
    generic numbering), ``named`` whether any identity survived stripping (numbering included),
    ``key2`` the first two tokens of ``full`` (the shared-base key), ``cross_tree`` the globally
    stripped identity used for cross-tree suggestions. ``variant_only`` marks files whose name
    has no identity at all (``Night.webp``, ``1st_Floor.png``), ``stripped`` the house-prefix
    tokens removed from each file's name (naming uses them to find the creator's folder).
    """

    full: list[Seq | None]
    named: list[bool]
    variant_only: list[bool]
    veto_key: list[Seq | None]
    stripped: list[frozenset[str]]
    key2: list[Seq | None]
    cross_tree: list[Seq | None]
    series: list[frozenset[str]]
    levels: list[tuple[str, ...]]
    folder_info: dict[Folder, FolderNames]
    common_raw: dict[Folder, set[str]]  # per folder: tokens common before any stripping
    global_house: set[str]  # tokens of global house prefixes and hubs

    def unstripped(self, i: int) -> set[str]:
        """A file's identity tokens with those the prefix strip removed put back: a folder's
        common name may be exactly what was stripped (a lone ``monster-hunter-restaurant/``
        map, whose files all start with ``monster hunter``)."""
        return set(self.full[i] or ()) | self.stripped[i]

    def contradict(self, x: int, y: int) -> bool:
        """Names say different maps: different series, or two different 2-token keys.

        The keys keep the level designator cut from the identity (``veto_key``), so cutting
        levels does not weaken the veto: "Warehouse - Roof" and "Spell Scroll Store - Roof" stay apart even
        though "warehouse" alone has no 2-token key.
        """
        sx, sy = self.series[x], self.series[y]
        if sx and sy and sx != sy:
            return True
        kx, ky = self.veto_key[x], self.veto_key[y]
        return kx is not None and ky is not None and kx != ky


def _strip_global_lead_hubs(seqs: list[Seq], folders: list[Folder]) -> tuple[list[Seq], set[Seq]]:
    """Strip one-token house prefixes that cover a quarter of the input across many folders."""
    hubs = lead_hubs(seqs, GLOBAL_LEAD_COVER, GLOBAL_LEAD_FANOUT)
    span: dict[Seq, set[Folder]] = defaultdict(set)
    for seq, folder in zip(seqs, folders, strict=True):
        if seq and (seq[0],) in hubs:
            span[(seq[0],)].add(folder)
    hubs = {h for h in hubs if len(span[h]) >= GLOBAL_LEAD_MIN_FOLDERS}
    if hubs:
        seqs = [strip_hub(s, hubs) for s in seqs]
    return seqs, hubs


def _strip_folder(seqs: list[Seq]) -> tuple[list[Seq], FolderNames]:
    """Folder IDF, then (in a big folder that is not a house bundle) nested hubs."""
    new, info = folder_names(seqs)
    if not info.house and len(seqs) >= FOLDER_HUB_MIN_FILES:
        own_name = info.common if info.named_map else ()
        hubs = folder_hubs([s for s in new if s], own_name)
        hubs |= {
            h
            for h in lead_hubs(new, FOLDER_LEAD_COVER, FOLDER_LEAD_FANOUT)
            if not (info.named_map and set(h) <= set(info.common))
        }
        if hubs:
            new = [strip_hub(s, hubs) for s in new]
    return new, info


def _strip_folder_name_keys(seqs: list[Seq], folders: list[Folder]) -> list[Seq]:
    """Strip a shared 2-token base that is only an enclosing folder's name, when it prefixes
    several different maps.

    ``Moonlight Maps/{Forest Cottage,Forest Switch}/Moonlight_Maps_…``: the key ``moonlight
    maps`` is the maker's folder, and after it come >= 2 distinct multi-token names, so it is a
    house prefix, generalising the folder-IDF test to small folders (where hub detection has too
    few files). If only variant words follow, the key is the map's name and stays.
    """
    subtree: dict[Folder, list[int]] = defaultdict(list)
    for i, folder in enumerate(folders):
        for d in range(1, len(folder) + 1):
            subtree[folder[:d]].append(i)
    out = list(seqs)
    for folder in sorted(subtree, key=lambda f: (len(f), f)):
        name = set(name_identity(folder[-1]))
        if len(name) < 2:
            continue
        family: dict[Seq, list[int]] = defaultdict(list)
        for i in subtree[folder]:
            if len(out[i]) >= 2 and set(out[i][:2]) <= name:
                family[out[i][:2]].append(i)
        for key, idx in family.items():
            resid = _without([out[i] for i in idx], key)
            if _is_house_prefix(resid, FOLDER_MIN_KEYS, min_key_tokens=2):
                for i, r in zip(idx, resid, strict=True):
                    out[i] = collapse_repeats(r)
    return out


def analyse_names(
    tokens: Sequence[Sequence[str]], stems: Sequence[str], folders: list[Folder]
) -> NameEvidence:
    """Name evidence for files given their stem tokens, stems and effective folders."""
    raw_identity = [identity_tokens(t) for t in tokens]
    named0 = [strip_level_suffix(s) for s in raw_identity]
    level_suffix = [r[len(s) :] for r, s in zip(raw_identity, named0, strict=True)]
    # a counter name (IMG_0012) is no identity; it is not a variant name either (a6 ignores it)
    seq0 = [() if len(s) == 1 and s[0] in V.COUNTER_WORDS else s for s in named0]
    seq1, removed, hubs = global_strip(seq0, folders)
    seq1, lead = _strip_global_lead_hubs(seq1, folders)
    global_house = removed | {t for h in hubs | lead for t in h}

    by_folder: dict[Folder, list[int]] = defaultdict(list)
    for i, folder in enumerate(folders):
        by_folder[folder].append(i)

    common_raw: dict[Folder, set[str]] = {}
    for folder, idx in by_folder.items():
        named = [seq0[i] for i in idx if seq0[i]]
        if len(named) >= 2:
            common_raw[folder] = common_tokens(named)

    seq = list(seq1)
    folder_info: dict[Folder, FolderNames] = {}
    for folder, idx in by_folder.items():
        new, info = _strip_folder([seq1[i] for i in idx])
        folder_info[folder] = info
        for i, s in zip(idx, new, strict=True):
            seq[i] = s
    seq = _strip_folder_name_keys(seq, folders)

    full: list[Seq | None] = [s or None for s in seq]
    for idx in by_folder.values():
        numbered = generic_keys([full[i] for i in idx], [stems[i] for i in idx])
        for i in idx:
            if full[i] in numbered:
                full[i] = None
    veto: list[Seq | None] = []
    for f, suffix in zip(full, level_suffix, strict=True):
        key = None if f is None else (f + suffix)[:2]
        veto.append(key if key is not None and len(key) >= 2 else None)
    return NameEvidence(
        full=full,
        veto_key=veto,
        named=[bool(s) for s in seq],
        variant_only=[not s for s in named0],
        stripped=[frozenset(set(a) - set(b)) for a, b in zip(seq0, seq, strict=True)],
        key2=[s[:2] if s is not None and len(s) >= 2 else None for s in full],
        cross_tree=[s if len(s) >= 2 else None for s in seq1],
        series=[series_of(s) for s in seq],
        levels=[level_numbers(t) for t in tokens],
        folder_info=folder_info,
        common_raw=common_raw,
        global_house=global_house,
    )
