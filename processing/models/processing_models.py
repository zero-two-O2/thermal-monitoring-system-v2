"""
processing_models.py

Core data models used by the processing subsystem.

Pipeline

Camera
    │
    ▼
RawFrame
    │
    ▼
ProcessedFrame
    │
    ▼
FrameResult

These classes are data containers only.
No image processing logic belongs here.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


# ==========================================================
# Raw Frame
# ==========================================================

@dataclass(slots=True)
class RawFrame:
    """
    Raw image received directly from the camera.
    """

    camera_id: str

    frame_number: int

    timestamp: datetime

    image: Any

    width: int

    height: int

    pixel_format: str = "Mono16"


# ==========================================================
# Processed Frame
# ==========================================================

@dataclass(slots=True)
class ProcessedFrame:
    """
    Image after the processing pipeline.

    Contains processed data only.
    No ROI or alarm information.
    """

    raw_frame: RawFrame

    thermal_image: Optional[Any] = None

    visible_image: Optional[Any] = None

    display_image: Optional[Any] = None

    temperature_matrix: Optional[Any] = None

    min_temperature: Optional[float] = None

    max_temperature: Optional[float] = None

    average_temperature: Optional[float] = None


# ==========================================================
# Camera Statistics
# ==========================================================

@dataclass(slots=True)
class CameraStatistics:
    """
    Runtime statistics for one camera.
    """

    fps: float = 0.0

    dropped_frames: int = 0

    acquisition_time_ms: float = 0.0

    processing_time_ms: float = 0.0

    total_time_ms: float = 0.0

    uptime_seconds: float = 0.0


# ==========================================================
# Final Processing Result
# ==========================================================

@dataclass(slots=True)
class FrameResult:
    """
    Final output of the processing pipeline.

    Shared with:
        - GUI
        - Alarm Engine
        - Recorder
        - Database
    """

    processed_frame: ProcessedFrame

    roi_results: List[Any] = field(default_factory=list)

    alarms: List[Any] = field(default_factory=list)

    statistics: Optional[CameraStatistics] = None