"""
frame_source.py

Frame providers for the validation scenarios.

CameraFrameSource
    Reads the latest raw frame from a connected TV46LCamera and converts
    it to a float32 temperature image via CalibrationManager. Used for
    real-camera validation (Object 1/6/8).

SimulatedFrameSource
    Generates deterministic float32 temperature scenes so every scenario
    can also run without hardware. Scenes contain hot spots and gradients
    that exercise hotspot detection and ROI statistics.
"""

from __future__ import annotations

import time

import numpy as np

# Seed camera.models before camera.services: their import order is
# order-dependent (camera_context <-> tv46l_camera cycle) and the app
# relies on entering camera.models first.
import camera.models  # noqa: E402, F401
from camera.services.tv46l_camera import TV46LCamera
from calibration.calibration_manager import CalibrationManager
from utilities import logger

BASE_TEMPERATURE = 20.0
DEFAULT_SCENE = (320, 256)


class CameraFrameSource:
    """Pulls latest frames from a real camera."""

    def __init__(self, camera: TV46LCamera, calibration: CalibrationManager) -> None:
        self._camera = camera
        self._calibration = calibration
        self._last_frame_number = 0
        self._first = True

    def next_frame(self) -> tuple[np.ndarray, int] | None:
        """Return (temperature_image, frame_number) or None if no new frame.

        Detects frame skips between acquisitions and reports them via
        `last_dropped` so the harness can count dropped frames.
        """
        raw = self._camera.get_frame()
        if raw is None:
            return None
        temperature = self._calibration.raw_to_temperature(raw)
        return temperature, 0

    def close(self) -> None:
        """No-op; the rig owns camera lifetime."""


class SimulatedFrameSource:
    """Deterministic synthetic temperature frames (float32, °C)."""

    def __init__(
        self,
        shape: tuple[int, int] = DEFAULT_SCENE,
        spots: int = 4,
    ) -> None:
        self._shape = shape
        self._spots = spots
        self._frame_number = 0
        self._t0 = time.time()

    @property
    def shape(self) -> tuple[int, int]:
        """Height and width of generated frames."""
        return self._shape

    def next_frame(self) -> tuple[np.ndarray, int]:
        """Generate the next frame: gradient + drifting hot spots."""
        h, w = self._shape
        rows = np.arange(h, dtype=np.float32).reshape(-1, 1)
        cols = np.arange(w, dtype=np.float32).reshape(1, -1)
        frame = BASE_TEMPERATURE + rows * 0.05 + cols * 0.03

        rng = np.random.default_rng(seed=42 + self._frame_number % 7)
        for s in range(self._spots):
            cx = int((s + 1) * w / (self._spots + 1))
            cy = int((s + 1) * h / (self._spots + 1))
            dx = (cols - cx) ** 2
            dy = (rows - cy) ** 2
            radius = w * 0.08
            spot = np.exp(-(dx + dy) / (radius ** 2)) * (70.0 + (s % 3) * 15.0)
            frame += spot.astype(np.float32)

        frame += (rng.standard_normal(h * w).reshape(h, w) * 0.05).astype(np.float32)
        self._frame_number += 1
        return frame, self._frame_number

    def close(self) -> None:
        """No-op."""
