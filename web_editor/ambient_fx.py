"""Modular Dynamic Ambient FX Engine for VK03M 960x360 (and arbitrary WxH) LCD.

Contains 13 distinct procedural ambient light effects (3 classic + 10 new open-source
inspired effects from WLED 2D, OpenRGB Effects, Vanta.js, Shadertoy, cmatrix, tsParticles):

Classic (3):
- waves     : 多頻柔和平滑波浪 (Flowing Sine Waves)
- particles : 科技星座連線點陣 (Constellation Particles)
- dual      : 波浪 + 點線雙重融合 (Dual Waves & Particles)

New 10 Effects:
- aurora    : 極光幕簾 (Northern Lights Curtain — NumPy shader)
- plasma    : 等離子雲 (Demoscene Plasma Interference — NumPy shader)
- metaballs : 熔岩光球 (Liquid Light Metaballs — NumPy shader)
- matrix    : 駭客代碼雨 (Digital Matrix Rain)
- synthgrid : 賽博網格 (Outrun 3D Perspective Horizon Grid)
- starfield : 星際躍遷 (3D Hyperspace Warp Starfield)
- circuit   : 晶片脈衝 (Cyberpunk PCB Signal Traces)
- hexpulse  : 蜂巢脈動 (Sci-Fi Hexagonal Energy Wave)
- radar     : 雷達掃描 (Tactical Phosphor Sonar Sweep)
- fireflies : 流螢光斑 (Soft Breathing Bokeh Fireflies)
"""

from __future__ import annotations

import math
import os
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RGB = tuple[int, int, int]

AMBIENT_FX_CATALOG: list[dict[str, str]] = [
    {"id": "off",       "name": "關閉",     "en": "Off"},
    {"id": "waves",     "name": "波浪",     "en": "Waves"},
    {"id": "particles", "name": "點線",     "en": "Constellation"},
    {"id": "dual",      "name": "融合",     "en": "Dual"},
    {"id": "aurora",    "name": "極光幕簾", "en": "Aurora"},
    {"id": "plasma",    "name": "等離子雲", "en": "Plasma"},
    {"id": "metaballs", "name": "熔岩光球", "en": "Metaballs"},
    {"id": "matrix",    "name": "代碼雨",   "en": "Matrix Rain"},
    {"id": "synthgrid", "name": "賽博網格", "en": "SynthGrid"},
    {"id": "starfield", "name": "星際躍遷", "en": "Starfield"},
    {"id": "circuit",   "name": "晶片脈衝", "en": "Circuit"},
    {"id": "hexpulse",  "name": "蜂巢脈動", "en": "HexPulse"},
    {"id": "radar",     "name": "雷達掃描", "en": "Radar"},
    {"id": "fireflies", "name": "流螢光斑", "en": "Fireflies"},
]

VALID_AMBIENT_FX: set[str] = {item["id"] for item in AMBIENT_FX_CATALOG}

# ── Cached Precomputations (Zero Per-Frame Allocation Overhead) ───────────────
_GRID_CACHE: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
_HEX_CACHE: dict[tuple[int, int], list[tuple[float, float, list[tuple[float, float]]]]] = {}
_CIRCUIT_CACHE: dict[tuple[int, int], list[dict]] = {}
_MONO_FONT: ImageFont.FreeTypeFont | None = None

_MATRIX_GLYPHS = "0123456789ABCDEF<>/:*+=#"


def _get_mono_font(size: int = 13) -> ImageFont.FreeTypeFont:
    global _MONO_FONT
    if _MONO_FONT is not None:
        return _MONO_FONT
    for path in (
        r"C:\Windows\Fonts\consolab.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        r"C:\Windows\Fonts\bahnschrift.ttf",
    ):
        if os.path.exists(path):
            try:
                _MONO_FONT = ImageFont.truetype(path, size)
                return _MONO_FONT
            except Exception:
                pass
    _MONO_FONT = ImageFont.load_default()
    return _MONO_FONT


def _get_norm_grid(gw: int, gh: int) -> tuple[np.ndarray, np.ndarray]:
    key = (gw, gh)
    if key not in _GRID_CACHE:
        xs = np.linspace(0.0, 1.0, gw, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, gh, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        _GRID_CACHE[key] = (gx, gy)
    return _GRID_CACHE[key]


def _get_hex_cells(w: int, h: int, radius: float = 28.0):
    key = (w, h)
    if key in _HEX_CACHE:
        return _HEX_CACHE[key]
    cells = []
    dx = radius * 1.5
    dy = radius * math.sqrt(3.0)
    cols = int(w / dx) + 3
    rows = int(h / dy) + 3
    for col in range(-1, cols):
        cx = col * dx
        y_off = (dy * 0.5) if (col % 2 != 0) else 0.0
        for row in range(-1, rows):
            cy = row * dy + y_off
            if cx < -radius or cx > w + radius or cy < -radius or cy > h + radius:
                continue
            pts = [
                (
                    cx + (radius - 1.5) * math.cos(math.radians(60 * k)),
                    cy + (radius - 1.5) * math.sin(math.radians(60 * k)),
                )
                for k in range(6)
            ]
            cells.append((cx, cy, pts))
    _HEX_CACHE[key] = cells
    return cells


def _get_circuit_traces(w: int, h: int) -> list[dict]:
    key = (w, h)
    if key in _CIRCUIT_CACHE:
        return _CIRCUIT_CACHE[key]

    # 14 clean deterministic PCB routes with 45-degree bends spanning across WxH
    specs = [
        ([(0.0, 0.14), (0.22, 0.14), (0.28, 0.28), (0.58, 0.28), (0.64, 0.16), (1.0, 0.16)], 0, 1.0, 0.00),
        ([(0.0, 0.30), (0.14, 0.30), (0.19, 0.44), (0.42, 0.44), (0.48, 0.34), (0.80, 0.34), (0.86, 0.22), (1.0, 0.22)], 1, 0.85, 0.31),
        ([(1.0, 0.48), (0.76, 0.48), (0.70, 0.36), (0.36, 0.36), (0.30, 0.52), (0.0, 0.52)], 2, 0.92, 0.62),
        ([(0.0, 0.68), (0.18, 0.68), (0.25, 0.56), (0.55, 0.56), (0.61, 0.72), (1.0, 0.72)], 0, 0.78, 0.18),
        ([(1.0, 0.84), (0.68, 0.84), (0.62, 0.68), (0.32, 0.68), (0.26, 0.82), (0.0, 0.82)], 1, 1.05, 0.47),
        ([(0.0, 0.92), (0.38, 0.92), (0.44, 0.78), (0.78, 0.78), (0.84, 0.92), (1.0, 0.92)], 2, 0.72, 0.83),
        ([(0.08, 0.0), (0.08, 0.24), (0.16, 0.38), (0.16, 0.76), (0.09, 0.90), (0.09, 1.0)], 0, 0.90, 0.25),
        ([(0.34, 0.0), (0.34, 0.18), (0.40, 0.30), (0.40, 0.64), (0.33, 0.78), (0.33, 1.0)], 2, 0.82, 0.55),
        ([(0.66, 1.0), (0.66, 0.76), (0.60, 0.62), (0.60, 0.26), (0.67, 0.12), (0.67, 0.0)], 1, 0.88, 0.12),
        ([(0.90, 0.0), (0.90, 0.32), (0.83, 0.46), (0.83, 0.80), (0.91, 0.94), (0.91, 1.0)], 0, 0.96, 0.74),
        ([(0.0, 0.07), (0.48, 0.07), (0.53, 0.20), (0.88, 0.20), (0.94, 0.08), (1.0, 0.08)], 1, 0.68, 0.40),
        ([(1.0, 0.60), (0.82, 0.60), (0.76, 0.46), (0.50, 0.46), (0.45, 0.62), (0.18, 0.62), (0.12, 0.46), (0.0, 0.46)], 2, 0.80, 0.09),
        ([(0.20, 1.0), (0.20, 0.86), (0.27, 0.72), (0.52, 0.72), (0.58, 0.86), (0.58, 1.0)], 0, 0.75, 0.66),
        ([(0.74, 0.0), (0.74, 0.14), (0.79, 0.28), (0.79, 0.54), (0.72, 0.68), (0.72, 1.0)], 2, 0.86, 0.91),
    ]

    traces = []
    for norm_pts, col_idx, spd, phase in specs:
        pts = [(px * w, py * h) for px, py in norm_pts]
        cum = [0.0]
        total = 0.0
        for i in range(len(pts) - 1):
            seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            total += seg
            cum.append(total)
        traces.append({
            "pts": pts,
            "cum": cum,
            "total": max(1.0, total),
            "col_idx": col_idx,
            "speed": spd,
            "phase": phase,
        })
    _CIRCUIT_CACHE[key] = traces
    return traces


def _sample_polyline(pts: list[tuple[float, float]], cum: list[float], dist: float) -> tuple[float, float]:
    if dist <= 0.0:
        return pts[0]
    if dist >= cum[-1]:
        return pts[-1]
    for i in range(len(cum) - 1):
        if cum[i] <= dist <= cum[i + 1]:
            span = max(1e-5, cum[i + 1] - cum[i])
            u = (dist - cum[i]) / span
            return (
                pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u,
                pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u,
            )
    return pts[-1]


# ── Classic 3 Effects (Preserved) ────────────────────────────────────────────
def _render_waves(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                  c1: RGB, c2: RGB, c3: RGB) -> None:
    pts1 = [(0, h)]
    for x in range(0, w + 12, 12):
        y = h * 0.755 + 14 * math.sin(0.0060 * x + t * 0.42) + 5 * math.cos(0.011 * x - t * 0.24)
        pts1.append((x, y))
    pts1.append((w, h))
    fd.polygon(pts1, fill=(*c1, int(255 * 0.16 * opacity)))
    fd.line(pts1[1:-1], fill=(*c1, int(255 * 0.75 * opacity)), width=2)

    pts2 = [(0, h)]
    for x in range(0, w + 12, 12):
        y = h * 0.805 + 11 * math.sin(0.0075 * x - t * 0.34 + 1.4) + 4 * math.cos(0.005 * x + t * 0.18)
        pts2.append((x, y))
    pts2.append((w, h))
    fd.polygon(pts2, fill=(*c2, int(255 * 0.14 * opacity)))
    fd.line(pts2[1:-1], fill=(*c2, int(255 * 0.65 * opacity)), width=2)

    pts3 = [(0, h)]
    for x in range(0, w + 12, 12):
        y = h * 0.861 + 9 * math.sin(0.0095 * x + t * 0.48 + 2.8)
        pts3.append((x, y))
    pts3.append((w, h))
    fd.polygon(pts3, fill=(*c3, int(255 * 0.18 * opacity)))
    fd.line(pts3[1:-1], fill=(*c3, int(255 * 0.80 * opacity)), width=2)


def _render_particles(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                      c1: RGB, c2: RGB, c3: RGB) -> None:
    p_coords = []
    num_nodes = 30
    for i in range(num_nodes):
        speed_x = 18.0 if i % 2 == 0 else -14.0
        speed_y = 12.0 if i % 3 == 0 else -10.0
        px = (i * 32.0 + t * speed_x) % w
        py = (i * 19.0 + t * speed_y) % h
        p_coords.append((px, py))

    max_d = 115.0
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            dist = math.hypot(p_coords[i][0] - p_coords[j][0], p_coords[i][1] - p_coords[j][1])
            if dist < max_d:
                line_alpha = int(255 * (1.0 - dist / max_d) * 0.35 * opacity)
                fd.line([p_coords[i], p_coords[j]], fill=(*c1, line_alpha), width=1)

    for i, (px, py) in enumerate(p_coords):
        node_col = c1 if i % 2 == 0 else c2
        r = 2.0 if i % 3 == 0 else 1.5
        fd.ellipse((px - r, py - r, px + r, py + r), fill=(*node_col, int(255 * 0.85 * opacity)))


# ── New Effect 1: Aurora Borealis (極光幕簾) ──────────────────────────────────
def _render_aurora(w: int, h: int, t: float, opacity: float, c1: RGB, c2: RGB, c3: RGB) -> Image.Image:
    gw, gh = 160, 60
    gx, gy = _get_norm_grid(gw, gh)

    # 3 undulating northern lights ribbon curtains with vertical shimmer streaks
    y1 = 0.34 + 0.14 * np.sin(gx * 5.2 + t * 0.48) + 0.06 * np.cos(gx * 10.5 - t * 0.31)
    s1 = 0.58 + 0.42 * np.sin(gx * 22.0 + t * 0.85 + gy * 3.0)
    b1 = np.exp(-((gy - y1) / 0.22) ** 2) * s1

    y2 = 0.56 + 0.13 * np.sin(gx * 6.4 - t * 0.42 + 1.7) + 0.05 * np.sin(gx * 13.0 + t * 0.52)
    s2 = 0.58 + 0.42 * np.sin(gx * 19.0 - t * 0.72 + gy * 2.5 + 1.1)
    b2 = np.exp(-((gy - y2) / 0.24) ** 2) * s2

    y3 = 0.74 + 0.11 * np.cos(gx * 4.6 + t * 0.36 + 2.9)
    s3 = 0.62 + 0.38 * np.sin(gx * 15.0 + t * 0.64 + 2.4)
    b3 = np.exp(-((gy - y3) / 0.20) ** 2) * s3

    # Soft vertical edge fade so curtains feel airy
    vfade = np.clip(np.sin(gy * math.pi) * 1.15, 0.0, 1.0)
    b1 *= vfade
    b2 *= vfade
    b3 *= vfade

    total = np.clip(b1 + b2 + b3, 1e-4, 2.2)
    w1, w2, w3 = b1 / total, b2 / total, b3 / total

    rgba = np.empty((gh, gw, 4), dtype=np.uint8)
    for ch in range(3):
        val = w1 * c1[ch] + w2 * c2[ch] + w3 * c3[ch]
        # Slight luminous highlight along curtain peaks
        peak = np.clip((total - 0.85) * 95.0, 0.0, 65.0)
        rgba[:, :, ch] = np.clip(val + peak, 0, 255).astype(np.uint8)

    alpha = np.clip(total * 0.62 * opacity * 255.0, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = alpha
    return Image.fromarray(rgba, mode="RGBA").resize((w, h), Image.Resampling.BILINEAR)


# ── New Effect 2: Demoscene Plasma (等離子雲) ─────────────────────────────────
def _render_plasma(w: int, h: int, t: float, opacity: float, c1: RGB, c2: RGB, c3: RGB) -> Image.Image:
    gw, gh = 120, 45
    gx, gy = _get_norm_grid(gw, gh)
    px = gx * (w / float(h))  # Aspect-preserving (~2.67)
    py = gy

    cx = 1.33 + 0.55 * math.sin(t * 0.38)
    cy = 0.50 + 0.28 * math.cos(t * 0.47)

    v1 = np.sin(px * 3.6 + t * 0.65)
    v2 = np.sin(py * 4.4 - t * 0.52)
    v3 = np.sin((px * 2.5 + py * 3.1) + t * 0.58)
    v4 = np.sin(np.sqrt((px - cx) ** 2 + (py - cy) ** 2) * 5.8 - t * 0.88)
    v = (v1 + v2 + v3 + v4) * 0.25  # [-1, 1]

    # Map smoothly to 3-color harmonic weights
    p1 = 0.5 + 0.5 * np.sin(v * math.pi + 0.0)
    p2 = 0.5 + 0.5 * np.sin(v * math.pi + 2.094)
    p3 = 0.5 + 0.5 * np.sin(v * math.pi + 4.188)
    s = p1 + p2 + p3 + 1e-4

    rgba = np.empty((gh, gw, 4), dtype=np.uint8)
    for ch in range(3):
        val = (p1 * c1[ch] + p2 * c2[ch] + p3 * c3[ch]) / s
        rgba[:, :, ch] = np.clip(val * 1.15, 0, 255).astype(np.uint8)

    # Flowing luminous ribbons rather than flat wash
    intensity = 0.30 + 0.55 * (0.5 + 0.5 * np.cos(v * math.pi * 1.6))
    rgba[:, :, 3] = np.clip(intensity * opacity * 210.0, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA").resize((w, h), Image.Resampling.BILINEAR)


# ── New Effect 3: Liquid Metaballs (熔岩光球) ─────────────────────────────────
def _render_metaballs(w: int, h: int, t: float, opacity: float, c1: RGB, c2: RGB, c3: RGB) -> Image.Image:
    gw, gh = 120, 45
    gx, gy = _get_norm_grid(gw, gh)
    aspect = w / float(h)
    px = gx * aspect
    py = gy

    colors = (c1, c2, c3)
    blobs = [
        (0.50 * aspect + 0.38 * aspect * math.sin(t * 0.42 + 0.0), 0.50 + 0.30 * math.cos(t * 0.53 + 0.4), 0.23, 0),
        (0.50 * aspect + 0.40 * aspect * math.cos(t * 0.35 + 1.2), 0.50 + 0.32 * math.sin(t * 0.48 + 2.1), 0.21, 1),
        (0.50 * aspect + 0.35 * aspect * math.sin(t * 0.51 + 2.7), 0.50 + 0.28 * math.cos(t * 0.39 + 1.5), 0.24, 2),
        (0.50 * aspect + 0.42 * aspect * math.cos(t * 0.29 + 3.9), 0.50 + 0.34 * math.sin(t * 0.61 + 0.9), 0.19, 0),
        (0.50 * aspect + 0.32 * aspect * math.sin(t * 0.46 + 4.8), 0.50 + 0.26 * math.sin(t * 0.33 + 3.2), 0.20, 1),
        (0.50 * aspect + 0.36 * aspect * math.cos(t * 0.40 + 5.5), 0.50 + 0.31 * math.cos(t * 0.44 + 4.7), 0.22, 2),
    ]

    field = np.zeros((gh, gw), dtype=np.float32)
    r_acc = np.zeros((gh, gw), dtype=np.float32)
    g_acc = np.zeros((gh, gw), dtype=np.float32)
    b_acc = np.zeros((gh, gw), dtype=np.float32)

    for bx, by, rad, cidx in blobs:
        d2 = (px - bx) ** 2 + (py - by) ** 2 + 0.014
        f = (rad * rad) / d2
        field += f
        col = colors[cidx]
        r_acc += f * col[0]
        g_acc += f * col[1]
        b_acc += f * col[2]

    inv_f = 1.0 / (field + 1e-4)
    # Soft outer glow + crisp liquid rim + bright core
    glow = np.clip((field - 0.32) / 1.15, 0.0, 1.0)
    core = np.clip((field - 1.55) * 0.45, 0.0, 0.35)

    rgba = np.empty((gh, gw, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(r_acc * inv_f + core * 255.0, 0, 255).astype(np.uint8)
    rgba[:, :, 1] = np.clip(g_acc * inv_f + core * 255.0, 0, 255).astype(np.uint8)
    rgba[:, :, 2] = np.clip(b_acc * inv_f + core * 255.0, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.clip((glow ** 1.35) * 0.85 * opacity * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA").resize((w, h), Image.Resampling.BILINEAR)


# ── New Effect 4: Matrix Digital Rain (代碼雨) ────────────────────────────────
def _render_matrix(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                   c1: RGB, c2: RGB, c3: RGB) -> None:
    font = _get_mono_font(14)
    col_step = 18
    row_step = 15
    num_cols = max(1, w // col_step)
    vis_rows = (h // row_step) + 2
    glyphs = _MATRIX_GLYPHS
    g_len = len(glyphs)
    colors = (c1, c1, c2, c3)

    for c in range(num_cols):
        seed = (c * 37 + 13) % 97
        speed_rows = 4.6 + (seed % 7) * 0.90
        trail_len = 9 + (seed % 9)
        cycle = vis_rows + trail_len - 4
        phase = (seed * 2.17) % cycle
        head_row = int((t * speed_rows + phase) % cycle)
        base_col = colors[c % len(colors)]
        x = c * col_step + 4

        for k in range(trail_len):
            row = head_row - k
            y = row * row_step
            if y < -row_step or y > h:
                continue
            ch_idx = (c * 17 + row * 13 + int(t * (3.0 if k == 0 else 0.8))) % g_len
            ch = glyphs[ch_idx]
            if k == 0:
                hr = min(255, int(base_col[0] * 0.35 + 175))
                hg = min(255, int(base_col[1] * 0.35 + 175))
                hb = min(255, int(base_col[2] * 0.35 + 175))
                fd.text((x, y), ch, fill=(hr, hg, hb, int(255 * 0.98 * opacity)), font=font)
            else:
                fade = (1.0 - (k / float(trail_len))) ** 1.25
                a = int(255 * 0.88 * fade * opacity)
                if a > 10:
                    fd.text((x, y), ch, fill=(*base_col, a), font=font)


# ── New Effect 5: Outrun SynthGrid (賽博網格) ─────────────────────────────────
def _render_synthgrid(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                      c1: RGB, c2: RGB, c3: RGB) -> None:
    cx = w * 0.5
    horizon = int(h * 0.42)
    floor_h = h - horizon

    # Retro Outrun sliced sun rising cleanly ABOVE the horizon (180..360 deg upper semicircle)
    sun_r = int(min(w, h) * 0.29)
    sun_cy = horizon + 10
    for layer in range(4, 0, -1):
        rr = sun_r + layer * 10
        a = int(255 * (0.045 * (5 - layer)) * opacity)
        fd.pieslice((cx - rr, sun_cy - rr, cx + rr, sun_cy + rr), start=180, end=360, fill=(*c3, a))

    # Draw horizontal retro-sliced sun bands strictly above y = horizon
    for sy in range(sun_cy - sun_r, horizon, 2):
        # Classic outrun horizontal cutouts near lower sun
        rel_h = (horizon - sy) / float(max(1, sun_r))
        if rel_h < 0.45 and ((horizon - sy) % 10 < 3):
            continue
        dy = sy - sun_cy
        if abs(dy) >= sun_r:
            continue
        half_w = math.sqrt(max(0.0, sun_r * sun_r - dy * dy))
        # Blend from c3 (top) to c2 (horizon)
        mix = max(0.0, min(1.0, 1.0 - rel_h))
        sr = int(c3[0] * (1.0 - mix) + c2[0] * mix)
        sg = int(c3[1] * (1.0 - mix) + c2[1] * mix)
        sb = int(c3[2] * (1.0 - mix) + c2[2] * mix)
        fd.line([(cx - half_w, sy), (cx + half_w, sy)], fill=(sr, sg, sb, int(255 * 0.62 * opacity)), width=2)

    # Soft horizon glow band
    for dy in range(-12, 13, 3):
        fall = 1.0 - abs(dy) / 14.0
        fd.line([(0, horizon + dy), (w, horizon + dy)],
                fill=(*c2, int(255 * 0.30 * fall * opacity)), width=2)
    fd.line([(0, horizon), (w, horizon)], fill=(*c1, int(255 * 0.90 * opacity)), width=2)

    # Perspective vertical rays fanning out from vanishing point
    num_rays = 18
    for i in range(-num_rays // 2, num_rays // 2 + 1):
        bx = cx + i * (w * 0.135)
        edge_fade = max(0.28, 1.0 - abs(i) / (num_rays * 0.68))
        col = c1 if i % 2 == 0 else c2
        fd.line([(cx, horizon), (bx, h)], fill=(*col, int(255 * 0.58 * edge_fade * opacity)), width=1)

    # Scrolling perspective horizontal lines (exponential depth spacing)
    num_hlines = 11
    scroll = (t * 0.55) % 1.0
    for i in range(num_hlines):
        u = (i + scroll) / float(num_hlines)
        z = u * u
        y = horizon + int(z * floor_h)
        alpha = int(255 * (0.20 + 0.75 * u) * opacity)
        width = 2 if u > 0.58 else 1
        fd.line([(0, y), (w, y)], fill=(*c1, alpha), width=width)


# ── New Effect 6: 3D Hyperspace Starfield (星際躍遷) ──────────────────────────
def _render_starfield(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                      c1: RGB, c2: RGB, c3: RGB) -> None:
    cx, cy = w * 0.5, h * 0.5
    spread_x = w * 0.24
    spread_y = h * 0.28
    colors = (c1, c2, c3, (235, 245, 255))

    num_stars = 135
    for i in range(num_stars):
        # Deterministic pseudo-random scatter (avoids spiral-arm correlation)
        h1 = ((i + 1) * 2654435761) & 0xFFFFFFFF
        h2 = ((i + 1) * 2246822519 ^ (h1 >> 13)) & 0xFFFFFFFF
        h3 = ((i + 1) * 3266489917 ^ (h2 >> 11)) & 0xFFFFFFFF
        angle = (h1 / 4294967296.0) * math.tau
        rad_mul = 0.22 + (h2 / 4294967296.0) * 0.88
        spd = 0.24 + (h3 % 11) * 0.026
        z_raw = (t * spd + ((h3 >> 8) / 16777216.0)) % 1.0
        z = 1.0 - z_raw * 0.92  # 1.0 (far) -> 0.08 (near)
        z_prev = min(1.0, z + 0.11 * (1.25 - z))

        dx = math.cos(angle) * rad_mul
        dy = math.sin(angle) * rad_mul

        sx = cx + (dx * spread_x) / z
        sy = cy + (dy * spread_y) / z
        px = cx + (dx * spread_x) / z_prev
        py = cy + (dy * spread_y) / z_prev

        if (sx < -50 or sx > w + 50 or sy < -50 or sy > h + 50) and (px < 0 or px > w or py < 0 or py > h):
            continue

        closeness = max(0.0, min(1.0, 1.0 - z))
        col = colors[i % len(colors)]
        trail_a = int(255 * (0.20 + 0.78 * closeness) * opacity)
        lw = 2 if closeness > 0.55 else 1
        fd.line([(px, py), (sx, sy)], fill=(*col, trail_a), width=lw)

        r = 1.1 + closeness * 2.4
        head_a = int(255 * min(1.0, 0.40 + 0.60 * closeness) * opacity)
        fd.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, head_a))


# ── New Effect 7: Cyberpunk Circuit Traces (晶片脈衝) ─────────────────────────
def _render_circuit(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                    c1: RGB, c2: RGB, c3: RGB) -> None:
    traces = _get_circuit_traces(w, h)
    colors = (c1, c2, c3)

    for tr in traces:
        pts = tr["pts"]
        cum = tr["cum"]
        total = tr["total"]
        col = colors[tr["col_idx"]]

        # Faint static PCB trace
        fd.line(pts, fill=(*col, int(255 * 0.19 * opacity)), width=2)

        # Solder pads / vias at bends
        for vx, vy in pts[1:-1]:
            fd.ellipse((vx - 3, vy - 3, vx + 3, vy + 3),
                       outline=(*col, int(255 * 0.32 * opacity)), width=1)

        # Two light pulses racing along the trace
        for p_idx in range(2):
            u = (t * 0.24 * tr["speed"] + tr["phase"] + p_idx * 0.5) % 1.0
            head_d = u * total
            tail_span = 95.0
            steps = 5
            for s in range(steps):
                d0 = max(0.0, head_d - (s + 1) * (tail_span / steps))
                d1 = max(0.0, head_d - s * (tail_span / steps))
                if d1 <= d0:
                    continue
                p0 = _sample_polyline(pts, cum, d0)
                p1 = _sample_polyline(pts, cum, d1)
                fade = 1.0 - (s / float(steps))
                a = int(255 * 0.85 * fade * opacity)
                fd.line([p0, p1], fill=(*col, a), width=3 if s < 2 else 2)

            hx, hy = _sample_polyline(pts, cum, head_d)
            fd.ellipse((hx - 5, hy - 5, hx + 5, hy + 5), fill=(*col, int(255 * 0.38 * opacity)))
            fd.ellipse((hx - 2.5, hy - 2.5, hx + 2.5, hy + 2.5), fill=(255, 255, 255, int(255 * 0.92 * opacity)))


# ── New Effect 8: Sci-Fi Hexagonal Pulse (蜂巢脈動) ───────────────────────────
def _render_hexpulse(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                     c1: RGB, c2: RGB, c3: RGB) -> None:
    cells = _get_hex_cells(w, h, radius=28.0)
    # Orbiting radial ripple epicenter
    ex = w * (0.5 + 0.36 * math.sin(t * 0.42))
    ey = h * (0.5 + 0.32 * math.cos(t * 0.55))

    for cx, cy, pts in cells:
        dist = math.hypot(cx - ex, cy - ey)
        wave_rad = 0.5 + 0.5 * math.sin(dist * 0.024 - t * 2.4)
        wave_diag = 0.5 + 0.5 * math.sin((cx * 0.0085 + cy * 0.011) - t * 1.35)
        energy = (wave_rad * 0.62 + wave_diag * 0.38) ** 2.2

        # Select color smoothly across bands
        if wave_rad > 0.68:
            col = c1
        elif wave_diag > 0.58:
            col = c2
        else:
            col = c3

        border_a = int(255 * (0.10 + 0.72 * energy) * opacity)
        fill_a = int(255 * 0.26 * energy * opacity)

        if fill_a > 6:
            fd.polygon(pts, fill=(*col, fill_a), outline=(*col, border_a))
        else:
            fd.polygon(pts, outline=(*col, border_a))


# ── New Effect 9: Tactical Radar Sonar (雷達掃描) ─────────────────────────────
def _render_radar(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                  c1: RGB, c2: RGB, c3: RGB) -> None:
    cx, cy = w * 0.5, h * 0.5
    max_r = math.hypot(cx, cy)

    # Concentric tactical rings
    ring_a = int(255 * 0.24 * opacity)
    for r in (60, 125, 195, 275, 365, 460):
        fd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*c1, ring_a), width=1)

    # Crosshair & 45-degree bearing lines
    axis_a = int(255 * 0.16 * opacity)
    fd.line([(0, cy), (w, cy)], fill=(*c1, axis_a), width=1)
    fd.line([(cx, 0), (cx, h)], fill=(*c1, axis_a), width=1)
    for deg in (45, 135, 225, 315):
        rad = math.radians(deg)
        fd.line([(cx, cy), (cx + max_r * math.cos(rad), cy + max_r * math.sin(rad))],
                fill=(*c1, int(axis_a * 0.7)), width=1)

    # Rotating phosphor sweep trail (12 stepped fading wedges over 55 degrees)
    sweep_deg = (t * 68.0) % 360.0
    trail_span = 54.0
    steps = 12
    step_deg = trail_span / steps
    for s in range(steps):
        a0 = sweep_deg - (s + 1) * step_deg
        a1 = sweep_deg - s * step_deg
        fade = (1.0 - s / float(steps)) ** 1.7
        wedge_a = int(255 * 0.28 * fade * opacity)
        if wedge_a > 3:
            fd.pieslice((cx - max_r, cy - max_r, cx + max_r, cy + max_r),
                        start=a0, end=a1, fill=(*c1, wedge_a))

    # Bright leading scan beam
    lead_rad = math.radians(sweep_deg)
    fd.line([(cx, cy), (cx + max_r * math.cos(lead_rad), cy + max_r * math.sin(lead_rad))],
            fill=(*c1, int(255 * 0.90 * opacity)), width=2)

    # Deterministic target blips that ping right after sweep passes over them
    blips = [
        (22.0, 180.0, c3), (68.0, 135.0, c2), (118.0, 290.0, c3), (156.0, 210.0, c1),
        (195.0, 355.0, c2), (232.0, 155.0, c3), (278.0, 120.0, c2), (314.0, 260.0, c3),
        (344.0, 390.0, c1), (42.0, 330.0, c2),
    ]
    for b_deg, b_r, b_col in blips:
        delta = (sweep_deg - b_deg) % 360.0
        if delta < 160.0:
            decay = (1.0 - delta / 160.0) ** 1.8
            br = math.radians(b_deg)
            bx = cx + b_r * math.cos(br)
            by = cy + b_r * math.sin(br)
            if 0 <= bx <= w and 0 <= by <= h:
                # Expanding ping ring
                pr = 4.0 + (delta / 160.0) * 18.0
                fd.ellipse((bx - pr, by - pr, bx + pr, by + pr),
                           outline=(*b_col, int(255 * 0.55 * decay * opacity)), width=1)
                fd.ellipse((bx - 3.5, by - 3.5, bx + 3.5, by + 3.5),
                           fill=(*b_col, int(255 * 0.92 * decay * opacity)))

    # Center emitter dot
    fd.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=(*c1, int(255 * 0.85 * opacity)))


# ── New Effect 10: Breathing Firefly Bokeh (流螢光斑) ─────────────────────────
def _render_fireflies(fd: ImageDraw.ImageDraw, w: int, h: int, t: float, opacity: float,
                      c1: RGB, c2: RGB, c3: RGB) -> None:
    colors = (c1, c2, c3)
    num_orbs = 36
    for i in range(num_orbs):
        seed = i * 1.6180339
        base_x = ((i * 97 + 31) % w)
        base_y = ((i * 53 + 17) % h)
        drift_y = 10.0 + (i % 5) * 4.5
        sway_x = 18.0 + (i % 4) * 9.0

        px = (base_x + math.sin(t * (0.35 + (i % 5) * 0.09) + seed * 3.0) * sway_x) % w
        py = (base_y - t * drift_y) % h

        # Smooth breathing glow
        pulse = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * (1.1 + (i % 6) * 0.22) + seed * 5.0)) ** 1.6
        r_core = 2.0 + (i % 4) * 0.9
        r_mid = r_core * 2.6
        r_halo = r_core * 5.0
        col = colors[i % 3]

        a_halo = int(255 * 0.14 * pulse * opacity)
        a_mid = int(255 * 0.34 * pulse * opacity)
        a_core = int(255 * 0.90 * pulse * opacity)

        fd.ellipse((px - r_halo, py - r_halo, px + r_halo, py + r_halo), fill=(*col, a_halo))
        fd.ellipse((px - r_mid, py - r_mid, px + r_mid, py + r_mid), fill=(*col, a_mid))
        # Warm bright center
        cr = min(255, int(col[0] * 0.5 + 135))
        cg = min(255, int(col[1] * 0.5 + 135))
        cb = min(255, int(col[2] * 0.5 + 135))
        fd.ellipse((px - r_core, py - r_core, px + r_core, py + r_core), fill=(cr, cg, cb, a_core))


# ── Unified Entrypoint ───────────────────────────────────────────────────────
def render_ambient_fx(
    mode: str,
    w: int,
    h: int,
    t: float,
    opacity: float,
    c1: RGB,
    c2: RGB,
    c3: RGB,
) -> Image.Image | None:
    """Render a transparent RGBA overlay layer for the requested ambient effect."""
    mode = str(mode or "off").lower().strip()
    if mode == "off" or opacity <= 0.02:
        return None

    # Fast NumPy shader effects (return RGBA Image directly)
    if mode == "aurora":
        return _render_aurora(w, h, t, opacity, c1, c2, c3)
    if mode == "plasma":
        return _render_plasma(w, h, t, opacity, c1, c2, c3)
    if mode == "metaballs":
        return _render_metaballs(w, h, t, opacity, c1, c2, c3)

    # Pillow vector/glyph effects
    fx_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fx_layer)

    if mode == "waves":
        _render_waves(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "particles":
        _render_particles(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "dual":
        _render_waves(fd, w, h, t, opacity, c1, c2, c3)
        _render_particles(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "matrix":
        _render_matrix(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "synthgrid":
        _render_synthgrid(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "starfield":
        _render_starfield(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "circuit":
        _render_circuit(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "hexpulse":
        _render_hexpulse(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "radar":
        _render_radar(fd, w, h, t, opacity, c1, c2, c3)
    elif mode == "fireflies":
        _render_fireflies(fd, w, h, t, opacity, c1, c2, c3)
    else:
        return None

    return fx_layer
