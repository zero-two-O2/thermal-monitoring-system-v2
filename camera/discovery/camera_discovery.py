"""
camera_discovery.py

Discovers TV46L thermal cameras available on the network.
"""

from typing import List

from camera.models import CameraModel
from utilities import logger


class CameraDiscovery:
    """
    Discovers available TV46L cameras.
    """

    def __init__(self):

        self._cameras: List[CameraModel] = []

    # ==========================================================
    # Public
    # ==========================================================

    def discover(self) -> List[CameraModel]:
        """
        Discover all available cameras.

        Returns
        -------
        List[CameraModel]
        """

        logger.info("Searching for TV46L cameras...")

        self._cameras.clear()

        #
        # Discovery implementation will be added later.
        #
        # Possible methods:
        #   - GigE Vision Discovery
        #   - HTTP Scan
        #   - SDK Discovery
        #

        logger.info(f"Discovered {len(self._cameras)} camera(s).")

        return self._cameras

    # ==========================================================
    # Helpers
    # ==========================================================

    def add_camera(self, camera: CameraModel):

        self._cameras.append(camera)

    def clear(self):

        self._cameras.clear()

    def camera_count(self) -> int:

        return len(self._cameras)