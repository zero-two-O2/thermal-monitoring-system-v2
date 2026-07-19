"""
alarm_models.py

Models used by the Alarm Processor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


# ==========================================================
# Enumerations
# ==========================================================

class AlarmSeverity(Enum):
    """
    Alarm priority.
    """

    INFO = auto()

    WARNING = auto()

    CRITICAL = auto()


class AlarmState(Enum):
    """
    Current alarm state.
    """

    NORMAL = auto()

    ACTIVE = auto()

    ACKNOWLEDGED = auto()

    CLEARED = auto()


class AlarmType(Enum):
    """
    Supported alarm types.
    """

    HIGH = auto()

    LOW = auto()

    DELTA = auto()

    RATE_OF_RISE = auto()


# ==========================================================
# Alarm Configuration
# ==========================================================

@dataclass(slots=True)
class AlarmThreshold:
    """
    Alarm configuration.
    """

    enabled: bool = True

    alarm_type: AlarmType = AlarmType.HIGH

    severity: AlarmSeverity = AlarmSeverity.WARNING

    limit: float = 0.0

    hysteresis: float = 1.0

    delay_ms: int = 0

    latch: bool = False


# ==========================================================
# Alarm Event
# ==========================================================

@dataclass(slots=True)
class AlarmEvent:
    """
    One generated alarm.
    """

    camera_id: str

    position_id: str

    roi_id: str

    alarm_type: AlarmType

    severity: AlarmSeverity

    value: float

    limit: float

    timestamp: datetime = field(
        default_factory=datetime.now
    )


# ==========================================================
# Alarm Result
# ==========================================================

@dataclass(slots=True)
class AlarmResult:
    """
    Alarm evaluation result for one ROI.
    """

    state: AlarmState = AlarmState.NORMAL

    event: AlarmEvent | None = None

    active: bool = False

    acknowledged: bool = False