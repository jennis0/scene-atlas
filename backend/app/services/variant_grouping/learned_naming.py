"""Learned group names and authors: candidate token runs of the members' paths, and the rule
names, scored by bundled gradient-boosted trees (design/variant-grouping-algorithm.md §8).

The feature code must match the models and tables in ``backend/app/data/group_naming/``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from . import names as N
from . import vocab as V
from .names import Folder, FolderClass
from .schema import FolderReason, WalkFiles, WalkResult

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

    from .naming import GroupName

logger = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).resolve().parents[2] / "data" / "group_naming"

MAX_SPAN = 7  # tokens per candidate run
MAX_STEMS = 24  # distinct member stems read per group
PAIR_K = 8  # candidates re-ranked pairwise
AUTHOR_THRESHOLD = 0.05
REASONS = list(FolderReason)
PURE_NOISE = V.REND | V.STOPWORDS | {V.DIMS}
SMALL_WORDS = frozenset(
    {"of", "the", "a", "an", "and", "in", "on", "at", "to", "for", "by", "from", "with", "or", "n"}
)
TRAILING_WORDS = frozenset({"and", "of", "with", "the", "a", "by", "&", "in", "on", "at", "to"})
SIZE_UNITS = frozenset({"mb", "kb", "gb", "pps", "ppi", "dpi", "px"})
KEEP_NUMBER_AFTER = V.SERIES | V.LEVEL | {"part", "pt", "act", "no", "number", "chapter", "episode"}
AUTHOR_SOURCES = ("folder", "by", "known", "house_stem", "rule", "shared", "credit")
# a name candidate's folder source, before the run's position in the folder name
FOLDER_FEATURES = (
    "depth", "dist", "share", "transparent", "container", "named_after", "variant_only",
    "files_ratio", "n_groups", "only_this", "known", "house", "global_house", "naming",
    "common", "is_top", "rendition_name",
)  # fmt: skip

_HARD_SEP = re.compile(r"\s-\s|[,;$&+]|_-_|\s{2,}")
# ``by`` credit: after a lower-case letter, digit or separator and before a capital letter
# ("TemplebyMiss", "_by_Upsetti"); never "Lobby" or "bypass".
_CREDIT = re.compile(r"(?:(?<=[a-z0-9])|(?<=[_\-\s.,]))by(?=[\s_\-]*[A-Z])")
_CREDIT_RUN = re.compile(r"[A-Z][A-Za-z]*[0-9]*")
_NOT_KEY = re.compile(r"[^0-9a-z&]")
_MAPS_SUFFIX = re.compile(r"(battlemaps|maps|map)$")


def author_key(text: str) -> str:
    """Loose author key: case-folded letters and digits, without a leading "the" or a trailing
    "maps" ("The Moonlight Maps" == "moonlight")."""
    k = _NOT_KEY.sub("", text.casefold()).replace("&", "and").removeprefix("the")
    return _MAPS_SUFFIX.sub("", k) or k


def _loose(word: str) -> str:
    return re.sub(r"[^0-9a-z]", "", word.casefold())


def _words(text: str) -> list[str]:
    return [text[t.start : t.end] for t in N.tokenize_spans(text)]


def _by_split(stem: str, by_author: str | None) -> str:
    """Spaces around a glued ``by<Author>``: "CampsitebyUpsetti" -> "Campsite by Upsetti"."""
    if not by_author:
        return stem
    return re.sub(r"(?i)(?<=[a-z])by" + re.escape(by_author), " by " + by_author, stem)


def _credits(stem: str) -> list[tuple[str, str]]:
    """(credited name, fragment) per ``by`` credit: the capitalised run after ``by`` minus
    trailing variant, rendition or part words; the fragment is the glued word ``by`` ends
    ("rubyby" for "RubyGhost", "" after a separator)."""
    out = []
    for m in _CREDIT.finditer(stem):
        run = _CREDIT_RUN.match(stem[m.end() :].lstrip(" _-"))
        if not run:
            continue
        toks = N.tokenize_spans(run.group(0))
        while toks and (
            toks[-1].text in V.AXIS or toks[-1].text in V.REND or toks[-1].text in V.PART_WORDS
        ):
            toks.pop()
        if toks:
            frag = re.search(r"([A-Za-z]*)$", stem[: m.start()])
            word = frag.group(1) if frag else ""
            out.append((run.group(0)[: toks[-1].end], (word + "by").lower() if word else ""))
    return out


def _spans(text: str, split_glued: bool):
    """(key, original text, start, tokens after, cover, hard separators) of each candidate run.
    Runs of noise or digits only are skipped; runs never cross a bracket."""
    toks = N.tokenize_spans(text, split_glued=split_glued)
    n = len(toks)
    for s in range(n):
        for e in range(s + 1, min(n, s + MAX_SPAN) + 1):
            key = tuple(t.text for t in toks[s:e])
            if all(k in PURE_NOISE or k.isdigit() for k in key):
                continue
            sub = text[toks[s].start : toks[e - 1].end]
            if any(ch in sub for ch in "()[]{}"):
                break
            yield key, sub, s, n - e, (e - s) / n, len(_HARD_SEP.findall(sub))


def _runs(toks: Sequence[str], out: set[tuple[str, ...]]) -> None:
    for a in range(len(toks)):
        for e in range(a + 1, min(len(toks), a + MAX_SPAN) + 1):
            out.add(tuple(toks[a:e]))


def _sample(members: Sequence[int], stems: Sequence[str]) -> list[int]:
    """Members with distinct stems, at most ``MAX_STEMS`` spread evenly."""
    seen: set[str] = set()
    out = []
    for i in members:
        if stems[i] not in seen:
            seen.add(stems[i])
            out.append(i)
    if len(out) > MAX_STEMS:
        step = len(out) / MAX_STEMS
        out = [out[int(k * step)] for k in range(MAX_STEMS)]
    return out


def _token_class(t: str) -> int:
    if t in V.STOPWORDS:
        return 1
    if t.isdigit() or t == V.DIMS:
        return 2
    if t in V.REND:
        return 3
    if t in V.AXIS:
        return 4
    if t in V.GENERIC:
        return 5
    return 6 if t in V.PART_WORDS else 0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


# ----------------------------------------------------------------------------- tables


class _Tables:
    """``tables.json``: token rates, the cleaner's vocabulary and word lists."""

    def __init__(self, data: dict):
        rates = data["rates"]
        self.alpha = float(rates["alpha"])
        self.prior_name, self.prior_author = rates["prior"]
        self.n: dict[str, int] = rates["n"]
        self.in_name: dict[str, int] = rates["name"]
        self.in_author: dict[str, int] = rates["auth"]
        cleaner = data["cleaner"]
        self.surface: dict[str, str] = cleaner["surface"]
        self.vocab: dict[str, int] = cleaner["vocab"]
        self.names_vocab: dict[str, int] = cleaner["names_vocab"]
        self.common_path_words = frozenset(cleaner["path_vocab_ge40"])
        self.vocab_total = int(cleaner["total"])
        words = data["word_lists"]
        self.severity_noise = frozenset(words["sev_noise"])
        self.containerish = V.GENERIC | frozenset(words["containerish_extra"])
        self.library_words = frozenset(words["author_library"])

    def rate(self, t: str) -> tuple[float, float, float]:
        """(name rate, author rate, log count) of a token in training groups."""
        n = self.n.get(t, 0)
        rn = (self.in_name.get(t, 0) + self.alpha * self.prior_name) / (n + self.alpha)
        ra = (self.in_author.get(t, 0) + self.alpha * self.prior_author) / (n + self.alpha)
        return rn, ra, math.log1p(n)


class _Cleaner:
    """A picked run into a display name: drop a ``by`` credit, ``clean_group_name``, separators,
    size leftovers and sequence numbers, split glued words, then case."""

    def __init__(self, parser: ImageParser, tables: _Tables):
        self._parser = parser
        self._t = tables

    def __call__(self, text: str) -> str:
        t = re.sub(r"(?<=[a-z0-9])by(?=[A-Z])", " by ", text)
        t = re.sub(r"(?i)[\s_\-]+by[\s_\-]+\S.*$", "", t) or t
        t = self._parser.clean_group_name(t) or t
        words = [w if re.fullmatch(r".*\d\.\d.*", w) else w.strip("-_,;:.") for w in t.split()]
        words = [w for w in words if w]
        kept = []
        for k, w in enumerate(words):
            lw = w.casefold()
            if (
                re.fullmatch(r"@?\d+(mb|kb|gb|pps|ppi|dpi|px|k)?", lw)
                and k + 1 < len(words)
                and words[k + 1].casefold() in SIZE_UNITS
            ):
                continue
            if lw in SIZE_UNITS or re.fullmatch(r"@\d+\w*|\d+(mb|kb|pps|ppi|dpi|px)", lw):
                continue
            kept.append(w)
        words = kept or words
        while len(words) > 1 and words[-1].casefold() in TRAILING_WORDS:
            words.pop()
        while len(words) > 1 and re.fullmatch(r"#?\d+[.)]?", words[0]):
            words = words[1:]
        while (
            len(words) > 1
            and re.fullmatch(r"#?\d+", words[-1])
            and _loose(words[-2]) not in KEEP_NUMBER_AFTER
        ):
            words = words[:-1]
        out = " ".join(self._case(self._unglue(words))).strip()
        return out or text.strip()

    def _segment(self, w: str) -> tuple[str, ...] | None:
        """An unseen glued word as 2-4 known words (fewest parts, then most probable)."""
        n = len(w)
        if n < 6 or self._t.names_vocab.get(w, 0) >= 1 or w in self._t.common_path_words:
            return None
        best: dict[int, tuple[int, float, tuple[str, ...]]] = {0: (0, 0.0, ())}
        for e in range(1, n + 1):
            for s in range(max(0, e - 14), e - 1):
                if s not in best:
                    continue
                part = w[s:e]
                if len(part) < 3 and part not in ("an", "of", "on", "in", "to"):
                    continue
                count = self._t.vocab.get(part)
                if count is None:
                    continue
                prev = best[s]
                cand = (
                    prev[0] + 1,
                    prev[1] - math.log(count / self._t.vocab_total),
                    (*prev[2], part),
                )
                if e not in best or cand[:2] < best[e][:2]:
                    best[e] = cand
        if n not in best or not 2 <= len(best[n][2]) <= 4:
            return None
        return best[n][2]

    def _unglue(self, words: list[str]) -> list[str]:
        out = []
        for w in words:
            lw = w.casefold()
            if lw.isalpha() and (
                w.islower() or w.isupper() or (w[0].isupper() and w[1:].islower())
            ):
                parts = self._segment(lw)
                if parts:
                    out.extend(parts if w.islower() else [p.capitalize() for p in parts])
                    continue
            out.append(w)
        return out

    def _case(self, words: list[str]) -> list[str]:
        out = []
        for k, w in enumerate(words):
            surface = self._t.surface.get(_loose(w))
            if surface is not None:
                out.append(surface[0].upper() + surface[1:] if k == 0 else surface)
            elif k > 0 and w.casefold() in SMALL_WORDS:
                out.append(w.casefold())
            elif w.islower() or (w.isupper() and (len(w) > 2 or (len(w) == 2 and not w.isalpha()))):
                out.append(w[:1].upper() + w[1:].lower())
            else:
                out.append(w)
        return out


# ----------------------------------------------------------------------------- models


class LearnedNamer:
    """The bundled models and tables (stateless; one per process, see ``load``)."""

    def __init__(self, asset_dir: Path):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self._sessions = {
            k: ort.InferenceSession(
                str(asset_dir / f"{k}.onnx"), opts, providers=["CPUExecutionProvider"]
            )
            for k in ("point", "pair", "author", "identity")
        }
        self.tables = _Tables(json.loads((asset_dir / "tables.json").read_text(encoding="utf-8")))

    def predict(self, model: str, x: np.ndarray) -> np.ndarray:
        """Severity (``point``, lower is better) or P(yes) of the other models, per row."""
        x = np.ascontiguousarray(x, dtype=np.float64)
        return np.asarray(self._sessions[model].run(None, {"x": x})[0])


@cache
def load() -> LearnedNamer | None:
    """The process-wide namer, or None (naming falls back to the rules) when the assets fail."""
    try:
        return LearnedNamer(ASSET_DIR)
    except Exception:
        logger.exception("Learned group naming unavailable; using the naming rules")
        return None


# ----------------------------------------------------------------------------- one walk


@dataclass
class _Cand:
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


@dataclass
class _ACand:
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


@dataclass
class _Group:
    """The group being named, and the rules' choices for it."""

    index: int
    members: Sequence[int]
    sample: list[int]  # members read for stem candidates
    common_eff: Folder  # the members' common effective folder
    rule: GroupName
    naming_folder: Folder | None
    folders: dict[Folder, dict] = field(init=False)  # raw prefix -> ``_folder_info``


class WalkNamer:
    """Names the groups of one walk; import-wide statistics are computed once.

    ``known_author`` maps a folder name to the known author it names; ``authors`` maps
    ``author_key``s to known authors' display names."""

    def __init__(
        self,
        model: LearnedNamer,
        parser: ImageParser,
        result: WalkResult,
        files: WalkFiles,
        known_author: Callable[[str], str | None],
        authors: Mapping[str, str],
    ):
        self._m = model
        self._t = model.tables
        self._clean = _Cleaner(parser, model.tables)
        self._res = result
        self._files = files
        self._known_author = known_author
        self._authors = authors
        by_root: dict[int, list[int]] = defaultdict(list)
        for i, root in enumerate(result.root):
            by_root[root].append(i)
        self._groups = list(by_root.values())
        self._group_of = {}
        for g, members in enumerate(self._groups):
            for i in members:
                self._group_of[i] = g
        self._folder_groups: dict[Folder, set[int]] = defaultdict(set)
        for i, eff in enumerate(result.effective):
            for d in range(len(eff) + 1):
                self._folder_groups[eff[:d]].add(self._group_of[i])
        self._by_author = [parser.author_from_stem(s) for s in files.stems]
        self._split_stems = [
            _by_split(s, a) for s, a in zip(files.stems, self._by_author, strict=True)
        ]
        self._clean_name = lru_cache(maxsize=None)(parser.clean_group_name)
        self._index_tokens()

    def _index_tokens(self) -> None:
        """Per token, the number of groups whose paths hold it (``gdf``); per group its stem
        tokens; per token run, the groups whose stems or folder names hold it."""
        files = self._files
        self._gdf: Counter[str] = Counter()
        self._stem_tokens: list[frozenset[str]] = []
        self._run_groups: dict[tuple[str, ...], set[int]] = defaultdict(set)
        stem_runs: dict[str, set[tuple[str, ...]]] = {}
        folder_runs: dict[str, set[tuple[str, ...]]] = {}
        for g, members in enumerate(self._groups):
            toks = {t for i in members for t in files.tokens[i]}
            self._stem_tokens.append(frozenset(toks))
            runs: set[tuple[str, ...]] = set()
            for i in members:
                stem = files.stems[i]
                if stem not in stem_runs:
                    stem_runs[stem] = set()
                    _runs(N.tokenize(self._split_stems[i], split_glued=True), stem_runs[stem])
                runs |= stem_runs[stem]
                for f in files.folders[i]:
                    toks.update(N.name_tokens(f))
                    if f not in folder_runs:
                        folder_runs[f] = set()
                        _runs(N.name_tokens(f), folder_runs[f])
                    runs |= folder_runs[f]
            self._gdf.update(toks)
            for run in runs:
                self._run_groups[run].add(g)

    # -- shared pieces

    def _scope(self, grp: _Group) -> set[int]:
        """Groups under the group's effective folder; when it holds only this group, under the
        nearest enclosing folder holding others."""
        folder = grp.common_eff
        while True:
            groups = self._folder_groups.get(folder, {grp.index})
            if len(groups) >= 2 or not folder:
                return groups
            folder = folder[:-1]

    def _folder_info(self, grp: _Group, prefix: Folder, count: int, dist: int) -> dict:
        """What the walk made of a raw folder prefix of the members."""
        res, tree, members = self._res, self._res.tree, grp.members
        eff = tree.effective_of[prefix]
        verdict = res.folders.get(eff)
        name = prefix[-1]
        ident = set(N.name_identity(name))
        under = self._folder_groups.get(eff, set())
        return {
            "depth": len(prefix) - 1,
            "dist": dist,
            "share": count / len(members),
            "transparent": eff == tree.effective_of[prefix[:-1]],
            "container": bool(verdict and verdict.container),
            "named_after": bool(verdict and verdict.named_after_files),
            "variant_only": bool(verdict and verdict.variant_only),
            "files_ratio": verdict.files / len(members) if verdict else 0.0,
            "n_groups": len(under),
            "only_this": under == {grp.index},
            "known": self._known_author(name) is not None,
            "house": sum(bool(ident) and ident <= res.names.stripped[i] for i in members)
            / len(members),
            "global_house": bool(ident) and ident <= res.names.global_house,
            "naming": grp.naming_folder is not None and eff == grp.naming_folder,
            "common": eff == grp.common_eff,
            "is_top": len(prefix) == 1,
            "rendition_name": bool(ident) and all(t in V.REND or t in V.AXIS for t in ident),
            "reason": REASONS.index(verdict.reason) if verdict else -1,
            "generic": tree.name_class.get(eff) is FolderClass.GENERIC,
        }

    # -- names

    def name(
        self,
        members: Sequence[int],
        rule: GroupName,
        naming_folder: Folder | None,
        identity_name: str | None,
        folder_name: str | None,
    ) -> tuple[str, str | None, bool]:
        """(name, author, is_identity) of a group, given the rules' choices for it."""
        grp = self._group(members, rule, naming_folder)
        cands = self._name_candidates(grp, identity_name, folder_name)
        if not cands:
            return rule.name, rule.author, rule.is_identity
        X = self._name_features(grp, cands)
        scores = self._m.predict("point", X)
        best = self._pick(X, scores)
        ranked = np.sort(scores)
        margin = ranked[1] - ranked[0] if len(scores) > 1 else 0.0
        x_id = np.concatenate([[scores[best], margin], X[best]])[None, :]
        is_identity = bool(self._m.predict("identity", x_id)[0] >= 0.5)
        name = self._clean(list(cands.values())[best].text) or rule.name
        return name, self._author(grp), is_identity

    def _group(
        self, members: Sequence[int], rule: GroupName, naming_folder: Folder | None
    ) -> _Group:
        grp = _Group(
            self._group_of[members[0]],
            members,
            _sample(members, self._files.stems),
            N.common_prefix(self._res.effective[i] for i in members),
            rule,
            naming_folder,
        )
        count: Counter[Folder] = Counter()
        dist: dict[Folder, int] = {}
        for i in members:
            raw = self._files.folders[i]
            for d in range(1, len(raw) + 1):
                count[raw[:d]] += 1
                dist[raw[:d]] = min(dist.get(raw[:d], 99), len(raw) - d)
        grp.folders = {p: self._folder_info(grp, p, n, dist[p]) for p, n in count.items()}
        return grp

    def _pick(self, X: np.ndarray, scores: np.ndarray) -> int:
        """The best candidate: the ``PAIR_K`` best by score, re-ranked by pairwise wins."""
        top = np.argsort(scores, kind="stable")[:PAIR_K]
        if len(top) < 2:
            return int(top[0])
        a, b = (ix.ravel() for ix in np.indices((len(top), len(top))))
        a, b = a[a != b], b[a != b]  # ordered pairs, row-major
        rows = np.column_stack([X[top[a]] - X[top[b]], scores[top[a]] - scores[top[b]]])
        wins = np.bincount(a, weights=self._m.predict("pair", rows), minlength=len(top))
        return int(top[int(np.argmax(wins))])

    def _name_candidates(
        self, grp: _Group, identity_name: str | None, folder_name: str | None
    ) -> dict[tuple[str, ...], _Cand]:
        """Candidates by key, in order: stem runs, folder-name runs, then the rule names."""
        cands: dict[tuple[str, ...], _Cand] = {}
        for i in grp.sample:
            stem = self._split_stems[i]
            for key, text, start, gap, cover, hard in _spans(stem, split_glued=True):
                c = cands.get(key) or cands.setdefault(key, _Cand(key))
                c.hard = min(c.hard, hard)
                c.texts[text] += 1
                c.stem_members.add(i)
                c.stem_start = min(c.stem_start, start)
                c.stem_gap = min(c.stem_gap, gap)
                c.stem_cover = max(c.stem_cover, cover)
        for prefix, info in grp.folders.items():
            whole = N.name_tokens(prefix[-1])
            for key, text, start, gap, cover, hard in _spans(prefix[-1], split_glued=False):
                c = cands.get(key) or cands.setdefault(key, _Cand(key))
                c.hard = min(c.hard, hard)
                c.texts[text] += 1
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
        for flag, text in enumerate((grp.rule.name, identity_name, folder_name)):
            key = tuple(N.tokenize(text)) if text else ()
            if key:
                c = cands.get(key) or cands.setdefault(key, _Cand(key))
                c.rule_flags[flag] = True
                if not c.texts:
                    c.extra_text = text
        return cands

    def _name_features(self, grp: _Group, cands: dict[tuple[str, ...], _Cand]) -> np.ndarray:
        """One row of the 101 features per candidate, in the models' column order."""
        res, files, t = self._res, self._files, self._t
        g, members, sample, rule = grp.index, grp.members, grp.sample, grp.rule
        stripped = set().union(*(res.names.stripped[i] for i in members))
        global_house = res.names.global_house
        full_tokens = set().union(*((res.names.full[i] or ()) for i in members))
        by_authors = [set(N.tokenize(a)) for i in sample if (a := self._by_author[i])]
        rule_tokens = set(N.tokenize(rule.name))
        n_groups = len(self._groups)
        G = max(1, n_groups - 1)
        sibs = self._folder_groups.get(grp.common_eff, set()) - {g}
        if len(sibs) > 200:
            sibs = sorted(sibs)[:: max(1, len(sibs) // 200)]
        sdf: Counter[str] = Counter()
        for h in sibs:
            sdf.update(self._stem_tokens[h])
        n_sibs = len(sibs)
        scope = self._scope(grp)
        credited = [
            tuple(sorted({N.name_key(a) for a, _ in _credits(files.stems[i])})) for i in sample
        ]
        credited = [c for c in credited if c]
        credit_share = len(credited) / max(1, len(sample))
        credit_const = float(bool(credited) and len(set(credited)) == 1)
        S = max(1, len(sample))

        rows = []
        for key, c in cands.items():
            n = len(key)
            kset = set(key)
            r: list[float] = [
                len(c.stem_members) / S,
                float(bool(c.stem_members)),
                c.stem_start if c.stem_members else -1,
                c.stem_gap if c.stem_members else -1,
                c.stem_cover,
            ]
            r += [float(x) for x in c.folder] if c.folder else [-1.0] * 22
            r += [c.n_folders, *map(float, c.rule_flags)]
            r += [
                n,
                sum(x in V.REND or x == V.DIMS for x in key) / n,
                sum(x in V.AXIS and x not in V.REND for x in key) / n,
                sum(x in V.GENERIC for x in key) / n,
                sum(x in t.containerish for x in key) / n,
                sum(x in V.STOPWORDS for x in key) / n,
                sum(x in V.PART_WORDS for x in key) / n,
                sum(x.isdigit() for x in key) / n,
                sum(len(x) == 1 for x in key) / n,
                sum(x in t.severity_noise for x in key) / n,
                sum(x in V.COUNTER_WORDS for x in key) / n,
                _token_class(key[0]),
                _token_class(key[-1]),
                sum(len(x) for x in key),
                len(kset & stripped) / n,
                len(kset & global_house) / n,
                len(kset & full_tokens) / n,
                float("by" in kset),
                float(any(a & kset for a in by_authors)),
            ]
            content = [x for x in key if x not in V.STOPWORDS]
            rates = [t.rate(x) for x in content] or [t.rate(key[0])]
            rn = [x[0] for x in rates]
            ra = [x[1] for x in rates]
            rc = [x[2] for x in rates]
            r += [
                _mean(rn),
                min(rn),
                max(rn),
                max(ra),
                _mean(ra),
                rn[0],
                rn[-1],
                min(rc),
                sum(x == 0 for x in rc) / len(rc),
            ]
            df = [(self._gdf.get(x, 1) - 1) / G for x in content] or [0.0]
            r += [_mean(df), max(df), min(df), c.hard if c.hard < 9 else -1]
            if n_sibs:
                sd = [sdf.get(x, 0) / n_sibs for x in content] or [0.0]
                r += [_mean(sd), max(sd), min(sd), math.log1p(n_sibs)]
            else:
                r += [-1.0, -1.0, -1.0, 0.0]
            # shared (house / series) tokens: leading, trailing, share
            house = [
                max((self._gdf.get(x, 1) - 1) / G, sdf.get(x, 0) / n_sibs if n_sibs else 0.0) >= 0.5
                or x in stripped
                or x in global_house
                for x in key
            ]
            lead = next((k for k, h in enumerate(house) if not h), n)
            trail = next((k for k, h in enumerate(reversed(house)) if not h), n)
            r += [lead / n, trail / n, sum(house) / n, float(house[0]), float(house[-1])]
            r += [
                len(kset & rule_tokens) / max(1, len(kset | rule_tokens)),
                float(kset <= rule_tokens),
                float(bool(rule_tokens) and rule_tokens <= kset),
            ]
            holders = self._run_groups.get(key, set()) | {g}
            in_scope = len(holders & scope)
            r += [
                math.log(len(holders)),
                (len(holders) - 1) / G,
                in_scope - 1,
                (in_scope - 1) / max(1, len(scope) - 1),
                math.log(len(scope)),
            ]
            # two unused feature columns, always 0
            r += [0.0, 0.0, credit_share, credit_const]
            rows.append(r)

        context = [
            math.log(len(members)),
            math.log(len({files.stems[i] for i in members})),
            len(grp.common_eff),
            float(any(res.sublabel[i] is not None for i in members)),
            math.log(len(files.stems)),
            math.log(n_groups),
            float(rule.is_identity),
            float(grp.naming_folder is not None),
            math.log(len(cands) + 1),
        ]
        A = np.asarray(rows, dtype=np.float64)
        relative = []
        for col in (0, 50, 51, 31):  # share, rn_mean, rn_min, n_tok
            v = A[:, col]
            relative += [v - v.max(), v - np.median(v)]
        return np.column_stack([A, np.tile(context, (len(rows), 1)), *relative])

    # -- authors

    def _author(self, grp: _Group) -> str | None:
        """The credited author if most members carry one, else the classifier's pick (or none)."""
        cands, flags = self._author_candidates(grp)
        credited = [
            c
            for c in cands
            if "credit" in c.src and c.credit_share >= 0.5 and not self._frag_word(c)
        ]
        if credited:
            return max(credited, key=lambda c: c.credit_share).text
        if not cands:
            return None
        X = self._author_features(grp, cands, flags)
        p = self._m.predict("author", X)
        k = int(np.argmax(p))
        return cands[k].text if p[k] >= AUTHOR_THRESHOLD else None

    def _frag_word(self, c: _ACand) -> bool:
        """Whether a credit was cut from a real word ("Ruby" in "RubyGhost")."""
        return any(
            f and (self._t.n.get(f, 0) > 0 or f in V.AXIS or f in V.GENERIC) for f in c.frag_words
        )

    def _author_candidates(self, grp: _Group) -> tuple[list[_ACand], dict]:
        """Author candidates in order of discovery, and the group's author context."""
        files, res, known, members = self._files, self._res, self._authors, grp.members
        clean = self._clean_name
        cands: dict[str, _ACand] = {}

        def add(text: str | None, src: str, raw: str | None = None) -> _ACand | None:
            k = author_key(text) if text else ""
            if not k:
                return None
            c = cands.get(k)
            if c is None:
                c = cands[k] = _ACand(text or "", raw or text or "", set())
            c.src.add(src)
            return c

        top_nonrend = set()
        for i in members:
            raw = files.folders[i]
            k = 0
            while k < len(raw) and N.is_rendition_folder_name(raw[k]):
                k += 1
            if k < len(raw):
                top_nonrend.add(raw[: k + 1])
        for prefix, info in grp.folders.items():
            name = prefix[-1]
            hit = known.get(author_key(name))
            ident = [x for x in N.name_identity(name) if not x.isdigit()]
            if not hit and all(x in self._t.library_words or x in V.GENERIC for x in ident):
                continue
            c = add(hit or clean(name) or name, "folder", name)
            if c is None:
                continue
            if c.folder is None or (info["share"], -info["depth"]) > (
                c.folder["share"],
                -c.folder["depth"],
            ):
                c.folder = info
            c.share = max(c.share, info["share"])
            c.top_nonrend |= prefix in top_nonrend

        by: Counter[str] = Counter(a for i in members if (a := self._by_author[i]))
        for a, n in by.items():
            c = add(known.get(author_key(a)) or a, "by")
            if c is not None:
                c.by_share = max(c.by_share, n / len(members))
                c.share = max(c.share, n / len(members))

        credits: Counter[str] = Counter()
        frags: dict[str, set[str]] = defaultdict(set)
        for i in members:
            for raw, frag in sorted(set(_credits(files.stems[i]))):
                credits[raw] += 1
                frags[raw].add(frag)
        for raw, n in credits.items():
            c = add(known.get(author_key(raw)) or clean(raw) or raw, "credit", raw)
            if c is not None:
                c.credit_share = max(c.credit_share, n / len(members))
                c.frag_words |= frags[raw]

        hits: Counter[str] = Counter()
        for i in members if known else ():
            words = [w for f in files.folders[i] for w in _words(f)] + _words(files.stems[i])
            hits.update(sorted(self._known_hits(words)))
        for h, n in hits.items():
            c = add(h, "known")
            if c is not None:
                c.share = max(c.share, n / len(members))

        house: Counter[str] = Counter()
        for i in members:
            st = res.names.stripped[i]
            if not st:
                continue
            spans = N.tokenize_spans(files.stems[i])
            k = 0
            while k < len(spans) and (spans[k].text in st or spans[k].text.isdigit()):
                k += 1
            if k:
                house[files.stems[i][spans[0].start : spans[k - 1].end]] += 1
        for raw, n in house.items():
            c = add(known.get(author_key(raw)) or clean(raw) or raw, "house_stem", raw)
            if c is not None:
                c.share = max(c.share, n / len(members))

        if grp.rule.author:
            add(known.get(author_key(grp.rule.author)) or grp.rule.author, "rule")

        # the longest leading stem run found in >= 30% of the import's groups (>= 5 groups)
        n_groups = len(self._groups)
        if n_groups >= 5:
            shared: Counter[str] = Counter()
            for i in members:
                stem = self._split_stems[i]
                spans = N.tokenize_spans(stem, split_glued=True)
                best = 0
                for e in range(1, min(len(spans), MAX_SPAN) + 1):
                    key = tuple(x.text for x in spans[:e])
                    if len(self._run_groups.get(key, ())) < max(3, 0.3 * n_groups):
                        break
                    best = e
                if best and any(x.text.isalpha() and len(x.text) > 2 for x in spans[:best]):
                    shared[stem[spans[0].start : spans[best - 1].end]] += 1
            for raw, n in shared.items():
                c = add(known.get(author_key(raw)) or clean(raw) or raw, "shared", raw)
                if c is not None:
                    c.share = max(c.share, n / len(members))

        flags = {
            "any_by": bool(by),
            "any_known": bool(hits),
            "any_house": bool(house),
            "credit_const": float(len(credits) == 1 and max(credits.values()) == len(members)),
        }
        return list(cands.values()), flags

    def _known_hits(self, words: list[str]) -> set[str]:
        """Known authors named by a run of 1-3 words (2-letter keys only in capitals)."""
        hits = set()
        for s in range(len(words)):
            for e in range(s + 1, min(len(words), s + 3) + 1):
                k = author_key("".join(words[s:e]))
                if k in self._authors and (
                    len(k) >= 3 or (len(k) == 2 and e - s == 1 and words[s].isupper())
                ):
                    hits.add(self._authors[k])
        return hits

    def _author_features(self, grp: _Group, cands: list[_ACand], flags: dict) -> np.ndarray:
        """One row of the 52 author features per candidate."""
        t, known, g, members, rule = self._t, self._authors, grp.index, grp.members, grp.rule
        n_groups = len(self._groups)
        G = max(1, n_groups - 1)
        rule_key = author_key(rule.author) if rule.author else ""
        scope = self._scope(grp)
        context = [
            math.log(len(members)),
            math.log(n_groups),
            len(grp.common_eff),
            float(flags["any_by"]),
            float(flags["any_known"]),
            float(flags["any_house"]),
            len(grp.folders),
        ]
        rows = []
        for c in cands:
            k = author_key(c.text)
            r: list[float] = [float(s in c.src) for s in AUTHOR_SOURCES] + [0.0, c.share]
            f = c.folder
            if f is None:
                r += [-1.0] * 17
            else:
                r += [
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
            toks = N.tokenize(c.raw) or [k]
            df = [(self._gdf.get(x, 1) - 1) / G for x in toks]
            rates = [t.rate(x) for x in toks]
            holders = self._run_groups.get(tuple(toks), set()) | {g}
            r += [
                len(toks),
                _mean(df),
                max(df),
                _mean([x[1] for x in rates]),
                max(x[1] for x in rates),
                _mean([x[0] for x in rates]),
                min(x[2] for x in rates),
                sum(x[2] == 0 for x in rates) / len(rates),
                float(k in known or author_key(c.raw) in known),
                sum(author_key(x) in known for x in toks if len(x) > 2) / len(toks),
                float(k == rule_key),
                c.by_share,
                sum(x in V.REND or x in V.AXIS or x in V.GENERIC for x in toks) / len(toks),
                (len(holders) - 1) / G,
                (len(holders & scope) - 1) / max(1, len(scope) - 1),
                math.log(len(holders)),
                c.credit_share,
                flags["credit_const"] if "credit" in c.src else 0.0,
                float(self._frag_word(c)),
            ]
            rows.append(r + context)
        return np.asarray(rows, dtype=np.float64)
