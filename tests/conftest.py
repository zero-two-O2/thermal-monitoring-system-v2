"""
Shared fixtures and helpers for the roi_engine test suites.

The roi_engine package uses the real store factory (roi_engine.store.factory).
This file only provides shared test helpers that do not depend on the store
implementation: configuration builders and synthetic image generators.
"""

from __future__ import annotations

import numpy as np

from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import (
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.recording_settings import ROIRecordingSettings


def make_config(
    roi_id: str,
    geometry: CircleROI | EllipseROI | PolygonROI | Rectangle1ROI | Rectangle2ROI,
    enabled: bool = True,
) -> ROIConfiguration:
    """Build an ROIConfiguration with default style/alarm/recording."""
    return ROIConfiguration(
        roi_id=roi_id,
        name=f"roi_{roi_id}",
        acquisition_state=AcquisitionState(camera_id="cam_1", pan=0),
        geometry=geometry,
        enabled=enabled,
        visible=True,
        alarm=ROIAlarmSettings(),
        recording=ROIRecordingSettings(),
    )


def synthetic_image(height: int = 480, width: int = 640) -> np.ndarray:
    """
    Deterministic float32 image: 20.0 base plus a strictly monotone
    gradient in both axes, so every region's maximum is at its
    bottom-right-most pixel.
    """
    rows = np.arange(height, dtype=np.float32)
    cols = np.arange(width, dtype=np.float32)
    return 20.0 + rows[:, None] * 0.05 + cols[None, :] * 0.03
