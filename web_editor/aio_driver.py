"""SilverStone E360MAX 480x480 AIO Water Cooler LCD Driver (VID=0145 PID=3002, HWCX HID).

Wraps SilverStone ICENODE's LcdComm.dll (64-bit native HID library) via ctypes.
Requires no Zadig / libusb driver replacement and supports high-speed JPEG frames
(~14 ms per 480x480 Q90 frame).
"""

from __future__ import annotations

import ctypes
import io
import os
import time
from pathlib import Path

from PIL import Image

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_icenode_dir() -> Path:
    """Auto-locate SilverStone ICENODE directory containing LcdComm.dll."""
    candidates: list[Path] = []
    env_dir = os.environ.get("ICENODE_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([
        _PROJECT_ROOT / "tools" / "icenode",
        Path(r"C:\Program Files\ICENODE"),
        Path(r"C:\Program Files (x86)\ICENODE"),
        Path(r"C:\ICENODE"),
        Path(r"D:\ICENODE"),
        Path(r"E:\ICENODE"),
    ])
    for d in candidates:
        if (d / "LcdComm.dll").exists():
            return d
    return candidates[0] if env_dir else Path(r"C:\Program Files\ICENODE")


DEFAULT_ICENODE_DIR = find_icenode_dir()


class AioPanelError(RuntimeError):
    pass


class SilverStoneAioPanel:
    """Driver for SilverStone E360MAX 480x480 HWCX USB HID pump-block LCD."""

    def __init__(self, icenode_dir: Path | str | None = None):
        self.icenode_dir = Path(icenode_dir) if icenode_dir else find_icenode_dir()
        self.dll_path = self.icenode_dir / "LcdComm.dll"
        self.dll = None
        self.width = 480
        self.height = 480
        self.uuid = ""
        self.connected = False
        self._dll_dir_handle = None

    def connect(self) -> "SilverStoneAioPanel":
        if not self.dll_path.exists():
            raise AioPanelError(
                f"找不到銀欣驅動庫 LcdComm.dll（已檢查 {self.icenode_dir}）。"
                "請安裝銀欣 ICENODE，或設定環境變數 ICENODE_DIR 指向 LcdComm.dll 所在資料夾。"
            )

        if hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(str(self.icenode_dir))

        dll = ctypes.WinDLL(str(self.dll_path))
        dll.SetUsbID.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.DeviceChange.argtypes = []
        dll.GetDevices.argtypes = [ctypes.c_void_p]
        dll.DirPlayOneFrame.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        dll.DirPlayOneFrame.restype = ctypes.c_uint32
        dll.DeleteAllDevice.argtypes = []

        # Exact USB IDs matching SilverStone DeviceInfoHelp.dll
        dll.SetUsbID(0x0483, 0xABA0, 0x0145, 0x2003, 0x3002)
        dll.DeviceChange()
        time.sleep(0.45)

        dev_buf = ctypes.create_string_buffer(1024)
        dll.GetDevices(dev_buf)
        raw = dev_buf.raw[:10]
        is_conn = raw[1]
        w = (raw[2] << 8) | raw[3]
        h = (raw[4] << 8) | raw[5]
        uuid_hex = raw[6:10].hex().upper()

        if not is_conn or w == 0 or h == 0:
            try:
                dll.DeleteAllDevice()
            except Exception:
                pass
            raise AioPanelError("未偵測到銀欣 480×480 水冷頭螢幕 (VID=0145 PID=3002)")

        self.dll = dll
        self.width = w
        self.height = h
        self.uuid = uuid_hex
        self.connected = True
        return self

    def show_jpeg(self, jpeg_bytes: bytes) -> float:
        """Push raw Baseline 4:2:0 JPEG bytes to device index 1 (zoom=256 = 1.0x)."""
        if self.dll is None or not self.connected:
            raise AioPanelError("水冷頭尚未連線")
        t0 = time.perf_counter()
        c_buf = ctypes.create_string_buffer(jpeg_bytes, len(jpeg_bytes))
        ret = self.dll.DirPlayOneFrame(1, c_buf, len(jpeg_bytes), 256)
        if ret == 0:
            raise AioPanelError("DirPlayOneFrame 推送回傳 0（裝置可能已斷線）")
        return time.perf_counter() - t0

    def show(self, image: Image.Image, quality: int = 88) -> float:
        """Encode PIL Image (480x480 RGB) to JPEG and push to the water cooler."""
        if image.size != (self.width, self.height) or image.mode != "RGB":
            image = image.convert("RGB").resize((self.width, self.height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        q = max(40, min(96, int(quality)))
        image.save(buf, format="JPEG", quality=q, subsampling=2)
        return self.show_jpeg(buf.getvalue())

    def close(self):
        if self.dll is not None:
            try:
                self.dll.DeleteAllDevice()
            except Exception:
                pass
            self.dll = None
        self.connected = False
        if self._dll_dir_handle is not None:
            try:
                self._dll_dir_handle.close()
            except Exception:
                pass
            self._dll_dir_handle = None
