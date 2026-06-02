const GESTURES = [
  { key: "open_palm",   emoji: "✋", name: "Open palm",   cmd: "Play / Pause" },
  { key: "thumb_up",    emoji: "👍", name: "Thumb up",    cmd: "Volume Up" },
  { key: "thumb_down",  emoji: "👎", name: "Thumb down",  cmd: "Volume Down" },
  { key: "two_fingers", emoji: "✌️", name: "Two fingers", cmd: "Next track" },
  { key: "one_finger",  emoji: "☝️", name: "One finger",  cmd: "Previous" },
];

const GESTURE_EMOJI = {
  open_palm: "✋", thumb_up: "👍", thumb_down: "👎",
  two_fingers: "✌️", one_finger: "☝️", fist: "✊",
  none: "🤚", unknown: "🤚",
};
const GESTURE_NAME = {
  open_palm: "Open palm", thumb_up: "Thumb up", thumb_down: "Thumb down",
  two_fingers: "Two fingers", one_finger: "One finger", fist: "Fist",
  none: "—", unknown: "—",
};
const ACTION_TEXT = {
  play_pause:     "⏯️  Play / Pause",
  next_track:     "⏭️  Next track",
  previous_track: "⏮️  Previous",
  volume_up:      "🔊  Volume Up",
  volume_down:    "🔉  Volume Down",
  mute:           "🔇  Mute",
};

// ── DOM refs ────────────────────────────────────────────────────────────────
const dot          = document.getElementById("dot");
const statusText   = document.getElementById("status-text");
const gestureEmoji = document.getElementById("gesture-emoji");
const gestureName  = document.getElementById("gesture-name");
const gcHint       = document.getElementById("gc-hint");
const gestureCard  = document.getElementById("gesture-card");
const confBar      = document.getElementById("conf-bar");
const toggleBtn    = document.getElementById("toggle");
const toggleLabel  = document.getElementById("toggle-label");
const sourceBadge  = document.getElementById("source-badge");
const fpsBadge     = document.getElementById("fps-badge");
const historyList  = document.getElementById("history-list");
const legendList   = document.getElementById("legend-list");
const toast        = document.getElementById("action-toast");
const toastText    = document.getElementById("toast-text");

// ── Build legend ─────────────────────────────────────────────────────────────
legendList.innerHTML = GESTURES.map(g => `
  <li class="legend-item" data-key="${g.key}">
    <span class="li-emoji">${g.emoji}</span>
    <span class="li-name">${g.name}</span>
    <span class="li-cmd">${g.cmd}</span>
  </li>`).join("");

// ── State ────────────────────────────────────────────────────────────────────
let lastGesture    = null;
let lastActionSeen = null;
let toastTimer     = null;
const MAX_HISTORY  = 5;
const history      = [];

// ── Helpers ──────────────────────────────────────────────────────────────────
function setOnline(on) {
  dot.className = "dot " + (on ? "online" : "offline");
  statusText.textContent = on ? "connected" : "reconnecting…";
}

function setToggle(enabled) {
  toggleBtn.className = "toggle-btn " + (enabled ? "on" : "off");
  toggleLabel.textContent = enabled ? "Actions enabled" : "Actions paused";
}

function showToast(text) {
  toastText.textContent = text;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 1600);
}

function addHistory(action) {
  const text = ACTION_TEXT[action] ?? action;
  const now  = new Date();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  history.unshift({ text, time });
  if (history.length > MAX_HISTORY) history.pop();

  historyList.innerHTML = history.map(h => `
    <li class="history-item">
      <span class="hi-action">${h.text}</span>
      <span class="hi-time">${h.time}</span>
    </li>`).join("");
}

function updateLegendActive(gesture) {
  legendList.querySelectorAll(".legend-item").forEach(el => {
    el.classList.toggle("active", el.dataset.key === gesture);
  });
}

// ── Toggle action ─────────────────────────────────────────────────────────────
toggleBtn.addEventListener("click", async () => {
  const res  = await fetch("/api/toggle_actions", { method: "POST" });
  const data = await res.json();
  setToggle(data.fire_actions);
});

// ── Initial state ─────────────────────────────────────────────────────────────
fetch("/api/state").then(r => r.json()).then(s => {
  sourceBadge.textContent = s.source ?? "—";
  setToggle(s.fire_actions);
}).catch(() => {});

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws    = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen  = () => setOnline(true);
  ws.onclose = () => { setOnline(false); setTimeout(connect, 1500); };
  ws.onerror = () => ws.close();

  ws.onmessage = (ev) => {
    const d = JSON.parse(ev.data);

    // FPS badge
    fpsBadge.textContent = (d.fps ?? 0).toFixed(1) + " fps";

    // Confidence bar
    const score = d.score ?? 0;
    const pct   = (score * 100).toFixed(0);
    confBar.style.width = pct + "%";

    // Gesture display
    if (d.gesture !== lastGesture) {
      const emoji = GESTURE_EMOJI[d.gesture] ?? "🤚";
      const name  = GESTURE_NAME[d.gesture]  ?? d.gesture;
      const hand  = !["none", "unknown"].includes(d.gesture);

      gestureEmoji.textContent = emoji;
      gestureEmoji.classList.remove("pop");
      void gestureEmoji.offsetWidth;
      gestureEmoji.classList.add("pop");

      gestureName.textContent = name;
      gestureCard.classList.toggle("active", hand);
      gcHint.textContent = hand ? `${pct}% confidence` : "show your hand to the camera";

      updateLegendActive(hand ? d.gesture : null);
      lastGesture = d.gesture;
    } else if (!["none","unknown"].includes(d.gesture)) {
      // Update hint with latest confidence even if gesture didn't change
      gcHint.textContent = `${pct}% confidence`;
    }

    // Action fired
    if (d.last_action && d.last_action !== lastActionSeen) {
      const text = ACTION_TEXT[d.last_action] ?? d.last_action;
      showToast(text);
      addHistory(d.last_action);
      lastActionSeen = d.last_action;
    }

    setToggle(d.fire_actions);
  };
}

connect();
