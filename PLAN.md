# ESP32 Hand Detection — Project Plan

## Goal
Scan live footage from an ESP32 camera, detect hand gestures, and convert them into media commands (play/pause, skip, volume). Later: control iPhone media via BLE.

## Target Audience
Personal use — laptop first, iPhone later.

## Key Architecture Decisions

- **Backend is the sole MJPEG consumer** from the ESP32. Browser never connects to ESP32 directly (ESP32-CAM chokes on 2 clients).
- **Pluggable video source**: `WebcamSource` now → `Esp32Source` after hardware is confirmed. Lets the full pipeline be built and tested without hardware.
- **WiFi provisioning via WiFiManager** (AP captive portal): ESP32 boots as AP if no creds saved, user provisions from any browser, creds saved to NVS flash.
- **mDNS auto-discovery**: ESP32 advertises as `esp32cam.local` — no hardcoded IP.
- **iPhone media control = BLE-HID bridge**: iOS doesn't allow remote media control over network. The only working path is a Bluetooth HID device emitting consumer media keys (play/pause, next, vol). Detection runs on laptop → command goes to BLE bridge ESP32 → Bluetooth to iPhone.
- **Gesture debounce**: pose stable ~0.5s / ~8 frames → fire once → ~1.5s cooldown → must return to neutral before re-fire. Prevents command spam.
- **Media keys via `pynput`** (not pyautogui) for reliable Windows media control.
- **Gesture classification = MediaPipe's pre-trained Gesture Recognizer** (Tasks API), NOT hand-rolled landmark geometry. Hand-rolled heuristics had terrible accuracy (assumed upright hand, broke on rotation). The trained model's canned labels (Open_Palm, Thumb_Up/Down, Victory, Pointing_Up, Closed_Fist) map 1:1 to our gestures. Note: MediaPipe 0.10.35 removed the legacy `mp.solutions` API — must use Tasks API + downloaded `.task` model. Phase 7 custom gestures → MediaPipe Model Maker.

## Phased Workplan

| Phase | Goal | Done when… |
|---|---|---|
| **0** | Toolchain setup | IDE flashes blink; Python venv imports mediapipe |
| **1** | Camera diagnostic | Serial prints chip/PSRAM verdict; frame visible in browser → **DECISION POINT** |
| **2** | Webcam → gestures → laptop media | Open palm pauses Spotify on laptop, reliably, no spam |
| **3** | ESP32 firmware: WiFiManager + MJPEG + mDNS | Phone provisions WiFi via web form; stream at `esp32cam.local` |
| **4** | Swap ESP32 in as video source | Same pipeline as Phase 2, now fed by ESP32 (auto-discovered) |
| **5** | UI polish (laptop browser) | Annotated feed, live gesture label, connection status, nice styling |
| **6** | iPhone media control via BLE-HID bridge | Gesture pauses music on iPhone via BLE bridge |
| **7** (future) | Custom gestures + mappings | Record new pose in UI, assign command, persisted to SQLite |

## Phase 1 Detail — Camera Diagnostic

Reports via Serial:
- `ESP.getChipModel()`
- Camera sensor PID (OV2640 vs clone)
- `psramFound()` + actual allocation test
- Format × resolution matrix: JPEG/RGB565/YUV422/GRAYSCALE × QQVGA→VGA

First working combo served at `/test` (single frame) and `/stream` (MJPEG).
Output of this phase decides: format/resolution for Phase 3, and BLE bridge hardware for Phase 6.

## Starter Gestures (Static Poses)

| Pose | Command |
|---|---|
| ✋ Open palm (5 fingers) | Play / Pause |
| 👍 Thumb up | Volume Up |
| 👎 Thumb down | Volume Down |
| ✌️ Two fingers (V) | Next track |
| ☝️ One finger | Previous track |
| ✊ Fist / no hand | Neutral (resets debounce) |

Static poses only for MVP (single-frame classification). Swipes are Phase 7.

## File Structure

```
esp32_hand_detection/
├── firmware/
│   ├── camera_test/          camera_test.ino      ← Phase 1
│   ├── esp32cam_main/        esp32cam_main.ino    ← Phase 3
│   └── ble_bridge/           ble_bridge.ino       ← Phase 6
├── backend/
│   ├── main.py               # FastAPI: UI + /video + /ws
│   ├── sources/
│   │   ├── base.py
│   │   ├── webcam.py
│   │   └── esp32.py
│   ├── detector.py           # MediaPipe → landmarks + overlay
│   ├── gestures.py           # landmarks → gesture + debounce
│   ├── actions.py            # gesture → media command
│   ├── discovery.py          # zeroconf mDNS discovery
│   ├── config.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── config.json
└── PLAN.md
```

## Open Decision Points

1. ~~After Phase 1: exact resolution/format/fps~~ → **RESOLVED**: YUV422 @ QVGA → software JPEG (`frame2jpg`) → MJPEG. Fallback: raw YUV422 over WebSocket, encode in Python.
2. After Phase 1: BLE bridge hardware for Phase 6 — chip is ESP32-D0WD (classic, supports BLE HID). Recommend a 2nd cheap ESP32/ESP32-C3 as dedicated bridge so streaming + BLE don't compete. Finalize at Phase 6.
3. Phase 2: confirm/adjust gesture↔command map

## Tech Stack

- **Arduino IDE 2.x** + esp32 by Espressif core
- **Libraries**: WiFiManager (tzapu), ESP32-BLE-Keyboard (T-vK)
- **Python 3.11/3.12** in a venv
- **Packages**: opencv-python, mediapipe, fastapi, uvicorn[standard], pynput, zeroconf, httpx, numpy
- **Board settings**: Partition = "Huge APP (3MB No OTA)", PSRAM = Enabled

## Hardware Notes (CONFIRMED via Phase 1 diagnostic)

- **Chip**: ESP32-D0WD, rev 1.00, 2 cores, 4MB flash
- **PSRAM**: genuine & healthy — real 4MB, fully allocates. NOT the problem.
- **Camera sensor**: **GC2145** (PID 0x2145), NOT the OV2640 a genuine AI-Thinker ships.
  - GC2145 has **no hardware JPEG encoder** → `PIXFORMAT_JPEG` fails. THIS is the historical "image format" problem.
  - All raw formats (RGB565, YUV422, GRAYSCALE) work at all resolutions QQVGA→VGA.
  - **Workaround**: capture YUV422, software-encode to JPEG with `frame2jpg()`, serve MJPEG.
- WiFi provisioning resets: hold reset button or send serial command to wipe NVS creds and re-enter AP mode
- Harmless during diagnostic: repeated `gpio_install_isr_service already installed` errors come from re-init in the test loop; real firmware inits once.
