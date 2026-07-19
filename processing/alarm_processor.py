"""
alarm_processor.py

Evaluates ROI results and generates alarm results.
"""

from __future__ import annotations

import time

from processing.models.alarm_models import (
    AlarmEvent,
    AlarmResult,
    AlarmState,
    AlarmThreshold,
    AlarmType,
)

from processing.models.roi_models import (
    ROIResult,
)


class AlarmProcessor:
    """
    Evaluates alarms for ROI results.
    """

    def __init__(self) -> None:

        #
        # Runtime state
        #

        self._previous_states: dict[
            str,
            AlarmState,
        ] = {}

        self._activation_times: dict[
            str,
            float,
        ] = {}

    # ==========================================================
    # Public API
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

            result = self._evaluate_roi(
                camera_id,
                position_id,
                roi_result,
            )

            results.append(result)

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

            threshold = roi_result.roi.alarm_threshold

            if (
                threshold is None
                or
                not threshold.enabled
            ):
                return AlarmResult()

            if threshold.alarm_type == AlarmType.HIGH:

                triggered = self._check_high_alarm(
                    roi_result,
                    threshold,
                )

            elif threshold.alarm_type == AlarmType.LOW:

                triggered = self._check_low_alarm(
                    roi_result,
                    threshold,
                )

            elif threshold.alarm_type == AlarmType.DELTA:

                triggered = self._check_delta_alarm(
                    roi_result,
                    threshold,
                )

            else:

                return AlarmResult()

            key = self._alarm_key(
                camera_id,
                position_id,
                roi_result.roi.roi_id,
            )

            if not triggered:

                self._activation_times.pop(
                    key,
                    None,
                )

                self._previous_states[key] = AlarmState.NORMAL

                return AlarmResult()

            if not self._apply_delay(
                key,
                threshold.delay_ms,
            ):
                return AlarmResult()

            state = self._apply_hysteresis(
                key,
                threshold,
                triggered,
            )

            if state != AlarmState.ACTIVE:

                return AlarmResult()

            event = self._create_event(
                camera_id,
                position_id,
                roi_result,
                threshold,
            )

            return AlarmResult(
                state=AlarmState.ACTIVE,
                event=event,
                active=True,
            )

    # ==========================================================
    # Alarm Evaluation
    # ==========================================================

    def _check_high_alarm(
        self,
        roi_result: ROIResult,
        threshold: AlarmThreshold,
    ) -> bool:

        return (
            roi_result.statistics.maximum
            > threshold.limit
        )

    def _check_low_alarm(
        self,
        roi_result: ROIResult,
        threshold: AlarmThreshold,
    ) -> bool:

        return (
            roi_result.statistics.minimum
            < threshold.limit
        )

    def _check_delta_alarm(
        self,
        roi_result: ROIResult,
        threshold: AlarmThreshold,
    ) -> bool:

        return (
            roi_result.statistics.delta
            > threshold.limit
        )
    
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
            >= delay_ms
        )

    # ==========================================================
    # Hysteresis
    # ==========================================================

    def _apply_hysteresis(
        self,
        key: str,
        threshold: AlarmThreshold,
        triggered: bool,
    ) -> AlarmState:

        previous = self._previous_states.get(
            key,
            AlarmState.NORMAL,
        )

        if triggered:

            self._previous_states[key] = (
                AlarmState.ACTIVE
            )

            return AlarmState.ACTIVE

        self._previous_states[key] = (
            AlarmState.NORMAL
        )

        return AlarmState.NORMAL
    
        # ==========================================================
    # Alarm Event
    # ==========================================================

    def _create_event(
        self,
        camera_id: str,
        position_id: str,
        roi_result: ROIResult,
        threshold: AlarmThreshold,
    ) -> AlarmEvent:

        if threshold.alarm_type == AlarmType.HIGH:

            value = roi_result.statistics.maximum

        elif threshold.alarm_type == AlarmType.LOW:

            value = roi_result.statistics.minimum

        else:

            value = roi_result.statistics.delta

        return AlarmEvent(

            camera_id=camera_id,

            position_id=position_id,

            roi_id=roi_result.roi.roi_id,

            alarm_type=threshold.alarm_type,

            severity=threshold.severity,

            value=value,

            limit=threshold.limit,

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

        return (
            f"{camera_id}:"
            f"{position_id}:"
            f"{roi_id}"
        )

    def clear(
        self,
    ) -> None:

        self._previous_states.clear()

        self._activation_times.clear()

    @property
    def active_alarm_count(
        self,
    ) -> int:

        return sum(

            state == AlarmState.ACTIVE

            for state in self._previous_states.values()

        )