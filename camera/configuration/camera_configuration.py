"""
camera_configuration.py

Logical camera configuration.

Unlike CameraInfo, which contains information discovered directly from
the hardware, CameraConfiguration contains user-defined information
stored in the application's database.

The serial number is used to associate a physical camera with its
logical configuration.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(slots=True)
class CameraConfiguration:
    """
    Logical configuration for one camera.
    """
    # Database identity
    camera_id: int
    # Hardware identity
    serial_number: str
    # GUI
    gui_tile: int
    friendly_name: str
    location: str
    # Network
    expected_ip: str
    # Enable / Disable
    enabled: bool = True
    # Optional
    description: str = ""