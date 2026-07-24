from __future__ import annotations

from dataclasses import dataclass

from alarm.events import AlarmEvent
from alarm.state_machine import AlarmState


@dataclass(slots=True)
class AlarmResult:
    roi_id: str = ""
    active: bool = False
    state: AlarmState = AlarmState.NORMAL
    measured_value: float = 0.0
    threshold: float = 0.0
    event: AlarmEvent | None = None
