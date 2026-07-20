"""
alarm_models.py

Runtime alarm models.

These models are produced by the AlarmProcessor and consumed by:

    - GUI
    - Database
    - Alarm History
    - Logger
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


# ==========================================================
# Alarm Severity
# ==========================================================

class AlarmSeverity(Enum):
    """
    Alarm priority.
    """

    INFO = auto()

    WARNING = auto()

    CRITICAL = auto()


# ==========================================================
# Alarm State
# ==========================================================

class AlarmState(Enum):
    """
    Current runtime alarm state.
    """

    NORMAL = auto()

    ACTIVE = auto()

    ACKNOWLEDGED = auto()

    CLEARED = auto()


# ==========================================================
# Alarm Event
# ==========================================================

@dataclass(slots=True)
class AlarmEvent:
    """
    One alarm occurrence.
    """

    camera_id: str

    position_id: str

    roi_id: str

    roi_name: str

    severity: AlarmSeverity

    measured_value: float

    threshold_value: float

    timestamp: datetime = field(
        default_factory=datetime.now
    )


# ==========================================================
# Alarm Result
# ==========================================================

@dataclass(slots=True)
class AlarmResult:
    """
    Result returned by AlarmProcessor after evaluating one ROI.
    """

    active: bool = False

    state: AlarmState = AlarmState.NORMAL

    event: AlarmEvent | None = None
    