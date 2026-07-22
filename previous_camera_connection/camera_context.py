"""
camera_context.py

Stores all runtime information for one thermal camera.

Author : Shubham
"""

from dataclasses import dataclass, field

import numpy as np

from live_camera import LiveCamera


@dataclass
class CameraContext:
    """
    Runtime information for one camera.
    """
    camera: LiveCamera
    window_name: str
    lut: np.ndarray
    raw: np.ndarray | None = None
    temperature: np.ndarray | None = None
    display: np.ndarray | None = None
    min_temp: float = 0.0
    max_temp: float = 0.0
    avg_temp: float = 0.0
    center_temp: float = 0.0
    mouse_x: int = 0
    mouse_y: int = 0
    mouse_temp: float = 0.0
    frame_count: int = 0
    fps: float = 0.0
    frame_number: int = 0
    palette: str = "JET"
    recording: bool = False
    is_connected: bool = True
    def next_frame(self):

        self.frame_count += 1