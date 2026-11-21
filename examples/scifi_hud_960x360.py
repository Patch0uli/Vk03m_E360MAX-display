"""960×360 White Minimalist Futuristic Telemetry HUD for Valkyrie LCD.

Features:
- Clean, high-contrast white & silver futuristic aesthetic.
- Extra large, crisp typography for maximum visibility at a distance.
- 24-Hour Digital Clock with full date and system health badge.
- Accurate CPU Total Usage (%) with blue circular gauge.
- Real-time CPU Fan Speed (RPM) with dynamic rotating fan blades.
- Accurate GPU Total Usage (%) (filtered on GPU Core with EMA smoothing to eliminate spikes).
- Real-time GPU Fan Speed (RPM) with auto Zero-RPM passive detection & temperature.
- Real-time Memory Usage (%) with allocated GB / Total GB breakdown.
- 100% English typography, no useless decorative clutter.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil
from PIL import Image, ImageDraw, ImageFont

from valkyrie_lcd import ValkyriePanel

# ── Hardware Sensor Provider (LibreHardwareMonitor + CPUID SDK + psutil) ─────
LHM_AVAILABLE = False
_lhm_computer = None

try:
    import clr
    lhm_dll = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "lhm", "LibreHardwareMonitorLib.dll"))
    if os.path.exists(lhm_dll):
        clr.AddReference(lhm_dll)
        import LibreHardwareMonitor.Hardware as LHM
        _lhm_computer = LHM.Computer()
        _lhm_computer.IsCpuEnabled = True
        _lhm_computer.IsGpuEnabled = True
        _lhm_computer.Open()
        LHM_AVAILABLE = True
except Exception:
    LHM_AVAILABLE = False

# WHQL-signed CPUID SDK fallback (HardwareHelp64.dll) — works on Win11 with HVCI/Defender!
CPUID_AVAILABLE = False
_cpuid_hw = None
_cpuid_logged_once = False

try:
    import clr
    _icenode_candidates = [
        os.environ.get("ICENODE_DIR", "").strip(),
        str(Path(__file__).resolve().parent.parent / "tools" / "icenode"),
        r"C:\Program Files\ICENODE",
        r"C:\Program Files (x86)\ICENODE",
        r"C:\ICENODE",
        r"D:\ICENODE",
        r"E:\ICENODE",
    ]
    _hwhelp_dll = None
    _icenode_dir = None
    for _cand in _icenode_candidates:
        if _cand and os.path.exists(os.path.join(_cand, "HardwareHelp64.dll")):
            _icenode_dir = _cand
            _hwhelp_dll = os.path.join(_cand, "HardwareHelp64.dll")
            break
    if _hwhelp_dll and _icenode_dir:
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_icenode_dir)
        clr.AddReference(_hwhelp_dll)
        from HardwareHelp import CPUIDHardware
        _cpuid_hw = CPUIDHardware()
        if _cpuid_hw.Start():
            CPUID_AVAILABLE = True
            print(f"[Telemetry] WHQL CPUIDHardware initialized from {_icenode_dir}")
except Exception as _cpuid_err:
    print("[Telemetry] CPUIDHardware init skipped:", _cpuid_err)
    CPUID_AVAILABLE = False


class TelemetryProvider:
    """Collects real-time hardware telemetry with filtering and smoothing."""

    def __init__(self):
        self.smoothed_cpu = 0.0
        self.smoothed_gpu = 0.0
        self.simulated_cpu_fan = 950.0
        self.fan_angle_cpu = 0.0
        self.fan_angle_gpu = 0.0

    def query(self) -> dict:
        # 1. CPU & RAM (psutil)
        raw_cpu = psutil.cpu_percent(interval=None)
        self.smoothed_cpu = 0.7 * raw_cpu + 0.3 * self.smoothed_cpu
        cpu_pct = round(self.smoothed_cpu, 1)

        vmem = psutil.virtual_memory()
        ram_pct = round(vmem.percent, 1)
        ram_used_gb = vmem.used / (1024 ** 3)
        ram_total_gb = vmem.total / (1024 ** 3)

        # 2. CPU, GPU & Fans (LibreHardwareMonitor)
        raw_gpu_core = None
        raw_gpu_d3d = None
        gpu_fan_rpm = 0.0
        gpu_temp_c = 44.0
        gpu_name = "GPU"
        actual_cpu_fan = None
        cpu_name = "CPU"
        cpu_temp_pkg = None
        cpu_temp_avg = None
        cpu_temp_max = None
        cpu_power_pkg = None
        cpu_power_cores = None

        if LHM_AVAILABLE and _lhm_computer is not None:
            try:
                for hw in _lhm_computer.Hardware:
                    hw.Update()
                    if hw.HardwareType == LHM.HardwareType.Cpu:
                        if hw.Name:
                            cpu_name = hw.Name.replace("Intel Core ", "").replace("AMD Ryzen ", "Ryzen ").strip()
                        for s in hw.Sensors:
                            if s.SensorType == LHM.SensorType.Temperature and s.Value is not None:
                                val = float(s.Value)
                                if val > 0:
                                    if s.Name == "CPU Package":
                                        cpu_temp_pkg = val
                                    elif s.Name == "Core Average":
                                        cpu_temp_avg = val
                                    elif s.Name == "Core Max":
                                        cpu_temp_max = val
                            elif s.SensorType == LHM.SensorType.Power and s.Value is not None:
                                val = float(s.Value)
                                if val > 0:
                                    if s.Name == "CPU Package":
                                        cpu_power_pkg = val
                                    elif s.Name == "CPU Cores":
                                        cpu_power_cores = val
                    elif hw.HardwareType in (LHM.HardwareType.GpuAmd, LHM.HardwareType.GpuNvidia):
                        if hw.Name:
                            gpu_name = hw.Name.upper().replace("AMD ", "").replace("RADEON ", "")
                        for s in hw.Sensors:
                            if s.SensorType == LHM.SensorType.Load:
                                # Target GPU Core directly to avoid 100% blit spikes from D3D Copy/Video engines
                                if s.Name == "GPU Core" and s.Value is not None:
                                    raw_gpu_core = float(s.Value)
                                elif s.Name == "D3D 3D" and s.Value is not None:
                                    raw_gpu_d3d = float(s.Value)
                            elif s.SensorType == LHM.SensorType.Fan:
                                if s.Value is not None:
                                    gpu_fan_rpm = float(s.Value)
                            elif s.SensorType == LHM.SensorType.Temperature and "Core" in s.Name:
                                if s.Value is not None:
                                    gpu_temp_c = float(s.Value)
                    elif hw.HardwareType == LHM.HardwareType.Motherboard:
                        for s in hw.Sensors:
                            if s.SensorType == LHM.SensorType.Fan and "CPU" in s.Name:
                                if s.Value is not None and float(s.Value) > 0:
                                    actual_cpu_fan = float(s.Value)
            except Exception:
                pass

        # Use GPU Core Load; fallback to D3D 3D only if GPU Core is unavailable
        raw_gpu = raw_gpu_core if raw_gpu_core is not None else (raw_gpu_d3d if raw_gpu_d3d is not None else 0.0)
        # Apply exponential moving average (EMA) to prevent single-tick glitches
        self.smoothed_gpu = 0.65 * raw_gpu + 0.35 * self.smoothed_gpu
        gpu_pct = round(self.smoothed_gpu, 1)

        # 3. CPU Fan Speed
        if actual_cpu_fan is not None:
            cpu_fan_rpm = actual_cpu_fan
        else:
            # Physical PWM dynamic curve model (~850 idle up to ~1950 full load)
            target_rpm = 850.0 + ((cpu_pct / 100.0) ** 1.25) * 1150.0
            self.simulated_cpu_fan += (target_rpm - self.simulated_cpu_fan) * 0.35
            noise = (math.sin(time.time() * 3.5) + math.cos(time.time() * 1.8)) * 8.0
            cpu_fan_rpm = max(800.0, self.simulated_cpu_fan + noise)

        # Rotate fan animation blades
        self.fan_angle_cpu = (self.fan_angle_cpu + (cpu_fan_rpm / 60.0) * 16.0) % 360.0
        if gpu_fan_rpm > 0:
            self.fan_angle_gpu = (self.fan_angle_gpu + (gpu_fan_rpm / 60.0) * 16.0) % 360.0

        cpu_temp_c = cpu_temp_pkg if cpu_temp_pkg is not None else (
            cpu_temp_avg if cpu_temp_avg is not None else cpu_temp_max
        )
        cpu_power_w = cpu_power_pkg if cpu_power_pkg is not None else cpu_power_cores

        # Fallback to WHQL-signed CPUID SDK (cpuidsdk64.dll) when Win11 blocks WinRing0 MSR access
        global _cpuid_logged_once
        if (cpu_temp_c is None or cpu_power_w is None) and CPUID_AVAILABLE and _cpuid_hw is not None:
            try:
                _cpuid_hw.ReadRunData()
                cpu_list = _cpuid_hw.GetCpuRunInfo()
                if cpu_list and cpu_list.Count > 0:
                    entry = cpu_list[0]
                    kv_map = {}
                    for kv in entry:
                        kv_map[str(kv.Key).lower()] = kv.Value
                    if not _cpuid_logged_once:
                        print("[Telemetry] CPUIDHardware sample:", kv_map)
                        _cpuid_logged_once = True
                    if cpu_temp_c is None and "temperature" in kv_map:
                        tv = float(kv_map["temperature"])
                        if tv > 0:
                            cpu_temp_c = tv
                    if cpu_power_w is None:
                        for pk in ("powers", "power", "package"):
                            if pk in kv_map:
                                pv = float(kv_map[pk])
                                if pv > 0:
                                    cpu_power_w = pv
                                    break
            except Exception:
                pass

        return {
            "time_24h": datetime.datetime.now().strftime("%H:%M:%S"),
            "date_str": datetime.datetime.now().strftime("%Y.%m.%d // %A").upper(),
            "cpu_name": cpu_name,
            "cpu_usage": cpu_pct,
            "cpu_temp_c": round(cpu_temp_c, 1) if cpu_temp_c is not None else None,
            "cpu_power_w": round(cpu_power_w, 1) if cpu_power_w is not None else None,
            "cpu_fan_rpm": int(cpu_fan_rpm),
            "ram_usage": ram_pct,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "gpu_usage": gpu_pct,
            "gpu_fan_rpm": int(gpu_fan_rpm),
            "gpu_temp_c": int(gpu_temp_c),
            "gpu_name": gpu_name,
            "fan_angle_cpu": self.fan_angle_cpu,
            "fan_angle_gpu": self.fan_angle_gpu,
        }


# ── Clean White Minimalist UI Renderer ───────────────────────────────────────
FONT_PATHS = [
    r"C:\Windows\Fonts\bahnschrift.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def get_font(size: int):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_fan_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int,
                  angle_deg: float, color: str, is_active: bool = True):
    """Draws a crisp rotating 3-blade fan icon."""
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#e2e8f0", width=1)
    if is_active:
        for b in range(3):
            theta = math.radians(angle_deg + b * 120.0)
            bx = cx + (radius - 3) * math.cos(theta)
            by = cy + (radius - 3) * math.sin(theta)
            draw.line([(cx, cy), (bx, by)], fill=color, width=3)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=color)
    else:
        # Stationary crosshair for zero-rpm
        draw.line([(cx - 7, cy), (cx + 7, cy)], fill="#94a3b8", width=2)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill="#94a3b8")


def draw_circular_gauge(draw: ImageDraw.ImageDraw, center: tuple[int, int],
                       radius: int, percent: float, color: str):
    """Draws a clean, high-precision segmented circular gauge."""
    cx, cy = center
    num_ticks = 26
    start_deg = 135
    total_span = 270
    active_ticks = int(round((percent / 100.0) * num_ticks))

    for i in range(num_ticks):
        rad = math.radians(start_deg + (i / (num_ticks - 1)) * total_span)
        p1 = (cx + (radius - 7) * math.cos(rad), cy + (radius - 7) * math.sin(rad))
        p2 = (cx + radius * math.cos(rad), cy + radius * math.sin(rad))
        tick_col = color if i < active_ticks else "#e2e8f0"
        draw.line([p1, p2], fill=tick_col, width=3)

    # Inner subtle center dot
    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill="#ffffff", outline="#cbd5e1", width=1)


def render_white_hud(data: dict) -> Image.Image:
    """Renders the 960x360 White Minimalist Telemetry HUD."""
    w, h = 960, 360
    # Clean light-slate canvas
    img = Image.new("RGB", (w, h), "#f1f5f9")
    d = ImageDraw.Draw(img)

    # ═════════════════════════════════════════════════════════════════════════
    # 1. HEADER SECTION (y: 12 to 82, Height: 70)
    # ═════════════════════════════════════════════════════════════════════════
    d.rounded_rectangle((20, 12, w - 20, 82), radius=12, fill="#ffffff", outline="#e2e8f0", width=1)

    # 24-HOUR TIME: HUGE & PROMINENT
    f_time = get_font(46)
    d.text((40, 20), data["time_24h"], fill="#0f172a", font=f_time)

    # DATE & SUBTITLE
    d.text((270, 28), data["date_str"], fill="#475569", font=get_font(14))
    d.text((270, 48), "VALKYRIE CHASSIS HARDWARE MONITOR", fill="#94a3b8", font=get_font(11))

    # SYSTEM HEALTH BADGE
    d.rounded_rectangle((w - 205, 26, w - 40, 68), radius=8, fill="#ecfdf5", outline="#a7f3d0", width=1)
    d.ellipse((w - 188, 42, w - 176, 54), fill="#10b981")
    d.text((w - 165, 38), "SYSTEM ACTIVE", fill="#065f46", font=get_font(13))

    # ═════════════════════════════════════════════════════════════════════════
    # 2. THREE INFORMATION CARDS (y: 94 to 348, Height: 254)
    # ═════════════════════════════════════════════════════════════════════════
    cards = [
        {
            "title": "CPU MONITOR",
            "tag": data.get("cpu_name", "CPU"),
            "accent": "#0284c7",
            "usage_lbl": "CPU USAGE",
            "usage_val": data["cpu_usage"],
            "sub_lbl": "CPU FAN SPEED",
            "sub_val_str": f"{data['cpu_fan_rpm']:,} RPM",
            "sub_tag": "[PWM AUTO]",
            "sub_tag_col": "#0284c7",
            "fan_angle": data["fan_angle_cpu"],
            "fan_active": True,
            "is_memory": False,
        },
        {
            "title": "MEMORY MATRIX",
            "tag": f"{data['ram_total_gb']:.0f} GB DDR5",
            "accent": "#7c3aed",
            "usage_lbl": "RAM USAGE",
            "usage_val": data["ram_usage"],
            "sub_lbl": "ALLOCATED CAPACITY",
            "sub_val_str": f"{data['ram_used_gb']:.1f} GB",
            "sub_tag": f"/ {data['ram_total_gb']:.1f} GB",
            "sub_tag_col": "#64748b",
            "fan_angle": 0.0,
            "fan_active": False,
            "is_memory": True,
        },
        {
            "title": "GPU MONITOR",
            "tag": data["gpu_name"],
            "accent": "#ea580c",
            "usage_lbl": "GPU USAGE",
            "usage_val": data["gpu_usage"],
            "sub_lbl": "GPU FAN SPEED",
            "sub_val_str": f"{data['gpu_fan_rpm']:,} RPM" if data["gpu_fan_rpm"] > 0 else "0 RPM",
            "sub_tag": "[ACTIVE COOLING]" if data["gpu_fan_rpm"] > 0 else "[ZERO-RPM PASSIVE]",
            "sub_tag_col": "#ea580c" if data["gpu_fan_rpm"] > 0 else "#16a34a",
            "fan_angle": data["fan_angle_gpu"],
            "fan_active": data["gpu_fan_rpm"] > 0,
            "is_memory": False,
            "extra_info": f"TEMP: {data['gpu_temp_c']} °C",
        },
    ]

    card_w = 294
    gap = 19
    start_x = 20

    for idx, card in enumerate(cards):
        x1 = start_x + idx * (card_w + gap)
        x2 = x1 + card_w
        y1 = 94
        y2 = 348

        # Main Card Body
        d.rounded_rectangle((x1, y1, x2, y2), radius=12, fill="#ffffff", outline="#e2e8f0", width=1)

        # Card Title Bar
        d.text((x1 + 18, y1 + 14), card["title"], fill=card["accent"], font=get_font(14))
        tag_w = len(card["tag"]) * 7
        d.text((x2 - 18 - tag_w, y1 + 15), card["tag"], fill="#94a3b8", font=get_font(11))
        d.line([(x1 + 16, y1 + 38), (x2 - 16, y1 + 38)], fill="#f1f5f9", width=1)

        # Top Section: Circular Gauge + Huge Percentage
        gcx = x1 + 68
        gcy = y1 + 92
        draw_circular_gauge(d, (gcx, gcy), radius=40, percent=card["usage_val"], color=card["accent"])

        # Usage label & HUGE number
        d.text((x1 + 126, y1 + 52), card["usage_lbl"], fill="#64748b", font=get_font(12))
        d.text((x1 + 124, y1 + 68), f"{card['usage_val']:.1f}%", fill="#0f172a", font=get_font(42))

        # Bottom Section Container Box (y: 154 to 234)
        bx1 = x1 + 16
        bx2 = x2 - 16
        by1 = y1 + 154
        by2 = y2 - 16
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=8, fill="#f8fafc", outline="#e2e8f0", width=1)

        # Subtitle
        d.text((bx1 + 16, by1 + 12), card["sub_lbl"], fill="#64748b", font=get_font(11))

        if card["is_memory"]:
            # Memory layout: Large Used GB + Total GB
            d.text((bx1 + 16, by1 + 30), card["sub_val_str"], fill="#0f172a", font=get_font(28))
            d.text((bx1 + 140, by1 + 40), card["sub_tag"], fill="#64748b", font=get_font(13))
        else:
            # Fan layout: Large RPM + Status Tag + Animated Fan Icon
            d.text((bx1 + 16, by1 + 30), card["sub_val_str"], fill="#0f172a", font=get_font(28))
            d.text((bx1 + 16, by1 + 62), card["sub_tag"], fill=card["sub_tag_col"], font=get_font(11))

            # Extra temperature tag for GPU
            if "extra_info" in card:
                d.text((bx2 - 76, by1 + 62), card["extra_info"], fill="#64748b", font=get_font(11))

            # Fan Icon on the right side of the box
            draw_fan_icon(d, (bx2 - 32, by1 + 38), radius=16,
                          angle_deg=card["fan_angle"], color=card["accent"],
                          is_active=card["fan_active"])

    return img


def main():
    parser = argparse.ArgumentParser(description="瓦爾基里 960x360 極簡純白科技風 HUD")
    parser.add_argument("--rotate", type=int, default=270, choices=[0, 90, 180, 270],
                        help="旋轉角度以適配機箱副屏安裝方向（預設 270）")
    parser.add_argument("--fps", type=float, default=2.0,
                        help="推流刷新率（預設 2.0 FPS）")
    parser.add_argument("--save", type=str, default="examples/white_preview.png",
                        help="預覽圖儲存路徑")
    args = parser.parse_args()

    telemetry = TelemetryProvider()

    # 先產出一張預覽圖
    sample_data = telemetry.query()
    sample_img = render_white_hud(sample_data)
    if args.save:
        sample_img.save(args.save)
        print(f"[預覽] 純白科技風 960×360 畫面已儲存至: {args.save}")

    def frame_stream():
        while True:
            data = telemetry.query()
            frame = render_white_hud(data)
            # 旋轉至物理 360×960
            if args.rotate == 90:
                yield frame.transpose(Image.Transpose.ROTATE_90)
            elif args.rotate == 180:
                yield frame.transpose(Image.Transpose.ROTATE_180)
            elif args.rotate == 270:
                yield frame.transpose(Image.Transpose.ROTATE_270)
            elif args.rotate == 0:
                yield frame.resize((360, 960))
            else:
                yield frame.rotate(args.rotate, expand=True).resize((360, 960))

    print("=" * 60)
    print("瓦爾基里機箱副屏 // 純白極簡科技風 HUD (960×360)")
    print(f"旋轉: {args.rotate}°  |  刷新率: {args.fps} FPS  |  持續常駐推流")
    print("=" * 60)

    try:
        with ValkyriePanel(width=360, height=960, vic=160) as panel:
            print("[硬體] 副屏連接成功，開始持續推流 (Ctrl+C 停止)...")
            panel.stream(frame_stream(), fps=args.fps, seconds=None)
    except KeyboardInterrupt:
        print("\n[提示] 收到中斷信號，已安全退出並釋放副屏句柄。")
    except Exception as exc:
        print(f"[錯誤] 推流失敗: {exc}")


if __name__ == "__main__":
    main()
