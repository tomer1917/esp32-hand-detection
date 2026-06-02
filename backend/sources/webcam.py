"""Laptop webcam source via OpenCV."""
import cv2
from .base import VideoSource


class WebcamSource(VideoSource):
    def __init__(self, index: int = 0):
        # CAP_DSHOW opens far faster than the default MSMF backend on Windows.
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Could not open webcam index {index}. "
                "Is another app using the camera? Try a different webcam_index in config.json."
            )
        # Keep latency low; request a modest resolution.
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self):
        return self.cap.read()

    def release(self):
        if self.cap:
            self.cap.release()
