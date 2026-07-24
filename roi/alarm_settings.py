"""
alarm_settings.py

ROI alarm configuration for the Thermal Monitoring System.

Defines the threshold and behavior for alarm generation
on one ROI.

This class contains ONLY alarm configuration data.
No alarm evaluation logic, no HALCON, no GUI code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ROIAlarmCondition(Enum):
    """
    The condition that triggers an alarm for an ROI.

    HIGH  : Alarm activates when temperature exceeds threshold.
    LOW   : Alarm activates when temperature drops below threshold.
    RANGE : Alarm activates when temperature is outside range.
    """

    HIGH = auto()
    LOW = auto()
    RANGE = auto()


@dataclass(slots=True)
class ROIAlarmSettings:
    """
    Alarm threshold and behavior for one ROI.

    Responsibilities
    ----------------
    - Store alarm threshold parameters.
    - Store alarm delay and hysteresis.
    - Enable or disable alarm evaluation.

    Must never:
    - Evaluate alarm conditions.
    - Track alarm state over time.
    - Reference ROI geometry or statistics.
    - Contain HALCON or GUI code.
    """

    enabled: bool = False

    condition: ROIAlarmCondition = ROIAlarmCondition.HIGH

    value: float = 0.0

    hysteresis: float = 1.0

    delay_ms: int = 0
