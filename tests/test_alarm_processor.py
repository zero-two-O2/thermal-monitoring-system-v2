"""
test_alarm_processor.py

Integration tests for AlarmProcessor.

Run:

    python test_alarm_processor.py
"""

from __future__ import annotations
import sys
import time
import traceback
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.alarm_processor import AlarmProcessor

from processing.models.roi_models import (
    ROI,
    ROIType,
    ROIStatistics,
    ROIResult,
    AlarmThreshold,
    AlarmCondition,
)

from processing.models.alarm_models import (
    AlarmState,
)



# ==========================================================
# Pretty Printing
# ==========================================================

PASS = "[PASS]"
FAIL = "[FAIL]"


def title(text: str):

    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def passed(message: str):

    print(f"{PASS} {message}")


def failed(message: str):

    print(f"{FAIL} {message}")


tests_run = 0
tests_failed = 0


def run_test(name, func):

    global tests_run
    global tests_failed

    tests_run += 1

    print(f"\n{name}")

    try:

        func()

        passed(name)

    except Exception:

        tests_failed += 1

        failed(name)

        traceback.print_exc()


# ==========================================================
# Global Processor
# ==========================================================

processor = AlarmProcessor()


# ==========================================================
# Helper
# ==========================================================

def create_roi_result(

    minimum=20.0,

    maximum=30.0,

    enabled=True,

    condition=AlarmCondition.HIGH,

    threshold=25.0,

    delay=0,

):

    roi = ROI(

        roi_id="ROI_1",

        name="Test ROI",

        roi_type=ROIType.RECTANGLE,

        points=[

            (0, 0),

            (10, 10),

        ],

    )

    roi.alarm = AlarmThreshold(

        enabled=enabled,

        condition=condition,

        value=threshold,

        delay_ms=delay,

    )

    statistics = ROIStatistics(

        minimum=minimum,

        maximum=maximum,

        mean=(minimum + maximum) / 2,

        median=(minimum + maximum) / 2,

        standard_deviation=1.0,

        hotspot_x=5,

        hotspot_y=5,

        pixel_count=100,

    )

    return ROIResult(

        roi=roi,

        statistics=statistics,

    )


# ==========================================================
# Alarm Disabled
# ==========================================================

def test_alarm_disabled():

    processor.clear()

    result = create_roi_result(

        enabled=False,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    assert len(alarms) == 1

    alarm = alarms[0]

    assert alarm.active is False

    assert alarm.event is None


# ==========================================================
# HIGH Alarm
# ==========================================================

def test_high_alarm():

    processor.clear()

    result = create_roi_result(

        maximum=120,

        threshold=100,

        condition=AlarmCondition.HIGH,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active

    assert alarm.state == AlarmState.ACTIVE

    assert alarm.event is not None

    assert alarm.event.measured_value == 120

    assert alarm.event.threshold_value == 100

    print(

        f"Measured : {alarm.event.measured_value}"

    )


# ==========================================================
# HIGH Not Triggered
# ==========================================================

def test_high_not_triggered():

    processor.clear()

    result = create_roi_result(

        maximum=80,

        threshold=100,

        condition=AlarmCondition.HIGH,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active is False

    assert alarm.event is None


# ==========================================================
# LOW Alarm
# ==========================================================

def test_low_alarm():

    processor.clear()

    result = create_roi_result(

        minimum=10,

        threshold=20,

        condition=AlarmCondition.LOW,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active

    assert alarm.event.measured_value == 10

    assert alarm.event.threshold_value == 20

    print(

        f"Measured : {alarm.event.measured_value}"

    )


# ==========================================================
# LOW Not Triggered
# ==========================================================

def test_low_not_triggered():

    processor.clear()

    result = create_roi_result(

        minimum=40,

        threshold=20,

        condition=AlarmCondition.LOW,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active is False

    assert alarm.event is None


# ==========================================================
# RANGE Alarm
# ==========================================================

def test_range_alarm():

    processor.clear()

    result = create_roi_result(

        minimum=30,

        maximum=120,

        threshold=100,

        condition=AlarmCondition.RANGE,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active

    assert alarm.event.measured_value == 120

    print(

        f"Measured : {alarm.event.measured_value}"

    )


# ==========================================================
# RANGE Not Triggered
# ==========================================================

def test_range_not_triggered():

    processor.clear()

    result = create_roi_result(

        minimum=100,

        maximum=100,

        threshold=100,

        condition=AlarmCondition.RANGE,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [result],

    )

    alarm = alarms[0]

    assert alarm.active is False




# ==========================================================
# Delay Timer
# ==========================================================

def test_delay_timer():

    processor.clear()

    result = create_roi_result(

        maximum=150,

        threshold=100,

        condition=AlarmCondition.HIGH,

        delay=500,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active is False

    print("Delay timer started.")


# ==========================================================
# Delay Expiration
# ==========================================================

def test_delay_expiration():

    processor.clear()

    result = create_roi_result(

        maximum=150,

        threshold=100,

        condition=AlarmCondition.HIGH,

        delay=200,

    )

    processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    time.sleep(0.25)

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    alarm = alarms[0]

    assert alarm.active

    assert alarm.state == AlarmState.ACTIVE

    print("Delay elapsed successfully.")


# ==========================================================
# Alarm Event
# ==========================================================

def test_alarm_event():

    processor.clear()

    result = create_roi_result(

        maximum=120,

        threshold=100,

    )

    alarm = processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )[0]

    event = alarm.event

    assert event is not None

    assert event.camera_id == "CAM1"

    assert event.position_id == "POS1"

    assert event.roi_id == "ROI_1"

    assert event.roi_name == "Test ROI"

    assert event.measured_value == 120

    assert event.threshold_value == 100

    print(event)


# ==========================================================
# Active Alarm Count
# ==========================================================

def test_active_alarm_count():

    processor.clear()

    roi1 = create_roi_result(

        maximum=150,

        threshold=100,

    )

    roi2 = create_roi_result(

        maximum=160,

        threshold=100,

    )

    roi2.roi.roi_id = "ROI_2"

    processor.process(

        "CAM1",

        "POS1",

        [

            roi1,

            roi2,

        ],

    )

    assert processor.active_alarm_count == 2

    print(

        f"Active Alarms : "

        f"{processor.active_alarm_count}"

    )


# ==========================================================
# Multiple ROI Alarms
# ==========================================================

def test_multiple_roi_alarms():

    processor.clear()

    results = [

        create_roi_result(

            maximum=120,

            threshold=100,

        ),

        create_roi_result(

            maximum=70,

            threshold=100,

        ),

        create_roi_result(

            minimum=10,

            threshold=20,

            condition=AlarmCondition.LOW,

        ),

    ]

    results[1].roi.roi_id = "ROI_2"

    results[2].roi.roi_id = "ROI_3"

    alarms = processor.process(

        "CAM1",

        "POS1",

        results,

    )

    assert len(alarms) == 3

    assert alarms[0].active

    assert not alarms[1].active

    assert alarms[2].active

    print("Multiple ROI alarms processed.")


# ==========================================================
# Clear
# ==========================================================

def test_clear():

    processor.clear()

    result = create_roi_result(

        maximum=150,

        threshold=100,

    )

    processor.process(

        "CAM1",

        "POS1",

        [

            result,

        ],

    )

    processor.clear()

    assert processor.active_alarm_count == 0

    assert len(processor._previous_states) == 0

    assert len(processor._activation_times) == 0

    print("Processor cleared.")


# ==========================================================
# Alarm Key
# ==========================================================

def test_alarm_key():

    key = processor._alarm_key(

        "CAM01",

        "POS05",

        "ROI12",

    )

    assert key == "CAM01:POS05:ROI12"

    print(key)


# ==========================================================
# Measured Value
# ==========================================================

def test_measured_value():

    roi = create_roi_result(

        minimum=25,

        maximum=75,

    )

    high = processor._measured_value(

        roi,

        AlarmCondition.HIGH,

    )

    low = processor._measured_value(

        roi,

        AlarmCondition.LOW,

    )

    rng = processor._measured_value(

        roi,

        AlarmCondition.RANGE,

    )

    assert high == 75

    assert low == 25

    assert rng == 75


# ==========================================================
# Alarm Reset
# ==========================================================

def test_alarm_reset():

    processor.clear()

    high = create_roi_result(

        maximum=150,

        threshold=100,

    )

    processor.process(

        "CAM1",

        "POS1",

        [

            high,

        ],

    )

    normal = create_roi_result(

        maximum=80,

        threshold=100,

    )

    alarms = processor.process(

        "CAM1",

        "POS1",

        [

            normal,

        ],

    )

    assert alarms[0].active is False

    assert processor.active_alarm_count == 0

    print("Alarm reset correctly.")


# ==========================================================
# Main
# ==========================================================

def main():

    title("Alarm Processor Tests")

    run_test("Alarm Disabled", test_alarm_disabled)

    run_test("HIGH Alarm", test_high_alarm)

    run_test("HIGH Not Triggered", test_high_not_triggered)

    run_test("LOW Alarm", test_low_alarm)

    run_test("LOW Not Triggered", test_low_not_triggered)

    run_test("RANGE Alarm", test_range_alarm)

    run_test("RANGE Not Triggered", test_range_not_triggered)

    run_test("Delay Timer", test_delay_timer)

    run_test("Delay Expiration", test_delay_expiration)

    run_test("Alarm Event", test_alarm_event)

    run_test("Active Alarm Count", test_active_alarm_count)

    run_test("Multiple ROI Alarms", test_multiple_roi_alarms)

    run_test("Clear", test_clear)

    run_test("Alarm Key", test_alarm_key)

    run_test("Measured Value", test_measured_value)

    run_test("Alarm Reset", test_alarm_reset)

    title("Summary")

    print(f"Tests Run    : {tests_run}")

    print(f"Tests Passed : {tests_run - tests_failed}")

    print(f"Tests Failed : {tests_failed}")

    if tests_failed == 0:

        print("\nALL ALARM PROCESSOR TESTS PASSED")

    else:

        print("\nSOME TESTS FAILED")


if __name__ == "__main__":

    main()
