"""Name candidates of a group and their features, in the models' column order."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .. import names as N
from .. import vocab as V
from .text import Tables, by_credits, mean, spans, token_class

if TYPE_CHECKING:
    from .namer import Group, WalkNamer

# a name candidate's folder source, before the run's position in the folder name
FOLDER_FEATURES = (
    "depth", "dist", "share", "transparent", "container", "named_after", "variant_only",
    "files_ratio", "n_groups", "only_this", "known", "house", "global_house", "naming",
    "common", "is_top", "rendition_name",
)  # fmt: skip
# kinds of token whose share of a candidate's tokens is a feature
_TOKEN_KINDS: tuple[Callable[[str, Tables], bool], ...] = (
    lambda x, t: x in V.REND or x == V.DIMS,
    lambda x, t: x in V.AXIS and x not in V.REND,
    lambda x, t: x in V.GENERIC,
    lambda x, t: x in t.containerish,
    lambda x, t: x in V.STOPWORDS,
    lambda x, t: x in V.PART_WORDS,
    lambda x, t: x.isdigit(),
    lambda x, t: len(x) == 1,
    lambda x, t: x in t.severity_noise,
    lambda x, t: x in V.COUNTER_WORDS,
)


@dataclass
class Cand:
    """A name candidate: one token run, its occurrences merged."""

    key: tuple[str, ...]
    texts: Counter[str] = field(default_factory=Counter)
    stem_members: set[int] = field(default_factory=set)
    stem_start: int = 99
    stem_gap: int = 99
    stem_cover: float = 0.0
    hard: int = 9
    folder: tuple[float, ...] | None = None  # folder features of the best folder source
    folder_rank: tuple[float, float, bool] = (-1.0, -1.0, False)
    n_folders: int = 0
    rule_flags: list[bool] = field(default_factory=lambda: [False, False, False])
    extra_text: str | None = None

    @property
    def text(self) -> str:
        if self.texts:
            return min(self.texts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return self.extra_text or " ".join(self.key)


Cands = dict[tuple[str, ...], Cand]


def name_candidates(
    namer: WalkNamer, grp: Group, identity_name: str | None, folder_name: str | None
) -> Cands:
    """Candidates by key, in order: stem runs, folder-name runs, then the rule names."""
    cands: Cands = {}
    for i in grp.sample:
        for key, text, start, gap, cover, hard in spans(namer.split_stems[i], split_glued=True):
            c = _seen(cands, key, text, hard)
            c.stem_members.add(i)
            c.stem_start = min(c.stem_start, start)
            c.stem_gap = min(c.stem_gap, gap)
            c.stem_cover = max(c.stem_cover, cover)
    for prefix, info in grp.folders.items():
        _add_folder_runs(cands, prefix[-1], info)
    for flag, text in enumerate((grp.rule.name, identity_name, folder_name)):
        key = tuple(N.tokenize(text)) if text else ()
        if key:
            c = _cand(cands, key)
            c.rule_flags[flag] = True
            if not c.texts:
                c.extra_text = text
    return cands


def _cand(cands: Cands, key: tuple[str, ...]) -> Cand:
    c = cands.get(key)
    if c is None:
        c = cands[key] = Cand(key)
    return c


def _seen(cands: Cands, key: tuple[str, ...], text: str, hard: int) -> Cand:
    c = _cand(cands, key)
    c.hard = min(c.hard, hard)
    c.texts[text] += 1
    return c


def _add_folder_runs(cands: Cands, name: str, info: dict) -> None:
    whole = N.name_tokens(name)
    for key, text, start, gap, cover, hard in spans(name, split_glued=False):
        c = _seen(cands, key, text, hard)
        c.n_folders += 1
        is_whole = key == whole or cover == 1.0
        rank = (info["share"], info["depth"], is_whole)
        if c.folder is None or rank > c.folder_rank:
            c.folder_rank = rank
            c.folder = (
                *(info[k] for k in FOLDER_FEATURES),
                is_whole,
                start,
                gap,
                cover,
                info["reason"],
            )


@dataclass
class _Context:
    """What the features of every candidate of one group share."""

    namer: WalkNamer
    grp: Group
    tables: Tables
    n_sample: int
    stripped: set[str]
    global_house: set[str]
    full_tokens: set[str]
    by_authors: list[set[str]]
    rule_tokens: set[str]
    sdf: Counter[str]  # per token, the sibling groups whose stems hold it
    n_sibs: int
    scope: set[int]
    credit_share: float
    credit_const: float


def _context(namer: WalkNamer, grp: Group) -> _Context:
    names, sample = namer.res.names, grp.sample
    sibs = namer.folder_groups.get(grp.common_eff, set()) - {grp.index}
    if len(sibs) > 200:
        sibs = sorted(sibs)[:: max(1, len(sibs) // 200)]
    sdf: Counter[str] = Counter()
    for h in sibs:
        sdf.update(namer.stem_tokens[h])
    credited = [
        tuple(sorted({N.name_key(a) for a, _ in by_credits(namer.files.stems[i])})) for i in sample
    ]
    credited = [c for c in credited if c]
    return _Context(
        namer=namer,
        grp=grp,
        tables=namer.tables,
        n_sample=max(1, len(sample)),
        stripped=set().union(*(names.stripped[i] for i in grp.members)),
        global_house=names.global_house,
        full_tokens=set().union(*((names.full[i] or ()) for i in grp.members)),
        by_authors=[set(N.tokenize(a)) for i in sample if (a := namer.by_author[i])],
        rule_tokens=set(N.tokenize(grp.rule.name)),
        sdf=sdf,
        n_sibs=len(sibs),
        scope=namer.scope(grp),
        credit_share=len(credited) / max(1, len(sample)),
        credit_const=float(bool(credited) and len(set(credited)) == 1),
    )


def name_features(namer: WalkNamer, grp: Group, cands: Cands) -> np.ndarray:
    """One row of the 101 features per candidate, in the models' column order."""
    ctx = _context(namer, grp)
    rows = [_row(ctx, key, c) for key, c in cands.items()]
    res, files, members = namer.res, namer.files, grp.members
    context = [
        math.log(len(members)),
        math.log(len({files.stems[i] for i in members})),
        len(grp.common_eff),
        float(any(res.sublabel[i] is not None for i in members)),
        math.log(len(files.stems)),
        math.log(len(namer.groups)),
        float(grp.rule.is_identity),
        float(grp.naming_folder is not None),
        math.log(len(cands) + 1),
    ]
    A = np.asarray(rows, dtype=np.float64)
    relative = []
    for col in (0, 50, 51, 31):  # share, rn_mean, rn_min, n_tok
        v = A[:, col]
        relative += [v - v.max(), v - np.median(v)]
    return np.column_stack([A, np.tile(context, (len(rows), 1)), *relative])


def _row(ctx: _Context, key: tuple[str, ...], c: Cand) -> list[float]:
    content = [x for x in key if x not in V.STOPWORDS]
    return [
        *_source_features(c, ctx.n_sample),
        *_token_features(ctx, key),
        *_rate_features(ctx.tables, key, content),
        *_frequency_features(ctx, content, c.hard),
        *_house_features(ctx, key),
        *_rule_features(ctx.rule_tokens, set(key)),
        *_holder_features(ctx, key),
        *(0.0, 0.0),  # two unused feature columns, always 0
        ctx.credit_share,
        ctx.credit_const,
    ]


def _source_features(c: Cand, n_sample: int) -> list[float]:
    """Where the run occurs: member stems, its best folder source, the rule names."""
    in_stems = bool(c.stem_members)
    r = [
        len(c.stem_members) / n_sample,
        float(in_stems),
        c.stem_start if in_stems else -1,
        c.stem_gap if in_stems else -1,
        c.stem_cover,
    ]
    r += [float(x) for x in c.folder] if c.folder else [-1.0] * 22
    return [*r, c.n_folders, *map(float, c.rule_flags)]


def _token_features(ctx: _Context, key: tuple[str, ...]) -> list[float]:
    n, kset = len(key), set(key)
    return [
        n,
        *(sum(kind(x, ctx.tables) for x in key) / n for kind in _TOKEN_KINDS),
        token_class(key[0]),
        token_class(key[-1]),
        sum(len(x) for x in key),
        len(kset & ctx.stripped) / n,
        len(kset & ctx.global_house) / n,
        len(kset & ctx.full_tokens) / n,
        float("by" in kset),
        float(any(a & kset for a in ctx.by_authors)),
    ]


def _rate_features(t: Tables, key: tuple[str, ...], content: list[str]) -> list[float]:
    """How often the content tokens were in training names and authors."""
    rates = [t.rate(x) for x in content] or [t.rate(key[0])]
    rn = [x[0] for x in rates]
    ra = [x[1] for x in rates]
    rc = [x[2] for x in rates]
    return [
        mean(rn),
        min(rn),
        max(rn),
        max(ra),
        mean(ra),
        rn[0],
        rn[-1],
        min(rc),
        sum(x == 0 for x in rc) / len(rc),
    ]


def _frequency_features(ctx: _Context, content: list[str], hard: int) -> list[float]:
    """How common the content tokens are across the import's groups and the siblings."""
    df = [ctx.namer.group_share(x) for x in content] or [0.0]
    r = [mean(df), max(df), min(df), hard if hard < 9 else -1]
    if not ctx.n_sibs:
        return [*r, -1.0, -1.0, -1.0, 0.0]
    sd = [ctx.sdf.get(x, 0) / ctx.n_sibs for x in content] or [0.0]
    return [*r, mean(sd), max(sd), min(sd), math.log1p(ctx.n_sibs)]


def _is_house(ctx: _Context, x: str) -> bool:
    """A shared (house / series) token."""
    sib = ctx.sdf.get(x, 0) / ctx.n_sibs if ctx.n_sibs else 0.0
    return max(ctx.namer.group_share(x), sib) >= 0.5 or x in ctx.stripped or x in ctx.global_house


def _house_features(ctx: _Context, key: tuple[str, ...]) -> list[float]:
    """Shared tokens: leading, trailing, share."""
    n = len(key)
    house = [_is_house(ctx, x) for x in key]
    lead = next((k for k, h in enumerate(house) if not h), n)
    trail = next((k for k, h in enumerate(reversed(house)) if not h), n)
    return [lead / n, trail / n, sum(house) / n, float(house[0]), float(house[-1])]


def _rule_features(rule_tokens: set[str], kset: set[str]) -> list[float]:
    return [
        len(kset & rule_tokens) / max(1, len(kset | rule_tokens)),
        float(kset <= rule_tokens),
        float(bool(rule_tokens) and rule_tokens <= kset),
    ]


def _holder_features(ctx: _Context, key: tuple[str, ...]) -> list[float]:
    """How many groups' paths hold the run, in the import and in the group's scope."""
    holders = ctx.namer.holders(ctx.grp, key)
    in_scope = len(holders & ctx.scope)
    return [
        math.log(len(holders)),
        (len(holders) - 1) / ctx.namer.n_others,
        in_scope - 1,
        (in_scope - 1) / max(1, len(ctx.scope) - 1),
        math.log(len(ctx.scope)),
    ]
