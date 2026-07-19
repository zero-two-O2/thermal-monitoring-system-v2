"""
position_model.py

Position model for the Thermal Monitoring System.

A Position represents one inspection point of a camera.

Each position contains:
    - PTZ coordinates
    - Calibration configuration
    - ROI configuration
    - Alarm configuration
    - Recording configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from processing.models.roi_models import ROI


# ==========================================================
# Recording Configuration
# ==========================================================

@dataclass(slots=True)
class RecordingConfiguration:

    enabled: bool = False

    duration_seconds: int = 20

    pre_trigger_seconds: int = 0

    post_trigger_seconds: int = 20

    save_images: bool = False

    save_video: bool = True


# ==========================================================
# Position
# ==========================================================

@dataclass(slots=True)
class PositionModel:
    """
    One monitoring position.

    Example

        Camera 1
            ├── Position 001
            ├── Position 002
            └── Position 003
    """

    #
    # Identity
    #

    position_id: str
    camera_id: str = ""

    name: str

    sequence: int = 0

    enabled: bool = True

    description: str = ""

    #
    # Camera Location
    #

    pan: float = 0.0

    tilt: float = 0.0

    zoom: float = 1.0

    #
    # Calibration
    #

    calibration_range: int = 0

    emissivity: float = 0.95

    background_temperature: float = 20.0

    transmission_coefficient: float = 1.0

    #
    # ROI
    #

    rois: list[ROI] = field(
        default_factory=list
    )

    #
    # Recording
    #

    recording: RecordingConfiguration = field(
        default_factory=RecordingConfiguration
    )

    #
    # User Metadata
    #

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # ======================================================
    # ROI Management
    # ======================================================

    def add_roi(
        self,
        roi: ROI,
    ) -> None:

        self.rois.append(
            roi
        )

    def remove_roi(
        self,
        roi_id: str,
    ) -> None:

        self.rois = [

            roi

            for roi in self.rois

            if roi.roi_id != roi_id

        ]

    def get_roi(
        self,
        roi_id: str,
    ) -> ROI | None:

        for roi in self.rois:

            if roi.roi_id == roi_id:

                return roi

        return None

    def clear_rois(
        self,
    ) -> None:

        self.rois.clear()

    @property
    def roi_count(
        self,
    ) -> int:

        return len(
            self.rois
        )