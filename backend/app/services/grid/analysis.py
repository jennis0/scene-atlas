"""Signal analysis for grid detection v3: decode, line-energy profiles, comb search.

How it works (see ``design/grid-detection-v3.md`` §2 for the evaluation behind it):

1. **Decode** grayscale at full resolution. Only when ``max_analysis_dim`` is set and
   the image is larger is it reduced, by the smallest power of two that fits; JPEGs then
   use libjpeg DCT scaling so the full-size image never exists.
2. **Profiles**, strip by strip (no full-size float buffer): per-pixel line energy
   ``|I - boxmean_5(I)|`` across x (vertical lines) and y (horizontal lines), after a
   1-D Gaussian pre-blur (sigma 1 px) across the line, summed into a column and a row
   profile. The pre-blur makes the non-linear ``|.|`` insensitive to a thin line's
   sub-pixel phase, which otherwise puts energy at half the grid frequency (a false 2c).
3. **Spectrum** of each profile, whitened by a running median of its own magnitude and
   zero-padded 8x for 1/8-cycle resolution.
4. **Harmonic comb.** For a cell size ``c`` the fundamental is ``W / c`` cycles per
   image, i.e. the tile count itself. ``score(c)`` is the 1/k-weighted mean log-whitened
   magnitude at harmonics ``k * W / c`` below Nyquist. A joint search over ``c`` on both
   axes enforces square cells; each axis is then refined independently.

All constants were fixed during evaluation; changing any of them invalidates the
trained models in ``backend/app/data/grid_models`` (retrain with
``scripts/models/grid/train_grid_models.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image as PILImage
from scipy.ndimage import median_filter


@dataclass(frozen=True)
class AnalysisParams:
    """Frozen analysis constants. ``max_analysis_dim`` is the only user-facing knob."""

    min_cell_px: int = 32
    max_cell_px: int = 320
    max_analysis_dim: int | None = None  # None: always full resolution
    hex_max_dim: int = 1536  # coarse copy used for the oblique (hex) projections
    strip_rows: int = 256
    harmonics: int = 6
    nyquist_frac: float = 0.42  # only use harmonics below this fraction of the sample rate
    whiten_halfwidth: int = 6  # bins either side for the running-median spectral floor
    pad: int = 8  # zero-padding factor -> 1/8-cycle frequency resolution
    subharmonic_ratio: float = 0.5
    odd_frac: float = 0.5  # odd-harmonic score needed, relative to the best comb score
    refine_window: float = 0.02  # per-axis refinement window around the joint estimate
    absdev_box: int = 5  # box width for the local mean in the line-energy measure
    preblur: float = 1.0  # Gaussian sigma across the line before |.|
    cell_samples: int = 4000  # log-spaced cell sizes in the joint search


N_BANDS = 4  # 4x4 blocks for the spatial-coverage features

_REDUCED_FLAGS = {
    2: cv2.IMREAD_REDUCED_GRAYSCALE_2,
    4: cv2.IMREAD_REDUCED_GRAYSCALE_4,
    8: cv2.IMREAD_REDUCED_GRAYSCALE_8,
}


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def is_jpeg(path: Path) -> bool:
    """Sniff the JPEG SOI marker (staged files may not carry a trustworthy extension)."""
    with open(path, "rb") as fh:
        return fh.read(3) == b"\xff\xd8\xff"


def reduction_factor(longest: int, max_analysis_dim: int | None) -> int:
    """1 (full resolution) unless the image exceeds ``max_analysis_dim``; then the
    smallest power-of-two reduction (2, 4 or 8) that brings it within the limit."""
    if max_analysis_dim is None:
        return 1
    factor = 1
    while factor < 8 and longest / factor > max_analysis_dim:
        factor *= 2
    return factor


def _box_reduce_strips(img: np.ndarray, factor: int, strip_rows: int) -> np.ndarray:
    """Area-downscale a uint8 image by an integer factor, strip by strip."""
    if factor == 1:
        return img
    h, w = img.shape
    out_w, out_h = max(1, w // factor), max(1, h // factor)
    out = np.empty((out_h, out_w), np.uint8)
    step = strip_rows * factor
    for y0 in range(0, out_h * factor, step):
        y1 = min(y0 + step, out_h * factor)
        cv2.resize(
            img[y0:y1, : out_w * factor],
            (out_w, (y1 - y0) // factor),
            dst=out[y0 // factor : y1 // factor],
            interpolation=cv2.INTER_AREA,
        )
    return out


def _read_gray(path: Path) -> np.ndarray | None:
    """Full-size uint8 grayscale; Pillow covers formats OpenCV can't read (e.g. AVIF)."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is not None:
        return img
    try:
        with PILImage.open(path) as im:
            return np.asarray(im.convert("L"))
    except (OSError, ValueError):
        return None


def decode_gray(
    path: Path, width: int, height: int, p: AnalysisParams, jpeg: bool
) -> tuple[np.ndarray | None, int]:
    """Return (analysis image, reduction factor)."""
    factor = reduction_factor(max(width, height), p.max_analysis_dim)
    if factor > 1 and jpeg:
        img = cv2.imread(str(path), _REDUCED_FLAGS[factor])
        if img is not None:
            return img, factor
    img = _read_gray(path)
    if img is None:
        return None, factor
    return _box_reduce_strips(img, factor, p.strip_rows), factor


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass
class Profiles:
    """Line-energy profiles of one image.

    ``col`` / ``row``: absolute line energy summed down columns / along rows.
    ``col_s`` / ``row_s``: the same, signed (line polarity).
    ``col_band[b]``: column profile of horizontal band ``b`` (vertical lines in band b).
    ``row_band[b]``: row profile of vertical band ``b`` (horizontal lines in band b).
    """

    col: np.ndarray
    row: np.ndarray
    col_s: np.ndarray | None = None
    row_s: np.ndarray | None = None
    col_band: np.ndarray | None = None
    row_band: np.ndarray | None = None


def axis_profiles(img: np.ndarray, p: AnalysisParams, extended: bool = True) -> Profiles:
    """Column and row line-energy profiles, accumulated over horizontal strips so no
    full-size float image is ever allocated. ``extended`` adds the signed and banded
    profiles used by the spatial features."""
    h, w = img.shape
    col = np.zeros(w, np.float64)
    row = np.zeros(h, np.float64)
    col_s = np.zeros(w, np.float64) if extended else None
    row_s = np.zeros(h, np.float64) if extended else None
    col_band = np.zeros((N_BANDS, w), np.float64) if extended else None
    row_band = np.zeros((N_BANDS, h), np.float64) if extended else None
    xb = np.linspace(0, w, N_BANDS + 1).astype(int)
    box = p.absdev_box
    blur_k = 2 * int(math.ceil(3 * p.preblur)) + 1
    halo = box // 2 + 1 + int(math.ceil(3 * p.preblur))
    for y0 in range(0, h, p.strip_rows):
        y1 = min(h, y0 + p.strip_rows)
        a0, a1 = max(0, y0 - halo), min(h, y1 + halo)
        s = img[a0:a1].astype(np.float32)
        # Vertical lines: blur and local mean along x only, so no halo rows are needed.
        sx = cv2.GaussianBlur(
            s[y0 - a0 : y1 - a0], (blur_k, 1), p.preblur, borderType=cv2.BORDER_REFLECT
        )
        dx = sx - cv2.blur(sx, (box, 1), borderType=cv2.BORDER_REFLECT)
        c = np.abs(dx).sum(axis=0, dtype=np.float64)
        col += c
        # Horizontal lines: blur and local mean along y, using the halo rows as context.
        sy = cv2.GaussianBlur(s, (1, blur_k), p.preblur, borderType=cv2.BORDER_REFLECT)
        dy = (sy - cv2.blur(sy, (1, box), borderType=cv2.BORDER_REFLECT))[y0 - a0 : y1 - a0]
        ay = np.abs(dy)
        row[y0:y1] += ay.sum(axis=1, dtype=np.float64)
        if extended:
            col_s += dx.sum(axis=0, dtype=np.float64)
            band = min(N_BANDS - 1, int((y0 + y1) / 2 / h * N_BANDS))
            col_band[band] += c
            row_s[y0:y1] += dy.sum(axis=1, dtype=np.float64)
            for j in range(N_BANDS):
                row_band[j, y0:y1] += ay[:, xb[j] : xb[j + 1]].sum(axis=1, dtype=np.float64)
    return Profiles(col, row, col_s, row_s, col_band, row_band)


def oblique_profile(img: np.ndarray, theta_deg: float, p: AnalysisParams) -> np.ndarray:
    """Radon-style projection of line energy onto the axis at ``theta_deg``, normalised
    by pixel count per bin and trimmed where few pixels contribute."""
    h, w = img.shape
    ct, st = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    xs = np.arange(w - 1, dtype=np.float32) * ct
    corners = [x * ct + y * st for x in (0, w - 2) for y in (0, h - 2)]
    umin, umax = min(corners), max(corners)
    nb = int(math.ceil(umax - umin)) + 2
    acc = np.zeros(nb, np.float64)
    cnt = np.zeros(nb, np.float64)
    box = p.absdev_box
    for y0 in range(0, h - 1, p.strip_rows):
        y1 = min(h, y0 + p.strip_rows + 1)
        a0, a1 = max(0, y0 - box), min(h, y1 + box)
        s = img[a0:a1].astype(np.float32)
        d = np.abs(s - cv2.blur(s, (box, box), borderType=cv2.BORDER_REFLECT))
        d = d[y0 - a0 : y1 - 1 - a0, :-1]
        ys = np.arange(y0, y1 - 1, dtype=np.float32)[:, None] * st
        idx = (xs[None, :] + ys - umin + 0.5).astype(np.int32).ravel()
        acc += np.bincount(idx, weights=d.ravel(), minlength=nb)
        cnt += np.bincount(idx, minlength=nb)
    keep = cnt >= 0.3 * cnt.max()
    i0, i1 = np.argmax(keep), len(keep) - np.argmax(keep[::-1])
    return acc[i0:i1] / cnt[i0:i1]


# ---------------------------------------------------------------------------
# Spectra and the harmonic comb
# ---------------------------------------------------------------------------


@dataclass
class Spectrum:
    """Whitened magnitude spectrum on a zero-padded grid (index = frequency * pad)."""

    ratio: np.ndarray
    n: int  # profile length
    pad: int
    _logratio_cache: np.ndarray | None = None

    def logratio(self) -> np.ndarray:
        if self._logratio_cache is None:
            lr = np.log(np.maximum(self.ratio, 1.0))
            # Tolerate rounding of k*f to the padded grid: max over +-1 padded bins.
            self._logratio_cache = np.maximum(lr, np.maximum(np.roll(lr, 1), np.roll(lr, -1)))
        return self._logratio_cache

    def comb(self, f: np.ndarray, harmonics: int, nyq_frac: float, parity: int = 0) -> np.ndarray:
        """1/k-weighted mean log-whitened magnitude over harmonics k*f below the Nyquist
        cut, vectorised over ``f``. ``parity``: 1 = odd k only, 2 = even k only, 0 = all."""
        f = np.atleast_1d(f).astype(np.float64)
        fmax = nyq_frac * self.n
        tot = np.zeros_like(f)
        num = np.zeros_like(f)
        lr = self.logratio()
        for k in range(1, harmonics + 1):
            if (parity == 1 and k % 2 == 0) or (parity == 2 and k % 2 == 1):
                continue
            kf = k * f
            ok = kf <= fmax
            idx = np.clip(np.round(kf * self.pad).astype(np.int64), 0, len(lr) - 1)
            weight = 1.0 / k  # a subharmonic (f/2) only collects half the weight
            tot += np.where(ok, weight * lr[idx], 0.0)
            num += np.where(ok, weight, 0.0)
        return np.where(num > 0, tot / np.maximum(num, 1e-9), 0.0)


def spectrum(profile: np.ndarray, p: AnalysisParams, block_period: float = 0.0) -> Spectrum:
    """Whitened, zero-padded magnitude spectrum. ``block_period`` (profile px) notches out
    a known artefact period and its harmonics (JPEG 8x8 blocks)."""
    x = profile - profile.mean()
    n = len(x)
    # Hann window: without it, sidelobes of a strong harmonic leak into the zero-padded
    # bins and fake energy at odd multiples of f/2, i.e. a false 2c.
    x = x * np.hanning(n)
    mag = np.abs(np.fft.rfft(x))
    floor = median_filter(mag, size=2 * p.whiten_halfwidth + 1, mode="nearest") + 1e-9
    magp = np.abs(np.fft.rfft(x, n=n * p.pad))
    fl = np.interp(np.arange(len(magp)) / p.pad, np.arange(len(floor)), floor)
    ratio = magp / fl
    if block_period > 2.0:
        fb = n / block_period
        for m in range(1, int(n / 2 / fb) + 1):
            c = int(round(m * fb * p.pad))
            ratio[max(0, c - 2 * p.pad) : c + 2 * p.pad + 1] = 1.0
    return Spectrum(ratio=ratio, n=n, pad=p.pad)


def pick_fundamental(
    cells: np.ndarray, score: np.ndarray, odd: np.ndarray, p: AnalysisParams
) -> int:
    """Choose the cell size among local maxima of ``score``.

    Whitening makes higher harmonics score at least as well as the fundamental, so
    "highest score" tends to pick c/2, and "largest c near the best" alone can pick 2c.
    Instead: among local maxima scoring >= ``subharmonic_ratio`` * best, take the largest
    cell whose odd harmonics reach ``odd_frac`` * best; a false 2c has almost nothing at
    the odd multiples of its fundamental.
    """
    best = float(score.max())
    if best <= 0:
        return int(np.argmax(score))
    lm = np.r_[False, (score[1:-1] >= score[:-2]) & (score[1:-1] >= score[2:]), False]
    lm |= score == best
    good = np.where(lm & (score >= p.subharmonic_ratio * best))[0]
    for i in good[np.argsort(-cells[good])]:
        if odd[i] >= p.odd_frac * best:
            return int(i)
    return int(np.argmax(score))


def refine_count(
    spec: Spectrum, n_px: int, dim: int, cell: float, p: AnalysisParams
) -> tuple[float, float]:
    """Fractional tile count near ``dim / cell`` on one axis (allows borders and a small
    x/y mismatch). Returns (count, comb score at that count)."""
    t0 = dim / cell
    lo, hi = t0 * (1 - p.refine_window) - 0.6, t0 * (1 + p.refine_window) + 0.6
    ts = np.arange(max(lo, 1.0), hi, 1.0 / p.pad)
    s = spec.comb(ts * (spec.n / n_px), p.harmonics, p.nyquist_frac)
    j = int(np.argmax(s))
    return float(ts[j]), float(s[j])


def null_scores(
    spec: Spectrum,
    fmin: float,
    fmax: float,
    p: AnalysisParams,
    n_draws: int = 256,
    seed: int = 0,
) -> tuple[float, float]:
    """Comb-score distribution at random non-harmonic frequency sets in the same spectrum
    (same 1/k weights, same band), as (mean, std). Seeded, so results are deterministic."""
    rng = np.random.default_rng(seed)
    lr = spec.logratio()
    fcap = p.nyquist_frac * spec.n
    f0 = np.exp(rng.uniform(math.log(max(fmin, 1.0)), math.log(max(fmax, fmin + 1.0)), n_draws))
    tot = np.zeros(n_draws)
    num = np.zeros(n_draws)
    for k in range(1, p.harmonics + 1):
        fk = f0 * k * (1.0 + rng.uniform(-0.25, 0.25, n_draws) / k)
        ok = fk <= fcap
        idx = np.clip(np.round(fk * spec.pad).astype(np.int64), 0, len(lr) - 1)
        tot += np.where(ok, lr[idx] / k, 0.0)
        num += np.where(ok, 1.0 / k, 0.0)
    v = np.where(num > 0, tot / np.maximum(num, 1e-9), 0.0)
    return float(v.mean()), float(v.std() + 1e-6)
