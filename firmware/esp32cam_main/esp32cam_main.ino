/*
  esp32cam_main.ino — Phase 3

  GC2145 sensor (no hardware JPEG): captures YUV422, software-encodes to JPEG
  via frame2jpg(), serves MJPEG stream at /stream.

  WiFi provisioning via WiFiManager (captive portal — no hardcoded credentials).
  mDNS: reachable at http://esp32cam.local once connected.

  First boot (or after reset): ESP32 creates AP "ESP32-CAM-Setup".
    1. Connect laptop/phone to "ESP32-CAM-Setup"
    2. Browser opens automatically (or visit 192.168.4.1)
    3. Enter your home WiFi name + password
    4. ESP32 reboots, joins your WiFi, advertises esp32cam.local

  To force re-provisioning: visit http://esp32cam.local/reset-wifi
  (or http://<ip>/reset-wifi). If saved creds are simply wrong, the ESP32
  auto-reopens the setup portal on its own.

  Arduino IDE settings:
    Board            : AI Thinker ESP32-CAM
    Partition Scheme : Huge APP (3MB No OTA/1MB SPIFFS)
    PSRAM            : Enabled
    Upload Speed     : 115200

  Required library: WiFiManager by tzapu (install via Library Manager)
*/

#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiManager.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include "img_converters.h"  // for frame2jpg()

// ── Pin map: AI-Thinker ESP32-CAM ────────────────────────────────────────
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

#define MDNS_NAME       "esp32cam"   // reachable at esp32cam.local
#define STREAM_PORT     80
#define JPEG_QUALITY    12           // 0–63, lower = better. 12 is good for QVGA.

WebServer server(STREAM_PORT);

// ── Camera init ───────────────────────────────────────────────────────────

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  // GC2145 has no hardware JPEG — capture YUV422, encode in software below
  config.pixel_format = PIXFORMAT_YUV422;
  config.frame_size   = FRAMESIZE_QVGA;   // 320×240 — fast enough for sw JPEG
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count     = 2;                // double-buffer with PSRAM
  config.grab_mode    = CAMERA_GRAB_LATEST;
  config.fb_location  = CAMERA_FB_IN_PSRAM;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("[camera] init FAILED");
    return false;
  }

  // Tune GC2145: slight brightness/contrast boost helps detection
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 1);
    s->set_contrast(s, 1);
    s->set_saturation(s, 0);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
  }
  Serial.println("[camera] init OK (YUV422 QVGA, software JPEG)");
  return true;
}

// ── MJPEG stream handler ──────────────────────────────────────────────────

void handleStream() {
  WiFiClient client = server.client();

  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=frame");
  client.println("Access-Control-Allow-Origin: *");
  client.println("Cache-Control: no-cache");
  client.println();

  uint8_t* jpegBuf = nullptr;
  size_t   jpegLen = 0;

  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[stream] frame capture failed");
      delay(10);
      continue;
    }

    // Software-encode YUV422 → JPEG (uses PSRAM for the output buffer)
    bool ok = frame2jpg(fb, JPEG_QUALITY, &jpegBuf, &jpegLen);
    esp_camera_fb_return(fb);

    if (!ok || jpegLen == 0) {
      Serial.println("[stream] frame2jpg failed");
      if (jpegBuf) { free(jpegBuf); jpegBuf = nullptr; }
      delay(10);
      continue;
    }

    client.println("--frame");
    client.println("Content-Type: image/jpeg");
    client.print("Content-Length: ");
    client.println(jpegLen);
    client.println();
    client.write(jpegBuf, jpegLen);
    client.println();

    free(jpegBuf);
    jpegBuf = nullptr;

    // ~15 fps cap — gives the backend plenty of time to process
    delay(66);
  }
}

void handleRoot() {
  String ip = WiFi.localIP().toString();
  String html =
    "<!DOCTYPE html><html><head><title>ESP32-CAM</title>"
    "<style>body{font-family:monospace;background:#111;color:#0f0;padding:20px;}"
    "img{max-width:100%;border:2px solid #0f0;}</style></head><body>"
    "<h2>ESP32-CAM (GC2145 / software JPEG)</h2>"
    "<p>Stream: <a href='/stream'>http://" + ip + "/stream</a></p>"
    "<img src='/stream'></body></html>";
  server.send(200, "text/html", html);
}

void handleStatus() {
  String json = "{\"ip\":\"" + WiFi.localIP().toString() +
                "\",\"rssi\":" + WiFi.RSSI() +
                ",\"format\":\"YUV422->JPEG\",\"resolution\":\"QVGA\"}";
  server.send(200, "application/json", json);
}

void handleResetWifi() {
  server.send(200, "text/html",
    "<h2>WiFi credentials cleared.</h2>"
    "<p>Rebooting into the setup portal (ESP32-CAM-Setup)…</p>");
  Serial.println("[wifi] /reset-wifi — wiping credentials and rebooting");
  delay(500);
  WiFiManager wm;
  wm.resetSettings();
  ESP.restart();
}

// ── Setup ─────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(300);

  // Camera must be up before WiFiManager so we know it's healthy
  if (!initCamera()) {
    Serial.println("[setup] camera failed — halting");
    while (true) delay(1000);
  }

  // WiFiManager: connects to saved creds, or opens AP for provisioning
  WiFiManager wm;
  wm.setConfigPortalTimeout(180);  // AP times out after 3 min if no one connects

  Serial.println("[wifi] connecting (or starting setup portal)…");
  if (!wm.autoConnect("ESP32-CAM-Setup")) {
    Serial.println("[wifi] failed / timed out — rebooting");
    ESP.restart();
  }

  Serial.printf("[wifi] connected: %s  RSSI: %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // mDNS — reachable as http://esp32cam.local
  if (MDNS.begin(MDNS_NAME)) {
    MDNS.addService("http", "tcp", STREAM_PORT);
    Serial.printf("[mdns] http://%s.local\n", MDNS_NAME);
  } else {
    Serial.println("[mdns] failed — use IP directly");
  }

  server.on("/",           handleRoot);
  server.on("/stream",     handleStream);
  server.on("/status",     handleStatus);
  server.on("/reset-wifi", handleResetWifi);
  server.begin();
  Serial.printf("[http] stream at http://%s/stream\n",
                WiFi.localIP().toString().c_str());
}

// ── Loop ──────────────────────────────────────────────────────────────────

void loop() {
  server.handleClient();
}
