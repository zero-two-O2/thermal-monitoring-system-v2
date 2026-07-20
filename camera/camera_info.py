"""
camera_info.py

Camera information model for the Thermal Monitoring System.

This class contains static information discovered from a TV46L camera.
It is passed to TV46LCamera during construction.

Runtime data (frame count, FPS, connection state, etc.) belongs to
TV46LCamera, not here.
"""

from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)

class CameraInfo:

    device: str
    serial: str
    model: str
    vendor: str
    ip: str
    firmware: str = ""
    user_name: str = ""

    # Database
    # Database Configuration
    camera_id: int | None = None
    gui_tile: int | None = None
    friendly_name: str = ""
    location: str = ""
    expected_ip: str = ""
    enabled: bool = True
    description: str = ""