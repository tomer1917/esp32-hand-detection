"""ESP32-CAM video source — pulls MJPEG from the camera over HTTP.

Designed to stay real-time:
- The reader always decodes only the FRESHEST frame in the buffer and discards
  any backlog, so latency can't accumulate.
- read() returns a frame only when a NEW one is available, so the detection
  pipeline never burns CPU reprocessing the same frame (which would starve this
  reader thread and cause the backlog in the first place).

Auto-discovers via mDNS (esp32cam.local) with a fallback to the config IP, and
reconnects automatically if the stream drops.
"""
import threading
import time

import cv2
import httpx
import numpy as np

from .base import VideoSource

SOI = b"\xff\xd8"   # JPEG start-of-image marker
EOI = b"\xff\xd9"   # JPEG end-of-image marker


class Esp32Source(VideoSource):
    def __init__(self, host="esp32cam.local", stream_path="/stream", fallback_ip=""):
        self._host = host
        self._path = stream_path
        self._fallback_ip = fallback_ip

        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._last_read_id = 0
        self._ok = False
        self._running = True
        self._thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self._thread.start()

    def _stream_url(self):
        return f"http://{self._host}{self._path}"

    def _fetch_loop(self):
        while self._running:
            url = self._stream_url()
            print(f"[esp32] connecting to {url}")
            try:
                with httpx.Client(timeout=10) as client:
                    with client.stream("GET", url) as resp:
                        print(f"[esp32] stream open (status {resp.status_code})")
                        buf = bytearray()
                        # Small chunks: httpx yields as soon as data trickles in
                        # (a large chunk_size makes it wait to fill the buffer,
                        # which tanks the frame rate). rfind-latest below still
                        # drops any backlog, so latency stays low.
                        for chunk in resp.iter_bytes(chunk_size=2048):
                            if not self._running:
                                break
                            buf += chunk
                            self._take_latest_frame(buf)
            except Exception as e:
                print(f"[esp32] stream error: {e}")
                with self._lock:
                    self._ok = False

            if self._running:
                # If the mDNS name failed, fall back to the configured IP
                if ".local" in self._host and self._fallback_ip:
                    self._host = self._fallback_ip
                    print(f"[esp32] mDNS failed — falling back to {self._fallback_ip}")
                time.sleep(2)

    def _take_latest_frame(self, buf: bytearray):
        """Decode only the newest complete JPEG in buf; drop everything older."""
        last_end = buf.rfind(EOI)
        if last_end == -1:
            # No complete frame yet; cap buffer growth as a safety net
            if len(buf) > 1_000_000:
                del buf[:-200_000]
            return
        last_start = buf.rfind(SOI, 0, last_end)
        if last_start == -1:
            del buf[:last_end + 2]
            return
        jpg = bytes(buf[last_start:last_end + 2])
        del buf[:last_end + 2]  # discard the frame AND any stale frames before it
        arr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if arr is not None:
            with self._lock:
                self._frame = arr
                self._frame_id += 1
                self._ok = True

    def read(self):
        with self._lock:
            if self._frame is None or self._frame_id == self._last_read_id:
                return False, None  # no new frame since last read → pipeline skips
            self._last_read_id = self._frame_id
            return True, self._frame.copy()

    def release(self):
        self._running = False
        self._thread.join(timeout=3)

    @property
    def name(self):
        return f"ESP32 ({self._host})"
