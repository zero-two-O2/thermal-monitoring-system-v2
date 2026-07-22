"""
camera_model.py

Contains the core data models for the camera subsystem.

These classes only store information.
They do not communicate with camera hardware.
"""

from dataclasses import dataclass
from enum import Enum


class CameraStatus(Enum):
    """
    Current runtime status of a camera.
    """

    OFFLINE = "Offline"
    DISCOVERED = "Discovered"
    CONNECTING = "Connecting"
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    ACQUIRING = "Acquiring"
    STREAMING = "Streaming"
    RUNNING = "Running"
    ERROR = "Error"


@dataclass
class CameraModel:
    """
    Represents one physical thermal camera.

    This class contains only camera metadata.
    No acquisition or processing logic belongs here.
    """

    # ==========================================================
    # Basic Information
    # ==========================================================

    camera_id: str
    camera_name: str
    calibration_file: str | None = None

    # ==========================================================
    # Hardware Information
    # ==========================================================

    vendor: str = ""
    model: str = ""
    serial_number: str = ""

    # ==========================================================
    # Network Information
    # ==========================================================

    ip_address: str = ""
    mac_address: str = ""

    # ==========================================================
    # Discovery Information
    # ==========================================================

    device_identifier: str = ""
    interface_name: str = ""

    # ==========================================================
    # Configuration
    # ==========================================================

    enabled: bool = True

    # ==========================================================
    # Runtime Status
    # ==========================================================

    status: CameraStatus = CameraStatus.OFFLINE

    # ==========================================================
    # Camera Capabilities
    # ==========================================================

    supports_focus: bool = False
    supports_nuc: bool = False
    supports_visible_stream: bool = False

    # ==========================================================
    # Optional Information
    # ==========================================================

    description: str = ""
    location: str = ""

    def is_online(self) -> bool:
        """
        Returns True if the camera is currently available.
        """

        return self.status in (
            CameraStatus.CONNECTED,
            CameraStatus.ACQUIRING,
        )

    def __str__(self) -> str:
        """
        Human-readable representation.
        """

        return (
            f"{self.camera_name} "
            f"({self.model}) "
            f"[{self.serial_number}] "
            f"- {self.status.value}"
        )