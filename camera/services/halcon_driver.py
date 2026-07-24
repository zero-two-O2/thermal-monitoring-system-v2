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

import time
from typing import Any

import halcon as ha
import numpy as np

from camera.models.camera_model import CameraModel

from utilities import logger


class HalconDriver:
    """
    Low-level HALCON interface.

    Every HALCON call in the application should go
    through this class.
    """

    FOCUS_STEP_MM = 250

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

                "progressive",

                -1,

                "default",

                -1,

                "false",

                "default",

                self.camera.device_identifier,

                0,

                -1,

            )

            self._connected = True

            logger.info(
                "Framegrabber opened."
            )

            self._configure_camera()

            ha.grab_image_start(
                self._framegrabber,
                -1,
            )

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

        try:
            self.set_parameter(
                "[Stream]DeviceStreamChannelNegotiatePacketSize",
                1,
            )
        except Exception as exc:
            logger.warning(
                f"Unable to negotiate packet size: {exc}"
            )

        try:
            self.set_parameter(
                "[Stream]GevStreamReceiveSocketSize",
                1048576,
            )
        except Exception as exc:
            logger.warning(
                f"Unable to set socket buffer size: {exc}"
            )

        try:
            self.set_parameter(
                "FLK_TI_ControlFeature_SetFrameRate",
                9,
            )
        except Exception:
            logger.warning(
                "Unable to set frame rate."
            )

        try:
            self.set_parameter(
                "FLK_TI_ControlFeature_REControlCmd",
                (
                    "FLK_TI_ControlFeature_"
                    "REControlCmd_DisableAutomaticFineOffsets"
                ),
            )
        except Exception:
            logger.warning(
                "Unable to disable automatic NUC."
            )

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

    # ==========================================================
    # Frame Grabbing
    # ==========================================================

    def grab_frame(
        self,
    ) -> np.ndarray | None:
        """
        Grab a single frame from the camera.

        Returns a 16-bit numpy array or None on timeout.
        """

        try:

            image = ha.grab_image_async(
                self._framegrabber,
                200,
            )

            return ha.himage_as_numpy_array(
                image
            )

        except Exception:

            logger.exception(
                "Frame grab failed."
            )

            return None

    # ==========================================================
    # NUC
    # ==========================================================

    def perform_nuc(self) -> None:
        """
        Execute manual Non-Uniformity Correction.
        Does not stop acquisition or restart streaming.
        """

        logger.info(
            f"{self.camera.camera_id}: Executing manual NUC."
        )

        self.set_parameter(
            "FLK_TI_ControlFeature_REControlCmd",
            "FLK_TI_ControlFeature_REControlCmd_RequestFineOffset",
        )

        self.set_parameter(
            "FLK_TI_ControlFeature_REControlCmd",
            "FLK_TI_ControlFeature_REControlCmd_ExecuteFineOffset",
        )

        time.sleep(0.05)

        #
        # Flush stale frames after NUC.
        #

        for _ in range(3):
            try:
                ha.grab_image_async(
                    self._framegrabber,
                    0,
                )
            except Exception:
                logger.warning(
                    f"{self.camera.camera_id}: "
                    f"NUC flush grab failed (iteration {_})"
                )

    # ==========================================================
    # Focus Control
    # ==========================================================

    def get_focus_distance(self) -> float:
        """
        Read current focus distance in mm.
        """

        return float(
            self.get_parameter(
                "FLK_TI_ControlFeature_CurrentFocusDistanceMm"
            )
        )

    def set_focus_distance(
        self,
        distance_mm: float,
    ) -> None:

        self.set_parameter(
            "FLK_TI_ControlFeature_SetFocusDistanceMm",
            distance_mm,
        )

    def get_focus_limits(self) -> tuple[float, float]:
        """
        Return (min_mm, max_mm) focus limits.
        """

        return (
            float(
                self.get_parameter(
                    "FLK_TI_ControlFeature_FocusDistanceMm_Min"
                )
            ),
            float(
                self.get_parameter(
                    "FLK_TI_ControlFeature_FocusDistanceMm_Max"
                )
            ),
        )

    def wait_for_focus(
        self,
        target_mm: float,
        tolerance_mm: float = 10,
        timeout: float = 2.0,
    ) -> bool:
        """
        Wait until focus reaches target distance.
        Returns True if target reached within timeout.
        """

        start = time.time()

        while time.time() - start < timeout:

            current = self.get_focus_distance()

            if abs(current - target_mm) <= tolerance_mm:
                return True

            time.sleep(0.02)

        return False

    def focus_busy(self) -> bool:
        """
        Returns True if focus is currently moving.
        """

        a = self.get_focus_distance()

        time.sleep(0.05)

        b = self.get_focus_distance()

        return abs(b - a) > 1.0