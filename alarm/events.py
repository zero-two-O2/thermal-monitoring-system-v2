from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto


class AlarmEventKind(Enum):
    ACTIVATED = auto()
    CLEARED = auto()
    ACKNOWLEDGED = auto()
    RESET = auto()


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    roi_id: str
    kind: AlarmEventKind
    previous_state: str
    new_state: str
    measured_value: float
    threshold: float
    condition: str
    timestamp: datetime = field(default_factory=datetime.now)
