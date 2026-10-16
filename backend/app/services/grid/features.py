"""Grid detection v3 measurements and the model feature vector.

``measure()`` runs the analysis in ``analysis.py`` on one image and returns a flat dict
of measurements: the comb search result, a per-image null distribution, spatial
consistency features, and two hex measures. ``feature_vector()`` turns that dict into
the ordered input expected by a trained model (the order lives in the model's
``meta.json``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from .analysis import (
    N_BANDS,
    AnalysisParams,
    Profiles,
    Spectrum,
    axis_profiles,
    decode_gray,
    is_jpeg,
    null_scores,
    oblique_profile,
    pick_fundamental,
    refine_count,
    spectrum,
)

HEX_ANGLES = (30, 60, 120, 150)


# ---------------------------------------------------------------------------
# Hex measures
# ---------------------------------------------------------------------------


def hex_oblique_measure(img: np.ndarray, scale: float, p: AnalysisParams) -> dict:
    """Hex strength from projections at the hex edge normals (on a coarse copy).

    Pointy-top hexes have edge families at 0/60/120 deg repeating every q = s/2, and hex
    *rows* at 90/30/150 deg repeating every sqrt(3)*q (flat-top: swapped). Requiring both
    rejects square lattices, however strong.
    """
    ah, aw = img.shape
    hs = min(1.0, p.hex_max_dim / max(aw, ah))
    coarse = (
        img
        if hs >= 1.0
        else cv2.resize(
            img, (max(2, int(aw * hs)), max(2, int(ah * hs))), interpolation=cv2.INTER_AREA
        )
    )
    sc = hs * scale  # coarse px per original px
    qmin = max(3.0, p.min_cell_px * sc / 2)
    qmax = p.max_cell_px * sc / 2
    prof = axis_profiles(coarse, p, extended=False)
    profs = {0: prof.col, 90: prof.row}
    for th in HEX_ANGLES:
        profs[th] = oblique_profile(coarse, th, p)
    qmax = min(qmax, min(len(v) for v in profs.values()) / 6)
    if qmax <= qmin:
        return {"hex": 0.0, "hex_edges": 0.0, "hex_pointy": 0.0, "hex_flat": 0.0}
    qs = np.exp(np.linspace(math.log(qmin), math.log(qmax), 1500))
    specs = {th: spectrum(pr, p) for th, pr in profs.items()}

    def score(th: int, period: np.ndarray) -> np.ndarray:
        sp = specs[th]
        return sp.comb(sp.n / period, p.harmonics, p.nyquist_frac)

    r3 = math.sqrt(3.0)
    pe = np.minimum(np.minimum(score(0, qs), score(60, qs)), score(120, qs))
    pl = np.minimum(np.minimum(score(90, r3 * qs), score(30, r3 * qs)), score(150, r3 * qs))
    fe = np.minimum(np.minimum(score(90, qs), score(30, qs)), score(150, qs))
    fl = np.minimum(np.minimum(score(0, r3 * qs), score(60, r3 * qs)), score(120, r3 * qs))
    pointy = np.minimum(pe, pl)
    flat = np.minimum(fe, fl)
    return {
        "hex": float(max(pointy.max(), flat.max())),
        "hex_edges": float(max(pe.max(), fe.max())),
        "hex_pointy": float(pointy.max()),
        "hex_flat": float(flat.max()),
    }


def hex_fft_measure(img: np.ndarray, scale: float, p: AnalysisParams) -> dict:
    """Six-fold vs four-fold symmetry in the 2-D spectrum of the line-energy image.

    The spectrum (on a coarse copy) is whitened by the annulus median and resampled to
    polar (r, theta), then searched exhaustively:
      hex2d = min of the three first-ring peaks theta, theta+60, theta+120 at radius r
      hex2d_both also requires the second ring (r*sqrt3 at theta+30/90/150)
      sq2d = min(theta, theta+90) at r; sq2d_both also requires the r*sqrt2 ring
    Scores are log whitened magnitudes, so they are comparable across images.
    """
    ah, aw = img.shape
    target = int(min(2048, max(768, max(aw, ah) / scale * 5 / p.min_cell_px)))
    hs = min(1.0, target / max(aw, ah))
    g = (
        img
        if hs >= 1.0
        else cv2.resize(
            img, (max(16, int(aw * hs)), max(16, int(ah * hs))), interpolation=cv2.INTER_AREA
        )
    )
    g = cv2.GaussianBlur(g.astype(np.float32), (3, 3), 0.8)
    e = np.abs(g - cv2.blur(g, (5, 5)))
    e -= e.mean()
    gh, gw = e.shape
    n = 1 << int(math.ceil(math.log2(max(gh, gw))))
    padded = np.zeros((n, n), np.float32)
    padded[:gh, :gw] = e * np.outer(np.hanning(gh), np.hanning(gw)).astype(np.float32)
    mag = np.fft.fftshift(np.abs(np.fft.rfft2(padded)), axes=0).astype(np.float32)
    ky = np.arange(-n // 2, n // 2)[:, None]
    kx = np.arange(0, n // 2 + 1)[None, :]
    ri = np.round(np.hypot(kx, ky)).astype(np.int64)
    nb = int(ri.max()) + 1
    order = np.argsort(ri, axis=None)
    rs = ri.ravel()[order]
    fs = mag.ravel()[order]
    bounds = np.searchsorted(rs, np.arange(nb + 1))
    med = np.ones(nb, np.float32)
    for i in range(nb):
        seg = fs[bounds[i] : bounds[i + 1]]
        if len(seg):
            med[i] = np.median(seg)
    whitened = np.log(np.maximum(mag / (med[ri] + 1e-9), 1.0)).astype(np.float32)
    sc = hs * scale
    rmin = max(4.0, n / (p.max_cell_px * sc))
    rmax = min(n / 2 - 2, n / (p.min_cell_px * sc) * 1.3)
    out = {"hex2d": 0.0, "hex2d_both": 0.0, "sq2d": 0.0, "sq2d_both": 0.0}
    if rmax <= rmin + 2:
        return out
    radii = np.arange(rmin, n / 2 - 2, 1.0, dtype=np.float32)
    thetas = np.radians(np.arange(0, 180, 1.0, dtype=np.float32))
    rr_grid, tt_grid = np.meshgrid(radii, thetas, indexing="ij")
    kxs = rr_grid * np.cos(tt_grid)
    kys = -rr_grid * np.sin(tt_grid)
    neg = kxs < 0
    kxs = np.where(neg, -kxs, kxs)
    kys = np.where(neg, -kys, kys)
    polar = cv2.remap(
        whitened,
        kxs.astype(np.float32),
        (kys + n // 2).astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    polar = np.concatenate([polar[:, -2:], polar, polar[:, :2]], axis=1)
    polar = cv2.dilate(polar, np.ones((3, 3), np.uint8))[:, 2:-2]  # +-1 radius bin, +-1 deg
    nr = polar.shape[0]
    in_band = radii <= rmax

    def ring(r_idx: np.ndarray, deg: np.ndarray) -> np.ndarray:
        return polar[np.clip(r_idx, 0, nr - 1)][:, np.asarray(deg) % 180]

    th0 = np.arange(0, 60)
    rr = np.arange(nr)
    h1 = np.minimum(np.minimum(ring(rr, th0), ring(rr, th0 + 60)), ring(rr, th0 + 120))
    r2 = np.clip(np.round(radii * math.sqrt(3) - rmin).astype(int), 0, nr - 1)
    ok2 = (np.round(radii * math.sqrt(3) - rmin).astype(int) < nr)[:, None]
    h2 = np.where(
        ok2,
        np.minimum(
            np.minimum(polar[r2][:, (th0 + 30) % 180], polar[r2][:, (th0 + 90) % 180]),
            polar[r2][:, (th0 + 150) % 180],
        ),
        0.0,
    )
    th90 = np.arange(0, 90)
    s1 = np.minimum(ring(rr, th90), ring(rr, th90 + 90))
    rq = np.clip(np.round(radii * math.sqrt(2) - rmin).astype(int), 0, nr - 1)
    okq = (np.round(radii * math.sqrt(2) - rmin).astype(int) < nr)[:, None]
    s2 = np.where(
        okq,
        np.minimum(polar[rq][:, (th90 + 45) % 180], polar[rq][:, (th90 + 135) % 180]),
        0.0,
    )
    for arr in (h1, h2, s1, s2):
        arr[~in_band] = 0
    out.update(
        hex2d=float(h1.max()),
        hex2d_both=float(np.minimum(h1, h2).max()),
        sq2d=float(s1.max()),
        sq2d_both=float(np.minimum(s1, s2).max()),
    )
    return out


# ---------------------------------------------------------------------------
# Spatial consistency
# ---------------------------------------------------------------------------


def _phase(profile: np.ndarray, period: float, steps: int = 64) -> np.ndarray:
    """Line positions of the best-aligned comb with the given period."""
    n = len(profile)
    ks = np.arange(0, int(n / period) + 1)
    grid = np.arange(n)
    best, best_phi = -1.0, 0.0
    for phi in np.linspace(0, period, steps, endpoint=False):
        xs = phi + ks * period
        xs = xs[xs <= n - 1]
        v = np.interp(xs, grid, profile).mean()
        if v > best:
            best, best_phi = v, phi
    xs = best_phi + ks * period
    return xs[xs <= n - 1]


def _line_contrast(
    profile: np.ndarray, xs: np.ndarray, period: float, lo: int = 0, hi: int | None = None
) -> float:
    """Mean line energy at the grid lines relative to the median at mid-cell."""
    n = len(profile)
    hi = n if hi is None else hi
    sel = xs[(xs >= lo) & (xs < hi)]
    if len(sel) == 0:
        return float("nan")
    idx = np.round(sel).astype(int)
    lines = np.max(np.stack([profile[np.clip(idx + d, 0, n - 1)] for d in (-1, 0, 1)]), axis=0)
    mids = np.interp(np.clip(sel + period / 2, 0, n - 1), np.arange(n), profile)
    return float(lines.mean() / (np.median(mids) + 1e-9))


def _polarity(signed: np.ndarray, absolute: np.ndarray, pos: np.ndarray) -> tuple[float, float]:
    """(|signed sum| / abs sum, mean sign) of line energy at the grid line positions."""
    n = len(signed)
    idx = np.clip(np.round(pos).astype(int), 0, n - 1)
    cand = np.stack([signed[np.clip(idx + d, 0, n - 1)] for d in (-1, 0, 1)])
    pick = cand[np.argmax(np.abs(cand), axis=0), np.arange(cand.shape[1])]
    a = np.max(np.stack([absolute[np.clip(idx + d, 0, n - 1)] for d in (-1, 0, 1)]), axis=0)
    return float(abs(pick.sum()) / (a.sum() + 1e-9)), float(np.mean(np.sign(pick)))


def spatial_features(prof: Profiles, aw: int, ah: int, nx: float, ny: float) -> dict:
    """Does the grid cover the whole map, with consistently coloured lines?

    Floor tiles and seat rows that line up with the grid are local; a drawn grid covers
    the whole map. Coverage is the fraction of 4x4 blocks whose phase-locked line contrast
    exceeds a threshold. Polarity coherence is high for an overlay (the same dark or light
    line everywhere) and low for tile seams of varying colour.
    """
    out: dict = {}
    px, py = aw / nx, ah / ny
    xs = _phase(prof.col, px)
    ys = _phase(prof.row, py)
    out["contrast_x"] = _line_contrast(prof.col, xs, px)
    out["contrast_y"] = _line_contrast(prof.row, ys, py)
    xb = np.linspace(0, aw, N_BANDS + 1).astype(int)
    yb = np.linspace(0, ah, N_BANDS + 1).astype(int)
    blocks = []
    for by in range(N_BANDS):
        for bx in range(N_BANDS):
            cvx = _line_contrast(prof.col_band[by], xs, px, xb[bx], xb[bx + 1])
            cvy = _line_contrast(prof.row_band[bx], ys, py, yb[by], yb[by + 1])
            vals = [v for v in (cvx, cvy) if not math.isnan(v)]
            blocks.append(min(vals) if vals else 1.0)
    block_arr = np.array(blocks)
    out["block_contrast_med"] = float(np.median(block_arr))
    out["block_contrast_min"] = float(block_arr.min())
    for t in (1.15, 1.3, 1.6):
        out[f"coverage_{t}"] = float((block_arr >= t).mean())
    pol_x, sign_x = _polarity(prof.col_s, prof.col, xs)
    pol_y, sign_y = _polarity(prof.row_s, prof.row, ys)
    out["polarity"] = 0.5 * (pol_x + pol_y)
    out["sign_agree"] = float(np.sign(sign_x) == np.sign(sign_y))
    return out


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def measure(
    path: Path,
    width: int,
    height: int,
    p: AnalysisParams,
    sibling_counts: Sequence[tuple[int, int]] = (),
) -> dict | None:
    """All measurements for one image, or None if it can't be decoded.

    ``ok`` is False when the image is too small for any allowed cell size; the counts are
    then missing and only the hex measures are meaningful.

    ``sibling_counts`` are tile counts read from other files' names in the same group.
    When given, ``sibling_scores`` holds the comb score at each, for the size-only prior.
    """
    jpeg = is_jpeg(path)
    img, factor = decode_gray(path, width, height, p, jpeg)
    if img is None:
        return None
    ah, aw = img.shape
    sx, sy = aw / width, ah / height  # analysis px per original px
    prof = axis_profiles(img, p, extended=True)
    block = 8.0 / factor if jpeg else 0.0
    spx, spy = spectrum(prof.col, p, block), spectrum(prof.row, p, block)
    min_c = max(p.min_cell_px, 2.2 / min(sx, sy))
    max_c = min(p.max_cell_px, min(width, height) / 3)
    out: dict = {"factor": factor, "aw": aw, "ah": ah, "width": width, "height": height}
    out.update(hex_fft_measure(img, min(sx, sy), p))
    if max_c <= min_c:
        # Too small for any allowed cell. The oblique hex measure is skipped too: the
        # models were trained with these fields at zero for such images.
        out.update(ok=False, joint=0.0, sx=0.0, sy=0.0, nx=None, ny=None, cell=None, hex=0.0)
        return out

    cells = np.exp(np.linspace(math.log(min_c), math.log(max_c), p.cell_samples))
    # Tile count == cycles per image; the profile has n samples spanning aw analysis px.
    tx, ty = (width / cells) * (spx.n / aw), (height / cells) * (spy.n / ah)
    jx = spx.comb(tx, p.harmonics, p.nyquist_frac)
    jy = spy.comb(ty, p.harmonics, p.nyquist_frac)
    joint = 0.5 * (jx + jy)
    odd = 0.5 * (
        spx.comb(tx, p.harmonics, p.nyquist_frac, 1) + spy.comb(ty, p.harmonics, p.nyquist_frac, 1)
    )
    i = pick_fundamental(cells, joint, odd, p)
    cell = float(cells[i])
    nx, _ = refine_count(spx, aw, width, cell, p)
    ny, _ = refine_count(spy, ah, height, cell, p)
    out.update(
        ok=True,
        joint=float(joint[i]),
        sx=float(jx[i]),
        sy=float(jy[i]),
        cell=cell,
        nx=nx,
        ny=ny,
        odd=float(odd[i]),
    )

    # How far the chosen comb stands out from random spacings in the same spectra.
    fx_lo, fx_hi = (width / max_c) * (spx.n / aw), (width / min_c) * (spx.n / aw)
    fy_lo, fy_hi = (height / max_c) * (spy.n / ah), (height / min_c) * (spy.n / ah)
    mean_x, sd_x = null_scores(spx, fx_lo, fx_hi, p, seed=1)
    mean_y, sd_y = null_scores(spy, fy_lo, fy_hi, p, seed=2)
    out["z_x"] = (out["sx"] - mean_x) / sd_x
    out["z_y"] = (out["sy"] - mean_y) / sd_y
    out["null_mean"] = 0.5 * (mean_x + mean_y)
    out["null_sd"] = 0.5 * math.sqrt(sd_x**2 + sd_y**2)
    out["z_joint"] = (out["joint"] - out["null_mean"]) / out["null_sd"]
    med = float(np.median(joint))
    mad = float(np.median(np.abs(joint - med))) * 1.4826 + 1e-6
    out["z_self"] = (out["joint"] - med) / mad

    out.update(spatial_features(prof, aw, ah, nx, ny))
    out.update(hex_oblique_measure(img, min(sx, sy), p))
    if sibling_counts:
        out["sibling_scores"] = {
            counts: _comb_at_counts(spx, spy, aw, ah, counts, p) for counts in sibling_counts
        }
        out["own_score"] = _comb_at_counts(spx, spy, aw, ah, (round(nx), round(ny)), p)
    return out


def _comb_at_counts(
    spx: Spectrum, spy: Spectrum, aw: int, ah: int, counts: tuple[int, int], p: AnalysisParams
) -> float:
    """Mean comb score of both axes at the given tile counts."""
    a = float(spx.comb(np.array([counts[0] * spx.n / aw]), p.harmonics, p.nyquist_frac)[0])
    b = float(spy.comb(np.array([counts[1] * spy.n / ah]), p.harmonics, p.nyquist_frac)[0])
    return 0.5 * (a + b)


def feature_vector(m: dict, names: Sequence[str]) -> list[float]:
    """Ordered model input; derived features are computed here, missing or non-finite
    values become 0 (as in training)."""
    d = dict(m)
    d["minax"] = min(m.get("sx", 0.0), m.get("sy", 0.0))
    d["z_minax"] = min(m.get("z_x", 0.0), m.get("z_y", 0.0))
    d["log_mindim"] = math.log(max(16, min(m.get("width", 16), m.get("height", 16))))
    d["log_cell"] = math.log(m["cell"]) if m.get("cell") else 0.0
    d["contrast_min"] = min(m.get("contrast_x", 1.0), m.get("contrast_y", 1.0))
    out = []
    for name in names:
        v = d.get(name, 0.0)
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            v = 0.0
        out.append(float(v))
    return out
