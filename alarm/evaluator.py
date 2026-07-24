from __future__ import annotations

import math

from roi.alarm_settings import ROIAlarmSettings, ROIAlarmCondition
from roi.runtime import RuntimeROIStatistics

from alarm.conditions import get_evaluator
from alarm.result import AlarmResult
from alarm.state_machine import AlarmState, AlarmStateMachine


def _select_measured_value(
    condition: ROIAlarmCondition, stats: RuntimeROIStatistics
) -> float:
    if condition == ROIAlarmCondition.HIGH:
        return stats.maximum
    if condition == ROIAlarmCondition.LOW:
        return stats.minimum
    if condition == ROIAlarmCondition.RANGE:
        return stats.mean
    return stats.maximum


class AlarmEvaluator:
    def evaluate(
        self,
        roi_id: str,
        settings: ROIAlarmSettings,
        stats: RuntimeROIStatistics,
        state_machine: AlarmStateMachine,
        frame_timestamp_ms: int,
    ) -> AlarmResult:
        if not settings.enabled:
            return AlarmResult(
                roi_id=roi_id,
                active=False,
                state=AlarmState.NORMAL,
            )

        if not stats.valid:
            return AlarmResult(
                roi_id=roi_id,
                active=state_machine.state != AlarmState.NORMAL,
                state=state_machine.state,
            )

        measured = _select_measured_value(settings.condition, stats)

        if math.isnan(measured):
            return AlarmResult(
                roi_id=roi_id,
                active=state_machine.state != AlarmState.NORMAL,
                state=state_machine.state,
            )

        evaluator = get_evaluator(settings.condition.name)

        is_triggered = evaluator.is_triggered(
            measured, settings.value, settings.hysteresis
        )
        should_clear = evaluator.should_clear(
            measured, settings.value, settings.hysteresis
        )

        new_state, transition = state_machine.evaluate(
            is_triggered, should_clear, frame_timestamp_ms
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
