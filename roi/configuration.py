"""
configuration.py

ROI configuration (persistent) for the Thermal Monitoring System.

ROIConfiguration is the persistent definition of one Region of Interest.
It is serialized to JSON and stored in the project/camera/position hierarchy.

This is Layer 1 of the ROI subsystem.

This class contains ONLY plain data.
No HALCON handles, no GUI code, no processing logic.

Boundary rule
-------------
ROIConfiguration must NEVER contain:
    - cached_region (belongs in RuntimeROICache)
    - statistics (belongs in RuntimeROIStatistics)
    - drawing_object (belongs in ROI Editor)
    - runtime_state (belongs in RuntimeROI)
    - alarm_since (belongs in RuntimeROIStatistics)
    - processing_time (belongs in RuntimeROIStatistics)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roi.acquisition_state import AcquisitionState
from roi.geometry import Rectangle1ROI, Rectangle2ROI, CircleROI, EllipseROI, PolygonROI
from roi.style import ROIStyle
from roi.alarm_settings import ROIAlarmSettings
from roi.recording_settings import ROIRecordingSettings


@dataclass(slots=True)
class ROIConfiguration:
    """
    Persistent definition of one Region of Interest.

    This is Layer 1 of the ROI subsystem (ROI Definition).
    It is stored in JSON and loaded when a position becomes active.

    Responsibilities
    ----------------
    - Uniquely identify an ROI within a camera and acquisition state.
    - Store geometric shape and parameters.
    - Store display style preferences.
    - Store alarm threshold configuration.
    - Store recording configuration.
    - Store metadata for extensibility.

    Must never:
    - Contain HALCON handles (Drawing Objects, HRegion, HWindow).
    - Contain GUI widgets or references.
    - Evaluate alarm conditions.
    - Generate regions or statistics.
    - Track runtime state (timestamps, statistics, alarms).
    - Reference other ROIs or positions directly.
    - Store cached or derived runtime data.

    Ownership
    ---------
    - Owns its geometry, style, alarm, and recording settings.
    - Belongs to exactly one camera acquisition state.

    Notes
    -----
    - geometry must be one of: Rectangle1ROI, Rectangle2ROI,
      CircleROI, EllipseROI, PolygonROI.
    - shape is derived from the geometry instance at runtime.
    - acquisition_state replaces the old position_id field and
      is more future-proof (supports pan/tilt/zoom/focus).
    """

    roi_id: str

    name: str

    acquisition_state: AcquisitionState

    geometry: Rectangle1ROI | Rectangle2ROI | CircleROI | EllipseROI | PolygonROI

    style: ROIStyle = field(default_factory=ROIStyle)

    alarm: ROIAlarmSettings = field(default_factory=ROIAlarmSettings)

    recording: ROIRecordingSettings = field(default_factory=ROIRecordingSettings)

    enabled: bool = True

    visible: bool = True

    description: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------
    # Convenience accessors (derived, no stored state)
    # ----------------------------------------------------------

    @property
    def camera_id(self) -> str:
        """Camera identifier from the acquisition state."""
        return self.acquisition_state.camera_id

    @property
    def position_id(self) -> str:
        """Position identifier from the acquisition state."""
        return self.acquisition_state.position_id
