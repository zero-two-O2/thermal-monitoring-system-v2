from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from alarm.events import AlarmEvent


@dataclass(slots=True)
class AlarmHistory:
    _events: list[AlarmEvent] = field(default_factory=list)
    _by_roi: dict[str, list[AlarmEvent]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def record(self, event: AlarmEvent) -> None:
        self._events.append(event)
        self._by_roi[event.roi_id].append(event)

    @property
    def all_events(self) -> list[AlarmEvent]:
        return list(self._events)

    def events_for_roi(self, roi_id: str) -> list[AlarmEvent]:
        return list(self._by_roi.get(roi_id, []))

    @property
    def count(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._by_roi.clear()
