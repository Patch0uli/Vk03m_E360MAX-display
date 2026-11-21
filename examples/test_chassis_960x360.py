"""960×360 機箱長條副屏專用測試卡與推流工具。

硬體物理規格：360×960（VIC 160，整幀 691216 字節，UYVY 格式）。
機箱橫向安裝時可視分辨率為 960×360，因此腳本支持按安裝方向旋轉（90° / 270°）。

使用方式：
    python examples/test_chassis_960x360.py                # 預設旋轉 270 度並推流 10 秒
    python examples/test_chassis_960x360.py --rotate 90    # 若方向顛倒可改為 90 度
    python examples/test_chassis_960x360.py --seconds 30   # 推流 30 秒
    python examples/test_chassis_960x360.py --save frame.png # 另存預覽圖
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil
from PIL import Image, ImageDraw, ImageFont

from valkyrie_lcd import ValkyriePanel

FONT_PATHS = [
    r"C:\Windows\Fonts\bahnschrift.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def get_font(size: int, bold: bool = False):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_panel_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str):
    x1, y1, x2, y2 = box
    # 背景
    draw.rectangle(box, fill="#131924", outline="#202c3d", width=1)
    # 頂部裝飾角標
    draw.line([(x1, y1), (x1 + 12, y1)], fill="#00f0ff", width=2)
    draw.line([(x1, y1), (x1, y1 + 12)], fill="#00f0ff", width=2)
    draw.line([(x2, y2), (x2 - 12, y2)], fill="#00f0ff", width=2)
    draw.line([(x2, y2), (x2, y2 - 12)], fill="#00f0ff", width=2)

    # 標題
    f_title = get_font(13)
    draw.text((x1 + 10, y1 + 8), title.upper(), fill="#6ce0f5", font=f_title)
    draw.line([(x1 + 10, y1 + 25), (x2 - 10, y1 + 25)], fill="#1d2837", width=1)


def make_chassis_card(rotate_deg: int = 270) -> Image.Image:
    """在 960×360 畫布上繪製監控與校色面板，並旋轉為物理 360×960。"""
    canvas_w, canvas_h = 960, 360
    img = Image.new("RGB", (canvas_w, canvas_h), "#0a0d14")
    d = ImageDraw.Draw(img)

    # ── 外框與邊緣定位標記 ──────────────────────────────────────────────
    d.rectangle((0, 0, canvas_w - 1, canvas_h - 1), outline="#1d2a3a", width=2)
    f_edge = get_font(12)
    d.text((canvas_w // 2 - 25, 4), "▲ TOP ▲", fill="#ff5555", font=f_edge)
    d.text((canvas_w // 2 - 35, canvas_h - 18), "▼ BOTTOM ▼", fill="#55ff55", font=f_edge)
    d.text((6, canvas_h // 2 - 8), "◄ LEFT", fill="#55aaff", font=f_edge)
    d.text((canvas_w - 55, canvas_h // 2 - 8), "RIGHT ►", fill="#ffaa55", font=f_edge)

    # ── 頂部導航欄 ───────────────────────────────────────────────────────
    d.line([(30, 24), (canvas_w - 30, 24)], fill="#1a2433", width=1)
    f_logo = get_font(20)
    d.text((35, 30), "VALKYRIE CHASSIS DISPLAY", fill="#ffffff", font=f_logo)

    f_sub = get_font(12)
    d.text((360, 35), "MacroSilicon MS9132  |  VIC 160 (360×960)  |  YUV422", fill="#8898aa", font=f_sub)

    # 狀態標籤
    d.rounded_rectangle((canvas_w - 190, 30, canvas_w - 100, 52), radius=4, fill="#123524", outline="#25b364", width=1)
    f_status = get_font(11)
    d.text((canvas_w - 180, 34), "LINK ACTIVE", fill="#38ef7d", font=f_status)

    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    d.text((canvas_w - 90, 34), now_str, fill="#cbd5e1", font=get_font(13))

    # ── 三列佈局 ─────────────────────────────────────────────────────────
    # 列 1: 系統即時監控 (x: 35~310)
    box1 = (35, 65, 315, 320)
    draw_panel_box(d, box1, "SYSTEM TELEMETRY")

    cpu_pct = psutil.cpu_percent()
    mem_pct = psutil.virtual_memory().percent

    f_metric_label = get_font(12)
    f_metric_val = get_font(22)

    # CPU
    d.text((50, 100), "CPU USAGE", fill="#94a3b8", font=f_metric_label)
    d.text((50, 115), f"{cpu_pct:.1f} %", fill="#38bdf8", font=f_metric_val)
    # CPU 進度條
    d.rectangle((50, 145, 300, 155), fill="#0f172a", outline="#334155")
    d.rectangle((50, 145, 50 + int(250 * (cpu_pct / 100.0)), 155), fill="#0284c7")

    # RAM
    d.text((50, 175), "MEMORY LOAD", fill="#94a3b8", font=f_metric_label)
    d.text((50, 190), f"{mem_pct:.1f} %", fill="#a855f7", font=f_metric_val)
    # RAM 進度條
    d.rectangle((50, 220, 300, 230), fill="#0f172a", outline="#334155")
    d.rectangle((50, 220, 50 + int(250 * (mem_pct / 100.0)), 230), fill="#9333ea")

    # 核心數
    cores = psutil.cpu_count(logical=True)
    d.text((50, 255), f"CPU Cores: {cores}T   |   RAM: {psutil.virtual_memory().total // (1024**3)} GB",
           fill="#64748b", font=get_font(12))
    d.text((50, 280), "Refresh: 60 Hz USB Bulk", fill="#475569", font=get_font(11))

    # 列 2: 色彩校驗與階調 (x: 330~630)
    box2 = (330, 65, 630, 320)
    draw_panel_box(d, box2, "COLOR & GRADIENT CALIBRATION")

    colors = [
        ("RED", (230, 45, 45)),
        ("GREEN", (40, 200, 75)),
        ("BLUE", (45, 110, 240)),
        ("CYAN", (0, 225, 235)),
        ("MAGENTA", (220, 50, 200)),
        ("YELLOW", (245, 215, 35)),
        ("WHITE", (250, 250, 250)),
        ("BLACK", (20, 20, 20)),
    ]
    bar_w = (280) // len(colors)
    start_x = 340
    for i, (name, col) in enumerate(colors):
        bx = start_x + i * bar_w
        d.rectangle((bx, 100, bx + bar_w - 2, 145), fill=col, outline="#000000", width=1)

    # 灰階階調 (16階)
    d.text((340, 160), "16-STEP GRAYSCALE RAMP", fill="#94a3b8", font=get_font(11))
    ramp_w = 280 // 16
    for i in range(16):
        v = int(i * (255 / 15))
        rx = 340 + i * ramp_w
        d.rectangle((rx, 178, rx + ramp_w - 1, 205), fill=(v, v, v))

    # 像素網格清晰度檢測區
    d.text((340, 220), "PIXEL ALIGNMENT PATTERN", fill="#94a3b8", font=get_font(11))
    grid_rect = (340, 238, 620, 295)
    d.rectangle(grid_rect, fill="#05080d", outline="#334155")
    for gy in range(240, 294, 4):
        d.line([(342, gy), (618, gy)], fill="#1e293b", width=1)
    for gx in range(342, 618, 10):
        d.line([(gx, 240), (gx, 294)], fill="#1e293b", width=1)
    d.text((430, 258), "SUBPIXEL 1:1 TEST", fill="#38bdf8", font=get_font(12))

    # 列 3: 機箱橫條視覺資訊 (x: 645~925)
    box3 = (645, 65, 925, 320)
    draw_panel_box(d, box3, "DISPLAY ORIENTATION")

    d.text((660, 95), "CANVAS: 960 × 360", fill="#f8fafc", font=get_font(18))
    d.text((660, 125), f"ROTATION: {rotate_deg}°", fill="#38bdf8", font=get_font(16))
    d.text((660, 155), "TARGET PANEL: 360 × 960", fill="#94a3b8", font=get_font(13))

    # 旋轉方向指示箭頭
    d.rounded_rectangle((660, 185, 910, 295), radius=6, fill="#0b1320", outline="#1e293b")
    f_big = get_font(28)
    d.text((710, 200), "960 × 360", fill="#ffffff", font=f_big)
    d.text((680, 245), "CHASSIS PANEL READY", fill="#22c55e", font=get_font(14))
    d.text((680, 270), "Open-Source Driver", fill="#64748b", font=get_font(11))

    # ── 底部版權 / 提示 ──────────────────────────────────────────────────
    f_footer = get_font(11)
    d.text((35, 335), "Valkyrie LCD Open Protocol Engine  |  Powered by Antigravity", fill="#475569", font=f_footer)

    # ── 根據要求旋轉畫布至物理 360×960 ────────────────────────────────────
    if rotate_deg == 90:
        return img.transpose(Image.Transpose.ROTATE_90)
    elif rotate_deg == 180:
        return img.transpose(Image.Transpose.ROTATE_180)
    elif rotate_deg == 270:
        return img.transpose(Image.Transpose.ROTATE_270)
    elif rotate_deg == 0:
        # 如果是 0 度，拉伸/縮放適配
        return img.resize((360, 960))
    else:
        return img.rotate(rotate_deg, expand=True).resize((360, 960))


def main():
    parser = argparse.ArgumentParser(description="推流 960x360 測試畫面至瓦爾基里副屏")
    parser.add_argument("--rotate", type=int, default=270, choices=[0, 90, 180, 270],
                        help="旋轉角度以適配機箱安裝方向（預設 270，可選 90、180、0）")
    parser.add_argument("--seconds", type=float, default=15.0,
                        help="推流持續秒數（預設 15 秒，設為 0 則一直持續推流直至 Ctrl+C）")
    parser.add_argument("--fps", type=float, default=2.0,
                        help="刷新幀率（預設 2 fps）")
    parser.add_argument("--save", type=str, default="examples/chassis_preview.png",
                        help="預覽圖儲存路徑")
    args = parser.parse_args()

    dur_str = f"{args.seconds} 秒" if args.seconds > 0 else "持續推流 (Ctrl+C 停止)"
    print("=" * 60)
    print("瓦爾基里機箱屏 (960×360) 測試推流")
    print(f"畫布尺寸: 960×360  ->  旋轉: {args.rotate}°  ->  物理傳輸尺寸: 360×960")
    print(f"推流時長: {dur_str} @ {args.fps} FPS")
    print("=" * 60)

    # 先繪製一幀並存檔預覽
    frame = make_chassis_card(args.rotate)
    if args.save:
        # 另存原始 960x360 和旋轉後的預覽
        raw_preview = make_chassis_card(0).resize((960, 360))
        raw_preview.save(args.save)
        print(f"[預覽] 960×360 原始效果已存檔至: {args.save}")

    def frame_generator():
        start = time.time()
        while True:
            if args.seconds > 0 and (time.time() - start >= args.seconds):
                break
            yield make_chassis_card(args.rotate)

    print("[硬體] 正在連接副屏 (360×960, VIC=160)...")
    try:
        with ValkyriePanel(width=360, height=960, vic=160) as panel:
            print("[硬體] 初始化序列已完成，開始推流...")
            stream_sec = args.seconds if args.seconds > 0 else None
            panel.stream(frame_generator(), fps=args.fps, seconds=stream_sec)
            print("[硬體] 推流完成！")
    except KeyboardInterrupt:
        print("\n[硬體] 收到終止訊號，已平穩停止推流並釋放副屏句柄。")
    except Exception as exc:
        print(f"[錯誤] 推流失敗: {exc}")
        print("提示：若提示設備被佔用，請確認官方 Myth.Cool 軟體是否已關閉。")


if __name__ == "__main__":
    main()
