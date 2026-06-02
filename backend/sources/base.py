"""Pluggable video source interface.

WebcamSource (Phase 2) and Esp32Source (Phase 4) both implement this, so the
pipeline never needs to know where frames come from.
"""
from abc import ABC, abstractmethod
from typing import Tuple
import numpy as np


class VideoSource(ABC):
    @abstractmethod
    def read(self) -> Tuple[bool, "np.ndarray | None"]:
        """Return (ok, frame_bgr). ok is False if no frame was available."""
        ...

    @abstractmethod
    def release(self) -> None:
        """Release any underlying resources."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
