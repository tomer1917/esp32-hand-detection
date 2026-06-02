"""MediaPipe Gesture Recognizer (Tasks API).

Uses MediaPipe's PRE-TRAINED gesture recognizer instead of hand-rolled landmark
geometry. It's a trained model (rotation/scale robust), and its canned labels
map directly onto the gestures this project needs. It also returns the 21 hand
landmarks, so we still draw the skeleton overlay.

Model (gesture_recognizer.task) auto-downloads on first run.
"""
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "gesture_recognizer.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
             "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task")

# MediaPipe canned label -> our internal gesture name (matches config.json keys)
LABEL_MAP = {
    "Open_Palm": "open_palm",
    "Thumb_Up": "thumb_up",
    "Thumb_Down": "thumb_down",
    "Victory": "two_fingers",
    "Pointing_Up": "one_finger",
    "Closed_Fist": "fist",
    "ILoveYou": "unknown",
    "None": "none",
}

# 21-point hand skeleton (MediaPipe landmark indices)
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm base
]


def _ensure_model():
    if MODEL_PATH.exists():
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[detector] downloading gesture_recognizer model -> {MODEL_PATH}")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("[detector] model ready")


class GestureDetector:
    def __init__(self, max_hands=1, min_detection_confidence=0.6,
                 min_tracking_confidence=0.5, min_gesture_confidence=0.5):
        _ensure_model()
        self.min_gesture_confidence = min_gesture_confidence
        options = vision.GestureRecognizerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_hands=max_hands,
            running_mode=vision.RunningMode.VIDEO,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.recognizer = vision.GestureRecognizer.create_from_options(options)
        self._start = time.monotonic()
        self._last_ts = -1

    def process(self, frame_bgr):
        """Run recognition on a BGR frame. Returns a GestureRecognizerResult."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # VIDEO mode needs strictly increasing timestamps (ms).
        ts = int((time.monotonic() - self._start) * 1000)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts
        return self.recognizer.recognize_for_video(mp_image, ts)

    def top_gesture(self, result):
        """Return (gesture_name, score) for hand 0. 'none' if below confidence."""
        if not result.gestures:
            return "none", 0.0
        top = result.gestures[0][0]  # highest-scoring category for the first hand
        name = LABEL_MAP.get(top.category_name, "unknown")
        if top.score < self.min_gesture_confidence and name != "none":
            return "none", top.score
        return name, top.score

    def draw(self, frame_bgr, result):
        """Draw landmarks + connections in place."""
        h, w = frame_bgr.shape[:2]
        for hand in result.hand_landmarks:
            pts = [(int(p.x * w), int(p.y * h)) for p in hand]
            for a, b in HAND_CONNECTIONS:
                cv2.line(frame_bgr, pts[a], pts[b], (0, 230, 118), 2)
            for (x, y) in pts:
                cv2.circle(frame_bgr, (x, y), 4, (0, 176, 255), -1)
        return frame_bgr

    def close(self):
        self.recognizer.close()
