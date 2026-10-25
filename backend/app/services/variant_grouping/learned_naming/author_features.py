"""Author candidates of a group and their features, in the author model's column order."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .. import names as N
from .. import vocab as V
from .text import MAX_SPAN, Tables, author_key, by_credits, mean, word_texts

if TYPE_CHECKING:
    from ..names import Folder
    from .namer import Group, WalkNamer

AUTHOR_SOURCES = ("folder", "by", "known", "house_stem", "rule", "shared", "credit")


@dataclass
class ACand:
    """An author candidate."""

    text: str
    raw: str
    src: set[str]
    folder: dict | None = None
    share: float = 0.0
    top_nonrend: bool = False
    by_share: float = 0.0
    credit_share: float = 0.0
    frag_words: set[str] = field(default_factory=set)


def is_frag_word(t: Tables, c: ACand) -> bool:
    """Whether a credit was cut from a real word ("Ruby" in "RubyGhost")."""
    return any(f and (t.n.get(f, 0) > 0 or f in V.AXIS or f in V.GENERIC) for f in c.frag_words)


class _Candidates:
    """Author candidates by ``author_key``, in order of discovery."""

    def __init__(self, namer: WalkNamer, grp: Group):
        self._namer = namer
        self._grp = grp
        self._n = len(grp.members)
        self.by_key: dict[str, ACand] = {}

    def add(self, text: str | None, src: str, raw: str | None = None) -> ACand | None:
        k = author_key(text) if text else ""
        if not k:
            return None
        c = self.by_key.get(k)
        if c is None:
            c = self.by_key[k] = ACand(text or "", raw or text or "", set())
        c.src.add(src)
        return c

    def display(self, raw: str) -> str:
        """A known author's display name, else the cleaned text."""
        return self._namer.authors.get(author_key(raw)) or self._namer.clean_name(raw) or raw

    def add_counted(self, counts: Counter[str], src: str, name: Callable[[str], str] | None = None):
        """Candidates found in ``counts[raw]`` members."""
        for raw, n in counts.items():
            c = self.add((name or self.display)(raw), src, raw)
            if c is not None:
                c.share = max(c.share, n / self._n)

    def add_folders(self) -> None:
        namer = self._namer
        top = _top_nonrend(namer.files.folders, self._grp.members)
        for prefix, info in self._grp.folders.items():
            name = prefix[-1]
            hit = namer.authors.get(author_key(name))
            ident = [x for x in N.name_identity(name) if not x.isdigit()]
            if not hit and all(x in namer.tables.library_words or x in V.GENERIC for x in ident):
                continue
            c = self.add(self.display(name), "folder", name)
            if c is None:
                continue
            if c.folder is None or (info["share"], -info["depth"]) > (
                c.folder["share"],
                -c.folder["depth"],
            ):
                c.folder = info
            c.share = max(c.share, info["share"])
            c.top_nonrend |= prefix in top

    def add_by(self, by: Counter[str]) -> None:
        for a, n in by.items():
            c = self.add(self._namer.authors.get(author_key(a)) or a, "by")
            if c is not None:
                c.by_share = max(c.by_share, n / self._n)
                c.share = max(c.share, n / self._n)

    def add_credits(self, credits: Counter[str], frags: dict[str, set[str]]) -> None:
        for raw, n in credits.items():
            c = self.add(self.display(raw), "credit", raw)
            if c is not None:
                c.credit_share = max(c.credit_share, n / self._n)
                c.frag_words |= frags[raw]


def author_candidates(namer: WalkNamer, grp: Group) -> tuple[list[ACand], dict]:
    """Author candidates in order of discovery, and the group's author context."""
    members = grp.members
    cands = _Candidates(namer, grp)
    cands.add_folders()
    by: Counter[str] = Counter(a for i in members if (a := namer.by_author[i]))
    cands.add_by(by)
    credits, frags = _credit_counts(namer.files.stems, members)
    cands.add_credits(credits, frags)
    hits = _known_counts(namer, members)
    cands.add_counted(hits, "known", str)
    house = _house_counts(namer, members)
    cands.add_counted(house, "house_stem")
    if grp.rule.author:
        cands.add(namer.authors.get(author_key(grp.rule.author)) or grp.rule.author, "rule")
    if len(namer.groups) >= 5:
        cands.add_counted(_shared_counts(namer, members), "shared")
    flags = {
        "any_by": bool(by),
        "any_known": bool(hits),
        "any_house": bool(house),
        "credit_const": float(len(credits) == 1 and max(credits.values()) == len(members)),
    }
    return list(cands.by_key.values()), flags


def _top_nonrend(folders: Sequence[Folder], members: Sequence[int]) -> set[Folder]:
    """Per member, its raw folders down to the first that isn't a rendition folder."""
    out = set()
    for i in members:
        raw = folders[i]
        k = 0
        while k < len(raw) and N.is_rendition_folder_name(raw[k]):
            k += 1
        if k < len(raw):
            out.add(raw[: k + 1])
    return out


def _credit_counts(
    stems: Sequence[str], members: Sequence[int]
) -> tuple[Counter[str], dict[str, set[str]]]:
    credits: Counter[str] = Counter()
    frags: dict[str, set[str]] = defaultdict(set)
    for i in members:
        for raw, frag in sorted(set(by_credits(stems[i]))):
            credits[raw] += 1
            frags[raw].add(frag)
    return credits, frags


def known_hits(authors: Mapping[str, str], words: list[str]) -> set[str]:
    """Known authors named by a run of 1-3 words (2-letter keys only in capitals)."""
    hits = set()
    for s in range(len(words)):
        for e in range(s + 1, min(len(words), s + 3) + 1):
            k = author_key("".join(words[s:e]))
            if k in authors and (
                len(k) >= 3 or (len(k) == 2 and e - s == 1 and words[s].isupper())
            ):
                hits.add(authors[k])
    return hits


def _known_counts(namer: WalkNamer, members: Sequence[int]) -> Counter[str]:
    hits: Counter[str] = Counter()
    if not namer.authors:
        return hits
    files = namer.files
    for i in members:
        words = [x for f in files.folders[i] for x in word_texts(f)] + word_texts(files.stems[i])
        hits.update(sorted(known_hits(namer.authors, words)))
    return hits


def _house_counts(namer: WalkNamer, members: Sequence[int]) -> Counter[str]:
    """Per member, the leading run of its stem made of house tokens and digits."""
    house: Counter[str] = Counter()
    for i in members:
        st = namer.res.names.stripped[i]
        if not st:
            continue
        stem = namer.files.stems[i]
        spans = N.tokenize_spans(stem)
        k = 0
        while k < len(spans) and (spans[k].text in st or spans[k].text.isdigit()):
            k += 1
        if k:
            house[stem[spans[0].start : spans[k - 1].end]] += 1
    return house


def _shared_counts(namer: WalkNamer, members: Sequence[int]) -> Counter[str]:
    """Per member, the longest leading stem run found in >= 30% of the import's groups."""
    floor = max(3, 0.3 * len(namer.groups))
    shared: Counter[str] = Counter()
    for i in members:
        stem = namer.split_stems[i]
        spans = N.tokenize_spans(stem, split_glued=True)
        best = 0
        for e in range(1, min(len(spans), MAX_SPAN) + 1):
            if len(namer.run_groups.get(tuple(x.text for x in spans[:e]), ())) < floor:
                break
            best = e
        if best and any(x.text.isalpha() and len(x.text) > 2 for x in spans[:best]):
            shared[stem[spans[0].start : spans[best - 1].end]] += 1
    return shared


def author_features(namer: WalkNamer, grp: Group, cands: list[ACand], flags: dict) -> np.ndarray:
    """One row of the 52 author features per candidate."""
    n_groups = len(namer.groups)
    context = [
        math.log(len(grp.members)),
        math.log(n_groups),
        len(grp.common_eff),
        float(flags["any_by"]),
        float(flags["any_known"]),
        float(flags["any_house"]),
        len(grp.folders),
    ]
    rows = []
    for c in cands:
        r = [float(s in c.src) for s in AUTHOR_SOURCES] + [0.0, c.share]
        r += _folder_features(c, n_groups)
        r += _token_features(namer, grp, c, flags)
        rows.append(r + context)
    return np.asarray(rows, dtype=np.float64)


def _folder_features(c: ACand, n_groups: int) -> list[float]:
    f = c.folder
    if f is None:
        return [-1.0] * 17
    return [
        f["depth"],
        f["dist"],
        float(f["is_top"]),
        float(c.top_nonrend),
        float(f["transparent"]),
        float(f["container"]),
        f["reason"],
        float(f["named_after"]),
        f["n_groups"],
        f["n_groups"] / n_groups,
        float(f["known"]),
        f["house"],
        float(f["global_house"]),
        float(f["naming"]),
        float(f["common"]),
        float(f["rendition_name"]),
        float(f["generic"]),
    ]


def _token_features(namer: WalkNamer, grp: Group, c: ACand, flags: dict) -> list[float]:
    known = namer.authors
    k = author_key(c.text)
    toks = N.tokenize(c.raw) or [k]
    scope = namer.scope(grp)
    holders = namer.holders(grp, tuple(toks))
    rule_key = author_key(grp.rule.author) if grp.rule.author else ""
    return [
        *_rate_features(namer, toks),
        float(k in known or author_key(c.raw) in known),
        sum(author_key(x) in known for x in toks if len(x) > 2) / len(toks),
        float(k == rule_key),
        c.by_share,
        sum(x in V.REND or x in V.AXIS or x in V.GENERIC for x in toks) / len(toks),
        (len(holders) - 1) / namer.n_others,
        (len(holders & scope) - 1) / max(1, len(scope) - 1),
        math.log(len(holders)),
        c.credit_share,
        flags["credit_const"] if "credit" in c.src else 0.0,
        float(is_frag_word(namer.tables, c)),
    ]


def _rate_features(namer: WalkNamer, toks: list[str]) -> list[float]:
    df = [namer.group_share(x) for x in toks]
    rates = [namer.tables.rate(x) for x in toks]
    return [
        len(toks),
        mean(df),
        max(df),
        mean([x[1] for x in rates]),
        max(x[1] for x in rates),
        mean([x[0] for x in rates]),
        min(x[2] for x in rates),
        sum(x[2] == 0 for x in rates) / len(rates),
    ]
