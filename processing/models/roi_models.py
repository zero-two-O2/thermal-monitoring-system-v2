"""
roi_models.py

ROI (Region of Interest) models.

Shared by:
    - ROI Processor
    - Alarm Processor
    - GUI
    - Database
    - Configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np


# ==========================================================
# ROI Type
# ==========================================================

class ROIType(Enum):
    """Supported ROI shapes."""

    RECTANGLE = auto()
    POLYGON = auto()
    CIRCLE = auto()


# ==========================================================
# Alarm Condition
# ==========================================================

class AlarmCondition(Enum):
    """
    Alarm evaluation mode.
    """

    HIGH = auto()
    LOW = auto()
    RANGE = auto()


# ==========================================================
# ROI Statistics
# ==========================================================

@dataclass(slots=True)
class ROIStatistics:
    """
    Temperature statistics inside one ROI.
    """

    minimum: float = np.nan

    maximum: float = np.nan

    mean: float = np.nan

    median: float = np.nan

    standard_deviation: float = np.nan

    hotspot_x: int = -1

    hotspot_y: int = -1

    pixel_count: int = 0


# ==========================================================
# Alarm Configuration
# ==========================================================

@dataclass(slots=True)
class AlarmThreshold:
    """
    Alarm configuration for one ROI.
    """

    enabled: bool = False

    condition: AlarmCondition = AlarmCondition.HIGH

    value: float = 0.0

    hysteresis: float = 1.0

    delay_ms: int = 0


# ==========================================================
# ROI Definition
# ==========================================================

@dataclass(slots=True)
class ROI:
    """
    One Region Of Interest.
    """

    # ------------------------------------------------------
    # Identity
    # ------------------------------------------------------

    roi_id: str

    name: str

    # ------------------------------------------------------
    # Geometry
    # ------------------------------------------------------

    roi_type: ROIType

    points: list[tuple[int, int]] = field(default_factory=list)

    radius: int = 0

    # ------------------------------------------------------
    # Display
    # ------------------------------------------------------

    enabled: bool = True

    visible: bool = True

    color: tuple[int, int, int] = (0, 255, 0)

    line_thickness: int = 2

    # ------------------------------------------------------
    # Alarm
    # ------------------------------------------------------

    alarm: AlarmThreshold = field(default_factory=AlarmThreshold)

    # ------------------------------------------------------
    # Metadata
    # ------------------------------------------------------

    description: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)


# ==========================================================
# ROI Processing Result
# ==========================================================

@dataclass(slots=True)
class ROIResult:
    """
    Result produced after processing one ROI.
    """

    roi: ROI

    statistics: ROIStatistics

    alarm_active: bool = False

    alarm_message: str | None = None