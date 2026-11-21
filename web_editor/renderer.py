"""Dynamic Modular Theme Renderer for Valkyrie 960x360 Secondary Display.

Renders hardware telemetry into a 960x360 canvas based on customizable theme settings:
- Header Card: Extra large 46px clock, date, subtitle, status pill.
- Real-time Dynamic Ambient FX: Flowing Sine Waves & Cyber Particles directly rendered onto physical screen.
- Modular Slot & Block Layout System:
  - 3-column customizable grid supporting 1x, 2x, and 3x column spans.
  - Widgets: CPU Monitor, GPU Monitor, RAM Matrix, Network Traffic, and Media Player (Now Playing).
  - Merged Block Mode: 2x wide cards (e.g. Middle+Right or Left+Middle merged) with full album art & 32-band equalizer spectrum!
- Full color customization (background, card borders, typography, component accents).
"""

from __future__ import annotations

import io
import math
import os
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

FONT_PATHS = [
    r"C:\Windows\Fonts\bahnschrift.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]

CJK_FONT_PATHS_BOLD = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msjhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]

CJK_FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def get_font(size: int):
    key = ("latin", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for p in FONT_PATHS:
        try:
            f = ImageFont.truetype(p, size)
            _FONT_CACHE[key] = f
            return f
        except OSError:
            continue
    return ImageFont.load_default()


def get_cjk_font(size: int, bold: bool = False):
    key = ("cjk_b" if bold else "cjk", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    paths = CJK_FONT_PATHS_BOLD if bold else CJK_FONT_PATHS
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            _FONT_CACHE[key] = f
            return f
        except OSError:
            continue
    return get_font(size)


def truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    """Truncate text cleanly by actual rendered pixel width (handles CJK + ASCII accurately)."""
    if not text:
        return ""
    try:
        if draw.textlength(text, font=font) <= max_px:
            return text
        ellipsis = "…"
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if draw.textlength(text[:mid] + ellipsis, font=font) <= max_px:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis if lo > 0 else ellipsis
    except Exception:
        return text[:16]


def hex_to_rgb(hex_str: str | None, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if not hex_str or not isinstance(hex_str, str):
        return default
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    try:
        val = int(hex_str, 16)
        return ((val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF)
    except Exception:
        return default


def safe_float(val, default: float) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default: int) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def make_rounded_thumb(img: Image.Image, size: tuple[int, int], radius: int = 8) -> Image.Image:
    """Crops and rounds image corners cleanly."""
    thumb = ImageOps.fit(img.convert("RGBA"), size, Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    thumb.putalpha(mask)
    return thumb


def draw_circular_gauge(draw: ImageDraw.ImageDraw, center: tuple[int, int],
                        radius: int, percent: float, active_rgb: tuple[int, int, int],
                        track_rgba: tuple[int, int, int, int]):
    """Draws a crisp segmented circular progress gauge."""
    cx, cy = center
    num_ticks = 26
    start_deg = 135
    total_span = 270
    percent = max(0.0, min(100.0, percent))
    active_ticks = int(round((percent / 100.0) * num_ticks))

    active_rgba = (*active_rgb, 255)

    for i in range(num_ticks):
        rad = math.radians(start_deg + (i / (num_ticks - 1)) * total_span)
        p1 = (cx + (radius - 7) * math.cos(rad), cy + (radius - 7) * math.sin(rad))
        p2 = (cx + radius * math.cos(rad), cy + radius * math.sin(rad))
        col = active_rgba if i < active_ticks else track_rgba
        draw.line([p1, p2], fill=col, width=3)

    # Subtle inner center dot
    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(*active_rgb, 30), outline=(*active_rgb, 120), width=1)


def draw_fan_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int,
                  angle_deg: float, color: tuple[int, int, int], is_active: bool = True):
    """Draws a 3-blade fan icon with smooth rotation."""
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*color, 80), width=1)
    if is_active:
        for b in range(3):
            theta = math.radians(angle_deg + b * 120.0)
            bx = cx + (radius - 3) * math.cos(theta)
            by = cy + (radius - 3) * math.sin(theta)
            draw.line([(cx, cy), (bx, by)], fill=(*color, 255), width=3)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(*color, 255))
    else:
        draw.line([(cx - 7, cy), (cx + 7, cy)], fill=(*color, 120), width=2)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(*color, 120))


def render_custom_hud(data: dict, theme: dict) -> Image.Image:
    """Renders the 960x360 canvas with modular slot widgets, dynamic ambient waves, and telemetry."""
    w, h = 960, 360

    # 1. Colors & Settings extraction with safe defaults
    canvas_bg_rgb = hex_to_rgb(theme.get("canvas_bg"), (8, 12, 20))
    card_bg_rgb = hex_to_rgb(theme.get("card_bg"), (15, 23, 42))
    card_opacity = max(0.0, min(1.0, safe_float(theme.get("card_opacity"), 0.90)))
    card_border_rgb = hex_to_rgb(theme.get("card_border"), (30, 41, 59))
    card_border_opacity = max(0.0, min(1.0, safe_float(theme.get("card_border_opacity"), 1.0)))

    text_primary_rgb = hex_to_rgb(theme.get("text_primary"), (248, 250, 252))
    text_secondary_rgb = hex_to_rgb(theme.get("text_secondary"), (148, 163, 184))

    cpu_accent_rgb = hex_to_rgb(theme.get("cpu_accent"), (0, 240, 255))
    ram_accent_rgb = hex_to_rgb(theme.get("ram_accent"), (168, 85, 247))
    gpu_accent_rgb = hex_to_rgb(theme.get("gpu_accent"), (255, 136, 0))
    status_accent_rgb = hex_to_rgb(theme.get("status_accent"), (34, 197, 94))

    bg_image_path = theme.get("bg_image")
    bg_dim = max(0.0, min(1.0, safe_float(theme.get("bg_dim"), 0.0)))
    bg_blur = max(0, min(50, safe_int(theme.get("bg_blur"), 0)))

    # 2. Build Base Canvas (Wallpaper or Solid Background)
    if bg_image_path and os.path.exists(str(bg_image_path)):
        try:
            raw_bg = Image.open(str(bg_image_path)).convert("RGBA")
            base_bg = ImageOps.fit(raw_bg, (w, h), Image.Resampling.LANCZOS)
            if bg_blur > 0:
                base_bg = base_bg.filter(ImageFilter.GaussianBlur(bg_blur))
            if bg_dim > 0:
                dim_layer = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * min(1.0, bg_dim))))
                base_bg = Image.alpha_composite(base_bg, dim_layer)
        except Exception:
            base_bg = Image.new("RGBA", (w, h), (*canvas_bg_rgb, 255))
    else:
        base_bg = Image.new("RGBA", (w, h), (*canvas_bg_rgb, 255))

    # 2.5 Dynamic Ambient FX directly on Screen Canvas (Waves & Particles)
    ambient_mode = str(theme.get("ambient_fx", "dual")).lower()
    ambient_opacity = max(0.0, min(1.0, safe_float(theme.get("ambient_opacity"), 0.55)))
    ambient_speed = max(0.2, min(3.0, safe_float(theme.get("ambient_speed"), 1.0)))

    if ambient_mode != "off" and ambient_opacity > 0.02:
        t = time.time() * ambient_speed
        fx_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fx_layer)

        # Flowing Multi-Frequency Sine Waves (gentle amplitude & speed for silky-smooth 15 FPS)
        if ambient_mode in ("waves", "dual"):
            pts1 = [(0, h)]
            for x in range(0, w + 12, 12):
                y = 272 + 14 * math.sin(0.0060 * x + t * 0.42) + 5 * math.cos(0.011 * x - t * 0.24)
                pts1.append((x, y))
            pts1.append((w, h))
            fd.polygon(pts1, fill=(*cpu_accent_rgb, int(255 * 0.16 * ambient_opacity)))
            for i in range(len(pts1) - 3):
                fd.line([pts1[i+1], pts1[i+2]], fill=(*cpu_accent_rgb, int(255 * 0.75 * ambient_opacity)), width=2)

            pts2 = [(0, h)]
            for x in range(0, w + 12, 12):
                y = 290 + 11 * math.sin(0.0075 * x - t * 0.34 + 1.4) + 4 * math.cos(0.005 * x + t * 0.18)
                pts2.append((x, y))
            pts2.append((w, h))
            fd.polygon(pts2, fill=(*ram_accent_rgb, int(255 * 0.14 * ambient_opacity)))
            for i in range(len(pts2) - 3):
                fd.line([pts2[i+1], pts2[i+2]], fill=(*ram_accent_rgb, int(255 * 0.65 * ambient_opacity)), width=2)

            pts3 = [(0, h)]
            for x in range(0, w + 12, 12):
                y = 310 + 9 * math.sin(0.0095 * x + t * 0.48 + 2.8)
                pts3.append((x, y))
            pts3.append((w, h))
            fd.polygon(pts3, fill=(*gpu_accent_rgb, int(255 * 0.18 * ambient_opacity)))
            for i in range(len(pts3) - 3):
                fd.line([pts3[i+1], pts3[i+2]], fill=(*gpu_accent_rgb, int(255 * 0.80 * ambient_opacity)), width=2)

        # Cybernetic Constellation Particles
        if ambient_mode in ("particles", "dual"):
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
                        line_alpha = int(255 * (1.0 - dist / max_d) * 0.35 * ambient_opacity)
                        fd.line([p_coords[i], p_coords[j]], fill=(*cpu_accent_rgb, line_alpha), width=1)

            for i, (px, py) in enumerate(p_coords):
                node_col = cpu_accent_rgb if i % 2 == 0 else ram_accent_rgb
                r = 2 if i % 3 == 0 else 1.5
                fd.ellipse((px - r, py - r, px + r, py + r), fill=(*node_col, int(255 * 0.85 * ambient_opacity)))

        base_bg = Image.alpha_composite(base_bg, fx_layer)

    # 3. Floating Transparent Cards Layer
    card_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card_layer)

    card_fill_rgba = (*card_bg_rgb, int(255 * card_opacity))
    card_border_rgba = (*card_border_rgb, int(255 * card_border_opacity))

    # Header Card (y: 12..82)
    cd.rounded_rectangle((20, 12, w - 20, 82), radius=12, fill=card_fill_rgba, outline=card_border_rgba, width=1)

    # System Status Pill (Vertically centered at Y=47 inside 12..82 header card)
    cd.rounded_rectangle((w - 200, 28, w - 40, 66), radius=8,
                        fill=(*status_accent_rgb, 30), outline=(*status_accent_rgb, 140), width=1)
    # Subtle halo & indicator dot (centered at Y=47)
    cd.ellipse((w - 188, 39, w - 172, 55), fill=(*status_accent_rgb, 45))
    cd.ellipse((w - 184, 43, w - 176, 51), fill=(*status_accent_rgb, 255))

    # Parse Modular Grid Widgets (3-column layout)
    col_w = 294
    gap = 19
    start_x = 20

    raw_widgets = theme.get("widgets")
    if raw_widgets is None or not isinstance(raw_widgets, list):
        raw_widgets = [
            {"id": "cpu", "x": 0, "w": 1},
            {"id": "ram", "x": 1, "w": 1},
            {"id": "gpu", "x": 2, "w": 1},
        ]

    widget_layouts = []
    occupied_cols = set()
    for wid in raw_widgets:
        if not isinstance(wid, dict):
            continue
        w_id = str(wid.get("id", "cpu")).lower()
        x_col = max(0, min(2, safe_int(wid.get("x"), 0)))
        w_span = max(1, min(3, safe_int(wid.get("w"), 1)))
        w_span = min(w_span, 3 - x_col)

        # Collision prevention: only one widget per column slot
        cols = set(range(x_col, x_col + w_span))
        if cols.intersection(occupied_cols):
            continue
        occupied_cols.update(cols)

        x1 = start_x + x_col * (col_w + gap)
        c_width = w_span * col_w + (w_span - 1) * gap
        x2 = min(w - 20, x1 + c_width)
        y1 = 94
        y2 = 348

        bx1 = x1 + 16
        bx2 = x2 - 16
        by1 = 94 + 154
        by2 = 348 - 16

        widget_layouts.append({
            "id": w_id,
            "x_col": x_col,
            "w_span": w_span,
            "x1": x1,
            "x2": x2,
            "y1": y1,
            "y2": y2,
            "bx1": bx1,
            "bx2": bx2,
            "by1": by1,
            "by2": by2,
        })

    # Draw widget card bases and sub-cards
    sub_card_alpha = int(255 * max(0.0, card_opacity * 0.75))
    sub_border_alpha = int(255 * card_border_opacity * 0.8)

    for wl in widget_layouts:
        cd.rounded_rectangle((wl["x1"], wl["y1"], wl["x2"], wl["y2"]), radius=12,
                             fill=card_fill_rgba, outline=card_border_rgba, width=1)
        cd.line([(wl["x1"] + 16, wl["y1"] + 38), (wl["x2"] - 16, wl["y1"] + 38)],
                fill=(*card_border_rgb, int(255 * card_border_opacity * 0.7)), width=1)
        cd.rounded_rectangle((wl["bx1"], wl["by1"], wl["bx2"], wl["by2"]), radius=8,
                             fill=(*card_bg_rgb, sub_card_alpha),
                             outline=(*card_border_rgb, sub_border_alpha), width=1)

    canvas = Image.alpha_composite(base_bg, card_layer)

    # 4. HUD Telemetry Graphics Overlay
    hud_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hud_overlay)
    track_rgba = (*text_secondary_rgb, 40)

    # Telemetry data unpacking
    cpu_usage = safe_float(data.get("cpu_usage"), 0.0)
    cpu_fan_rpm = safe_int(data.get("cpu_fan_rpm"), 0)
    ram_usage = safe_float(data.get("ram_usage"), 0.0)
    ram_used_gb = safe_float(data.get("ram_used_gb"), 0.0)
    ram_total_gb = safe_float(data.get("ram_total_gb"), 32.0)
    gpu_usage = safe_float(data.get("gpu_usage"), 0.0)
    gpu_fan_rpm = safe_int(data.get("gpu_fan_rpm"), 0)
    gpu_temp_c = safe_float(data.get("gpu_temp_c"), 40.0)
    gpu_name = str(data.get("gpu_name", "GPU"))

    net_down_kb = safe_float(data.get("net_down_kb"), 0.0)
    net_up_kb = safe_float(data.get("net_up_kb"), 0.0)

    media = data.get("media") or {}
    media_active = bool(media.get("active", False))
    media_status = str(media.get("status", "STOPPED")).upper()
    media_bands = media.get("spectrum_bands") or [0.1] * 32
    media_pos = safe_float(media.get("position"), 0.0)
    media_dur = safe_float(media.get("duration"), 0.0)
    media_prog = (media_pos / media_dur) if media_dur > 0 else 0.0

    # Draw graphics for each widget
    for wl in widget_layouts:
        wid = wl["id"]
        x1, y1, x2 = wl["x1"], wl["y1"], wl["x2"]
        bx1, by1, bx2, by2 = wl["bx1"], wl["by1"], wl["bx2"], wl["by2"]

        if wid == "cpu":
            gcx = x1 + 68
            gcy = y1 + 92
            draw_circular_gauge(hd, (gcx, gcy), radius=40, percent=cpu_usage,
                                active_rgb=cpu_accent_rgb, track_rgba=track_rgba)
            draw_fan_icon(hd, (bx2 - 32, by1 + 38), radius=16,
                          angle_deg=safe_float(data.get("fan_angle_cpu"), 0.0),
                          color=cpu_accent_rgb, is_active=True)

        elif wid == "gpu":
            gcx = x1 + 68
            gcy = y1 + 92
            draw_circular_gauge(hd, (gcx, gcy), radius=40, percent=gpu_usage,
                                active_rgb=gpu_accent_rgb, track_rgba=track_rgba)
            draw_fan_icon(hd, (bx2 - 32, by1 + 38), radius=16,
                          angle_deg=safe_float(data.get("fan_angle_gpu"), 0.0),
                          color=gpu_accent_rgb, is_active=(gpu_fan_rpm > 0))

        elif wid == "ram":
            gcx = x1 + 68
            gcy = y1 + 92
            draw_circular_gauge(hd, (gcx, gcy), radius=40, percent=ram_usage,
                                active_rgb=ram_accent_rgb, track_rgba=track_rgba)

        elif wid == "net":
            # Network Traffic Dual Track Gauges
            prog_down = min(1.0, net_down_kb / 50000.0)
            prog_up = min(1.0, net_up_kb / 20000.0)
            # Down Track
            hd.rounded_rectangle((x1 + 18, y1 + 64, x2 - 18, y1 + 72), radius=3, fill=(*text_secondary_rgb, 35))
            hd.rounded_rectangle((x1 + 18, y1 + 64, x1 + 18 + int((x2 - x1 - 36) * prog_down), y1 + 72),
                                 radius=3, fill=(*cpu_accent_rgb, 220))
            # Up Track
            hd.rounded_rectangle((x1 + 18, y1 + 112, x2 - 18, y1 + 120), radius=3, fill=(*text_secondary_rgb, 35))
            hd.rounded_rectangle((x1 + 18, y1 + 112, x1 + 18 + int((x2 - x1 - 36) * prog_up), y1 + 120),
                                 radius=3, fill=(*gpu_accent_rgb, 220))

        elif wid == "music":
            if wl["w_span"] == 1:
                # 1-Column Compact Music Card
                # Mini progress bar in sub-card
                p_w = bx2 - bx1 - 32
                fill_w = int(p_w * max(0.0, min(1.0, media_prog)))
                hd.rounded_rectangle((bx1 + 16, by1 + 14, bx2 - 16, by1 + 18), radius=2, fill=(*text_secondary_rgb, 40))
                if fill_w > 0:
                    hd.rounded_rectangle((bx1 + 16, by1 + 14, bx1 + 16 + fill_w, by1 + 18), radius=2, fill=(*status_accent_rgb, 220))
                # 14-band mini bouncing equalizer spectrum
                num_m_bars = 14
                avail_m_w = bx2 - bx1 - 32
                m_bar_w = (avail_m_w // num_m_bars) - 3
                for bi in range(num_m_bars):
                    bv = media_bands[bi * 2] if bi * 2 < len(media_bands) else 0.1
                    bh = int(bv * 36)
                    mbx = bx1 + 16 + bi * (m_bar_w + 3)
                    mby2 = by2 - 12
                    mby1 = mby2 - bh
                    hd.rounded_rectangle((mbx, mby1, mbx + m_bar_w, mby2), radius=2, fill=(*status_accent_rgb, 190))
                    hd.rectangle((mbx, mby1 - 2, mbx + m_bar_w, mby1), fill=(255, 255, 255, 220))

            else:
                # 2-Column or 3-Column Wide Merged Music Card
                # Progress Track
                bar_left = x1 + 126
                bar_right = x2 - 24
                bar_y = y1 + 104
                p_w = bar_right - bar_left
                fill_w = int(p_w * max(0.0, min(1.0, media_prog)))
                hd.rounded_rectangle((bar_left, bar_y, bar_right, bar_y + 6), radius=3, fill=(*text_secondary_rgb, 40))
                if fill_w > 0:
                    hd.rounded_rectangle((bar_left, bar_y, bar_left + fill_w, bar_y + 6), radius=3, fill=(*status_accent_rgb, 230))
                    hd.ellipse((bar_left + fill_w - 4, bar_y - 2, bar_left + fill_w + 6, bar_y + 8), fill=(*status_accent_rgb, 255))

                # Wide 32-band Neon Equalizer Spectrum Visualizer in Bottom Sub-Card!
                num_bars = 32
                avail_w = bx2 - bx1 - 40
                bar_w = max(4, (avail_w // num_bars) - 4)
                start_spec_x = bx1 + 20
                for bi in range(min(num_bars, len(media_bands))):
                    bv = media_bands[bi]
                    bh = max(4, int(bv * 50))
                    cur_bx = start_spec_x + bi * (bar_w + 4)
                    cur_by2 = by2 - 12
                    cur_by1 = cur_by2 - bh

                    # Gradient color interpolation from CPU Cyan to Status Emerald
                    ratio = bi / float(num_bars)
                    r_col = int(cpu_accent_rgb[0] * (1 - ratio) + status_accent_rgb[0] * ratio)
                    g_col = int(cpu_accent_rgb[1] * (1 - ratio) + status_accent_rgb[1] * ratio)
                    b_col = int(cpu_accent_rgb[2] * (1 - ratio) + status_accent_rgb[2] * ratio)

                    hd.rounded_rectangle((cur_bx, cur_by1, cur_bx + bar_w, cur_by2), radius=2, fill=(r_col, g_col, b_col, 200))
                    # Crisp white peak indicator cap
                    hd.rectangle((cur_bx, cur_by1 - 3, cur_bx + bar_w, cur_by1 - 1), fill=(255, 255, 255, 240))

    canvas = Image.alpha_composite(canvas, hud_overlay)
    d = ImageDraw.Draw(canvas)

    # 5. Crisp Text and Solid Typography Rendering (Directly onto RGB Canvas)
    # Header: Time (46px Bold Monospace - centered at y=48 inside 12..82 header card)
    f_time = get_font(46)
    d.text((40, 48), data.get("time_24h", "00:00:00"), fill=(*text_primary_rgb, 255), font=f_time, anchor="lm")

    # Header: Date & Subtitle (Vertically balanced inside header card)
    d.text((270, 38), data.get("date_str", "2026-01-01"), fill=(*text_secondary_rgb, 255), font=get_font(14), anchor="lm")
    d.text((270, 58), "VALKYRIE CHASSIS HARDWARE MONITOR", fill=(*text_secondary_rgb, 180), font=get_font(11), anchor="lm")

    # Header: Status Pill Text (Vertically centered at Y=47 in pill 28..66)
    d.text((w - 162, 47), "SYSTEM ACTIVE", fill=(*status_accent_rgb, 255), font=get_font(13), anchor="lm")

    # Widget Typography
    for wl in widget_layouts:
        wid = wl["id"]
        x1, y1, x2 = wl["x1"], wl["y1"], wl["x2"]
        bx1, by1, bx2 = wl["bx1"], wl["by1"], wl["bx2"]

        if wid == "cpu":
            cpu_name = str(telemetry.get("cpu_name") or "CPU")
            d.text((x1 + 18, y1 + 14), "CPU MONITOR", fill=(*cpu_accent_rgb, 255), font=get_font(14))
            d.text((x2 - 18, y1 + 15), cpu_name, fill=(*text_secondary_rgb, 200), font=get_font(11), anchor="ra")
            d.text((x1 + 126, y1 + 52), "CPU USAGE", fill=(*text_secondary_rgb, 255), font=get_font(12))
            d.text((x1 + 124, y1 + 68), f"{cpu_usage:.1f}%", fill=(*text_primary_rgb, 255), font=get_font(42))
            d.text((bx1 + 16, by1 + 12), "CPU FAN SPEED", fill=(*text_secondary_rgb, 255), font=get_font(11))
            d.text((bx1 + 16, by1 + 30), f"{cpu_fan_rpm:,} RPM", fill=(*text_primary_rgb, 255), font=get_font(28))
            d.text((bx1 + 16, by1 + 62), "[PWM AUTO]", fill=(*cpu_accent_rgb, 255), font=get_font(11))

        elif wid == "gpu":
            d.text((x1 + 18, y1 + 14), "GPU MONITOR", fill=(*gpu_accent_rgb, 255), font=get_font(14))
            tag_w = len(gpu_name) * 7
            d.text((x2 - 18 - tag_w, y1 + 15), gpu_name, fill=(*text_secondary_rgb, 200), font=get_font(11))
            d.text((x1 + 126, y1 + 52), "GPU USAGE", fill=(*text_secondary_rgb, 255), font=get_font(12))
            d.text((x1 + 124, y1 + 68), f"{gpu_usage:.1f}%", fill=(*text_primary_rgb, 255), font=get_font(42))
            d.text((bx1 + 16, by1 + 12), "GPU FAN SPEED", fill=(*text_secondary_rgb, 255), font=get_font(11))
            sub_fan_str = f"{gpu_fan_rpm:,} RPM" if gpu_fan_rpm > 0 else "0 RPM"
            d.text((bx1 + 16, by1 + 30), sub_fan_str, fill=(*text_primary_rgb, 255), font=get_font(28))
            sub_tag = "[ACTIVE COOLING]" if gpu_fan_rpm > 0 else "[ZERO-RPM PASSIVE]"
            sub_tag_col = gpu_accent_rgb if gpu_fan_rpm > 0 else status_accent_rgb
            d.text((bx1 + 16, by1 + 62), sub_tag, fill=(*sub_tag_col, 255), font=get_font(11))
            d.text((bx2 - 80, by1 + 62), f"TEMP: {gpu_temp_c:.0f} °C", fill=(*text_secondary_rgb, 220), font=get_font(11))

        elif wid == "ram":
            d.text((x1 + 18, y1 + 14), "MEMORY MATRIX", fill=(*ram_accent_rgb, 255), font=get_font(14))
            tag_str = f"{ram_total_gb:.0f} GB DDR5"
            d.text((x2 - 18 - len(tag_str) * 7, y1 + 15), tag_str, fill=(*text_secondary_rgb, 200), font=get_font(11))
            d.text((x1 + 126, y1 + 52), "RAM USAGE", fill=(*text_secondary_rgb, 255), font=get_font(12))
            d.text((x1 + 124, y1 + 68), f"{ram_usage:.1f}%", fill=(*text_primary_rgb, 255), font=get_font(42))
            d.text((bx1 + 16, by1 + 12), "ALLOCATED CAPACITY", fill=(*text_secondary_rgb, 255), font=get_font(11))
            d.text((bx1 + 16, by1 + 30), f"{ram_used_gb:.1f} GB", fill=(*text_primary_rgb, 255), font=get_font(28))
            d.text((bx1 + 140, by1 + 40), f"/ {ram_total_gb:.1f} GB", fill=(*text_secondary_rgb, 220), font=get_font(13))

        elif wid == "net":
            d.text((x1 + 18, y1 + 14), "NETWORK TRAFFIC", fill=(*cpu_accent_rgb, 255), font=get_font(14))
            d.text((x2 - 18 - 65, y1 + 15), "[ETH LIVE]", fill=(*text_secondary_rgb, 200), font=get_font(11))
            down_str = f"{net_down_kb/1024.0:.1f} MB/s" if net_down_kb >= 1024 else f"{net_down_kb:.0f} KB/s"
            up_str = f"{net_up_kb/1024.0:.1f} MB/s" if net_up_kb >= 1024 else f"{net_up_kb:.0f} KB/s"
            d.text((x1 + 18, y1 + 48), "DOWNLOAD RATE", fill=(*text_secondary_rgb, 255), font=get_font(11))
            d.text((x2 - 18 - len(down_str) * 8, y1 + 48), down_str, fill=(*cpu_accent_rgb, 255), font=get_font(12))
            d.text((x1 + 18, y1 + 96), "UPLOAD RATE", fill=(*text_secondary_rgb, 255), font=get_font(11))
            d.text((x2 - 18 - len(up_str) * 8, y1 + 96), up_str, fill=(*gpu_accent_rgb, 255), font=get_font(12))
            d.text((bx1 + 16, by1 + 14), "ETHERNET ADAPTER", fill=(*text_secondary_rgb, 255), font=get_font(11))
            d.text((bx1 + 16, by1 + 32), "ONLINE · 1 Gbps", fill=(*text_primary_rgb, 255), font=get_font(24))
            d.text((bx1 + 16, by1 + 62), "[DUPLEX FULL]", fill=(*status_accent_rgb, 255), font=get_font(11))

        elif wid == "music":
            title_str = str(media.get("title") or "NO ACTIVE MEDIA")
            artist_str = str(media.get("artist") or "Ready for Spotify / YouTube / Browser")
            app_str = str(media.get("app") or "System").upper()

            if wl["w_span"] == 1:
                # 1-Column Compact Music Card
                d.text((x1 + 18, y1 + 14), "NOW PLAYING", fill=(*status_accent_rgb, 255), font=get_font(14))
                d.text((x2 - 18 - len(app_str) * 7, y1 + 15), app_str, fill=(*text_secondary_rgb, 200), font=get_font(11))

                # Thumbnail or Icon
                thumb_raw = media.get("thumbnail")
                if thumb_raw and isinstance(thumb_raw, Image.Image):
                    try:
                        thumb = make_rounded_thumb(thumb_raw, (64, 64), radius=6)
                        canvas.paste(thumb, (x1 + 16, y1 + 52), thumb)
                    except Exception:
                        pass
                else:
                    # Draw music note icon / disc
                    d.ellipse((x1 + 18, y1 + 54, x1 + 78, y1 + 114), fill=(*status_accent_rgb, 30), outline=(*status_accent_rgb, 120), width=1)
                    d.ellipse((x1 + 42, y1 + 78, x1 + 54, y1 + 90), fill=(*status_accent_rgb, 200))

                # Song Title & Artist (CJK-capable font + pixel-width truncation)
                f_title_1 = get_cjk_font(14, bold=True)
                f_artist_1 = get_cjk_font(11, bold=False)
                max_w_1 = max(60, (x2 - 14) - (x1 + 90))
                disp_title = truncate_to_width(d, title_str, f_title_1, max_w_1)
                disp_artist = truncate_to_width(d, artist_str, f_artist_1, max_w_1)
                d.text((x1 + 90, y1 + 52), disp_title, fill=(*text_primary_rgb, 255), font=f_title_1)
                d.text((x1 + 90, y1 + 74), disp_artist, fill=(*text_secondary_rgb, 255), font=f_artist_1)
                status_col = status_accent_rgb if media_status == "PLAYING" else (245, 158, 11)
                d.text((x1 + 90, y1 + 96), f"● {media_status}", fill=(*status_col, 255), font=get_font(11))

                # Time text in sub-card
                m_time_str = f"{int(media_pos//60):02d}:{int(media_pos%60):02d} / {int(media_dur//60):02d}:{int(media_dur%60):02d}"
                d.text((bx1 + 16, by1 + 24), m_time_str, fill=(*text_secondary_rgb, 220), font=get_font(10))

            else:
                # 2-Column or 3-Column Merged Wide Music Card
                d.text((x1 + 18, y1 + 14), "MEDIA STATION // NOW PLAYING", fill=(*status_accent_rgb, 255), font=get_font(14))
                tag_label = f"[{app_str}] · GSMTC STREAM"
                d.text((x2 - 18 - len(tag_label) * 7, y1 + 15), tag_label, fill=(*text_secondary_rgb, 200), font=get_font(11))

                # Album Artwork Cover (92x92)
                thumb_raw = media.get("thumbnail")
                if thumb_raw and isinstance(thumb_raw, Image.Image):
                    try:
                        thumb = make_rounded_thumb(thumb_raw, (92, 92), radius=8)
                        canvas.paste(thumb, (x1 + 18, y1 + 48), thumb)
                        # Outer glow border
                        d.rounded_rectangle((x1 + 18, y1 + 48, x1 + 18 + 92, y1 + 48 + 92), radius=8,
                                            outline=(*status_accent_rgb, 180), width=1)
                    except Exception:
                        pass
                else:
                    # High-tech Cyberpunk Disc
                    d.ellipse((x1 + 18, y1 + 48, x1 + 110, y1 + 140), fill=(*status_accent_rgb, 25), outline=(*status_accent_rgb, 140), width=1)
                    d.ellipse((x1 + 40, y1 + 70, x1 + 88, y1 + 118), outline=(*status_accent_rgb, 90), width=1)
                    d.ellipse((x1 + 58, y1 + 88, x1 + 70, y1 + 100), fill=(*status_accent_rgb, 240))

                # Large Song Title & Artist (CJK-capable font + pixel-width truncation avoiding right status badge)
                f_title_w = get_cjk_font(19, bold=True)
                f_artist_w = get_cjk_font(13, bold=False)
                max_title_w = max(120, (x2 - 130) - (x1 + 126))
                max_artist_w = max(160, (x2 - 20) - (x1 + 126))
                disp_title = truncate_to_width(d, title_str, f_title_w, max_title_w)
                disp_artist = truncate_to_width(d, artist_str, f_artist_w, max_artist_w)
                d.text((x1 + 126, y1 + 46), disp_title, fill=(*text_primary_rgb, 255), font=f_title_w)
                d.text((x1 + 126, y1 + 76), disp_artist, fill=(*text_secondary_rgb, 255), font=f_artist_w)

                # Status pill badge
                status_col = status_accent_rgb if media_status == "PLAYING" else (245, 158, 11)
                st_pill_text = f"● {media_status}"
                d.text((x2 - 120, y1 + 52), st_pill_text, fill=(*status_col, 255), font=get_font(12))

                # Time stamps on progress bar
                pos_str = f"{int(media_pos//60):02d}:{int(media_pos%60):02d}"
                dur_str = f"{int(media_dur//60):02d}:{int(media_dur%60):02d}"
                d.text((x1 + 126, y1 + 114), pos_str, fill=(*text_secondary_rgb, 220), font=get_font(11))
                d.text((x2 - 58, y1 + 114), dur_str, fill=(*text_secondary_rgb, 220), font=get_font(11))

                # Spectrum Sub-card header label
                d.text((bx1 + 20, by1 + 10), "AUDIO EQUALIZER SPECTRUM // 32 CHANNELS", fill=(*text_secondary_rgb, 180), font=get_font(10))

    return canvas.convert("RGB")
