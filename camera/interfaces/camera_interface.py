"""
camera_interface.py

Defines the contract that every camera implementation
must follow.

Examples
--------
TV46LCamera
FLIRCamera
HikvisionCamera

The rest of the application communicates only through
this interface.
"""

from abc import ABC, abstractmethod

from camera.models import CameraModel
from processing.models import RawFrame


class CameraInterface(ABC):
    """
    Base interface for all camera implementations.
    """

    def __init__(self, camera: CameraModel):
        self.camera = camera

    # ==========================================================
    # Connection
    # ==========================================================

    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to the camera.

        Returns
        -------
        bool
            True if connection succeeds.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Disconnect from the camera.
        """
        pass

    # ==========================================================
    # Acquisition
    # ==========================================================

    @abstractmethod
    def start_acquisition(self) -> bool:
        """
        Start image acquisition.
        """
        pass

    @abstractmethod
    def stop_acquisition(self) -> None:
        """
        Stop image acquisition.
        """
        pass

    @abstractmethod
    def grab_frame(self) -> RawFrame | None:
        """
        Acquire one frame from the camera.

        Returns
        -------
        RawFrame | None
        """
        pass

    # ==========================================================
    # Camera Information
    # ==========================================================

    @abstractmethod
    def get_camera_info(self) -> CameraModel:
        """
        Return updated camera information.
        """
        pass

    # ==========================================================
    # Parameters
    # ==========================================================

    @abstractmethod
    def set_parameter(self, name: str, value) -> bool:
        """
        Set a camera parameter.
        """
        pass

    @abstractmethod
    def get_parameter(self, name: str):
        """
        Read a camera parameter.
        """
        pass

    # ==========================================================
    # Status
    # ==========================================================

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Returns True if the camera is connected.
        """
        pass