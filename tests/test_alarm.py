from __future__ import annotations


import pytest

from alarm import (
    AlarmEvent,
    AlarmEventKind,
    AlarmState,
    AlarmEvaluator,
    AlarmStateMachine,
    AlarmManager,
    AlarmHistory,
    ConditionEvaluator,
    HighConditionEvaluator,
    LowConditionEvaluator,
    RangeConditionEvaluator,
    get_evaluator,
    register_evaluator,
)
from alarm.state_machine import is_valid_transition
from roi.alarm_settings import ROIAlarmSettings, ROIAlarmCondition
from roi.runtime import RuntimeROIStatistics


def _stats(
    valid=True,
    minimum=20.0,
    maximum=80.0,
    mean=50.0,
):
    return RuntimeROIStatistics(
        valid=valid,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
    )


def _settings(
    enabled=True,
    condition=ROIAlarmCondition.HIGH,
    value=75.0,
    hysteresis=2.0,
    delay_ms=0,
):
    return ROIAlarmSettings(
        enabled=enabled,
        condition=condition,
        value=value,
        hysteresis=hysteresis,
        delay_ms=delay_ms,
    )


# ==============================================================
# Conditions
# ==============================================================


class TestHighConditionEvaluator:
    def test_triggered_above_threshold(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(81.0, 80.0, 2.0) is True

    def test_not_triggered_at_threshold(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(80.0, 80.0, 2.0) is False

    def test_not_triggered_below_threshold(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(79.0, 80.0, 2.0) is False

    def test_clear_below_hysteresis(self):
        ev = HighConditionEvaluator()
        assert ev.should_clear(77.0, 80.0, 2.0) is True

    def test_no_clear_at_hysteresis_boundary(self):
        ev = HighConditionEvaluator()
        assert ev.should_clear(78.0, 80.0, 2.0) is True

    def test_no_clear_above_hysteresis(self):
        ev = HighConditionEvaluator()
        assert ev.should_clear(79.0, 80.0, 2.0) is False

    def test_nan_not_triggered(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(float("nan"), 80.0, 2.0) is False

    def test_nan_not_clear(self):
        ev = HighConditionEvaluator()
        assert ev.should_clear(float("nan"), 80.0, 2.0) is False

    def test_select_maximum(self):
        ev = HighConditionEvaluator()
        assert ev.select_measured_value(10.0, 90.0, 50.0) == 90.0


class TestLowConditionEvaluator:
    def test_triggered_below_threshold(self):
        ev = LowConditionEvaluator()
        assert ev.is_triggered(19.0, 20.0, 2.0) is True

    def test_not_triggered_at_threshold(self):
        ev = LowConditionEvaluator()
        assert ev.is_triggered(20.0, 20.0, 2.0) is False

    def test_not_triggered_above_threshold(self):
        ev = LowConditionEvaluator()
        assert ev.is_triggered(21.0, 20.0, 2.0) is False

    def test_clear_above_hysteresis(self):
        ev = LowConditionEvaluator()
        assert ev.should_clear(22.0, 20.0, 2.0) is True

    def test_no_clear_at_hysteresis_boundary(self):
        ev = LowConditionEvaluator()
        assert ev.should_clear(22.0, 20.0, 2.0) is True

    def test_no_clear_below_hysteresis(self):
        ev = LowConditionEvaluator()
        assert ev.should_clear(21.0, 20.0, 2.0) is False

    def test_nan_not_triggered(self):
        ev = LowConditionEvaluator()
        assert ev.is_triggered(float("nan"), 20.0, 2.0) is False

    def test_select_minimum(self):
        ev = LowConditionEvaluator()
        assert ev.select_measured_value(10.0, 90.0, 50.0) == 10.0


class TestRangeConditionEvaluator:
    def test_triggered_above_range(self):
        ev = RangeConditionEvaluator()
        assert ev.is_triggered(83.0, 80.0, 2.0) is True

    def test_triggered_below_range(self):
        ev = RangeConditionEvaluator()
        assert ev.is_triggered(77.0, 80.0, 2.0) is True

    def test_not_triggered_within_range(self):
        ev = RangeConditionEvaluator()
        assert ev.is_triggered(80.0, 80.0, 2.0) is False

    def test_not_triggered_at_hysteresis_edge(self):
        ev = RangeConditionEvaluator()
        assert ev.is_triggered(82.0, 80.0, 2.0) is False

    def test_clear_within_half_hysteresis(self):
        ev = RangeConditionEvaluator()
        assert ev.should_clear(81.0, 80.0, 2.0) is True

    def test_no_clear_outside_half_hysteresis(self):
        ev = RangeConditionEvaluator()
        assert ev.should_clear(82.0, 80.0, 2.0) is False

    def test_nan_not_triggered(self):
        ev = RangeConditionEvaluator()
        assert ev.is_triggered(float("nan"), 80.0, 2.0) is False

    def test_select_mean(self):
        ev = RangeConditionEvaluator()
        assert ev.select_measured_value(10.0, 90.0, 50.0) == 50.0


class TestGetEvaluator:
    def test_high(self):
        assert isinstance(get_evaluator("HIGH"), HighConditionEvaluator)

    def test_low(self):
        assert isinstance(get_evaluator("LOW"), LowConditionEvaluator)

    def test_range(self):
        assert isinstance(get_evaluator("RANGE"), RangeConditionEvaluator)

    def test_case_insensitive(self):
        assert isinstance(get_evaluator("high"), HighConditionEvaluator)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="No evaluator"):
            get_evaluator("UNKNOWN")

    def test_register_custom(self):
        class CustomEval(ConditionEvaluator):
            def is_triggered(self, *a): return True
            def should_clear(self, *a): return True
            def select_measured_value(self, *a): return 0.0
        register_evaluator("custom_test", CustomEval)
        result = get_evaluator("custom_test")
        assert isinstance(result, CustomEval)


# ==============================================================
# State Machine
# ==============================================================


class TestAlarmStateMachine:
    def test_initial_state(self):
        sm = AlarmStateMachine()
        assert sm.state == AlarmState.NORMAL

    def test_normal_to_active_no_delay(self):
        sm = AlarmStateMachine(delay_ms=0)
        new, transition = sm.evaluate(True, False, 0)
        assert new == AlarmState.ACTIVE
        assert transition is not None

    def test_normal_to_pending_with_delay(self):
        sm = AlarmStateMachine(delay_ms=1000)
        new, transition = sm.evaluate(True, False, 0)
        assert new == AlarmState.PENDING
        assert transition is not None

    def test_pending_back_to_normal(self):
        sm = AlarmStateMachine(delay_ms=1000)
        sm.evaluate(True, False, 0)
        new, transition = sm.evaluate(False, False, 500)
        assert new == AlarmState.NORMAL
        assert transition is not None

    def test_pending_to_active_after_delay(self):
        sm = AlarmStateMachine(delay_ms=1000)
        sm.evaluate(True, False, 0)
        new, transition = sm.evaluate(True, False, 1000)
        assert new == AlarmState.ACTIVE
        assert transition is not None

    def test_pending_stays_pending_before_delay(self):
        sm = AlarmStateMachine(delay_ms=1000)
        sm.evaluate(True, False, 0)
        new, transition = sm.evaluate(True, False, 500)
        assert new == AlarmState.PENDING
        assert transition is None

    def test_active_to_cleared(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        assert sm.state == AlarmState.ACTIVE
        new, transition = sm.evaluate(False, True, 0)
        assert new == AlarmState.CLEARED
        assert transition is not None

    def test_cleared_to_normal(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        sm.evaluate(False, True, 0)
        assert sm.state == AlarmState.CLEARED
        new, transition = sm.evaluate(False, False, 0)
        assert new == AlarmState.NORMAL
        assert transition is not None

    def test_acknowledge_from_active(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        prev = sm.acknowledge()
        assert prev == AlarmState.ACTIVE
        assert sm.state == AlarmState.ACKNOWLEDGED

    def test_acknowledge_from_non_active_returns_none(self):
        sm = AlarmStateMachine()
        prev = sm.acknowledge()
        assert prev is None
        assert sm.state == AlarmState.NORMAL

    def test_acknowledged_to_cleared(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        sm.acknowledge()
        new, transition = sm.evaluate(False, True, 0)
        assert new == AlarmState.CLEARED
        assert transition is not None

    def test_active_stays_active_when_still_triggered(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        new, transition = sm.evaluate(True, False, 0)
        assert new == AlarmState.ACTIVE
        assert transition is None

    def test_force_clear(self):
        sm = AlarmStateMachine(delay_ms=0)
        sm.evaluate(True, False, 0)
        assert sm.state == AlarmState.ACTIVE
        prev = sm.force_clear()
        assert prev == AlarmState.ACTIVE
        assert sm.state == AlarmState.CLEARED

    def test_reset(self):
        sm = AlarmStateMachine(delay_ms=1000)
        sm.evaluate(True, False, 0)
        assert sm.state == AlarmState.PENDING
        sm.reset()
        assert sm.state == AlarmState.NORMAL

    def test_delay_ms_setter(self):
        sm = AlarmStateMachine(delay_ms=500)
        assert sm.delay_ms == 500
        sm.delay_ms = 2000
        assert sm.delay_ms == 2000


class TestStateTransitionValidation:
    def test_valid_normal_to_pending(self):
        assert is_valid_transition(AlarmState.NORMAL, AlarmState.PENDING)

    def test_valid_pending_to_active(self):
        assert is_valid_transition(AlarmState.PENDING, AlarmState.ACTIVE)

    def test_valid_active_to_acknowledged(self):
        assert is_valid_transition(AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)

    def test_valid_active_to_cleared(self):
        assert is_valid_transition(AlarmState.ACTIVE, AlarmState.CLEARED)

    def test_valid_acknowledged_to_cleared(self):
        assert is_valid_transition(AlarmState.ACKNOWLEDGED, AlarmState.CLEARED)

    def test_valid_cleared_to_normal(self):
        assert is_valid_transition(AlarmState.CLEARED, AlarmState.NORMAL)

    def test_invalid_skip(self):
        assert not is_valid_transition(AlarmState.NORMAL, AlarmState.ACTIVE)

    def test_invalid_reverse(self):
        assert not is_valid_transition(AlarmState.ACTIVE, AlarmState.NORMAL)


# ==============================================================
# AlarmEvent
# ==============================================================


class TestAlarmEvent:
    def test_immutable(self):
        event = AlarmEvent(
            roi_id="roi_1",
            kind=AlarmEventKind.ACTIVATED,
            previous_state="NORMAL",
            new_state="ACTIVE",
            measured_value=85.0,
            threshold=80.0,
            condition="HIGH",
        )
        with pytest.raises(AttributeError):
            event.roi_id = "roi_2"

    def test_frozen_true(self):
        import dataclasses
        assert dataclasses.is_dataclass(AlarmEvent)
        assert AlarmEvent.__dataclass_params__.frozen

    def test_fields_present(self):
        event = AlarmEvent(
            roi_id="roi_1",
            kind=AlarmEventKind.ACTIVATED,
            previous_state="NORMAL",
            new_state="ACTIVE",
            measured_value=85.0,
            threshold=80.0,
            condition="HIGH",
        )
        assert event.roi_id == "roi_1"
        assert event.kind == AlarmEventKind.ACTIVATED
        assert event.previous_state == "NORMAL"
        assert event.new_state == "ACTIVE"
        assert event.measured_value == 85.0
        assert event.threshold == 80.0
        assert event.condition == "HIGH"
        assert event.timestamp is not None

    def test_kind_values(self):
        assert AlarmEventKind.ACTIVATED.value == 1
        assert AlarmEventKind.CLEARED.value == 2
        assert AlarmEventKind.ACKNOWLEDGED.value == 3
        assert AlarmEventKind.RESET.value == 4


# ==============================================================
# AlarmEvaluator
# ==============================================================


class TestAlarmEvaluator:
    def test_disabled_alarm_returns_normal(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(enabled=False),
            _stats(),
            sm,
            0,
        )
        assert result.active is False
        assert result.state == AlarmState.NORMAL

    def test_invalid_stats_returns_current_state(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(),
            _stats(valid=False),
            sm,
            0,
        )
        assert result.state == AlarmState.NORMAL

    def test_high_alarm_triggers(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(condition=ROIAlarmCondition.HIGH, value=75.0),
            _stats(maximum=85.0),
            sm,
            0,
        )
        assert result.active is True
        assert result.state == AlarmState.ACTIVE
        assert result.measured_value == 85.0

    def test_high_alarm_not_triggered(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(condition=ROIAlarmCondition.HIGH, value=75.0),
            _stats(maximum=70.0),
            sm,
            0,
        )
        assert result.active is False
        assert result.state == AlarmState.NORMAL

    def test_low_alarm_triggers(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(condition=ROIAlarmCondition.LOW, value=30.0),
            _stats(minimum=20.0),
            sm,
            0,
        )
        assert result.active is True
        assert result.state == AlarmState.ACTIVE
        assert result.measured_value == 20.0

    def test_range_alarm_triggers(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "roi_1",
            _settings(condition=ROIAlarmCondition.RANGE, value=50.0),
            _stats(mean=55.0, minimum=40.0, maximum=60.0),
            sm,
            0,
        )
        assert result.state != AlarmState.NORMAL

    def test_returns_roi_id(self):
        ev = AlarmEvaluator()
        sm = AlarmStateMachine()
        result = ev.evaluate(
            "my_roi",
            _settings(enabled=False),
            _stats(),
            sm,
            0,
        )
        assert result.roi_id == "my_roi"


# ==============================================================
# AlarmHistory
# ==============================================================


class TestAlarmHistory:
    def test_empty_initial(self):
        h = AlarmHistory()
        assert h.count == 0
        assert h.all_events == []

    def test_record_event(self):
        h = AlarmHistory()
        event = AlarmEvent(
            roi_id="roi_1",
            kind=AlarmEventKind.ACTIVATED,
            previous_state="NORMAL",
            new_state="ACTIVE",
            measured_value=85.0,
            threshold=80.0,
            condition="HIGH",
        )
        h.record(event)
        assert h.count == 1

    def test_events_for_roi(self):
        h = AlarmHistory()
        e1 = AlarmEvent("roi_1", AlarmEventKind.ACTIVATED, "NORMAL", "ACTIVE", 85.0, 80.0, "HIGH")
        e2 = AlarmEvent("roi_2", AlarmEventKind.ACTIVATED, "NORMAL", "ACTIVE", 10.0, 20.0, "LOW")
        e3 = AlarmEvent("roi_1", AlarmEventKind.CLEARED, "ACTIVE", "CLEARED", 75.0, 80.0, "HIGH")
        for e in (e1, e2, e3):
            h.record(e)
        roi1_events = h.events_for_roi("roi_1")
        assert len(roi1_events) == 2
        roi2_events = h.events_for_roi("roi_2")
        assert len(roi2_events) == 1

    def test_clear(self):
        h = AlarmHistory()
        e1 = AlarmEvent("roi_1", AlarmEventKind.ACTIVATED, "NORMAL", "ACTIVE", 85.0, 80.0, "HIGH")
        h.record(e1)
        h.clear()
        assert h.count == 0
        assert h.all_events == []

    def test_events_for_unknown_roi_returns_empty(self):
        h = AlarmHistory()
        assert h.events_for_roi("nonexistent") == []

    def test_all_events_order(self):
        h = AlarmHistory()
        e1 = AlarmEvent("roi_1", AlarmEventKind.ACTIVATED, "NORMAL", "ACTIVE", 85.0, 80.0, "HIGH")
        e2 = AlarmEvent("roi_1", AlarmEventKind.CLEARED, "ACTIVE", "CLEARED", 75.0, 80.0, "HIGH")
        h.record(e1)
        h.record(e2)
        assert h.all_events == [e1, e2]


# ==============================================================
# AlarmManager
# ==============================================================


class TestAlarmManager:
    def test_initial_state(self):
        mgr = AlarmManager()
        assert mgr.active_count == 0
        assert mgr.active_roi_ids == []

    def test_register_and_get_state(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings())
        assert mgr.get_state("roi_1") == AlarmState.NORMAL

    def test_get_state_unregistered_returns_none(self):
        mgr = AlarmManager()
        assert mgr.get_state("nonexistent") is None

    def test_unregister(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings())
        mgr.unregister("roi_1")
        assert mgr.get_state("roi_1") is None

    def test_evaluate_unregistered_returns_default(self):
        mgr = AlarmManager()
        result = mgr.evaluate("nonexistent", _stats(), 0)
        assert result.roi_id == "nonexistent"
        assert result.active is False
        assert result.state == AlarmState.NORMAL

    def test_high_alarm_full_lifecycle(self):
        events: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=events.append)
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.active_count == 1
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        assert len(events) == 1
        assert events[0].kind == AlarmEventKind.ACTIVATED

        mgr.evaluate("roi_1", _stats(maximum=70.0), 0)
        assert mgr.active_count == 0
        assert mgr.get_state("roi_1") == AlarmState.CLEARED
        assert len(events) == 2
        assert events[1].kind == AlarmEventKind.CLEARED

        mgr.evaluate("roi_1", _stats(maximum=70.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.NORMAL

    def test_multiple_roi_independence(self):
        mgr = AlarmManager()
        mgr.register("roi_a", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.register("roi_b", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_a", _stats(maximum=85.0), 0)
        mgr.evaluate("roi_b", _stats(maximum=70.0), 0)
        assert mgr.get_state("roi_a") == AlarmState.ACTIVE
        assert mgr.get_state("roi_b") == AlarmState.NORMAL
        assert mgr.active_count == 1
        assert mgr.active_roi_ids == ["roi_a"]

    def test_disabled_alarm_no_event(self):
        events: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=events.append)
        mgr.register("roi_1", _settings(enabled=False))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.active_count == 0
        assert len(events) == 0

    def test_acknowledge(self):
        events: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=events.append)
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        result = mgr.acknowledge("roi_1")
        assert result is not None
        assert result.state == AlarmState.ACKNOWLEDGED
        assert mgr.get_state("roi_1") == AlarmState.ACKNOWLEDGED
        assert len(events) == 2
        assert events[1].kind == AlarmEventKind.ACKNOWLEDGED

    def test_acknowledge_clears_when_value_safe(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        mgr.acknowledge("roi_1")
        assert mgr.get_state("roi_1") == AlarmState.ACKNOWLEDGED
        mgr.evaluate("roi_1", _stats(maximum=70.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.CLEARED

    def test_acknowledge_nonexistent_returns_none(self):
        mgr = AlarmManager()
        result = mgr.acknowledge("nonexistent")
        assert result is None

    def test_reset(self):
        events: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=events.append)
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        result = mgr.reset("roi_1")
        assert result is not None
        assert result.state == AlarmState.NORMAL
        assert mgr.get_state("roi_1") == AlarmState.NORMAL
        assert len(events) == 2
        assert events[1].kind == AlarmEventKind.RESET

    def test_reset_nonexistent_returns_none(self):
        mgr = AlarmManager()
        result = mgr.reset("nonexistent")
        assert result is None

    def test_clear_all(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings())
        mgr.register("roi_2", _settings())
        mgr.clear_all()
        assert mgr.active_count == 0
        assert mgr.get_state("roi_1") is None

    def test_evaluate_all(self):
        mgr = AlarmManager()
        mgr.register("roi_a", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.register("roi_b", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        all_stats = {
            "roi_a": _stats(maximum=85.0),
            "roi_b": _stats(maximum=70.0),
        }
        results = mgr.evaluate_all(all_stats, 0)
        assert len(results) == 2
        result_map = {r.roi_id: r for r in results}
        assert result_map["roi_a"].active is True
        assert result_map["roi_b"].active is False

    def test_nan_statistics_does_not_crash(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        result = mgr.evaluate(
            "roi_1",
            _stats(maximum=float("nan")),
            0,
        )
        assert result.roi_id == "roi_1"

    def test_history_is_populated(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.history.count == 1
        mgr.evaluate("roi_1", _stats(maximum=70.0), 0)
        assert mgr.history.count == 2

    def test_on_event_callback(self):
        received: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=received.append)
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert len(received) == 1
        assert received[0].roi_id == "roi_1"
        assert received[0].kind == AlarmEventKind.ACTIVATED

    def test_register_updates_settings(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(value=75.0))
        mgr.register("roi_1", _settings(value=90.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.NORMAL

    def test_hysteresis_prevents_chatter(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=80.0, hysteresis=3.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(maximum=79.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(maximum=76.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.CLEARED

    def test_delay_prevents_transient(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=80.0, delay_ms=1000))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.PENDING
        mgr.evaluate("roi_1", _stats(maximum=85.0), 500)
        assert mgr.get_state("roi_1") == AlarmState.PENDING
        mgr.evaluate("roi_1", _stats(maximum=85.0), 1000)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE

    def test_delay_transient_spike_returns_to_normal(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=80.0, delay_ms=1000))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.PENDING
        mgr.evaluate("roi_1", _stats(maximum=70.0), 500)
        assert mgr.get_state("roi_1") == AlarmState.NORMAL

    def test_register_delay_from_settings(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(delay_ms=2000))
        sm = mgr._machines["roi_1"]
        assert sm.delay_ms == 2000

    def test_invalid_stats_keeps_current_alarm_state(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        result = mgr.evaluate("roi_1", _stats(valid=False), 0)
        assert result.active is True
        assert result.state == AlarmState.ACTIVE

    def test_low_alarm_lifecycle(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.LOW, value=30.0, hysteresis=2.0))
        mgr.evaluate("roi_1", _stats(minimum=20.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(minimum=31.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(minimum=33.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.CLEARED

    def test_range_alarm_lifecycle(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.RANGE, value=50.0, hysteresis=3.0))
        mgr.evaluate("roi_1", _stats(mean=55.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(mean=52.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE
        mgr.evaluate("roi_1", _stats(mean=51.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.CLEARED

    def test_force_clear_emits_cleared_event(self):
        events: list[AlarmEvent] = []
        mgr = AlarmManager(on_event=events.append)
        mgr.register("roi_1", _settings(enabled=True))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.active_count == 1
        mgr.register("roi_1", _settings(enabled=False))
        mgr.evaluate("roi_1", _stats(maximum=85.0), 0)
        assert mgr.active_count == 0
        assert any(e.kind == AlarmEventKind.CLEARED for e in events)


# ==============================================================
# Edge cases
# ==============================================================


class TestEdgeCases:
    def test_negative_threshold(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings(condition=ROIAlarmCondition.LOW, value=-10.0))
        mgr.evaluate("roi_1", _stats(minimum=-15.0), 0)
        assert mgr.get_state("roi_1") == AlarmState.ACTIVE

    def test_zero_hysteresis(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(80.0, 80.0, 0.0) is False
        assert ev.is_triggered(80.001, 80.0, 0.0) is True
        assert ev.should_clear(80.0, 80.0, 0.0) is True
        assert ev.should_clear(79.999, 80.0, 0.0) is True

    def test_infinity_value(self):
        ev = HighConditionEvaluator()
        assert ev.is_triggered(float("inf"), 80.0, 2.0) is True

    def test_missing_roi_in_evaluate_all(self):
        mgr = AlarmManager()
        mgr.register("roi_a", _settings())
        result = mgr.evaluate_all({"roi_a": _stats(), "roi_b": _stats()}, 0)
        assert len(result) == 1

    def test_active_roi_ids_list(self):
        mgr = AlarmManager()
        mgr.register("roi_a", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.register("roi_b", _settings(condition=ROIAlarmCondition.HIGH, value=75.0))
        mgr.evaluate("roi_a", _stats(maximum=85.0), 0)
        mgr.evaluate("roi_b", _stats(maximum=70.0), 0)
        assert "roi_a" in mgr.active_roi_ids
        assert "roi_b" not in mgr.active_roi_ids

    def test_repeated_register_does_not_duplicate(self):
        mgr = AlarmManager()
        mgr.register("roi_1", _settings())
        mgr.register("roi_1", _settings())
        assert len(mgr._machines) == 1
