"""Test script to light up the SilverStone 480x480 AIO LCD (VID=0145 PID=3002, HWCX).

Uses D:\\ICENODE\\LcdComm.dll (64-bit native HID driver) directly via ctypes —
no Zadig / libusb driver replacement required.
"""

from __future__ import annotations

import ctypes
import io
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICENODE_DIR = Path(r"D:\ICENODE")
DLL_PATH = ICENODE_DIR / "LcdComm.dll"


def make_test_image(width: int = 480, height: int = 480) -> Image.Image:
    """Create a crisp circular-friendly 480x480 sci-fi test card."""
    img = Image.new("RGB", (width, height), (8, 12, 22))
    draw = ImageDraw.Draw(img)

    # Outer glowing circular rings (great for round AIO pump blocks)
    draw.ellipse((14, 14, width - 14, height - 14), outline=(0, 220, 255), width=6)
    draw.ellipse((30, 30, width - 30, height - 30), outline=(255, 140, 0), width=3)

    # Subtle crosshair guides
    cx, cy = width // 2, height // 2
    draw.line((40, cy, width - 40, cy), fill=(30, 55, 80), width=1)
    draw.line((cx, 40, cx, height - 40), fill=(30, 55, 80), width=1)

    # Load clean system font
    font_big = font_med = font_sm = None
    for fpath in (r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(fpath):
            font_big = ImageFont.truetype(fpath, 58)
            font_med = ImageFont.truetype(fpath, 30)
            font_sm = ImageFont.truetype(fpath, 22)
            break
    if font_big is None:
        font_big = font_med = font_sm = ImageFont.load_default()

    draw.text((cx, cy - 88), "SILVERSTONE", fill=(0, 220, 255), font=font_med, anchor="mm")
    draw.text((cx, cy - 18), "480 x 480", fill=(255, 255, 255), font=font_big, anchor="mm")
    draw.text((cx, cy + 52), "HID CONNECTED OK", fill=(52, 211, 153), font=font_med, anchor="mm")
    draw.text((cx, cy + 105), time.strftime("%H:%M:%S"), fill=(255, 170, 50), font=font_sm, anchor="mm")

    return img


def encode_jpeg_under_limit(img: Image.Image, max_bytes: int = 28000) -> bytes:
    """Encode 480x480 RGB image to Baseline 4:2:0 JPEG safely under the MCU's ~32KB buffer limit."""
    for q in (75, 65, 55, 45, 35, 25):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q, subsampling=2)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data
    return data


def main():
    if not DLL_PATH.exists():
        raise FileNotFoundError(f"找不到 {DLL_PATH}")

    os.add_dll_directory(str(ICENODE_DIR))
    dll = ctypes.WinDLL(str(DLL_PATH))

    dll.SetUsbID.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dll.DeviceChange.argtypes = []
    dll.GetDevices.argtypes = [ctypes.c_void_p]
    dll.DirPlayOneFrame.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    dll.DirPlayOneFrame.restype = ctypes.c_uint32
    dll.DeleteAllDevice.argtypes = []

    # Exact IDs from DeviceInfoHelp.dll DeviceService.Start()
    dll.SetUsbID(0x0483, 0xABA0, 0x0145, 0x2003, 0x3002)
    dll.DeviceChange()
    time.sleep(0.5)

    dev_buf = ctypes.create_string_buffer(1024)
    dll.GetDevices(dev_buf)
    raw = dev_buf.raw[:10]
    connected = raw[1]
    w = (raw[2] << 8) | raw[3]
    h = (raw[4] << 8) | raw[5]
    uuid_hex = raw[6:10].hex().upper()
    print(f"[Device 0] connected={connected} size={w}x{h} uuid={uuid_hex}")

    if not connected or w == 0 or h == 0:
        print("[FAIL] 未偵測到銀欣水冷頭螢幕")
        dll.DeleteAllDevice()
        return

    print("[Stream] Pushing live 480x480 test frames (Ctrl+C to stop)...")
    try:
        while True:
            img = make_test_image(w, h)
            jpeg_bytes = encode_jpeg_under_limit(img, max_bytes=28000)
            t0 = time.perf_counter()
            c_buf = ctypes.create_string_buffer(jpeg_bytes, len(jpeg_bytes))
            ret = dll.DirPlayOneFrame(1, c_buf, len(jpeg_bytes), 256)
            dt = (time.perf_counter() - t0) * 1000
            print(f"[Push] ret={ret} size={len(jpeg_bytes)}B took={dt:.1f}ms")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        dll.DeleteAllDevice()


if __name__ == "__main__":
    main()
