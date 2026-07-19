"""
roi_models.py

ROI data models for the Thermal Monitoring System.

These models are shared by:

- ROI Processor
- Alarm Processor
- GUI
- Database
- Project Save/Load
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ==========================================================
# ROI Types
# ==========================================================

class ROIType(Enum):

    RECTANGLE = "rectangle"

    POLYGON = "polygon"

    CIRCLE = "circle"


# ==========================================================
# Alarm Types
# ==========================================================

class AlarmCondition(Enum):

    HIGH = "high"

    LOW = "low"

    RANGE = "range"


# ==========================================================
# ROI Statistics
# ==========================================================

@dataclass(slots=True)
class ROIStatistics:

    minimum: float = np.nan

    maximum: float = np.nan

    mean: float = np.nan

    median: float = np.nan

    standard_deviation: float = np.nan

    hotspot_x: int = -1

    hotspot_y: int = -1


# ==========================================================
# Alarm Threshold
# ==========================================================

@dataclass(slots=True)
class AlarmThreshold:

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

    roi_id: str

    name: str

    roi_type: ROIType

    enabled: bool = True

    visible: bool = True

    color: tuple[int, int, int] = (0, 255, 0)

    #
    # Geometry
    #

    points: list[tuple[int, int]] = field(
        default_factory=list
    )

    radius: int = 0

    #
    # Alarm
    #

    alarm: AlarmThreshold = field(
        default_factory=AlarmThreshold
    )

    #
    # User data
    #

    description: str = ""

    metadata: dict = field(
        default_factory=dict
    )


# ==========================================================
# ROI Result
# ==========================================================

@dataclass(slots=True)
class ROIResult:

    roi_id: str

    statistics: ROIStatistics

    alarm_active: bool = False

    alarm_message: Optional[str] = None

    