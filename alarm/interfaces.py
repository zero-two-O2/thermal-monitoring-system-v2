from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from alarm.events import AlarmEvent


class ConditionEvaluator(ABC):
    @abstractmethod
    def is_triggered(
        self, measured_value: float, threshold: float, hysteresis: float
    ) -> bool:
        ...

    @abstractmethod
    def should_clear(
        self, measured_value: float, threshold: float, hysteresis: float
    ) -> bool:
        ...

    @abstractmethod
    def select_measured_value(
        self, minimum: float, maximum: float, mean: float
    ) -> float:
        ...


class AlarmEventHandler(Protocol):
    def handle_alarm_event(self, event: AlarmEvent) -> None:
        ...
