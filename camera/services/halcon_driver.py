"""
halcon_driver.py

Low-level HALCON driver for the Fluke TV46L camera.

Responsibilities
----------------
- Open/close camera
- Configure acquisition
- Grab raw frames
- Execute camera commands
- Read camera parameters

No threading or image processing is performed here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import halcon as ha

from camera.models.camera_model import CameraModel

from utilities import logger


class HalconDriver:
    """
    Low-level HALCON interface.

    Every HALCON call in the application should go
    through this class.
    """

    def __init__(
        self,
        camera: CameraModel,
    ) -> None:

        self.camera = camera

        self._framegrabber = None

        self._connected = False

    # ==========================================================
    # Connection
    # ==========================================================

    def connect(self) -> None:
        """
        Open the GigE Vision camera.
        """

        if self._connected:
            return

        logger.info(
            f"Opening camera {self.camera.camera_id}"
        )

        try:

            #
            # Open Framegrabber
            #

            self._framegrabber = ha.open_framegrabber(

                "GigEVision2",

                0,
                0,
                0,
                0,
                0,
                0,

                "default",

                -1,

                "default",

                -1,

                "false",

                self.camera.ip_address,

                0,

                -1,

            )

            self._connected = True

            logger.info(
                "Framegrabber opened."
            )

            self._configure_camera()

        except Exception:

            logger.exception(
                "Unable to connect camera."
            )

            raise

    def disconnect(self) -> None:
        """
        Close framegrabber.
        """

        if not self._connected:
            return

        try:

            ha.close_framegrabber(
                self._framegrabber
            )

        finally:

            self._framegrabber = None

            self._connected = False

            logger.info(
                "Camera disconnected."
            )

    # ==========================================================
    # Camera Configuration
    # ==========================================================

    def _configure_camera(self) -> None:
        """
        Configure TV46L acquisition parameters.
        """

        logger.info(
            "Configuring camera..."
        )

        self.set_parameter(
            "FLK_TI_StreamDataSourceSelector",
            "IR_Data",
        )

        self.set_parameter(
            "bits_per_channel",
            16,
        )

        #
        # Additional parameters can be added
        # here as required.
        #

        logger.info(
            "Camera configuration complete."
        )

    # ==========================================================
    # Parameters
    # ==========================================================

    def set_parameter(
        self,
        name: str,
        value: Any,
    ) -> None:
        """
        Set a camera parameter.
        """

        ha.set_framegrabber_param(

            self._framegrabber,

            name,

            value,

        )

    def get_parameter(
        self,
        name: str,
    ) -> Any:
        """
        Read a camera parameter.
        """

        return ha.get_framegrabber_param(

            self._framegrabber,

            name,

        )

    # ==========================================================
    # Status
    # ==========================================================

    def is_connected(self) -> bool:

        return self._connected