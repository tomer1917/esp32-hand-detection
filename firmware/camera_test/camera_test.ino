/*
  camera_test.ino — Phase 1 diagnostic

  Reports: chip model, PSRAM, camera sensor ID
  Tests every format × resolution combo and prints results
  Serves the first working combo at /test (JPEG frame) and /stream (MJPEG)

  Wiring for AI-Thinker ESP32-CAM flash mode:
    GPIO0 → GND (before powering on), remove after flash, press RST to run
*/

#include "esp_camera.h"
#include "esp_chip_info.h"
#include <WiFi.h>
#include <WebServer.h>

// ── WiFi — only for serving the test page. Replace with your network. ──────
// After Phase 1 these will be replaced by WiFiManager.
const char* WIFI_SSID     = "dorm-wifi-615";
const char* WIFI_PASSWORD = "dorm-wifi";
// ──────────────────────────────────────────────────────────────────────────

// AI-Thinker ESP32-CAM pin map (most common AliExpress board)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);

// Working config discovered by the test
pixformat_t   workingFormat     = PIXFORMAT_JPEG;
framesize_t   workingFramesize  = FRAMESIZE_QVGA;
bool          foundWorkingCombo = false;

// ── Hardware report ────────────────────────────────────────────────────────

void reportHardware() {
  Serial.println("\n========== ESP32 HARDWARE REPORT ==========");

  esp_chip_info_t chip;
  esp_chip_info(&chip);
  Serial.printf("Chip model   : %s\n", ESP.getChipModel());
  Serial.printf("Chip revision: %d\n", chip.revision);
  Serial.printf("CPU cores    : %d\n", chip.cores);
  Serial.printf("Flash size   : %d MB\n", ESP.getFlashChipSize() / (1024 * 1024));

  Serial.println();
  bool psramPresent = psramFound();
  Serial.printf("PSRAM found  : %s\n", psramPresent ? "YES" : "NO");
  if (psramPresent) {
    size_t total = ESP.getPsramSize();
    size_t free_ = ESP.getFreePsram();
    Serial.printf("PSRAM total  : %u bytes (%.1f MB)\n", total, total / 1048576.0f);
    Serial.printf("PSRAM free   : %u bytes\n", free_);
    if (total < 100000) {
      Serial.println(">>> WARNING: PSRAM reported but suspiciously small — may be fake/broken");
    }
  } else {
    Serial.println(">>> Without PSRAM: JPEG is limited to QQVGA/QVGA; larger sizes will fail");
  }
  Serial.println("===========================================\n");
}

// ── Camera init + sensor report ───────────────────────────────────────────

bool initCamera(pixformat_t fmt, framesize_t size) {
  // Free any previous session
  esp_camera_deinit();
  delay(100);

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
  config.pixel_format = fmt;
  config.frame_size   = size;
  config.jpeg_quality = 12;   // 0–63, lower = better quality
  config.fb_count     = psramFound() ? 2 : 1;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location  = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  return (esp_camera_init(&config) == ESP_OK);
}

void reportSensor() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) { Serial.println("Could not get sensor handle"); return; }
  Serial.println("---------- Camera Sensor ----------");
  Serial.printf("Sensor PID   : 0x%04X\n", s->id.PID);
  switch (s->id.PID) {
    case 0x2640: Serial.println("Sensor type  : OV2640 (genuine)"); break;
    case 0x2660: Serial.println("Sensor type  : OV2660"); break;
    case 0x7740: Serial.println("Sensor type  : OV7740"); break;
    case 0x7725: Serial.println("Sensor type  : OV7725"); break;
    default:     Serial.printf ("Sensor type  : Unknown (PID 0x%04X)\n", s->id.PID); break;
  }
  Serial.printf("Sensor MID   : 0x%02X%02X\n", s->id.MIDH, s->id.MIDL);
  Serial.println("-----------------------------------\n");
}

// ── Format × resolution test matrix ──────────────────────────────────────

struct FormatInfo  { pixformat_t fmt; const char* name; };
struct FrameInfo   { framesize_t size; const char* name; };

const FormatInfo formats[] = {
  { PIXFORMAT_JPEG,      "JPEG"      },
  { PIXFORMAT_RGB565,    "RGB565"    },
  { PIXFORMAT_YUV422,    "YUV422"    },
  { PIXFORMAT_GRAYSCALE, "GRAYSCALE" },
};

const FrameInfo framesizes[] = {
  { FRAMESIZE_QQVGA, "QQVGA 160×120"  },
  { FRAMESIZE_QVGA,  "QVGA  320×240"  },
  { FRAMESIZE_CIF,   "CIF   400×296"  },
  { FRAMESIZE_HVGA,  "HVGA  480×320"  },
  { FRAMESIZE_VGA,   "VGA   640×480"  },
};

void runFormatTest() {
  Serial.println("===== FORMAT × RESOLUTION MATRIX =====");
  Serial.println("Format       | Resolution      | Result");
  Serial.println("-------------|-----------------|-------");

  for (auto& f : formats) {
    for (auto& fs : framesizes) {
      bool ok = initCamera(f.fmt, fs.size);
      if (ok) {
        // Try to actually capture a frame — init succeeding isn't enough
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb && fb->len > 0) {
          Serial.printf("%-12s | %-15s | OK (%u bytes)\n", f.name, fs.name, fb->len);
          if (!foundWorkingCombo) {
            workingFormat    = f.fmt;
            workingFramesize = fs.size;
            foundWorkingCombo = true;
            Serial.println("  ^^^ First working combo — will serve this one ^^^");
          }
          esp_camera_fb_return(fb);
        } else {
          Serial.printf("%-12s | %-15s | INIT OK but capture failed\n", f.name, fs.name);
          if (fb) esp_camera_fb_return(fb);
        }
      } else {
        Serial.printf("%-12s | %-15s | FAILED\n", f.name, fs.name);
      }
      delay(200);
    }
  }
  Serial.println("=======================================\n");
}

// ── HTTP handlers ─────────────────────────────────────────────────────────

void handleTest() {
  if (!foundWorkingCombo) {
    server.send(503, "text/plain", "No working camera format found. Check Serial output.");
    return;
  }
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { server.send(500, "text/plain", "Frame capture failed"); return; }

  if (workingFormat == PIXFORMAT_JPEG) {
    server.sendHeader("Content-Type", "image/jpeg");
    server.sendHeader("Content-Disposition", "inline");
    server.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
  } else {
    // For raw formats, wrap in a minimal BMP so browser can display it
    server.send(200, "text/plain",
      "Raw frame captured OK (" + String(fb->len) + " bytes). "
      "Format is not JPEG — see Serial output for details.");
  }
  esp_camera_fb_return(fb);
}

void handleStream() {
  if (!foundWorkingCombo || workingFormat != PIXFORMAT_JPEG) {
    server.send(503, "text/plain",
      "MJPEG stream only available when JPEG format works. Check /test.");
    return;
  }

  WiFiClient client = server.client();
  String boundary = "frame";
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=" + boundary);
  client.println("Access-Control-Allow-Origin: *");
  client.println();

  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) break;

    client.println("--" + boundary);
    client.println("Content-Type: image/jpeg");
    client.println("Content-Length: " + String(fb->len));
    client.println();
    client.write(fb->buf, fb->len);
    client.println();
    esp_camera_fb_return(fb);

    delay(33); // ~30 fps cap
  }
}

void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html><html><head><title>ESP32-CAM Test</title>
<style>body{font-family:monospace;background:#111;color:#0f0;padding:20px;}
img{max-width:100%;border:2px solid #0f0;display:block;margin:20px 0;}
a{color:#0f0;}</style></head><body>
<h2>ESP32-CAM Diagnostic</h2>
<p>Check Serial Monitor for the full hardware + format matrix report.</p>
<h3>Single Frame</h3>
<img src="/test" alt="test frame"><br>
<h3>Live Stream (JPEG only)</h3>
<img src="/stream" alt="live stream">
<p><a href="/test">Raw /test endpoint</a> | <a href="/stream">Raw /stream endpoint</a></p>
</body></html>
)rawliteral";
  server.send(200, "text/html", html);
}

// ── Setup & loop ──────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(500);

  reportHardware();
  runFormatTest();

  if (foundWorkingCombo) {
    // Re-init with the best working combo before serving
    initCamera(workingFormat, workingFramesize);
    reportSensor();
  } else {
    Serial.println("!!! NO WORKING FORMAT FOUND !!!");
    Serial.println("Possible causes:");
    Serial.println("  1. Wrong pin map — are you using AI-Thinker board?");
    Serial.println("  2. Power issue — ESP32-CAM needs solid 5V, not 3.3V");
    Serial.println("  3. Broken/fake camera module");
    Serial.println("Not starting WiFi.");
    return;
  }

  // Connect WiFi
  Serial.printf("Connecting to WiFi: %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nConnected! IP: http://%s\n", WiFi.localIP().toString().c_str());
    Serial.printf("  Single frame : http://%s/test\n", WiFi.localIP().toString().c_str());
    Serial.printf("  MJPEG stream : http://%s/stream\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWiFi failed — serving not available. Check SSID/password.");
    Serial.println("The Serial format matrix above is still valid.");
  }

  server.on("/",       handleRoot);
  server.on("/test",   handleTest);
  server.on("/stream", handleStream);
  server.begin();
}

void loop() {
  server.handleClient();
}
