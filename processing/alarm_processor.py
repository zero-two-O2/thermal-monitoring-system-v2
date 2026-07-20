"""
alarm_processor.py

Evaluates ROI results and generates runtime alarms.
"""

from __future__ import annotations

import time

from processing.models.roi_models import (
    ROIResult,
    AlarmCondition,
)

from processing.models.alarm_models import (
    AlarmEvent,
    AlarmResult,
    AlarmSeverity,
    AlarmState,
)


class AlarmProcessor:
    """
    Evaluates alarms for ROI results.
    """

    def __init__(self) -> None:

        #
        # Runtime state
        #

        self._previous_states: dict[str, AlarmState] = {}

        self._activation_times: dict[str, float] = {}

    # ==========================================================
    # Public
    # ==========================================================

    def process(
        self,
        camera_id: str,
        position_id: str,
        roi_results: list[ROIResult],
    ) -> list[AlarmResult]:
        """
        Evaluate all ROI results.
        """

        results: list[AlarmResult] = []

        for roi_result in roi_results:

            results.append(

                self._evaluate_roi(

                    camera_id,

                    position_id,

                    roi_result,

                )

            )

        return results

    # ==========================================================
    # ROI Evaluation
    # ==========================================================

    def _evaluate_roi(
        self,
        camera_id: str,
        position_id: str,
        roi_result: ROIResult,
    ) -> AlarmResult:

        roi = roi_result.roi

        threshold = roi.alarm

        #
        # Alarm disabled
        #

        if not threshold.enabled:

            return AlarmResult()

        #
        # Evaluate condition
        #

        triggered = self._is_triggered(

            roi_result,

            threshold,

        )

        key = self._alarm_key(

            camera_id,

            position_id,

            roi.roi_id,

        )

        #
        # Not triggered
        #

        if not triggered:

            self._previous_states[key] = AlarmState.NORMAL

            self._activation_times.pop(

                key,

                None,

            )

            return AlarmResult()

        #
        # Delay
        #

        if not self._apply_delay(

            key,

            threshold.delay_ms,

        ):

            return AlarmResult()

        #
        # Active
        #

        self._previous_states[key] = AlarmState.ACTIVE

        event = AlarmEvent(

            camera_id=camera_id,

            position_id=position_id,

            roi_id=roi.roi_id,

            roi_name=roi.name,

            severity=AlarmSeverity.WARNING,

            measured_value=self._measured_value(

                roi_result,

                threshold.condition,

            ),

            threshold_value=threshold.value,

        )

        return AlarmResult(

            active=True,

            state=AlarmState.ACTIVE,

            event=event,

        )

    # ==========================================================
    # Condition Evaluation
    # ==========================================================

    @staticmethod
    def _is_triggered(
        roi_result: ROIResult,
        threshold,
    ) -> bool:

        stats = roi_result.statistics

        if threshold.condition == AlarmCondition.HIGH:

            return (

                stats.maximum

                >=

                threshold.value

            )

        if threshold.condition == AlarmCondition.LOW:

            return (

                stats.minimum

                <=

                threshold.value

            )

        if threshold.condition == AlarmCondition.RANGE:

            return (

                stats.minimum < threshold.value

                or

                stats.maximum > threshold.value

            )

        return False

    # ==========================================================
    # Alarm Value
    # ==========================================================

    @staticmethod
    def _measured_value(
        roi_result: ROIResult,
        condition: AlarmCondition,
    ) -> float:

        stats = roi_result.statistics

        if condition == AlarmCondition.HIGH:

            return stats.maximum

        if condition == AlarmCondition.LOW:

            return stats.minimum

        return stats.maximum

    # ==========================================================
    # Delay
    # ==========================================================

    def _apply_delay(
        self,
        key: str,
        delay_ms: int,
    ) -> bool:

        if delay_ms <= 0:

            return True

        now = time.monotonic()

        start = self._activation_times.get(

            key

        )

        if start is None:

            self._activation_times[key] = now

            return False

        return (

            (now - start) * 1000

            >=

            delay_ms

        )

    # ==========================================================
    # Utilities
    # ==========================================================

    @staticmethod
    def _alarm_key(
        camera_id: str,
        position_id: str,
        roi_id: str,
    ) -> str:

        return f"{camera_id}:{position_id}:{roi_id}"

    def clear(self) -> None:

        self._previous_states.clear()

        self._activation_times.clear()

    @property
    def active_alarm_count(self) -> int:

        return sum(

            state == AlarmState.ACTIVE

            for state in self._previous_states.values()

        )