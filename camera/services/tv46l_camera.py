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

        is_connected()
        is_running()
    """

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

        self.driver.perform_nuc()

    # ---------------------------------------------------------
    # Information
    # ---------------------------------------------------------

    def get_camera_information(self) -> dict:

        return self.driver.get_camera_information()

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

        return self.camera.status == CameraStatus.CONNECTED

    def is_running(self) -> bool:

        return self.camera.status == CameraStatus.RUNNING

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