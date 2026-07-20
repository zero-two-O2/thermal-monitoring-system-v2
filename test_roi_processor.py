"""
test_roi_processor.py

Integration tests for ROIProcessor.

Run:

    python test_roi_processor.py
"""

from __future__ import annotations
import traceback
import numpy as np
from processing.roi_processor import ROIProcessor
from processing.models.processing_models import (
    RawFrame,
    ProcessedFrame,
)
from processing.models.roi_models import (
    ROI,
    ROIType,
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
# Global ROI Processor
processor = ROIProcessor()

# ==========================================================
# Helper Functions
def create_temperature_image():
    """
    Creates a predictable temperature image.
    Value at pixel (x,y):
        temperature = x + y
    """
    h = 480
    w = 640
    x = np.arange(w, dtype=np.float32)
    y = np.arange(h, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    return xx + yy


def create_processed_frame():
    temperature = create_temperature_image()
    display = np.zeros(
        temperature.shape,
        dtype=np.uint8,
    )
    raw = RawFrame(
        image=np.zeros(
            temperature.shape,
            dtype=np.uint16,
        )
    )
    return ProcessedFrame(
        raw_frame=raw,
        temperature_image=temperature,
        display_image=display,
    )


# ==========================================================
# ROI Factory
# ==========================================================

def rectangle_roi():
    return ROI(
        roi_id="rect",
        name="Rectangle",
        roi_type=ROIType.RECTANGLE,
        points=[
            (100, 100),
            (200, 200),
        ],
    )


def polygon_roi():
    return ROI(
        roi_id="poly",
        name="Polygon",
        roi_type=ROIType.POLYGON,
        points=[
            (100, 100),
            (200, 100),
            (250, 180),
            (150, 250),
        ],

    )


def circle_roi():
    return ROI(
        roi_id="circle",
        name="Circle",
        roi_type=ROIType.CIRCLE,
        points=[
            (300, 300),
        ],
        radius=50,
    )

# ==========================================================
# ROI Loading
# ==========================================================

def test_load_rois():
    processor.load(
        [
            rectangle_roi(),
            polygon_roi(),
            circle_roi(),
        ]
    )
    assert len(processor._rois) == 3
    print(
        f"Loaded {len(processor._rois)} ROIs"
    )


# ==========================================================
# Add ROI
# ==========================================================

def test_add_roi():

    processor.clear()

    roi = rectangle_roi()

    processor.add_roi(roi)

    assert len(processor._rois) == 1

    assert "rect" in processor._rois


# ==========================================================
# Remove ROI
# ==========================================================

def test_remove_roi():

    processor.clear()

    processor.add_roi(

        rectangle_roi()

    )

    processor.remove_roi(

        "rect"

    )

    assert len(processor._rois) == 0


# ==========================================================
# Update ROI
# ==========================================================

def test_update_roi():

    processor.clear()

    roi = rectangle_roi()

    processor.add_roi(roi)

    roi.points = [

        (50, 50),

        (120, 120),

    ]

    processor.update_roi(

        roi

    )

    assert processor._rois["rect"].points[0] == (

        50,

        50,

    )


# ==========================================================
# Clear ROIs
# ==========================================================

def test_clear():

    processor.load(

        [

            rectangle_roi(),

            polygon_roi(),

        ]

    )

    processor.clear()

    assert len(processor._rois) == 0

    assert len(processor._mask_cache) == 0


# ==========================================================
# Rectangle ROI
# ==========================================================

def test_rectangle_roi():

    processor.clear()

    processor.add_roi(

        rectangle_roi()

    )

    frame = create_processed_frame()

    results = processor.process(

        frame

    )

    assert len(results) == 1

    result = results[0]

    assert result.roi.roi_type == ROIType.RECTANGLE

    stats = result.statistics

    assert stats.pixel_count > 0

    assert stats.maximum >= stats.minimum

    print(

        f"Pixels : {stats.pixel_count}"

    )

    print(

        f"Min : {stats.minimum:.2f}"

    )

    print(

        f"Max : {stats.maximum:.2f}"

    )


# ==========================================================
# Polygon ROI
# ==========================================================

def test_polygon_roi():

    processor.clear()

    processor.add_roi(

        polygon_roi()

    )

    frame = create_processed_frame()

    results = processor.process(

        frame

    )

    assert len(results) == 1

    stats = results[0].statistics

    assert stats.pixel_count > 0

    assert stats.maximum >= stats.minimum

    print(

        f"Pixels : {stats.pixel_count}"

    )


# ==========================================================
# Circle ROI
# ==========================================================

def test_circle_roi():

    processor.clear()

    processor.add_roi(

        circle_roi()

    )

    frame = create_processed_frame()

    results = processor.process(

        frame

    )

    assert len(results) == 1

    stats = results[0].statistics

    assert stats.pixel_count > 0

    assert stats.maximum >= stats.minimum

    print(

        f"Pixels : {stats.pixel_count}"

    )

# ==========================================================
# Cache Creation
# ==========================================================

def test_mask_cache():

    processor.clear()

    processor.load(
        [
            rectangle_roi(),
            polygon_roi(),
            circle_roi(),
        ]
    )

    frame = create_processed_frame()

    processor.process(frame)

    assert len(processor._mask_cache) == 3

    assert processor._mask_size == frame.temperature_image.shape

    print(
        f"Cached Masks : {len(processor._mask_cache)}"
    )


# ==========================================================
# Cache Invalidation
# ==========================================================

def test_cache_invalidation():

    processor.clear()

    processor.add_roi(
        rectangle_roi()
    )

    frame = create_processed_frame()

    processor.process(frame)

    assert len(processor._mask_cache) == 1

    processor.invalidate_cache()

    assert len(processor._mask_cache) == 0

    assert processor._mask_size is None

    print("Cache invalidated successfully.")


# ==========================================================
# Statistics Verification
# ==========================================================

def test_statistics():

    processor.clear()

    processor.add_roi(
        rectangle_roi()
    )

    frame = create_processed_frame()

    result = processor.process(frame)[0]

    stats = result.statistics

    assert stats.minimum <= stats.mean <= stats.maximum

    assert stats.minimum <= stats.median <= stats.maximum

    assert stats.standard_deviation >= 0

    assert stats.pixel_count > 0

    print(stats)


# ==========================================================
# Hotspot Detection
# ==========================================================

def test_hotspot():

    processor.clear()

    roi = rectangle_roi()

    processor.add_roi(roi)

    frame = create_processed_frame()

    result = processor.process(frame)[0]

    stats = result.statistics

    x = stats.hotspot_x
    y = stats.hotspot_y

    assert x >= 0
    assert y >= 0

    value = frame.temperature_image[y, x]

    assert value == stats.maximum

    print(

        f"Hotspot : ({x}, {y})"

        f"  "

        f"{value:.2f}°C"

    )


# ==========================================================
# Disabled ROI
# ==========================================================

def test_disabled_roi():

    processor.clear()

    roi = rectangle_roi()

    roi.enabled = False

    processor.add_roi(roi)

    frame = create_processed_frame()

    results = processor.process(frame)

    assert len(results) == 0

    print("Disabled ROI skipped.")


# ==========================================================
# Empty ROI
# ==========================================================

def test_empty_roi():

    processor.clear()

    roi = ROI(

        roi_id="empty",

        name="Empty",

        roi_type=ROIType.RECTANGLE,

        points=[],

    )

    processor.add_roi(roi)

    frame = create_processed_frame()

    results = processor.process(frame)

    assert len(results) == 1

    stats = results[0].statistics

    assert stats.pixel_count == 0

    assert np.isnan(stats.minimum)

    print("Empty ROI handled correctly.")


# ==========================================================
# NaN Handling
# ==========================================================

def test_nan_handling():

    processor.clear()

    processor.add_roi(
        rectangle_roi()
    )

    frame = create_processed_frame()

    frame.temperature_image[
        120:140,
        120:140,
    ] = np.nan

    result = processor.process(frame)[0]

    stats = result.statistics

    assert np.isfinite(stats.minimum)

    assert np.isfinite(stats.maximum)

    print("NaN handling passed.")


# ==========================================================
# Multiple ROIs
# ==========================================================

def test_multiple_rois():

    processor.clear()

    processor.load(
        [
            rectangle_roi(),
            polygon_roi(),
            circle_roi(),
        ]
    )

    frame = create_processed_frame()

    results = processor.process(frame)

    assert len(results) == 3

    print(
        f"Processed {len(results)} ROIs"
    )


# ==========================================================
# Invalid Rectangle
# ==========================================================

def test_invalid_rectangle():

    processor.clear()

    roi = ROI(

        roi_id="bad",

        name="Bad",

        roi_type=ROIType.RECTANGLE,

        points=[

            (100, 100),

        ],

    )

    processor.add_roi(roi)

    frame = create_processed_frame()

    results = processor.process(frame)

    stats = results[0].statistics

    assert stats.pixel_count == 0

    print("Invalid rectangle handled.")


# ==========================================================
# Invalid Circle
# ==========================================================

def test_invalid_circle():

    processor.clear()

    roi = ROI(

        roi_id="circle",

        name="Circle",

        roi_type=ROIType.CIRCLE,

        points=[

            (100, 100),

        ],

        radius=0,

    )

    processor.add_roi(roi)

    frame = create_processed_frame()

    results = processor.process(frame)

    stats = results[0].statistics

    assert stats.pixel_count == 0

    print("Invalid circle handled.")


# ==========================================================
# Main
# ==========================================================

def main():

    title("ROI Processor Tests")

    run_test("Load ROIs", test_load_rois)

    run_test("Add ROI", test_add_roi)

    run_test("Remove ROI", test_remove_roi)

    run_test("Update ROI", test_update_roi)

    run_test("Clear ROIs", test_clear)

    run_test("Rectangle ROI", test_rectangle_roi)

    run_test("Polygon ROI", test_polygon_roi)

    run_test("Circle ROI", test_circle_roi)

    run_test("Mask Cache", test_mask_cache)

    run_test("Cache Invalidation", test_cache_invalidation)

    run_test("Statistics", test_statistics)

    run_test("Hotspot", test_hotspot)

    run_test("Disabled ROI", test_disabled_roi)

    run_test("Empty ROI", test_empty_roi)

    run_test("NaN Handling", test_nan_handling)

    run_test("Multiple ROIs", test_multiple_rois)

    run_test("Invalid Rectangle", test_invalid_rectangle)

    run_test("Invalid Circle", test_invalid_circle)

    title("Summary")

    print(f"Tests Run    : {tests_run}")

    print(f"Tests Passed : {tests_run - tests_failed}")

    print(f"Tests Failed : {tests_failed}")

    if tests_failed == 0:

        print("\nALL ROI PROCESSOR TESTS PASSED")

    else:

        print("\nSOME TESTS FAILED")


if __name__ == "__main__":

    main()