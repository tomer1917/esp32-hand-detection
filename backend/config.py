"""Loads config.json from the project root, with sensible defaults."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULTS = {
    "source": "webcam",
    "webcam_index": 0,
    "esp32": {
        "use_mdns": True,
        "host": "esp32cam.local",
        "stream_path": "/stream",
        "fallback_ip": "",
    },
    "detection": {
        "max_hands": 1,
        "min_detection_confidence": 0.6,
        "min_tracking_confidence": 0.5,
        "min_gesture_confidence": 0.5,
    },
    "debounce": {
        "stable_time_s": 0.4,
        "cooldown_s": 1.2,
        "repeat_interval_s": 0.5,
    },
    "fire_actions": True,
    "gestures": {
        "open_palm": "play_pause",
        "thumb_up": "volume_up",
        "thumb_down": "volume_down",
        "two_fingers": "next_track",
        "one_finger": "previous_track",
    },
    "server": {"host": "0.0.0.0", "port": 8000},
}


def _merge(base, override):
    """Deep-merge override into a copy of base."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        return _merge(DEFAULTS, user_cfg)
    print(f"[config] {CONFIG_PATH} not found — using defaults")
    return dict(DEFAULTS)
