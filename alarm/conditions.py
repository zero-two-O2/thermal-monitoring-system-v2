from __future__ import annotations

import math

from alarm.interfaces import ConditionEvaluator

_EVALUATOR_REGISTRY: dict[str, type[ConditionEvaluator]] = {}


def register_evaluator(
    name: str, evaluator_cls: type[ConditionEvaluator]
) -> None:
    _EVALUATOR_REGISTRY[name.lower()] = evaluator_cls


def get_evaluator(name: str) -> ConditionEvaluator:
    key = name.lower()
    cls = _EVALUATOR_REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"No evaluator registered for condition: {name}")
    return cls()


class HighConditionEvaluator(ConditionEvaluator):
    def is_triggered(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return measured_value > threshold

    def should_clear(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return measured_value <= threshold - hysteresis

    def select_measured_value(
        self, minimum: float, maximum: float, mean: float
    ) -> float:
        return maximum


class LowConditionEvaluator(ConditionEvaluator):
    def is_triggered(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return measured_value < threshold

    def should_clear(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return measured_value >= threshold + hysteresis

    def select_measured_value(
        self, minimum: float, maximum: float, mean: float
    ) -> float:
        return minimum


class RangeConditionEvaluator(ConditionEvaluator):
    def is_triggered(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return abs(measured_value - threshold) > hysteresis

    def should_clear(
        self, measured_value: float, threshold: float, hysteresis: float = 1.0
    ) -> bool:
        if math.isnan(measured_value) or math.isnan(threshold):
            return False
        return abs(measured_value - threshold) <= hysteresis * 0.5

    def select_measured_value(
        self, minimum: float, maximum: float, mean: float
    ) -> float:
        return mean


register_evaluator("high", HighConditionEvaluator)
register_evaluator("low", LowConditionEvaluator)
register_evaluator("range", RangeConditionEvaluator)
