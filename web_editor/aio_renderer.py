"""SilverStone 480x480 Square AIO Modular 2x2 Grid Renderer.

Layout:
- Fixed Top Header Bar (y: 22..84): CPU Model Name + Live 24h Clock
- Dynamic 2x2 Modular Grid (x: 22..458, y: 98..456):
  Supports 1x1, 2x1 (wide), 1x2 (tall), and 2x2 (full) merged blocks.
  Each block independently configures its metric, accent color, and grid span.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_AIO_FONT_CACHE: dict[tuple[str, int, bool], ImageFont.FreeTypeFont] = {}
_AIO_BG_CACHE: dict[tuple[str, int, float], Image.Image] = {}

DEFAULT_AIO_WIDGETS = [
    {"id": "w1", "x": 0, "y": 0, "w": 2, "h": 1, "metric": "cpu_usage", "color": "#00e5ff"},
    {"id": "w2", "x": 0, "y": 1, "w": 1, "h": 1, "metric": "cpu_temp",  "color": "#ff8800"},
    {"id": "w3", "x": 1, "y": 1, "w": 1, "h": 1, "metric": "cpu_power", "color": "#a855f7"},
]

VALID_AIO_METRICS = {
    "cpu_usage", "cpu_temp", "cpu_power", "cpu_fan",
    "gpu_temp", "gpu_usage", "gpu_fan", "ram", "clock",
}


def _hex_to_rgb(hex_str: str, fallback=(0, 229, 255)) -> tuple[int, int, int]:
    try:
        s = str(hex_str or "").strip().lstrip("#")
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        pass
    return fallback


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v)) if v is not None else default
    except Exception:
        return default


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = ("latin", size, bold)
    if key in _AIO_FONT_CACHE:
        return _AIO_FONT_CACHE[key]
    candidates = (
        [r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\arialbd.ttf"]
        if bold
        else [r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                _AIO_FONT_CACHE[key] = f
                return f
            except Exception:
                pass
    return ImageFont.load_default()


def _get_bg_image(path_str: str, blur: int, dim: float) -> Image.Image | None:
    key = (path_str, blur, round(dim, 2))
    if key in _AIO_BG_CACHE:
        return _AIO_BG_CACHE[key]
    p = Path(path_str)
    if not p.exists():
        return None
    try:
        src = Image.open(p).convert("RGB")
        sw, sh = src.size
        side = min(sw, sh)
        left = (sw - side) // 2
        top = (sh - side) // 2
        sq = src.crop((left, top, left + side, top + side)).resize((480, 480), Image.Resampling.LANCZOS)
        if blur > 0:
            sq = sq.filter(ImageFilter.GaussianBlur(radius=blur))
        rgba = sq.convert("RGBA")
        if dim > 0.01:
            overlay = Image.new("RGBA", (480, 480), (0, 0, 0, int(255 * min(0.95, dim))))
            rgba = Image.alpha_composite(rgba, overlay)
        if len(_AIO_BG_CACHE) > 8:
            _AIO_BG_CACHE.clear()
        _AIO_BG_CACHE[key] = rgba
        return rgba
    except Exception:
        return None


def _draw_progress_bar(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int,
                       ratio: float, color: tuple, track_alpha: int = 45):
    r = max(2, (y1 - y0) // 2)
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=(*color, track_alpha))
    clamped = max(0.0, min(1.0, ratio))
    fill_w = int((x1 - x0) * clamped)
    if fill_w > r * 2:
        d.rounded_rectangle((x0, y0, x0 + fill_w, y1), radius=r, fill=(*color, 255))
    elif fill_w > 2:
        d.rounded_rectangle((x0, y0, x0 + max(fill_w, 6), y1), radius=r, fill=(*color, 255))


def _draw_square_frame(d: ImageDraw.ImageDraw, accent_p: tuple, text_s: tuple, ambient_ring: bool):
    d.rounded_rectangle((8, 8, 472, 472), radius=24, outline=(*text_s, 55), width=2)
    if ambient_ring:
        perim = 452.0
        pos = (time.time() * 140.0) % (perim * 4.0)
        if pos < perim:
            ox, oy = 14 + pos, 14
        elif pos < perim * 2:
            ox, oy = 466, 14 + (pos - perim)
        elif pos < perim * 3:
            ox, oy = 466 - (pos - perim * 2), 466
        else:
            ox, oy = 14, 466 - (pos - perim * 3)
        ox, oy = int(ox), int(oy)
        d.ellipse((ox - 9, oy - 9, ox + 9, oy + 9), fill=(*accent_p, 75))
        d.ellipse((ox - 4, oy - 4, ox + 4, oy + 4), fill=(*accent_p, 255))


def _metric_payload(metric: str, data: dict) -> tuple[str, str, str, float]:
    """Return (label, big_value, sub_text, bar_ratio) for any supported metric."""
    cpu_pct = max(0.0, min(100.0, _safe_float(data.get("cpu_usage"), 0.0)))
    cpu_temp_raw = data.get("cpu_temp_c")
    cpu_power_raw = data.get("cpu_power_w")
    cpu_rpm = _safe_int(data.get("cpu_fan_rpm"), 0)

    gpu_pct = max(0.0, min(100.0, _safe_float(data.get("gpu_usage"), 0.0)))
    gpu_temp = _safe_float(data.get("gpu_temp_c"), 42.0)
    gpu_rpm = _safe_int(data.get("gpu_fan_rpm"), 0)
    gpu_name = str(data.get("gpu_name", "GPU"))[:14]

    ram_pct = max(0.0, min(100.0, _safe_float(data.get("ram_usage"), 0.0)))
    ram_used = _safe_float(data.get("ram_used_gb"), 0.0)
    ram_total = _safe_float(data.get("ram_total_gb"), 32.0)

    time_full = str(data.get("time_24h", time.strftime("%H:%M:%S")))
    date_str = str(data.get("date_str", time.strftime("%Y.%m.%d"))).split("//")[0].strip()

    if metric == "cpu_usage":
        return ("CPU USAGE", f"{cpu_pct:.1f}%", f"FAN {cpu_rpm} RPM", cpu_pct / 100.0)
    if metric == "cpu_temp":
        val = f"{float(cpu_temp_raw):.0f}°C" if cpu_temp_raw is not None else "--°C"
        ratio = max(0.0, min(1.0, (float(cpu_temp_raw) - 25.0) / 70.0)) if cpu_temp_raw is not None else 0.0
        return ("CPU TEMP", val, "PACKAGE", ratio)
    if metric == "cpu_power":
        val = f"{float(cpu_power_raw):.0f}W" if cpu_power_raw is not None else "--W"
        ratio = max(0.0, min(1.0, float(cpu_power_raw) / 253.0)) if cpu_power_raw is not None else 0.0
        return ("CPU POWER", val, "PACKAGE TDP", ratio)
    if metric == "cpu_fan":
        return ("CPU FAN", f"{cpu_rpm}", "RPM", min(1.0, cpu_rpm / 2400.0))
    if metric == "gpu_temp":
        ratio = max(0.0, min(1.0, (gpu_temp - 25.0) / 65.0))
        return ("GPU TEMP", f"{gpu_temp:.0f}°C", gpu_name, ratio)
    if metric == "gpu_usage":
        return ("GPU USAGE", f"{gpu_pct:.0f}%", f"TEMP {gpu_temp:.0f}°C", gpu_pct / 100.0)
    if metric == "gpu_fan":
        return ("GPU FAN", f"{gpu_rpm}", "RPM" if gpu_rpm > 0 else "ZERO-RPM", min(1.0, gpu_rpm / 2800.0))
    if metric == "ram":
        return ("MEMORY", f"{ram_pct:.0f}%", f"{ram_used:.1f}/{ram_total:.0f} GB", ram_pct / 100.0)
    if metric == "clock":
        sec = int(time_full[6:8]) if len(time_full) >= 8 and time_full[6:8].isdigit() else 0
        return ("CLOCK", time_full[:5], date_str, sec / 60.0)
    return ("CPU USAGE", f"{cpu_pct:.1f}%", "", cpu_pct / 100.0)


def render_aio_480x480(data: dict, cfg: dict) -> Image.Image:
    """Render 480x480 square display: fixed CPU+Clock header + modular 2x2 grid."""
    w = h = 480

    canvas_bg = _hex_to_rgb(cfg.get("canvas_bg"), (8, 12, 22))
    accent_p = _hex_to_rgb(cfg.get("accent_primary"), (0, 229, 255))
    text_p = _hex_to_rgb(cfg.get("text_primary"), (248, 250, 252))
    text_s = _hex_to_rgb(cfg.get("text_secondary"), (148, 163, 184))
    ambient_ring = bool(cfg.get("ambient_ring", True))

    bg_path = cfg.get("bg_image")
    bg_blur = max(0, min(25, _safe_int(cfg.get("bg_blur"), 0)))
    bg_dim = max(0.0, min(0.9, _safe_float(cfg.get("bg_dim"), 0.35)))

    base = None
    if bg_path:
        bg_img = _get_bg_image(str(bg_path), bg_blur, bg_dim)
        if bg_img is not None:
            base = bg_img.copy()
    if base is None:
        base = Image.new("RGBA", (w, h), (*canvas_bg, 255))

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cpu_name = str(data.get("cpu_name") or "CPU")[:18]
    time_full = str(data.get("time_24h", time.strftime("%H:%M:%S")))

    card_alpha = 185 if bg_path else 235
    card_bg = (min(255, canvas_bg[0] + 12), min(255, canvas_bg[1] + 16), min(255, canvas_bg[2] + 24), card_alpha)
    card_border = (*text_s, 65)

    _draw_square_frame(d, accent_p, text_s, ambient_ring)

    # ── Fixed Top Header Bar (y: 22..84): CPU Name + Live Clock ──
    d.rounded_rectangle((22, 22, 458, 84), radius=14, fill=card_bg, outline=card_border, width=1)
    d.ellipse((38, 46, 52, 60), fill=(*accent_p, 255))
    d.text((62, 53), cpu_name, fill=(*text_p, 255), font=_get_font(22, bold=True), anchor="lm")
    d.text((442, 53), time_full, fill=(*accent_p, 240), font=_get_font(22, bold=True), anchor="rm")

    # ── Dynamic 2x2 Modular Grid (x: 22..458, y: 98..456) ──
    # Cell bounds:
    #   col 0: x 22..234 (212px), col 1: x 246..458 (212px), gap=12px
    #   row 0: y 98..270 (172px), row 1: y 284..456 (172px), gap=14px
    col_x = [(22, 234), (246, 458)]
    row_y = [(98, 270), (284, 456)]

    widgets = cfg.get("widgets")
    if not isinstance(widgets, list) or len(widgets) == 0:
        widgets = DEFAULT_AIO_WIDGETS

    for item in widgets:
        if not isinstance(item, dict):
            continue
        gx = max(0, min(1, _safe_int(item.get("x"), 0)))
        gy = max(0, min(1, _safe_int(item.get("y"), 0)))
        gw = max(1, min(2 - gx, _safe_int(item.get("w"), 1)))
        gh = max(1, min(2 - gy, _safe_int(item.get("h"), 1)))
        metric = str(item.get("metric", "cpu_usage")).lower()
        col_rgb = _hex_to_rgb(item.get("color"), accent_p)

        x0 = col_x[gx][0]
        x1 = col_x[gx + gw - 1][1]
        y0 = row_y[gy][0]
        y1 = row_y[gy + gh - 1][1]
        bw = x1 - x0
        bh = y1 - y0
        bcx = (x0 + x1) // 2
        bcy = (y0 + y1) // 2

        d.rounded_rectangle((x0, y0, x1, y1), radius=16, fill=card_bg, outline=(*col_rgb, 125), width=2)

        label, big_val, sub_txt, ratio = _metric_payload(metric, data)

        if gw == 2 and gh == 2:
            # 2x2 Full Block
            d.text((bcx, y0 + 44), label, fill=(*col_rgb, 255), font=_get_font(26, bold=True), anchor="mm")
            d.text((bcx, bcy - 12), big_val, fill=(*text_p, 255), font=_get_font(120, bold=True), anchor="mm")
            if sub_txt:
                d.text((bcx, y1 - 74), sub_txt, fill=(*text_s, 230), font=_get_font(24), anchor="mm")
            _draw_progress_bar(d, x0 + 28, y1 - 36, x1 - 28, y1 - 20, ratio, col_rgb)
        elif gw == 2 and gh == 1:
            # 2x1 Wide Block (like top hero bar)
            d.text((x0 + 20, y0 + 28), label, fill=(*col_rgb, 255), font=_get_font(20, bold=True), anchor="lm")
            if sub_txt:
                d.text((x1 - 20, y0 + 28), sub_txt, fill=(*text_s, 220), font=_get_font(18), anchor="rm")
            d.text((bcx, y0 + 92), big_val, fill=(*text_p, 255), font=_get_font(86, bold=True), anchor="mm")
            _draw_progress_bar(d, x0 + 20, y1 - 28, x1 - 20, y1 - 14, ratio, col_rgb)
        elif gw == 1 and gh == 2:
            # 1x2 Tall Block
            d.text((bcx, y0 + 36), label, fill=(*col_rgb, 255), font=_get_font(20, bold=True), anchor="mm")
            v_size = 64 if len(big_val) <= 4 else 52
            d.text((bcx, bcy - 10), big_val, fill=(*text_p, 255), font=_get_font(v_size, bold=True), anchor="mm")
            if sub_txt:
                d.text((bcx, bcy + 58), sub_txt, fill=(*text_s, 225), font=_get_font(18), anchor="mm")
            _draw_progress_bar(d, x0 + 18, y1 - 32, x1 - 18, y1 - 18, ratio, col_rgb)
        else:
            # 1x1 Square Cell
            d.text((x0 + 18, y0 + 28), label, fill=(*col_rgb, 255), font=_get_font(19, bold=True), anchor="lm")
            v_size = 60 if len(big_val) <= 4 else (48 if len(big_val) <= 5 else 42)
            d.text((bcx, y0 + 92), big_val, fill=(*text_p, 255), font=_get_font(v_size, bold=True), anchor="mm")
            _draw_progress_bar(d, x0 + 18, y1 - 28, x1 - 18, y1 - 16, ratio, col_rgb)

    return Image.alpha_composite(base, layer).convert("RGB")
