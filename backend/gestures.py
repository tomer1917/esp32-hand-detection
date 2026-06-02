"""Debounce / stability layer over the per-frame gesture stream.

Classification is done by MediaPipe's trained Gesture Recognizer (see
detector.py). This module turns that noisy per-frame stream into discrete
'fire' events so a held pose doesn't spam a command every frame.

Stability is TIME-based (hold for N seconds), not frame-count based, so it
behaves the same regardless of the frame rate.
"""
import time


class GestureStabilizer:
    """Turns a per-frame gesture stream into discrete 'fire' events.

    - A gesture must be held for `stable_time_s` (and at least `min_frames`
      frames) before it can fire.
    - Single-shot gestures fire once, then require returning to neutral (fist /
      no hand) before the same gesture fires again.
    - Repeatable gestures (e.g. volume) re-fire every `repeat_interval_s` while
      held.
    """

    NEUTRAL = {"fist", "none", "unknown"}

    def __init__(self, stable_time_s=0.4, cooldown_s=1.2, repeat_interval_s=0.5,
                 repeatable=None, min_frames=2):
        self.stable_time_s = stable_time_s
        self.cooldown_s = cooldown_s
        self.repeat_interval_s = repeat_interval_s
        self.repeatable = set(repeatable or [])
        self.min_frames = min_frames

        self.candidate = None
        self.candidate_since = 0.0
        self.count = 0
        self.last_fired = None
        self.last_fire_time = 0.0

    def update(self, gesture):
        """Feed the current frame's gesture. Returns a gesture name to FIRE, or None."""
        now = time.time()

        # Track how long the current gesture has been held
        if gesture == self.candidate:
            self.count += 1
        else:
            self.candidate = gesture
            self.candidate_since = now
            self.count = 1

        # Neutral resets the single-shot latch so a pose can be repeated
        if gesture in self.NEUTRAL:
            self.last_fired = None
            return None

        held = now - self.candidate_since
        if self.count < self.min_frames or held < self.stable_time_s:
            return None

        if gesture in self.repeatable:
            if now - self.last_fire_time >= self.repeat_interval_s:
                self.last_fire_time = now
                return gesture
            return None

        # Single-shot
        if gesture != self.last_fired and (now - self.last_fire_time) >= self.cooldown_s:
            self.last_fired = gesture
            self.last_fire_time = now
            return gesture
        return None
