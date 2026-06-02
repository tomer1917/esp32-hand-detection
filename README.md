# ✋ GestureMedia — ESP32 Hand Gesture Media Controller

Control your music with hand gestures, powered by an ESP32 camera and MediaPipe AI.

---

## How it works

A Python backend pulls the live video stream from an ESP32-CAM, runs MediaPipe's hand gesture recognizer on every frame, and translates recognized gestures into system-wide media keys — pausing Spotify, skipping tracks, adjusting volume — all without touching your keyboard.

A local web dashboard shows the annotated live feed, the current gesture, confidence level, and a history of recent actions.

```
ESP32-CAM  ──MJPEG──►  Python backend  ──media keys──►  Spotify / any player
                             │
                         MediaPipe
                        Gesture AI
                             │
                        Web dashboard
                       localhost:8000
```

---

## Gestures

| Gesture | Action |
|---|---|
| ✋ Open palm | Play / Pause |
| 👍 Thumb up | Volume Up |
| 👎 Thumb down | Volume Down |
| ✌️ Two fingers | Next track |
| ☝️ One finger | Previous track |
| ✊ Fist | Neutral (re-arms the next gesture) |

---

## Hardware

| Part | Notes |
|---|---|
| ESP32-CAM (AI-Thinker) | Works with GC2145 sensor (common AliExpress variant) — no hardware JPEG required |
| USB-to-TTL / FTDI adapter | For flashing the firmware |
| 5V power supply | The CAM board needs solid 5V — USB from a PC works |

> **AliExpress clone note:** The board uses a **GC2145** sensor instead of the OV2640. This sensor has no hardware JPEG encoder, so the firmware captures raw YUV422 and software-encodes it to JPEG before streaming. Everything still works; you don't need to do anything differently.

---

## Project structure

```
esp32_hand_detection/
├── firmware/
│   ├── camera_test/          # Phase 1: diagnostic sketch — identifies chip, sensor, PSRAM
│   └── esp32cam_main/        # Main firmware: WiFi provisioning + MJPEG stream
├── backend/
│   ├── main.py               # FastAPI server — pipeline, MJPEG re-stream, WebSocket
│   ├── detector.py           # MediaPipe Gesture Recognizer (Tasks API)
│   ├── gestures.py           # Time-based debounce / stability layer
│   ├── actions.py            # Gesture → OS media key (pynput)
│   ├── config.py             # Loads config.json with defaults
│   ├── sources/
│   │   ├── webcam.py         # Laptop webcam source
│   │   └── esp32.py          # ESP32-CAM MJPEG source (auto-reconnects)
│   └── requirements.txt
├── frontend/
│   ├── index.html            # Dashboard UI
│   ├── style.css
│   └── app.js                # WebSocket client, toast notifications, history feed
└── config.json               # Source selection, gesture mappings, tuning knobs
```

---

## Setup

### 1. Flash the ESP32

**Install the Arduino library first:**
Arduino IDE → Library Manager → search **WiFiManager** → install "WiFiManager by tzapu"

**Board settings:**
- Board: `AI Thinker ESP32-CAM`
- Partition Scheme: `Huge APP (3MB No OTA/1MB SPIFFS)`
- PSRAM: `Enabled`

Flash `firmware/esp32cam_main/esp32cam_main.ino`.

**First boot — WiFi provisioning:**
1. The ESP32 creates a WiFi network called **`ESP32-CAM-Setup`**
2. Connect your laptop or phone to it
3. A setup page opens automatically (or visit `192.168.4.1`)
4. Enter your home WiFi name and password → Save
5. The ESP32 reboots and joins your network. Note the IP it prints on Serial (115200 baud)

To re-provision later, visit `http://<esp32-ip>/reset-wifi`.

### 2. Python backend

Requires **Python 3.11 or 3.12** (MediaPipe does not support 3.13 yet).

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r backend/requirements.txt
```

MediaPipe model files (~8 MB) are downloaded automatically on first run.

### 3. Configure

Edit `config.json`:

```json
{
  "source": "esp32",
  "esp32": {
    "host": "10.0.0.XXX",
    "stream_path": "/stream",
    "fallback_ip": "10.0.0.XXX"
  }
}
```

Set `"source": "webcam"` to use your laptop camera instead (useful for testing without the hardware).

### 4. Run

```bash
cd backend
python main.py
```

Open **http://localhost:8000** in your browser.

---

## Dashboard

| Element | Description |
|---|---|
| Live feed | Annotated video with hand skeleton overlay |
| Gesture card | Current gesture, large emoji, confidence bar |
| Action toast | Pops up on the video whenever a command fires |
| Recent actions | Last 5 fired commands with timestamps |
| Legend | All gestures — highlights the one currently held |
| Actions toggle | Pause/resume media key output without stopping detection |

---

## Configuration reference

All tunable values live in `config.json`:

```json
{
  "source": "esp32",            // "webcam" or "esp32"
  "webcam_index": 0,            // webcam device index (if source = webcam)

  "esp32": {
    "host": "esp32cam.local",   // mDNS name or IP
    "stream_path": "/stream",
    "fallback_ip": ""           // used if mDNS fails
  },

  "detection": {
    "max_hands": 1,
    "min_detection_confidence": 0.6,
    "min_tracking_confidence": 0.5,
    "min_gesture_confidence": 0.5   // raise for stricter, lower for looser
  },

  "debounce": {
    "stable_time_s": 0.4,       // hold gesture this long before it fires
    "cooldown_s": 1.2,          // wait before the same gesture can fire again
    "repeat_interval_s": 0.5    // how fast volume repeats while held
  },

  "fire_actions": true,         // false = detect only, send no media keys

  "gestures": {
    "open_palm":   "play_pause",
    "thumb_up":    "volume_up",
    "thumb_down":  "volume_down",
    "two_fingers": "next_track",
    "one_finger":  "previous_track"
  }
}
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Firmware | Arduino / ESP-IDF, WiFiManager, ESPmDNS |
| Gesture AI | MediaPipe Gesture Recognizer (Tasks API) |
| Backend | Python, FastAPI, OpenCV, pynput |
| Frontend | Vanilla JS, WebSocket, CSS glassmorphism |
| Transport | MJPEG over HTTP, WebSocket for gesture state |
