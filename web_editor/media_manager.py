"""Windows Global System Media Transport Controls (GSMTC) Provider.

Extracts real-time media metadata (Spotify, Chrome, YouTube, Apple Music, Edge):
- Song title & artist name
- Playback status (PLAYING / PAUSED)
- Position & duration
- Album cover artwork (loaded as PIL Image)
- Simulated / real dynamic audio spectrum frequencies for visualizer
"""

from __future__ import annotations

import asyncio
import io
import math
import threading
import time
from typing import Any
from PIL import Image

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    from winsdk.windows.storage.streams import DataReader
    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False


class MediaManager:
    """Thread-safe background media poller querying Windows GSMTC without blocking."""

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False  # Only query Windows GSMTC when the music widget is placed on screen!
        self._mgr = None
        self._state: dict[str, Any] = {
            "active": False,
            "title": "NO ACTIVE MEDIA",
            "artist": "Ready to play on Spotify / YouTube / Browser",
            "app": "System",
            "status": "STOPPED",
            "position": 0.0,
            "duration": 0.0,
            "thumbnail": None,
            "has_thumbnail": False,
            "last_update": time.time(),
        }
        self._last_title = ""
        self._last_artist = ""
        self._cached_thumb: Image.Image | None = None
        self._thumb_raw: bytes | None = None

        if WINSDK_AVAILABLE:
            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()

    def set_enabled(self, enabled: bool):
        """Enable or hibernate media polling based on whether the music card is on screen."""
        with self._lock:
            self._enabled = enabled

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def _worker_loop(self):
        """Asynchronous worker querying Windows Media Sessions.
        
        Optimized to sleep when disabled and cache SessionManager to minimize NPSMSvc CPU usage.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _query():
            try:
                if self._mgr is None:
                    self._mgr = await SessionManager.request_async()

                session = self._mgr.get_current_session()
                if not session:
                    with self._lock:
                        self._state["active"] = False
                        self._state["status"] = "STOPPED"
                    return

                props = await session.try_get_media_properties_async()
                pb = session.get_playback_info()
                timeline = session.get_timeline_properties()
                app_id = session.source_app_user_model_id or "Media"

                title = props.title if props and props.title else "Unknown Title"
                artist = props.artist if props and props.artist else ""
                status = pb.playback_status.name if pb and pb.playback_status else "UNKNOWN"

                pos = timeline.position.total_seconds() if timeline and timeline.position else 0.0
                end = timeline.end_time.total_seconds() if timeline and timeline.end_time else 0.0

                # Read album thumbnail if track changed or thumbnail not yet cached
                thumb_img = self._cached_thumb
                if (title != self._last_title or artist != self._last_artist or thumb_img is None) and props and props.thumbnail:
                    try:
                        stream = await props.thumbnail.open_read_async()
                        reader = DataReader(stream)
                        await reader.load_async(stream.size)
                        buf = bytearray(stream.size)
                        reader.read_bytes(buf)
                        self._thumb_raw = bytes(buf)
                        thumb_img = Image.open(io.BytesIO(self._thumb_raw)).convert("RGB")
                        self._cached_thumb = thumb_img
                        self._last_title = title
                        self._last_artist = artist
                    except Exception:
                        pass

                with self._lock:
                    self._state = {
                        "active": True,
                        "title": title,
                        "artist": artist,
                        "app": app_id.split("!")[-1].replace(".exe", ""),
                        "status": status,
                        "position": pos,
                        "duration": end,
                        "thumbnail": thumb_img,
                        "has_thumbnail": thumb_img is not None,
                        "last_update": time.time(),
                    }
            except Exception:
                # Invalidate manager on error so next cycle re-initializes cleanly
                self._mgr = None

        while True:
            # Hibernate when no music widget is active on screen
            if not self.is_enabled():
                time.sleep(2.0)
                continue

            try:
                loop.run_until_complete(_query())
            except Exception:
                self._mgr = None

            # Relaxed 2.5s polling interval ensures zero noticeable CPU load on Windows NPSMSvc
            time.sleep(2.5)

    def get_snapshot(self) -> dict[str, Any]:
        """Returns snapshot with dynamic spectrum frequency bands."""
        with self._lock:
            snap = dict(self._state)

        # Generate 32 dynamic audio spectrum frequency bands
        now = time.time()
        is_playing = snap.get("status") == "PLAYING"
        amp = 1.0 if is_playing else (0.25 if snap.get("active") else 0.05)

        bands = []
        for i in range(32):
            freq = (i + 1) * 0.4
            phase = i * 0.28
            # Dynamic harmonic wave
            val = (
                math.sin(now * 8.0 * freq * 0.15 + phase) * 0.35 +
                math.cos(now * 12.0 * 0.2 - phase * 0.8) * 0.25 +
                math.sin(now * 5.0 + i * 0.5) * 0.2 +
                0.55
            )
            # Bass boost for lower frequencies (first 8 bands)
            if i < 8:
                val += math.sin(now * 6.28 * 2.0) * 0.25

            # Taper off higher frequencies naturally
            taper = 1.0 - (i / 36.0)
            band_val = max(0.06, min(1.0, val * amp * taper))
            bands.append(round(band_val, 3))

        snap["spectrum_bands"] = bands
        return snap


# Global singleton instance
media_manager = MediaManager()
