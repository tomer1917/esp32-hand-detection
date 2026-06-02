"""Maps action names to OS media commands via global media keys (pynput).

On Windows these are the VK_MEDIA_* virtual keys — they control whatever app
is currently playing (Spotify, YouTube in a browser, etc.), system-wide.
"""
from pynput.keyboard import Controller, Key


class MediaController:
    KEYMAP = {
        "play_pause": Key.media_play_pause,
        "next_track": Key.media_next,
        "previous_track": Key.media_previous,
        "volume_up": Key.media_volume_up,
        "volume_down": Key.media_volume_down,
        "mute": Key.media_volume_mute,
    }

    def __init__(self, enabled=True):
        self.kb = Controller()
        self.enabled = enabled

    def fire(self, action: str) -> bool:
        """Send the media key for `action`. Returns True if a key was sent."""
        key = self.KEYMAP.get(action)
        if key is None:
            print(f"[actions] unknown action: {action!r}")
            return False
        if not self.enabled:
            return False
        self.kb.press(key)
        self.kb.release(key)
        return True
