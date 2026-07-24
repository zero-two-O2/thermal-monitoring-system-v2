from __future__ import annotations

import math
from datetime import datetime
from threading import Lock
from typing import Callable

from roi.alarm_settings import ROIAlarmSettings
from roi.runtime import RuntimeROIStatistics

from alarm.conditions import get_evaluator
from alarm.events import AlarmEvent, AlarmEventKind
from alarm.history import AlarmHistory
from alarm.interfaces import ConditionEvaluator
from alarm.result import AlarmResult
from alarm.state_machine import AlarmState, AlarmStateMachine


def _select_measured_value(
    condition_name: str,
    stats: RuntimeROIStatistics,
    evaluator: ConditionEvaluator,
) -> float:
    return evaluator.select_measured_value(
        stats.minimum, stats.maximum, stats.mean
    )


class AlarmManager:
    def __init__(
        self,
        on_event: Callable[[AlarmEvent], None] | None = None,
    ) -> None:
        self._lock = Lock()
        self._machines: dict[str, AlarmStateMachine] = {}
        self._settings: dict[str, ROIAlarmSettings] = {}
        self._history = AlarmHistory()
        self._on_event = on_event

    @property
    def history(self) -> AlarmHistory:
        return self._history

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(
                1 for m in self._machines.values()
                if m.state in (
                    AlarmState.PENDING,
                    AlarmState.ACTIVE,
                    AlarmState.ACKNOWLEDGED,
                )
            )

    @property
    def active_roi_ids(self) -> list[str]:
        with self._lock:
            return [
                rid for rid, m in self._machines.items()
                if m.state in (
                    AlarmState.PENDING,
                    AlarmState.ACTIVE,
                    AlarmState.ACKNOWLEDGED,
                )
            ]

    def get_state(self, roi_id: str) -> AlarmState | None:
        with self._lock:
            machine = self._machines.get(roi_id)
            if machine is None:
                return None
            return machine.state

    def register(
        self, roi_id: str, settings: ROIAlarmSettings
    ) -> None:
        with self._lock:
            if roi_id not in self._machines:
                self._machines[roi_id] = AlarmStateMachine(
                    delay_ms=settings.delay_ms
                )
            self._settings[roi_id] = settings
            self._machines[roi_id].delay_ms = settings.delay_ms

    def unregister(self, roi_id: str) -> None:
        with self._lock:
            self._machines.pop(roi_id, None)
            self._settings.pop(roi_id, None)

    def evaluate(
        self,
        roi_id: str,
        stats: RuntimeROIStatistics,
        frame_timestamp_ms: int,
    ) -> AlarmResult:
        with self._lock:
            machine = self._machines.get(roi_id)
            settings = self._settings.get(roi_id)
            if machine is None or settings is None:
                return AlarmResult(roi_id=roi_id)

            return self._evaluate_one(
                roi_id, settings, stats, machine, frame_timestamp_ms
            )

    def evaluate_all(
        self,
        all_stats: dict[str, RuntimeROIStatistics],
        frame_timestamp_ms: int,
    ) -> list[AlarmResult]:
        results: list[AlarmResult] = []
        with self._lock:
            for roi_id, stats in all_stats.items():
                machine = self._machines.get(roi_id)
                settings = self._settings.get(roi_id)
                if machine is None or settings is None:
                    continue
                results.append(
                    self._evaluate_one(
                        roi_id, settings, stats, machine, frame_timestamp_ms
                    )
                )
        return results

    def _evaluate_one(
        self,
        roi_id: str,
        settings: ROIAlarmSettings,
        stats: RuntimeROIStatistics,
        machine: AlarmStateMachine,
        frame_timestamp_ms: int,
    ) -> AlarmResult:
        if not settings.enabled:
            prev = machine.state
            if prev != AlarmState.NORMAL:
                old = machine.force_clear()
                self._emit(
                    roi_id,
                    AlarmEventKind.CLEARED,
                    old,
                    AlarmState.CLEARED,
                    0.0,
                    settings.value,
                    settings.condition.name,
                )
            return AlarmResult(
                roi_id=roi_id,
                active=False,
                state=AlarmState.NORMAL,
            )

        if not stats.valid:
            return AlarmResult(
                roi_id=roi_id,
                active=machine.state not in (AlarmState.NORMAL, AlarmState.CLEARED),
                state=machine.state,
            )

        evaluator = get_evaluator(settings.condition.name)
        measured = evaluator.select_measured_value(
            stats.minimum, stats.maximum, stats.mean
        )

        if math.isnan(measured):
            return AlarmResult(
                roi_id=roi_id,
                active=machine.state not in (AlarmState.NORMAL, AlarmState.CLEARED),
                state=machine.state,
            )

        is_triggered = evaluator.is_triggered(
            measured, settings.value, settings.hysteresis
        )
        should_clear = evaluator.should_clear(
            measured, settings.value, settings.hysteresis
        )

        prev_state = machine.state
        new_state, transition = machine.evaluate(
            is_triggered, should_clear, frame_timestamp_ms
        )

        if transition is not None:
            if new_state == AlarmState.PENDING:
                self._emit(
                    roi_id,
                    AlarmEventKind.ACTIVATED,
                    prev_state,
                    new_state,
                    measured,
                    settings.value,
                    settings.condition.name,
                )
            elif new_state == AlarmState.ACTIVE:
                self._emit(
                    roi_id,
                    AlarmEventKind.ACTIVATED,
                    prev_state,
                    new_state,
                    measured,
                    settings.value,
                    settings.condition.name,
                )
            elif new_state == AlarmState.CLEARED:
                self._emit(
                    roi_id,
                    AlarmEventKind.CLEARED,
                    prev_state,
                    new_state,
                    measured,
                    settings.value,
                    settings.condition.name,
                )

        active = new_state in (
            AlarmState.PENDING,
            AlarmState.ACTIVE,
            AlarmState.ACKNOWLEDGED,
        )

        return AlarmResult(
            roi_id=roi_id,
            active=active,
            state=new_state,
            measured_value=measured,
            threshold=settings.value,
        )

    def acknowledge(self, roi_id: str) -> AlarmResult | None:
        with self._lock:
            machine = self._machines.get(roi_id)
            if machine is None:
                return None
            prev = machine.acknowledge()
            if prev is None:
                return None
            self._emit(
                roi_id,
                AlarmEventKind.ACKNOWLEDGED,
                prev,
                AlarmState.ACKNOWLEDGED,
                0.0,
                0.0,
                "",
            )
            return AlarmResult(
                roi_id=roi_id,
                active=True,
                state=AlarmState.ACKNOWLEDGED,
            )

    def reset(self, roi_id: str) -> AlarmResult | None:
        with self._lock:
            machine = self._machines.get(roi_id)
            if machine is None:
                return None
            prev = machine.state
            machine.reset()
            self._emit(
                roi_id,
                AlarmEventKind.RESET,
                prev,
                AlarmState.NORMAL,
                0.0,
                0.0,
                "",
            )
            return AlarmResult(
                roi_id=roi_id,
                active=False,
                state=AlarmState.NORMAL,
            )

    def clear_all(self) -> None:
        with self._lock:
            self._machines.clear()
            self._settings.clear()
            self._history.clear()

    def _emit(
        self,
        roi_id: str,
        kind: AlarmEventKind,
        prev_state: AlarmState | None,
        new_state: AlarmState,
        measured_value: float,
        threshold: float,
        condition: str,
    ) -> None:
        event = AlarmEvent(
            roi_id=roi_id,
            kind=kind,
            previous_state=prev_state.name if prev_state else "NORMAL",
            new_state=new_state.name,
            measured_value=measured_value,
            threshold=threshold,
            condition=condition,
            timestamp=datetime.now(),
        )
        self._history.record(event)
        if self._on_event:
            self._on_event(event)
