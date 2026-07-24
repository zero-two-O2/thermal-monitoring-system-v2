"""
roi package.

Region of Interest subsystem for the Thermal Monitoring System.

Architecture follows ROI_Design_Decisions.md.

Layers
------
Layer 1 - ROI Definition (persistent data):
    configuration.py, geometry.py, style.py,
    alarm_settings.py, recording_settings.py, types.py,
    acquisition_state.py

Layer 2 - Runtime ROI Cache (runtime data):
    runtime.py, runtime_cache.py

Layer 3 - ROI Editor (future):
    Not yet implemented.

Conversion:
    geometry_to_hregion.py   (HALCON HRegion generation)

Interfaces:
    interfaces.py

Dependencies
------------
- Depends on: standard library.
- Does NOT depend on: HALCON, GUI, processing pipeline.
- Used by: processing pipeline, GUI (future), persistence (future).
"""

from __future__ import annotations

from roi.types import ROIShape
from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
    BoundingBox,
)
from roi.style import ROIStyle
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.recording_settings import ROIRecordingSettings
from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.runtime_cache import RuntimeROICache
from roi.runtime import RuntimeROIState, RuntimeROIStatistics, RuntimeROI
from roi.interfaces import ROIRepository, ROIManager, RuntimeROIManager
from roi.geometry_to_hregion import geometry_to_hregion

__all__ = [
    # Types
    "ROIShape",
    # Geometry
    "ROIGeometry",
    "Rectangle1ROI",
    "Rectangle2ROI",
    "CircleROI",
    "EllipseROI",
    "PolygonROI",
    "BoundingBox",
    # Style
    "ROIStyle",
    # Alarm
    "ROIAlarmCondition",
    "ROIAlarmSettings",
    # Recording
    "ROIRecordingSettings",
    # Acquisition State
    "AcquisitionState",
    # Configuration
    "ROIConfiguration",
    # Runtime
    "RuntimeROICache",
    "RuntimeROIState",
    "RuntimeROIStatistics",
    "RuntimeROI",
    # Conversion
    "geometry_to_hregion",
    # Interfaces
    "ROIRepository",
    "ROIManager",
    "RuntimeROIManager",
]
