"""
tv46l_camera.py

High-level interface for a Fluke TV46L thermal camera.

This class exposes a simple API to the rest of the application while
delegating hardware access to HalconDriver and frame acquisition to
AcquisitionEngine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from camera.models.camera_model import CameraStatus
from camera.models.camera_model import CameraModel

from camera.services.halcon_driver import HalconDriver
from camera.services.acquisition_engine import AcquisitionEngine

from calibration.calibration_manager import CalibrationManager

from utilities import logger


class TV46LCamera:
    """
    High-level TV46L camera interface.

    Public API

        connect()
        disconnect()

        start()
        stop()

        get_frame()

        perform_nuc()

        focus_near()
        focus_far()
        get_focus_distance()
        get_focus_limits()
        wait_for_focus()

        is_connected()
        is_running()
    """

    FOCUS_STEP_MM = 250

    def __init__(
        self,
        camera_model: CameraModel,
        calibration_manager: CalibrationManager,
    ) -> None:

        self.camera = camera_model

        self.driver = HalconDriver(camera_model)

        self.acquisition = AcquisitionEngine(
            self.driver
        )

        self.calibration = calibration_manager

        self._connected = False

    # ---------------------------------------------------------
    # Connection
    # ---------------------------------------------------------

    def connect(self) -> None:

        if self._connected:

            logger.warning(
                "Camera already connected."
            )
            return

        self.driver.connect()

        self.camera.status = CameraStatus.CONNECTED

        self._connected = True

        logger.info(
            f"{self.camera.camera_id} connected."
        )

    def disconnect(self) -> None:

        if not self._connected:

            return

        self.stop()

        self.driver.disconnect()

        self.camera.status = CameraStatus.DISCONNECTED

        self._connected = False

        logger.info(
            f"{self.camera.camera_id} disconnected."
        )

    # ---------------------------------------------------------
    # Acquisition
    # ---------------------------------------------------------

    def start(self) -> None:

        if not self._connected:

            raise RuntimeError(
                "Camera is not connected."
            )

        self.acquisition.start()

        self.camera.status = CameraStatus.STREAMING

        logger.info(
            f"{self.camera.camera_id} acquisition started."
        )

    def stop(self) -> None:

        if self.acquisition.is_running():

            self.acquisition.stop()

        if self._connected:

            self.camera.status = CameraStatus.CONNECTED

    # ---------------------------------------------------------
    # Frames
    # ---------------------------------------------------------

    def get_frame(
        self,
    ) -> np.ndarray | None:
        """
        Return the most recent raw frame.
        """

        return self.acquisition.get_latest_frame()

    # ---------------------------------------------------------
    # Camera Operations
    # ---------------------------------------------------------

    def perform_nuc(self) -> None:
        """
        Execute manual Non-Uniformity Correction.

        Does NOT stop acquisition or restart streaming.
        Only the selected camera pauses briefly during NUC.
        """

        self.driver.perform_nuc()

    # ---------------------------------------------------------
    # Focus Control
    # ---------------------------------------------------------

    def focus_near(
        self,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus closer by step_mm.

        Returns (requested_mm, actual_mm) after movement completes.
        """

        if step_mm is None:
            step_mm = self.FOCUS_STEP_MM

        current = self.driver.get_focus_distance()
        limits = self.driver.get_focus_limits()
        target = max(current - step_mm, limits[0])

        self.driver.set_focus_distance(target)
        self.driver.wait_for_focus(target)

        actual = self.driver.get_focus_distance()

        return (target, actual)

    def focus_far(
        self,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus farther by step_mm.

        Returns (requested_mm, actual_mm) after movement completes.
        """

        if step_mm is None:
            step_mm = self.FOCUS_STEP_MM

        current = self.driver.get_focus_distance()
        limits = self.driver.get_focus_limits()
        target = min(current + step_mm, limits[1])

        self.driver.set_focus_distance(target)
        self.driver.wait_for_focus(target)

        actual = self.driver.get_focus_distance()

        return (target, actual)

    def get_focus_distance(self) -> float:
        """
        Read current focus distance in mm.
        """

        return self.driver.get_focus_distance()

    def get_focus_limits(self) -> tuple[float, float]:
        """
        Return (min_mm, max_mm) focus limits.
        """

        return self.driver.get_focus_limits()

    def wait_for_focus(
        self,
        target_mm: float,
        tolerance_mm: float = 10,
        timeout: float = 2.0,
    ) -> bool:
        """
        Wait until focus reaches target distance.
        """

        return self.driver.wait_for_focus(
            target_mm,
            tolerance_mm,
            timeout,
        )

    # ---------------------------------------------------------
    # Information
    # ---------------------------------------------------------

    def get_camera_information(self) -> dict:

        return {
            "camera_id": self.camera.camera_id,
            "model": self.camera.model,
            "serial_number": self.camera.serial_number,
            "ip_address": self.camera.ip_address,
            "vendor": self.camera.vendor,
            "connected": self._connected,
        }

    def get_stream_statistics(self) -> dict:

        return self.acquisition.get_statistics()

    # ---------------------------------------------------------
    # Calibration
    # ---------------------------------------------------------

    def get_calibration_manager(
        self,
    ) -> CalibrationManager:

        return self.calibration

    # ---------------------------------------------------------
    # Status
    # ---------------------------------------------------------

    def is_connected(self) -> bool:

        return self._connected

    def is_running(self) -> bool:

        return self.acquisition.is_running()

    # ---------------------------------------------------------
    # Context Manager
    # ---------------------------------------------------------

    def __enter__(self):

        self.connect()

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):

        self.disconnect()
