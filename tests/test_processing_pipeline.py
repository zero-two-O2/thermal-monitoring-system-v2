"""
test_processing_pipeline.py

Integration tests for ProcessingPipeline.

Run:

    python test_processing_pipeline.py
"""

from __future__ import annotations
import sys
import time
import traceback
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calibration.calibration_manager import CalibrationManager
from processing.pipeline.processing_pipeline import ProcessingPipeline
from processing.roi_processor import ROIProcessor
from processing.alarm_processor import AlarmProcessor
from processing.models.processing_models import (
    RawFrame,
)
from processing.models.roi_models import (
    ROI,
    ROIType,
    AlarmThreshold,
    AlarmCondition,
)


# ==========================================================
# Pretty Printing
# ==========================================================

PASS = "[PASS]"
FAIL = "[FAIL]"
tests_run = 0
tests_failed = 0


def title(text: str):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def passed(message: str):
    print(f"{PASS} {message}")


def failed(message: str):
    print(f"{FAIL} {message}")


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
# Global Objects
# ==========================================================

calibration_manager = CalibrationManager()
calibration_manager.initialize()
roi_processor = ROIProcessor()
alarm_processor = AlarmProcessor()
pipeline = ProcessingPipeline(
    calibration_manager,
    roi_processor,
    alarm_processor,
)

def test_calibration_initialized():
    assert calibration_manager.is_initialized
    assert calibration_manager.validate_lookup_tables()
# ==========================================================
# Helpers
# ==========================================================

def create_temperature_gradient():
    """
    Create a deterministic thermal image.
    """
    image = np.zeros(
        (240, 320),
        dtype=np.uint16,
    )
    for y in range(240):
        image[y] = np.arange(320) + y
    return image


def create_raw_frame():
    image = create_temperature_gradient()
    return RawFrame(
        image=image,
        range_index=0,
        timestamp=time.time(),
        frame_number=1,
    )

def create_roi(
    roi_id="ROI_1",
    threshold=400,
    enabled=True,
):

    roi = ROI(
        roi_id=roi_id,
        name=roi_id,
        roi_type=ROIType.RECTANGLE,
        points=[
            (50, 50),
            (150, 150),
        ],
    )
    roi.alarm = AlarmThreshold(
        enabled=enabled,
        condition=AlarmCondition.HIGH,
        value=threshold,
    )
    return roi


# ==========================================================
# Pipeline Initialization
# ==========================================================

def test_pipeline_creation():
    assert pipeline is not None
    assert pipeline.calibration_manager is calibration_manager
    assert pipeline.roi_processor is roi_processor
    assert pipeline.alarm_processor is alarm_processor


# ==========================================================
# Single Frame
# ==========================================================

def test_single_frame():
    pipeline.clear_rois()
    pipeline.clear_alarms()
    pipeline.load_rois(
        [
            create_roi(),
        ]
    )
    raw = create_raw_frame()
    result = pipeline.process(
        camera_id="CAM01",
        position_id="POS01",
        raw_frame=raw,
    )
    assert result is not None
    assert result.raw_frame is raw
    assert result.processed_frame is not None
    assert result.statistics is not None
    assert len(result.roi_results) == 1
    print(
        f"ROIs : {len(result.roi_results)}"
    )


# ==========================================================
# No ROI
# ==========================================================

def test_no_rois():
    pipeline.clear_rois()
    pipeline.clear_alarms()
    raw = create_raw_frame()
    result = pipeline.process(
        "CAM01",
        "POS01",
        raw,
    )
    assert len(result.roi_results) == 0
    assert len(result.alarms) == 0
    print("No ROI configuration handled.")


# ==========================================================
# Multiple ROIs
# ==========================================================

def test_multiple_rois():
    pipeline.clear_rois()
    pipeline.clear_alarms()
    pipeline.load_rois(
        [
            create_roi("ROI_1"),
            create_roi("ROI_2"),
            create_roi("ROI_3"),
        ]
    )

    raw = create_raw_frame()
    result = pipeline.process(
        "CAM01",
        "POS01",
        raw,
    )
    assert len(result.roi_results) == 3
    print(
        f"ROI Results : "
        f"{len(result.roi_results)}"
    )


# ==========================================================
# ROI Result Validation
# ==========================================================

def test_roi_results():
    pipeline.clear_rois()
    pipeline.load_rois(
        [
            create_roi(),
        ]
    )
    raw = create_raw_frame()
    result = pipeline.process(
        "CAM01",
        "POS01",
        raw,
    )

    roi = result.roi_results[0]
    assert roi.statistics is not None
    assert roi.statistics.pixel_count > 0
    assert roi.statistics.maximum >= roi.statistics.minimum
    print(
        f"ROI Max : "
        f"{roi.statistics.maximum:.2f}"
    )


# ==========================================================
# Processed Frame
# ==========================================================

def test_processed_frame():
    pipeline.clear_rois()
    raw = create_raw_frame()
    result = pipeline.process(
        "CAM01",
        "POS01",
        raw,
    )
    pf = result.processed_frame
    assert pf.temperature_image is not None
    assert pf.display_image is not None
    assert pf.raw_frame is raw
    print(
        f"Temperature Shape : "
        f"{pf.temperature_image.shape}"
    )

# ==========================================================
# Camera Statistics
# ==========================================================

def test_camera_statistics():

    pipeline.clear_rois()

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    stats = result.statistics

    assert stats is not None

    assert stats.maximum >= stats.minimum

    assert stats.mean >= stats.minimum

    assert stats.mean <= stats.maximum

    assert stats.standard_deviation >= 0

    print(

        f"Min : {stats.minimum:.2f}"

    )

    print(

        f"Max : {stats.maximum:.2f}"

    )

    print(

        f"Mean : {stats.mean:.2f}"

    )


# ==========================================================
# FrameResult
# ==========================================================

def test_frame_result():

    pipeline.clear_rois()

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert result.raw_frame is raw

    assert result.processed_frame is not None

    assert result.statistics is not None

    assert isinstance(result.roi_results, list)

    assert isinstance(result.alarms, list)


# ==========================================================
# Frame Metadata
# ==========================================================

def test_frame_metadata():

    pipeline.clear_rois()

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert result.raw_frame.frame_number == raw.frame_number

    assert result.raw_frame.timestamp == raw.timestamp

    assert result.raw_frame.range_index == raw.range_index

    print(

        f"Frame : {raw.frame_number}"

    )


# ==========================================================
# HIGH Alarm Integration
# ==========================================================

def test_high_alarm_pipeline():

    pipeline.clear_rois()

    pipeline.clear_alarms()

    pipeline.load_rois(

        [

            create_roi(

                threshold=100,

            ),

        ]

    )

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert len(result.alarms) == 1

    alarm = result.alarms[0]

    assert alarm.active

    assert alarm.event is not None

    print(

        f"Alarm Value : "

        f"{alarm.event.measured_value:.2f}"

    )


# ==========================================================
# No Alarm
# ==========================================================

def test_no_alarm_pipeline():

    pipeline.clear_rois()

    pipeline.clear_alarms()

    pipeline.load_rois(

        [

            create_roi(

                threshold=10000,

            ),

        ]

    )

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert len(result.alarms) == 1

    assert result.alarms[0].active is False

    print("Alarm correctly not triggered.")


# ==========================================================
# Multiple Alarm Integration
# ==========================================================

def test_multiple_alarm_pipeline():

    pipeline.clear_rois()

    pipeline.clear_alarms()

    roi1 = create_roi(

        roi_id="ROI_1",

        threshold=100,

    )

    roi2 = create_roi(

        roi_id="ROI_2",

        threshold=10000,

    )

    roi3 = create_roi(

        roi_id="ROI_3",

        threshold=150,

    )

    pipeline.load_rois(

        [

            roi1,

            roi2,

            roi3,

        ]

    )

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert len(result.alarms) == 3

    assert result.alarms[0].active

    assert result.alarms[1].active is False

    assert result.alarms[2].active

    print(

        f"Triggered : "

        f"{sum(a.active for a in result.alarms)}"

    )


# ==========================================================
# Clear ROIs
# ==========================================================

def test_clear_rois():

    pipeline.load_rois(

        [

            create_roi(),

        ]

    )

    pipeline.clear_rois()

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert len(result.roi_results) == 0

    print("ROI list cleared.")


# ==========================================================
# Clear Alarms
# ==========================================================

def test_clear_alarms():

    pipeline.clear_alarms()

    assert pipeline.alarm_processor.active_alarm_count == 0

    print("Alarm processor cleared.")


# ==========================================================
# Repeated Processing
# ==========================================================

def test_repeated_processing():

    pipeline.clear_rois()

    pipeline.load_rois(

        [

            create_roi(

                threshold=100,

            ),

        ]

    )

    raw = create_raw_frame()

    for _ in range(10):

        result = pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        assert result.processed_frame is not None

        assert len(result.roi_results) == 1

    print("Repeated processing successful.")


# ==========================================================
# Empty Image
# ==========================================================

def test_empty_image():

    pipeline.clear_rois()

    raw = RawFrame(

        image=np.empty((0, 0), dtype=np.uint16),

        range_index=0,

        timestamp=time.time(),

        frame_number=1,

    )

    try:

        pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        print("Empty image accepted.")

    except Exception as ex:

        print(f"Expected Exception : {type(ex).__name__}")


# ==========================================================
# NaN Image
# ==========================================================

def test_nan_image():

    pipeline.clear_rois()

    image = np.full(

        (240, 320),

        np.nan,

        dtype=np.float32,

    )

    raw = RawFrame(

        image=image,

        range_index=0,

        timestamp=time.time(),

        frame_number=1,

    )

    try:

        result = pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        print(result.statistics)

    except Exception as ex:

        print(f"Expected Exception : {type(ex).__name__}")


# ==========================================================
# Invalid Image Shape
# ==========================================================

def test_invalid_shape():

    pipeline.clear_rois()

    raw = RawFrame(

        image=np.zeros(

            (240,),

            dtype=np.uint16,

        ),

        range_index=0,

        timestamp=time.time(),

        frame_number=1,

    )

    try:

        pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        print("Invalid shape accepted.")

    except Exception as ex:

        print(f"Expected Exception : {type(ex).__name__}")


# ==========================================================
# Invalid Image Type
# ==========================================================

def test_invalid_dtype():

    pipeline.clear_rois()

    raw = RawFrame(

        image=np.random.random(

            (240, 320)

        ),

        range_index=0,

        timestamp=time.time(),

        frame_number=1,

    )

    try:

        pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        print("Unexpected dtype accepted.")

    except Exception as ex:

        print(f"Expected Exception : {type(ex).__name__}")


# ==========================================================
# Invalid Range Index
# ==========================================================

def test_invalid_range():

    pipeline.clear_rois()

    raw = create_raw_frame()

    raw.range_index = 999

    try:

        pipeline.process(

            "CAM01",

            "POS01",

            raw,

        )

        print("Unexpected range accepted.")

    except Exception as ex:

        print(f"Expected Exception : {type(ex).__name__}")


# ==========================================================
# Throughput Test
# ==========================================================

def test_throughput():

    pipeline.clear_rois()

    pipeline.load_rois(

        [

            create_roi(

                threshold=100,

            ),

        ]

    )

    start = time.perf_counter()

    frames = 100

    raw = create_raw_frame()

    start = time.perf_counter()

    for i in range(frames):

        raw.frame_number = i

        pipeline.process(
                "CAM01",
                "POS01",
                raw,
        )

    elapsed = time.perf_counter() - start

    elapsed = time.perf_counter() - start

    fps = frames / elapsed

    print(f"Frames : {frames}")

    print(f"Time   : {elapsed:.3f} sec")

    print(f"FPS    : {fps:.2f}")


# ==========================================================
# Stress Test
# ==========================================================

def test_stress():

    pipeline.clear_rois()

    rois = []

    for i in range(50):

        rois.append(

            create_roi(

                roi_id=f"ROI_{i}",

                threshold=100,

            )

        )

    pipeline.load_rois(rois)

    raw = create_raw_frame()

    result = pipeline.process(

        "CAM01",

        "POS01",

        raw,

    )

    assert len(result.roi_results) == 50

    assert len(result.alarms) == 50

    print(

        f"Processed {len(result.roi_results)} ROIs"

    )


# ==========================================================
# Main
# ==========================================================

def main():

    title("Processing Pipeline Tests")

    run_test("Pipeline Creation", test_pipeline_creation)

    run_test("Single Frame", test_single_frame)

    run_test("No ROIs", test_no_rois)

    run_test("Multiple ROIs", test_multiple_rois)

    run_test("ROI Results", test_roi_results)

    run_test("Processed Frame", test_processed_frame)

    run_test("Camera Statistics", test_camera_statistics)

    run_test("FrameResult", test_frame_result)

    run_test("Frame Metadata", test_frame_metadata)

    run_test("HIGH Alarm", test_high_alarm_pipeline)

    run_test("No Alarm", test_no_alarm_pipeline)

    run_test("Multiple Alarm", test_multiple_alarm_pipeline)

    run_test("Clear ROIs", test_clear_rois)

    run_test("Clear Alarms", test_clear_alarms)

    run_test("Repeated Processing", test_repeated_processing)

    run_test("Empty Image", test_empty_image)

    run_test("NaN Image", test_nan_image)

    run_test("Invalid Shape", test_invalid_shape)

    run_test("Invalid Dtype", test_invalid_dtype)

    run_test("Invalid Range", test_invalid_range)

    run_test("Throughput", test_throughput)

    run_test("Stress Test", test_stress)

    title("Summary")

    print(f"Tests Run    : {tests_run}")

    print(f"Tests Passed : {tests_run - tests_failed}")

    print(f"Tests Failed : {tests_failed}")

    if tests_failed == 0:

        print("\nALL PROCESSING PIPELINE TESTS PASSED")

    else:

        print("\nSOME TESTS FAILED")


if __name__ == "__main__":

    main()