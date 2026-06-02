"""FastAPI server: runs the detection pipeline in a background thread and
serves the web UI, the annotated MJPEG video stream, and a gesture WebSocket.

Run from the backend/ directory:
    python main.py
Then open http://localhost:8000
"""
import asyncio
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import load_config
from detector import GestureDetector
from gestures import GestureStabilizer
from actions import MediaController
from sources import WebcamSource, Esp32Source

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def make_source(cfg):
    kind = cfg.get("source", "webcam")
    if kind == "webcam":
        return WebcamSource(index=cfg.get("webcam_index", 0))
    if kind == "esp32":
        esp = cfg.get("esp32", {})
        host = esp.get("host", "esp32cam.local")
        return Esp32Source(
            host=host,
            stream_path=esp.get("stream_path", "/stream"),
            fallback_ip=esp.get("fallback_ip", ""),
        )
    raise ValueError(f"Unknown source type: {kind!r}")


class Pipeline:
    """Capture -> detect -> classify -> debounce -> act, on a background thread."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.source = make_source(cfg)

        det = cfg["detection"]
        self.detector = GestureDetector(
            max_hands=det["max_hands"],
            min_detection_confidence=det["min_detection_confidence"],
            min_tracking_confidence=det["min_tracking_confidence"],
            min_gesture_confidence=det.get("min_gesture_confidence", 0.5),
        )

        # Gestures whose action is a volume change should repeat while held.
        gmap = cfg["gestures"]
        repeatable = [g for g, a in gmap.items() if a in ("volume_up", "volume_down")]
        deb = cfg["debounce"]
        self.stabilizer = GestureStabilizer(
            stable_time_s=deb.get("stable_time_s", 0.4),
            cooldown_s=deb["cooldown_s"],
            repeat_interval_s=deb["repeat_interval_s"],
            repeatable=repeatable,
        )

        self.media = MediaController(enabled=cfg.get("fire_actions", True))

        self.lock = threading.Lock()
        self.latest_jpeg = None
        self.current_gesture = "none"
        self.current_score = 0.0
        self.last_action = None
        self.last_action_time = 0.0
        self.fps = 0.0
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(f"[pipeline] started on source: {self.source.name}")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.source.release()
        self.detector.close()

    def _loop(self):
        last_t = time.time()
        while self.running:
            ok, frame = self.source.read()
            if not ok or frame is None:
                time.sleep(0.005)  # no new frame yet — re-check promptly, don't busy-spin
                continue

            frame = cv2.flip(frame, 1)  # mirror — feels natural to the user
            result = self.detector.process(frame)

            gesture = "none"
            score = 0.0
            if result.hand_landmarks:
                self.detector.draw(frame, result)
                gesture, score = self.detector.top_gesture(result)

            fired = self.stabilizer.update(gesture)
            action = None
            if fired:
                action = self.cfg["gestures"].get(fired)
                if action:
                    sent = self.media.fire(action)
                    print(f"[action] {fired} -> {action}"
                          + ("" if sent else "  (actions OFF — toggle in UI)"))

            # FPS (smoothed)
            now = time.time()
            dt = now - last_t
            last_t = now
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)

            self._draw_overlay(frame, gesture, action)

            ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok2:
                with self.lock:
                    self.latest_jpeg = buf.tobytes()
                    self.current_gesture = gesture
                    self.current_score = score
                    if action:
                        self.last_action = action
                        self.last_action_time = now

    def _draw_overlay(self, frame, gesture, action):
        h, w = frame.shape[:2]
        label = gesture if gesture not in ("none", "unknown") else "—"
        cv2.rectangle(frame, (0, 0), (w, 40), (20, 20, 20), -1)
        cv2.putText(frame, f"Gesture: {label}", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2)
        cv2.putText(frame, f"{self.fps:4.1f} fps", (w - 110, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
        if action and (time.time() - self.last_action_time) < 1.0:
            cv2.putText(frame, f">> {action}", (12, h - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)


# ── App ─────────────────────────────────────────────────────────────────────

cfg = load_config()
pipeline: "Pipeline | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    pipeline = Pipeline(cfg)
    pipeline.start()
    yield
    pipeline.stop()


app = FastAPI(title="ESP32 Hand Detection", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _mjpeg():
    boundary = b"--frame"
    while True:
        with pipeline.lock:
            frame = pipeline.latest_jpeg
        if frame is None:
            time.sleep(0.03)
            continue
        yield (boundary + b"\r\n"
               b"Content-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
               + frame + b"\r\n")
        time.sleep(0.03)


@app.get("/video")
def video():
    return StreamingResponse(
        _mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/state")
def state():
    with pipeline.lock:
        return JSONResponse({
            "gesture": pipeline.current_gesture,
            "last_action": pipeline.last_action,
            "fire_actions": pipeline.media.enabled,
            "source": pipeline.source.name,
            "fps": round(pipeline.fps, 1),
        })


@app.post("/api/toggle_actions")
def toggle_actions():
    pipeline.media.enabled = not pipeline.media.enabled
    return JSONResponse({"fire_actions": pipeline.media.enabled})


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            with pipeline.lock:
                payload = {
                    "gesture": pipeline.current_gesture,
                    "score": round(pipeline.current_score, 2),
                    "last_action": pipeline.last_action,
                    "fire_actions": pipeline.media.enabled,
                    "fps": round(pipeline.fps, 1),
                }
            await websocket.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass


# Static assets (style.css, app.js) under /static
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host=cfg["server"]["host"], port=cfg["server"]["port"])
