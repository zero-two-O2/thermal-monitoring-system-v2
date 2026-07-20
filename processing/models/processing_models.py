"""
processing_models.py

Core processing models for the Thermal Monitoring System.

Pipeline

RawFrame
    ↓
ProcessedFrame
    ↓
ROI Results
    ↓
Alarm Results
    ↓
FrameResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from processing.models.roi_models import (
    ROIResult,
)

from processing.models.alarm_models import (
    AlarmResult,
)


# ==========================================================
# Raw Frame
# ==========================================================

@dataclass(slots=True)
class RawFrame:
    """
    Frame received directly from the camera.
    """

    image: np.ndarray

    range_index: int = 0

    timestamp: datetime = field(
        default_factory=datetime.now
    )

    frame_number: int = 0


# ==========================================================
# Processed Frame
# ==========================================================

@dataclass(slots=True)
class ProcessedFrame:
    """
    Frame after calibration.
    """

    raw_frame: RawFrame

    temperature_image: np.ndarray

    display_image: np.ndarray


# ==========================================================
# Camera Statistics
# ==========================================================

@dataclass(slots=True)
class CameraStatistics:
    """
    Statistics for the complete thermal frame.
    """

    minimum: float

    maximum: float

    mean: float

    median: float

    standard_deviation: float


# ==========================================================
# Final Pipeline Result
# ==========================================================

@dataclass(slots=True)
class FrameResult:
    """
    Complete result produced by the processing pipeline.
    """

    raw_frame: RawFrame

    processed_frame: ProcessedFrame

    statistics: CameraStatistics

    roi_results: list[ROIResult] = field(
        default_factory=list
    )

    alarms: list[AlarmResult] = field(
        default_factory=list
    )