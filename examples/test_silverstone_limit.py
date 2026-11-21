"""Visual JPEG size limit probe for SilverStone 480x480 AIO LCD.

Displays huge KB size & quality text directly on the 480x480 screen,
stepping up from ~25 KB -> ~42 KB -> ~65 KB -> ~95 KB -> ~130 KB (3 seconds each),
so you can watch with your own eyes whether/where the hardware JPEG buffer tops out.
"""

from __future__ import annotations

import ctypes
import io
import os
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICENODE_DIR = Path(r"D:\ICENODE")
DLL_PATH = ICENODE_DIR / "LcdComm.dll"


def make_probe_image(target_kb: int, step_idx: int, total_steps: int) -> tuple[Image.Image, bytes, int]:
    """Generate a 480x480 image whose JPEG size lands close to target_kb."""
    w, h = 480, 480
    img = Image.new("RGB", (w, h), (10, 14, 26))
    draw = ImageDraw.Draw(img)

    # Add fine background texture only when targeting higher KB sizes
    if target_kb >= 55:
        rng = random.Random(42 + step_idx)
        density = min(14000, (target_kb - 40) * 160)
        for _ in range(density):
            x = rng.randint(0, w - 1)
            y = rng.randint(0, h - 1)
            draw.point((x, y), fill=(rng.randint(15, 70), rng.randint(25, 95), rng.randint(45, 130)))

    # Clear dark center circle so text is super legible
    draw.ellipse((65, 65, w - 65, h - 65), fill=(8, 12, 22), outline=(0, 220, 255), width=6)
    draw.ellipse((14, 14, w - 14, h - 14), outline=(255, 150, 0), width=5)

    font_huge = font_med = font_sm = None
    for fpath in (r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(fpath):
            font_huge = ImageFont.truetype(fpath, 76)
            font_med = ImageFont.truetype(fpath, 32)
            font_sm = ImageFont.truetype(fpath, 24)
            break
    if font_huge is None:
        font_huge = font_med = font_sm = ImageFont.load_default()

    cx, cy = w // 2, h // 2
    draw.text((cx, cy - 95), f"STEP {step_idx}/{total_steps}", fill=(255, 170, 50), font=font_med, anchor="mm")

    # Find quality/subsampling closest to target_kb
    best_data = b""
    best_q = 75
    best_diff = 10**9
    candidates = [
        (q, sub)
        for sub in (2, 0)
        for q in (45, 55, 65, 75, 85, 90, 95, 98, 100)
    ]

    # Measure first with placeholder text, then re-render with exact KB label
    for q, sub in candidates:
        test_img = img.copy()
        td = ImageDraw.Draw(test_img)
        td.text((cx, cy - 10), f"{target_kb} KB", fill=(255, 255, 255), font=font_huge, anchor="mm")
        td.text((cx, cy + 68), f"Q={q} SUB={sub}", fill=(52, 211, 153), font=font_med, anchor="mm")
        buf = io.BytesIO()
        test_img.save(buf, format="JPEG", quality=q, subsampling=sub)
        data = buf.getvalue()
        diff = abs(len(data) - target_kb * 1024)
        if diff < best_diff:
            best_diff = diff
            best_q = q
            best_sub = sub
            best_data = data

    # Re-render with exact actual KB
    actual_kb = len(best_data) / 1024.0
    draw.text((cx, cy - 10), f"{actual_kb:.1f} KB", fill=(255, 255, 255), font=font_huge, anchor="mm")
    draw.text((cx, cy + 68), f"Q={best_q}  SUB={best_sub}", fill=(52, 211, 153), font=font_med, anchor="mm")
    draw.text((cx, cy + 115), f"{len(best_data)} bytes", fill=(148, 163, 184), font=font_sm, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=best_q, subsampling=best_sub)
    final_data = buf.getvalue()
    return img, final_data, best_q


def main():
    os.add_dll_directory(str(ICENODE_DIR))
    dll = ctypes.WinDLL(str(DLL_PATH))
    dll.SetUsbID.argtypes = [ctypes.c_int] * 5
    dll.DeviceChange.argtypes = []
    dll.GetDevices.argtypes = [ctypes.c_void_p]
    dll.DirPlayOneFrame.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    dll.DirPlayOneFrame.restype = ctypes.c_uint32
    dll.DeleteAllDevice.argtypes = []

    dll.SetUsbID(0x0483, 0xABA0, 0x0145, 0x2003, 0x3002)
    dll.DeviceChange()
    time.sleep(0.5)
    dev_buf = ctypes.create_string_buffer(1024)
    dll.GetDevices(dev_buf)

    targets = [25, 42, 65, 95, 130, 160]
    frames = []
    for idx, kb in enumerate(targets, 1):
        _, data, q = make_probe_image(kb, idx, len(targets))
        frames.append((idx, kb, data, q))
        print(f"[Prep] Step {idx}/{len(targets)}: target={kb}KB actual={len(data)/1024:.1f}KB ({len(data)}B) Q={q}")

    print("\n[Start] Cycling each step for 4 seconds (repeating loop, Ctrl+C to stop)...")
    try:
        while True:
            for idx, kb, data, q in frames:
                cb = ctypes.create_string_buffer(data, len(data))
                t0 = time.perf_counter()
                ret = dll.DirPlayOneFrame(1, cb, len(data), 256)
                dt = (time.perf_counter() - t0) * 1000
                print(f"[Push] Step {idx}: {len(data)/1024:.1f} KB ({len(data)} B) -> ret={ret}, took={dt:.1f} ms")
                # Keep pushing same frame every 0.8s for 4 seconds so watchdog never triggers
                for _ in range(4):
                    time.sleep(0.8)
                    dll.DirPlayOneFrame(1, cb, len(data), 256)
    except KeyboardInterrupt:
        pass
    finally:
        dll.DeleteAllDevice()


if __name__ == "__main__":
    main()
