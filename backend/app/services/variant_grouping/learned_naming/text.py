"""Text pieces of the learned namer: token runs of paths, ``by`` credits, the training groups'
token tables, and the cleaner that turns a picked run into a display name."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .. import names as N
from .. import vocab as V

if TYPE_CHECKING:
    from backend.app.services.image_parser import ImageParser

MAX_SPAN = 7  # tokens per candidate run
MAX_STEMS = 24  # distinct member stems read per group
PURE_NOISE = V.REND | V.STOPWORDS | {V.DIMS}
SMALL_WORDS = frozenset(
    {"of", "the", "a", "an", "and", "in", "on", "at", "to", "for", "by", "from", "with", "or", "n"}
)
TRAILING_WORDS = frozenset({"and", "of", "with", "the", "a", "by", "&", "in", "on", "at", "to"})
SIZE_UNITS = frozenset({"mb", "kb", "gb", "pps", "ppi", "dpi", "px"})
KEEP_NUMBER_AFTER = V.SERIES | V.LEVEL | {"part", "pt", "act", "no", "number", "chapter", "episode"}

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


def loose(word: str) -> str:
    return re.sub(r"[^0-9a-z]", "", word.casefold())


def word_texts(text: str) -> list[str]:
    return [text[t.start : t.end] for t in N.tokenize_spans(text)]


def by_split(stem: str, by_author: str | None) -> str:
    """Spaces around a glued ``by<Author>``: "CampsitebyUpsetti" -> "Campsite by Upsetti"."""
    if not by_author:
        return stem
    return re.sub(r"(?i)(?<=[a-z])by" + re.escape(by_author), " by " + by_author, stem)


def by_credits(stem: str) -> list[tuple[str, str]]:
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


def spans(text: str, split_glued: bool):
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


def runs(toks: Sequence[str], out: set[tuple[str, ...]]) -> None:
    for a in range(len(toks)):
        for e in range(a + 1, min(len(toks), a + MAX_SPAN) + 1):
            out.add(tuple(toks[a:e]))


def sample(members: Sequence[int], stems: Sequence[str]) -> list[int]:
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


def token_class(t: str) -> int:
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


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


class Tables:
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


def _drop_credit(text: str) -> str:
    t = re.sub(r"(?<=[a-z0-9])by(?=[A-Z])", " by ", text)
    return re.sub(r"(?i)[\s_\-]+by[\s_\-]+\S.*$", "", t) or t


def _is_size(words: list[str], k: int) -> bool:
    """A file size or resolution word ("40mb", "@2x", "100 ppi")."""
    lw = words[k].casefold()
    if lw in SIZE_UNITS or re.fullmatch(r"@\d+\w*|\d+(mb|kb|pps|ppi|dpi|px)", lw):
        return True
    return bool(
        re.fullmatch(r"@?\d+(mb|kb|gb|pps|ppi|dpi|px|k)?", lw)
        and k + 1 < len(words)
        and words[k + 1].casefold() in SIZE_UNITS
    )


def _trim(words: list[str]) -> list[str]:
    """Without trailing joining words, leading sequence numbers or trailing ones (unless they
    follow a part or level word)."""
    while len(words) > 1 and words[-1].casefold() in TRAILING_WORDS:
        words = words[:-1]
    while len(words) > 1 and re.fullmatch(r"#?\d+[.)]?", words[0]):
        words = words[1:]
    while (
        len(words) > 1
        and re.fullmatch(r"#?\d+", words[-1])
        and loose(words[-2]) not in KEEP_NUMBER_AFTER
    ):
        words = words[:-1]
    return words


class Cleaner:
    """A picked run into a display name: drop a ``by`` credit, ``clean_group_name``, separators,
    size leftovers and sequence numbers, split glued words, then case."""

    def __init__(self, parser: ImageParser, tables: Tables):
        self._parser = parser
        self._t = tables

    def __call__(self, text: str) -> str:
        t = _drop_credit(text)
        t = self._parser.clean_group_name(t) or t
        words = [w if re.fullmatch(r".*\d\.\d.*", w) else w.strip("-_,;:.") for w in t.split()]
        words = [w for w in words if w]
        words = _trim([w for k, w in enumerate(words) if not _is_size(words, k)] or words)
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
            surface = self._t.surface.get(loose(w))
            if surface is not None:
                out.append(surface[0].upper() + surface[1:] if k == 0 else surface)
            elif k > 0 and w.casefold() in SMALL_WORDS:
                out.append(w.casefold())
            elif w.islower() or (w.isupper() and (len(w) > 2 or (len(w) == 2 and not w.isalpha()))):
                out.append(w[:1].upper() + w[1:].lower())
            else:
                out.append(w)
        return out
