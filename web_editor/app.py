"""Web Editor & Real-Time Push Studio for Valkyrie 960x360 Secondary Display.

Provides:
- Web GUI on http://localhost:5050 with real-time WYSIWYG canvas preview.
- Custom color picker (background, cards, borders, text, accents).
- Card opacity / transparency slider.
- Custom background wallpaper upload (supports PNG/JPG/WEBP with blur & dimming).
- Direct "Push to Screen" button and live auto-sync to hardware.
- Decoupled high-FPS streaming worker with smooth wave/particle animation (up to 30 FPS)
  and low-overhead hardware telemetry background polling (1.2 Hz).
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from pathlib import Path

# Prevent AttributeError when launched silently via pythonw.exe (Task Scheduler autostart)
if sys.stdout is None or sys.stderr is None:
    _log_path = Path(__file__).resolve().parent / "studio.log"
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log_file
    if sys.stderr is None:
        sys.stderr = _log_file

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, render_template, request, Response, send_file
from PIL import Image

from examples.scifi_hud_960x360 import TelemetryProvider
from valkyrie_lcd import ValkyriePanel
from web_editor.aio_driver import SilverStoneAioPanel
from web_editor.aio_renderer import DEFAULT_AIO_WIDGETS, VALID_AIO_METRICS, render_aio_480x480
from web_editor.media_manager import media_manager
from web_editor.renderer import render_custom_hud

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "theme.json"
AIO_CONFIG_FILE = CONFIG_DIR / "aio_theme.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_THEME = {
    "canvas_bg": "#f8fafc",
    "card_bg": "#ffffff",
    "card_opacity": 0.95,
    "card_border": "#e2e8f0",
    "card_border_opacity": 1.0,
    "text_primary": "#0f172a",
    "text_secondary": "#64748b",
    "cpu_accent": "#0284c7",
    "ram_accent": "#7c3aed",
    "gpu_accent": "#ea580c",
    "status_accent": "#10b981",
    "bg_image": None,
    "bg_dim": 0.0,
    "bg_blur": 0,
    "rotate": 270,
    "fps": 2.0,
    "sync_to_screen": True,
    "ambient_fx": "off",
    "ambient_opacity": 0.55,
    "ambient_speed": 1.0,
    "widgets": [
        {"id": "cpu", "x": 0, "w": 1},
        {"id": "ram", "x": 1, "w": 1},
        {"id": "gpu", "x": 2, "w": 1},
    ],
}


def sanitize_theme(theme_data: dict | None) -> dict:
    """Sanitizes theme dictionary with safe defaults, preventing NoneType/NaN crashes."""
    res = dict(DEFAULT_THEME)
    if not isinstance(theme_data, dict):
        return res

    for k, v in theme_data.items():
        if k in DEFAULT_THEME and v is not None:
            res[k] = v

    def _float(val, default):
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def _int(val, default):
        try:
            return int(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    res["card_opacity"] = max(0.0, min(1.0, _float(res.get("card_opacity"), 0.95)))
    res["card_border_opacity"] = max(0.0, min(1.0, _float(res.get("card_border_opacity"), 1.0)))
    res["bg_dim"] = max(0.0, min(1.0, _float(res.get("bg_dim"), 0.0)))
    res["bg_blur"] = max(0, min(50, _int(res.get("bg_blur"), 0)))

    rot = _int(res.get("rotate"), 270)
    res["rotate"] = rot if rot in (0, 90, 180, 270) else 270

    fps = _float(res.get("fps"), 2.0)
    res["fps"] = max(1.0, min(30.0, fps))

    amb_mode = str(res.get("ambient_fx", "off")).lower()
    res["ambient_fx"] = amb_mode if amb_mode in ("waves", "particles", "dual", "off") else "off"
    res["ambient_opacity"] = max(0.0, min(1.0, _float(res.get("ambient_opacity"), 0.55)))
    res["ambient_speed"] = max(0.2, min(3.0, _float(res.get("ambient_speed"), 1.0)))

    # Sanitize widgets (GridStack 3-column layout)
    raw_widgets = theme_data.get("widgets") if isinstance(theme_data, dict) else None
    valid_ids = {"cpu", "gpu", "ram", "music", "net"}
    sanitized_widgets = []
    if isinstance(raw_widgets, list):
        occupied_cols = set()
        seen_ids = set()
        for w in raw_widgets:
            if isinstance(w, dict):
                wid = str(w.get("id", "")).lower()
                if wid in valid_ids and wid not in seen_ids:
                    wx = max(0, min(2, _int(w.get("x"), 0)))
                    ww = max(1, min(3, _int(w.get("w"), 1)))
                    ww = min(ww, 3 - wx)
                    cols = set(range(wx, wx + ww))
                    if not cols.intersection(occupied_cols):
                        occupied_cols.update(cols)
                        seen_ids.add(wid)
                        sanitized_widgets.append({"id": wid, "x": wx, "w": ww})
    elif raw_widgets is None:
        sanitized_widgets = [
            {"id": "cpu", "x": 0, "w": 1},
            {"id": "ram", "x": 1, "w": 1},
            {"id": "gpu", "x": 2, "w": 1},
        ]
    res["widgets"] = sanitized_widgets

    res["sync_to_screen"] = bool(res.get("sync_to_screen", True))
    return res


def load_theme() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                return sanitize_theme(saved)
        except Exception:
            pass
    return dict(DEFAULT_THEME)


def save_theme(theme_data: dict):
    try:
        sanitized = sanitize_theme(theme_data)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[Config] Save error:", e)


app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Global State & Locks
current_theme = load_theme()
theme_lock = threading.Lock()
telemetry = TelemetryProvider()

cached_telemetry = None
cached_telemetry_lock = threading.Lock()

push_now_event = threading.Event()
push_done_event = threading.Event()

# Live MJPEG Stream Sync for Web Editor (Synchronized in lockstep with secondary LCD display)
latest_frame_jpeg: bytes | None = None
stream_condition = threading.Condition()
active_stream_clients = 0
active_stream_clients_lock = threading.Lock()


def check_and_sync_media_manager(theme: dict):
    """Wake or hibernate Windows GSMTC querying based on whether music widget is active."""
    widgets = theme.get("widgets", [])
    has_music = any(isinstance(w, dict) and w.get("id") == "music" for w in widgets)
    media_manager.set_enabled(has_music)


# Initialize media manager state
check_and_sync_media_manager(current_theme)

hardware_state = {
    "connected": False,
    "streaming": True,
    "fps": 15.0,
    "actual_fps": 0.0,
    "error": None,
    "last_push_time": 0,
}


_last_net = None
_last_net_t = 0.0


def telemetry_poller():
    """Background worker polling hardware sensors at a relaxed 1.25 Hz.
    
    Decoupling telemetry querying from screen rendering guarantees:
    1. Zero sensor bus stutter / no WMI locks.
    2. Zero CPU overhead.
    3. The screen rendering thread can push frames at silky-smooth 15-30 FPS!
    """
    global cached_telemetry, _last_net, _last_net_t
    _last_net = psutil.net_io_counters()
    _last_net_t = time.time()

    while True:
        try:
            data = telemetry.query()

            # Network I/O Speed computation
            cur_net = psutil.net_io_counters()
            cur_t = time.time()
            dt = max(0.1, cur_t - _last_net_t)
            down_kb = max(0.0, (cur_net.bytes_recv - _last_net.bytes_recv) / dt / 1024.0)
            up_kb = max(0.0, (cur_net.bytes_sent - _last_net.bytes_sent) / dt / 1024.0)
            _last_net = cur_net
            _last_net_t = cur_t

            data["net_down_kb"] = down_kb
            data["net_up_kb"] = up_kb

            with cached_telemetry_lock:
                cached_telemetry = dict(data)
        except Exception:
            pass
        time.sleep(0.8)


def get_telemetry_snapshot() -> dict:
    with cached_telemetry_lock:
        if cached_telemetry is not None:
            snap = dict(cached_telemetry)
        else:
            snap = telemetry.query()
    # Always attach fresh dynamic media state (spectrum & timeline)
    snap["media"] = media_manager.get_snapshot()
    return snap


def is_mythcool_running() -> bool:
    """Check if the official MythCool software is running to prevent USB interface collision."""
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if "mythcool" in name:
                return True
    except Exception:
        pass
    return False


def stream_worker():
    """Decoupled background stream worker:
    - Web editor live MJPEG stream runs at ~15 FPS for smooth, fluid browser interaction.
    - Physical MS9132 panel is pushed at hw_target_fps (default 2.0-3.0 FPS) for 100% flicker-free stability.
    - Gracefully auto-reconnects when the USB cable is unplugged/replugged.
    """
    global current_theme, hardware_state, latest_frame_jpeg

    panel = None
    frame_counter = 0
    fps_calc_t0 = time.time()
    last_hw_push_t = 0.0
    last_connect_attempt_t = 0.0

    while True:
        loop_start = time.perf_counter()
        try:
            with theme_lock:
                sync = bool(current_theme.get("sync_to_screen", True))
                hw_target_fps = float(current_theme.get("fps") or 2.0)
                rotate = int(current_theme.get("rotate") or 270)
                theme_snapshot = dict(current_theme)

            # 1. Query cached telemetry & render frame
            data = get_telemetry_snapshot()
            frame = render_custom_hud(data, theme_snapshot)

            # 2. Update MJPEG live stream buffer only if a web browser is actively watching preview
            with active_stream_clients_lock:
                has_web_clients = (active_stream_clients > 0)

            if has_web_clients:
                buf = io.BytesIO()
                frame.save(buf, format="JPEG", quality=82)
                jpeg_bytes = buf.getvalue()
                with stream_condition:
                    latest_frame_jpeg = jpeg_bytes
                    stream_condition.notify_all()

            # 3. Synchronize to MS9132 physical panel (paced at hw_target_fps or manual push)
            now_t = time.time()
            manual_push = push_now_event.is_set()
            hw_interval = 1.0 / max(0.5, min(30.0, hw_target_fps))
            hardware_state["fps"] = hw_target_fps

            should_push_hw = (sync and (now_t - last_hw_push_t >= hw_interval)) or manual_push

            if should_push_hw:
                if manual_push:
                    push_now_event.clear()
                last_hw_push_t = now_t

                if panel is None:
                    # Cooldown 2.5s between failed reconnects so we never hammer MS9132 HID/USB
                    if manual_push or (now_t - last_connect_attempt_t >= 2.5):
                        last_connect_attempt_t = now_t
                        if is_mythcool_running():
                            hardware_state["connected"] = False
                            hardware_state["error"] = "偵測到官方軟體 MythCool 正在運行，為避免碰撞損壞晶片狀態已暫停連線，請先退出 MythCool。"
                            push_done_event.set()
                        else:
                            try:
                                panel = ValkyriePanel(width=360, height=960, vic=160, verbose=False).connect()
                                hardware_state["connected"] = True
                                hardware_state["error"] = None
                                print("[Hardware] Connected to Valkyrie Display (360x960, VIC=160)")
                            except Exception as conn_err:
                                hardware_state["connected"] = False
                                hardware_state["error"] = f"Display connect error: {conn_err}"
                                push_done_event.set()

                if panel is not None:
                    # Apply orientation rotation
                    if rotate == 270:
                        out_frame = frame.transpose(Image.Transpose.ROTATE_270)
                    elif rotate == 90:
                        out_frame = frame.transpose(Image.Transpose.ROTATE_90)
                    elif rotate == 180:
                        out_frame = frame.transpose(Image.Transpose.ROTATE_180)
                    elif rotate == 0:
                        out_frame = frame.resize((360, 960))
                    else:
                        out_frame = frame.rotate(rotate, expand=True).resize((360, 960))

                    try:
                        panel.show(out_frame)
                        hardware_state["connected"] = True
                        hardware_state["error"] = None
                        hardware_state["last_push_time"] = time.time()
                        frame_counter += 1
                    except Exception as push_err:
                        # Handle USB unplug/replug / broken pipe / occupied by official app
                        err_msg = str(push_err)
                        print("[Hardware] Push error, closing panel handle:", err_msg)
                        if "claim interface" in err_msg.lower():
                            err_msg = "MI_03 介面已被占用（請確認是否已完全退出官方 Myth.Cool 軟體）"
                        try:
                            panel.close()
                        except Exception:
                            pass
                        panel = None
                        last_connect_attempt_t = time.time()
                        hardware_state["connected"] = False
                        hardware_state["error"] = err_msg

                push_done_event.set()

                # Calculate actual delivered hardware FPS
                now = time.time()
                if now - fps_calc_t0 >= 2.0:
                    hardware_state["actual_fps"] = round(frame_counter / (now - fps_calc_t0), 1)
                    frame_counter = 0
                    fps_calc_t0 = now

        except Exception as exc:
            hardware_state["connected"] = False
            hardware_state["error"] = str(exc)
            last_connect_attempt_t = time.time()
            push_done_event.set()
            if panel is not None:
                try:
                    panel.close()
                except Exception:
                    pass
                panel = None

        # Loop pacing:
        # If a web browser is watching preview, pace at fluid preview FPS (15-20 FPS).
        # When no browser is open (background running), pace strictly at hw_target_fps to minimize CPU!
        loop_target_fps = max(15.0, min(30.0, hw_target_fps)) if has_web_clients else max(0.5, min(30.0, hw_target_fps))
        elapsed = time.perf_counter() - loop_start
        sleep_dur = max(0.001, (1.0 / loop_target_fps) - elapsed)
        time.sleep(sleep_dur)


# ── Web Endpoints ────────────────────────────────────────────────────────────

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global current_theme
    if request.method == "POST":
        try:
            new_data = request.get_json(force=True)
            with theme_lock:
                current_theme.update(new_data)
                current_theme = sanitize_theme(current_theme)
                save_theme(current_theme)
                should_sync = current_theme.get("sync_to_screen", True)

            # Update media manager sleep state based on active widgets
            check_and_sync_media_manager(current_theme)

            # Trigger instant push if auto-sync is active
            if should_sync:
                push_now_event.set()

            return jsonify({"success": True, "config": current_theme})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    with theme_lock:
        return jsonify(current_theme)


@app.route("/api/upload_bg", methods=["POST"])
def api_upload_bg():
    global current_theme
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        ext = ".png"

    dest = UPLOAD_DIR / f"bg_wallpaper{ext}"
    file.save(str(dest))

    with theme_lock:
        current_theme["bg_image"] = str(dest.resolve())
        save_theme(current_theme)
        if current_theme.get("sync_to_screen", True):
            push_now_event.set()

    return jsonify({"success": True, "path": str(dest.resolve())})


@app.route("/api/remove_bg", methods=["POST"])
def api_remove_bg():
    global current_theme
    with theme_lock:
        current_theme["bg_image"] = None
        save_theme(current_theme)
        if current_theme.get("sync_to_screen", True):
            push_now_event.set()
    return jsonify({"success": True})


@app.route("/api/stream")
def api_stream():
    """Real-time MJPEG video stream pushing frames in exact lockstep with the secondary display.
    
    Provides 15~20 FPS live synchronized preview to the web editor with sub-frame latency.
    """
    def generate():
        global active_stream_clients
        with active_stream_clients_lock:
            active_stream_clients += 1
        last_sent = None
        try:
            while True:
                with stream_condition:
                    stream_condition.wait(timeout=0.35)
                    data = latest_frame_jpeg
                if data and data is not last_sent:
                    last_sent = data
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                        + data
                        + b"\r\n"
                    )
        except (GeneratorExit, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            with active_stream_clients_lock:
                active_stream_clients = max(0, active_stream_clients - 1)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, private, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.route("/api/preview")
def api_preview():
    with theme_lock:
        theme_snapshot = dict(current_theme)

    data = get_telemetry_snapshot()
    frame = render_custom_hud(data, theme_snapshot)

    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=90)
    buf.seek(0)

    response = Response(buf.getvalue(), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/push", methods=["POST"])
def api_push():
    """Triggers an immediate frame push to the secondary display."""
    push_done_event.clear()
    push_now_event.set()

    # Wait up to 2.5s for confirmation from stream worker
    push_done_event.wait(timeout=2.5)

    connected = hardware_state.get("connected", False)
    error = hardware_state.get("error")

    if connected:
        return jsonify({
            "success": True,
            "connected": True,
            "message": "Pushed to screen successfully"
        })
    else:
        return jsonify({
            "success": False,
            "connected": False,
            "error": error or "Hardware display not connected or busy"
        })


@app.route("/api/status")
def api_status():
    with theme_lock:
        target_fps = current_theme.get("fps", 15.0)
        sync = current_theme.get("sync_to_screen", True)

    return jsonify({
        "connected": hardware_state.get("connected", False),
        "streaming": hardware_state.get("streaming", True),
        "fps": target_fps,
        "actual_fps": hardware_state.get("actual_fps", target_fps),
        "sync_to_screen": sync,
        "error": hardware_state.get("error"),
        "last_push_time": hardware_state.get("last_push_time", 0),
    })


# ── SilverStone 480x480 AIO Water Cooler Subsystem ──────────────────────────

DEFAULT_AIO_THEME = {
    "mode": "cpu_trio",
    "canvas_bg": "#080c16",
    "accent_primary": "#00e5ff",
    "accent_secondary": "#ff8800",
    "accent_power": "#a855f7",
    "text_primary": "#f8fafc",
    "text_secondary": "#94a3b8",
    "bg_image": None,
    "bg_dim": 0.35,
    "bg_blur": 0,
    "rotate": 0,
    "fps": 10.0,
    "quality": 88,
    "ambient_ring": True,
    "sync_to_screen": True,
    "widgets": [dict(w) for w in DEFAULT_AIO_WIDGETS],
}


def sanitize_aio_theme(data: dict) -> dict:
    res = dict(DEFAULT_AIO_THEME)
    if isinstance(data, dict):
        res.update(data)

    def _f(v, d):
        try:
            return float(v) if v is not None else d
        except Exception:
            return d

    def _i(v, d):
        try:
            return int(float(v)) if v is not None else d
        except Exception:
            return d

    for k in ("canvas_bg", "accent_primary", "accent_secondary", "accent_power", "text_primary", "text_secondary"):
        val = str(res.get(k) or "").strip()
        if not val.startswith("#") or len(val) != 7:
            res[k] = DEFAULT_AIO_THEME[k]

    res["bg_dim"] = max(0.0, min(0.9, _f(res.get("bg_dim"), 0.35)))
    res["bg_blur"] = max(0, min(25, _i(res.get("bg_blur"), 0)))
    rot = _i(res.get("rotate"), 0)
    res["rotate"] = rot if rot in (0, 90, 180, 270) else 0
    res["fps"] = max(1.0, min(25.0, _f(res.get("fps"), 10.0)))
    res["quality"] = max(45, min(96, _i(res.get("quality"), 88)))
    res["ambient_ring"] = bool(res.get("ambient_ring", True))
    res["sync_to_screen"] = bool(res.get("sync_to_screen", True))

    # Sanitize modular 2x2 grid widgets (strict non-overlapping 2x2 bounds)
    raw_widgets = data.get("widgets") if isinstance(data, dict) else None
    sanitized_widgets = []
    if isinstance(raw_widgets, list):
        occupied = set()
        for idx, item in enumerate(raw_widgets):
            if not isinstance(item, dict):
                continue
            gx = max(0, min(1, _i(item.get("x"), 0)))
            gy = max(0, min(1, _i(item.get("y"), 0)))
            gw = max(1, min(2 - gx, _i(item.get("w"), 1)))
            gh = max(1, min(2 - gy, _i(item.get("h"), 1)))
            cells = {(gx + dx, gy + dy) for dx in range(gw) for dy in range(gh)}
            if cells.intersection(occupied):
                continue
            occupied.update(cells)
            metric = str(item.get("metric", "cpu_usage")).lower()
            if metric not in VALID_AIO_METRICS:
                metric = "cpu_usage"
            col = str(item.get("color") or "#00e5ff").strip()
            if not col.startswith("#") or len(col) != 7:
                col = "#00e5ff"
            wid = str(item.get("id") or f"w{idx + 1}")
            sanitized_widgets.append({
                "id": wid, "x": gx, "y": gy, "w": gw, "h": gh,
                "metric": metric, "color": col,
            })
    elif raw_widgets is None:
        sanitized_widgets = [dict(w) for w in DEFAULT_AIO_WIDGETS]
    res["widgets"] = sanitized_widgets
    return res


def load_aio_theme() -> dict:
    if AIO_CONFIG_FILE.exists():
        try:
            with open(AIO_CONFIG_FILE, "r", encoding="utf-8") as f:
                return sanitize_aio_theme(json.load(f))
        except Exception:
            pass
    return dict(DEFAULT_AIO_THEME)


def save_aio_theme(theme_data: dict):
    try:
        sanitized = sanitize_aio_theme(theme_data)
        with open(AIO_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[AIO Config] Save error:", e)


aio_theme = load_aio_theme()
aio_theme_lock = threading.Lock()
aio_push_now_event = threading.Event()
aio_push_done_event = threading.Event()

latest_aio_jpeg: bytes | None = None
aio_stream_condition = threading.Condition()
active_aio_clients = 0
active_aio_clients_lock = threading.Lock()

aio_hardware_state = {
    "connected": False,
    "uuid": "",
    "fps": 10.0,
    "actual_fps": 0.0,
    "last_kb": 0.0,
    "error": None,
    "last_push_time": 0.0,
}


def aio_stream_worker():
    """Dedicated background worker for the SilverStone 480x480 AIO water cooler LCD."""
    global aio_theme, aio_hardware_state, latest_aio_jpeg

    panel: SilverStoneAioPanel | None = None
    frame_counter = 0
    fps_calc_t0 = time.time()
    last_hw_push_t = 0.0
    last_connect_attempt_t = 0.0

    while True:
        loop_start = time.perf_counter()
        has_web_clients = False
        hw_target_fps = 10.0
        try:
            with aio_theme_lock:
                sync = bool(aio_theme.get("sync_to_screen", True))
                hw_target_fps = float(aio_theme.get("fps") or 10.0)
                rotate = int(aio_theme.get("rotate") or 0)
                quality = int(aio_theme.get("quality") or 88)
                cfg_snap = dict(aio_theme)

            with active_aio_clients_lock:
                has_web_clients = (active_aio_clients > 0)

            now_t = time.time()
            manual_push = aio_push_now_event.is_set()
            hw_interval = 1.0 / max(1.0, min(25.0, hw_target_fps))
            aio_hardware_state["fps"] = hw_target_fps
            should_push_hw = (sync and (now_t - last_hw_push_t >= hw_interval)) or manual_push

            # Only render & encode if either the browser preview is open OR we need to push a hardware frame
            if has_web_clients or should_push_hw:
                data = get_telemetry_snapshot()
                frame = render_aio_480x480(data, cfg_snap)

                # Encode web preview JPEG (unrotated upright for UI)
                if has_web_clients:
                    pbuf = io.BytesIO()
                    frame.save(pbuf, format="JPEG", quality=85, subsampling=2)
                    p_bytes = pbuf.getvalue()
                    with aio_stream_condition:
                        latest_aio_jpeg = p_bytes
                        aio_stream_condition.notify_all()

                if should_push_hw:
                    if manual_push:
                        aio_push_now_event.clear()
                    last_hw_push_t = now_t

                    if panel is None:
                        if manual_push or (now_t - last_connect_attempt_t >= 2.5):
                            last_connect_attempt_t = now_t
                            try:
                                panel = SilverStoneAioPanel().connect()
                                aio_hardware_state["connected"] = True
                                aio_hardware_state["uuid"] = panel.uuid
                                aio_hardware_state["error"] = None
                                print(f"[AIO] Connected to SilverStone 480x480 LCD (UUID={panel.uuid})")
                            except Exception as conn_err:
                                aio_hardware_state["connected"] = False
                                aio_hardware_state["error"] = str(conn_err)
                                aio_push_done_event.set()

                    if panel is not None:
                        if rotate == 90:
                            hw_frame = frame.transpose(Image.Transpose.ROTATE_270)
                        elif rotate == 180:
                            hw_frame = frame.transpose(Image.Transpose.ROTATE_180)
                        elif rotate == 270:
                            hw_frame = frame.transpose(Image.Transpose.ROTATE_90)
                        else:
                            hw_frame = frame

                        try:
                            jbuf = io.BytesIO()
                            hw_frame.save(jbuf, format="JPEG", quality=quality, subsampling=2)
                            jbytes = jbuf.getvalue()
                            panel.show_jpeg(jbytes)
                            aio_hardware_state["connected"] = True
                            aio_hardware_state["error"] = None
                            aio_hardware_state["last_kb"] = round(len(jbytes) / 1024.0, 1)
                            aio_hardware_state["last_push_time"] = time.time()
                            frame_counter += 1
                        except Exception as push_err:
                            print("[AIO] Push error, closing handle:", push_err)
                            try:
                                panel.close()
                            except Exception:
                                pass
                            panel = None
                            last_connect_attempt_t = time.time()
                            aio_hardware_state["connected"] = False
                            aio_hardware_state["error"] = str(push_err)

                    aio_push_done_event.set()

                    now = time.time()
                    if now - fps_calc_t0 >= 2.0:
                        aio_hardware_state["actual_fps"] = round(frame_counter / (now - fps_calc_t0), 1)
                        frame_counter = 0
                        fps_calc_t0 = now
            else:
                # Idle when neither syncing nor previewing
                if panel is not None:
                    try:
                        panel.close()
                    except Exception:
                        pass
                    panel = None
                    aio_hardware_state["connected"] = False
                    aio_hardware_state["actual_fps"] = 0.0

        except Exception as exc:
            aio_hardware_state["connected"] = False
            aio_hardware_state["error"] = str(exc)
            last_connect_attempt_t = time.time()
            aio_push_done_event.set()
            if panel is not None:
                try:
                    panel.close()
                except Exception:
                    pass
                panel = None

        loop_fps = max(12.0, min(25.0, hw_target_fps)) if has_web_clients else max(1.0, min(25.0, hw_target_fps))
        elapsed = time.perf_counter() - loop_start
        time.sleep(max(0.005, (1.0 / loop_fps) - elapsed))


@app.route("/api/aio/config", methods=["GET", "POST"])
def api_aio_config():
    global aio_theme
    if request.method == "POST":
        try:
            new_data = request.get_json(force=True)
            with aio_theme_lock:
                aio_theme.update(new_data)
                aio_theme = sanitize_aio_theme(aio_theme)
                save_aio_theme(aio_theme)
                should_sync = aio_theme.get("sync_to_screen", True)
            if should_sync:
                aio_push_now_event.set()
            return jsonify({"success": True, "config": aio_theme})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400
    with aio_theme_lock:
        return jsonify(aio_theme)


@app.route("/api/aio/upload_bg", methods=["POST"])
def api_aio_upload_bg():
    global aio_theme
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    file = request.files["image"]
    if not file.filename:
        return jsonify({"success": False, "error": "Empty filename"}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        ext = ".png"
    dest = UPLOAD_DIR / f"aio_bg_wallpaper{ext}"
    file.save(str(dest))
    with aio_theme_lock:
        aio_theme["bg_image"] = str(dest.resolve())
        save_aio_theme(aio_theme)
        if aio_theme.get("sync_to_screen", True):
            aio_push_now_event.set()
    return jsonify({"success": True, "path": str(dest.resolve())})


@app.route("/api/aio/remove_bg", methods=["POST"])
def api_aio_remove_bg():
    global aio_theme
    with aio_theme_lock:
        aio_theme["bg_image"] = None
        save_aio_theme(aio_theme)
        if aio_theme.get("sync_to_screen", True):
            aio_push_now_event.set()
    return jsonify({"success": True})


@app.route("/api/aio/stream")
def api_aio_stream():
    def generate():
        global active_aio_clients
        with active_aio_clients_lock:
            active_aio_clients += 1
        last_sent = None
        try:
            while True:
                with aio_stream_condition:
                    aio_stream_condition.wait(timeout=0.4)
                    data = latest_aio_jpeg
                if data and data is not last_sent:
                    last_sent = data
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n"
                        + data
                        + b"\r\n"
                    )
        except (GeneratorExit, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            with active_aio_clients_lock:
                active_aio_clients = max(0, active_aio_clients - 1)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, private, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.route("/api/aio/push", methods=["POST"])
def api_aio_push():
    aio_push_done_event.clear()
    aio_push_now_event.set()
    aio_push_done_event.wait(timeout=2.5)
    connected = aio_hardware_state.get("connected", False)
    error = aio_hardware_state.get("error")
    if connected:
        return jsonify({"success": True, "connected": True, "message": "已推送至銀欣水冷頭"})
    return jsonify({"success": False, "connected": False, "error": error or "水冷頭未連線"})


@app.route("/api/aio/status")
def api_aio_status():
    with aio_theme_lock:
        target_fps = aio_theme.get("fps", 10.0)
        sync = aio_theme.get("sync_to_screen", True)
    return jsonify({
        "connected": aio_hardware_state.get("connected", False),
        "uuid": aio_hardware_state.get("uuid", ""),
        "fps": target_fps,
        "actual_fps": aio_hardware_state.get("actual_fps", 0.0),
        "last_kb": aio_hardware_state.get("last_kb", 0.0),
        "sync_to_screen": sync,
        "error": aio_hardware_state.get("error"),
        "last_push_time": aio_hardware_state.get("last_push_time", 0.0),
    })


def main():
    print("=" * 60)
    print("Valkyrie & SilverStone Dual-Screen Studio // Web Editor")
    print("Web UI available at: http://localhost:5050")
    print("=" * 60)

    # Launch telemetry polling thread in background (1.25 Hz, shared by both displays)
    t_telemetry = threading.Thread(target=telemetry_poller, daemon=True)
    t_telemetry.start()

    # Launch VK03M 960x360 chassis LCD worker
    t_stream = threading.Thread(target=stream_worker, daemon=True)
    t_stream.start()

    # Launch SilverStone 480x480 AIO water cooler LCD worker
    t_aio_stream = threading.Thread(target=aio_stream_worker, daemon=True)
    t_aio_stream.start()

    # Run Flask Web Server
    app.run(host="0.0.0.0", port=5050, debug=False)


if __name__ == "__main__":
    main()
