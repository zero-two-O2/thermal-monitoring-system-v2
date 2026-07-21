"""
test_calibration.py

Integration tests for the calibration subsystem.

Run:

    python tests/test_calibration.py
"""

from __future__ import annotations
import sys
import time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import traceback
import numpy as np

from calibration.calibration_manager import CalibrationManager
from calibration.calibration_processor import CalibrationProcessor


# ==========================================================
# Pretty Printing
# ==========================================================

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


def title(text: str) -> None:
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def passed(message: str) -> None:
    print(f"{PASS} {message}")


def failed(message: str) -> None:
    print(f"{FAIL} {message}")


# ==========================================================
# Test Runner
# ==========================================================

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
# Global Calibration Manager
# ==========================================================

manager = CalibrationManager()


# ==========================================================
# Initialization
# ==========================================================

def test_initialize():

    manager.initialize()

    assert manager.is_initialized

    calibration = manager.get_calibration()

    assert calibration is not None

    assert calibration.enabled_ranges > 0

    assert len(calibration.ranges) == calibration.enabled_ranges


# ==========================================================
# Calibration Header
# ==========================================================

def test_header():

    calibration = manager.get_calibration()

    assert calibration.magic != 0

    assert calibration.enabled_ranges > 0

    assert calibration.enabled_mask != 0

    assert calibration.calibration_date != ""

    print(f"Magic             : 0x{calibration.magic:08X}")

    print(f"Ranges            : {calibration.enabled_ranges}")

    print(f"Enabled Mask      : 0x{calibration.enabled_mask:08X}")

    print(f"Calibration Date  : {calibration.calibration_date}")


# ==========================================================
# Calibration Ranges
# ==========================================================

def test_ranges():

    calibration = manager.get_calibration()

    for index, calibration_range in enumerate(calibration.ranges):

        print(f"\nRange {index}")

        print(
            f"Calibration : "
            f"{calibration_range.calibration_min:.2f}"
            f" -> "
            f"{calibration_range.calibration_max:.2f}"
        )

        print(
            f"Display     : "
            f"{calibration_range.display_min:.2f}"
            f" -> "
            f"{calibration_range.display_max:.2f}"
        )

        print(
            f"Segments    : "
            f"{calibration_range.num_segments}"
        )

        assert calibration_range.num_segments > 0

        assert len(calibration_range.segments) >= calibration_range.num_segments

        assert (
            calibration_range.calibration_min
            <
            calibration_range.calibration_max
        )


# ==========================================================
# Lookup Tables
# ==========================================================

def test_lookup_tables():

    calibration = manager.get_calibration()

    assert CalibrationProcessor.validate_lookup_tables(
        calibration
    )

    for index in range(calibration.enabled_ranges):

        lut = calibration.get_lookup_table(index)

        assert lut is not None

        assert lut.dtype == np.float32

        assert lut.size == CalibrationProcessor.LUT_SIZE

        assert np.isfinite(lut).all()

        print(

            f"LUT {index}"

            f"   "

            f"Min={lut.min():.2f}"

            f" "

            f"Max={lut.max():.2f}"

        )


# ==========================================================
# Rebuild LUT
# ==========================================================

def test_rebuild_lookup_tables():

    manager.rebuild_lookup_tables()

    assert manager.validate_lookup_tables()

    print("Lookup tables rebuilt successfully.")


# ==========================================================
# Raw -> Temperature
# ==========================================================

def test_raw_to_temperature():

    raw = np.random.randint(

        0,

        65535,

        (480, 640),

        dtype=np.uint16,

    )

    temperature = manager.raw_to_temperature(raw)

    assert temperature.dtype == np.float32

    assert temperature.shape == raw.shape

    assert CalibrationProcessor.validate_temperature_image(
        temperature
    )

    finite = np.isfinite(
        temperature
    )

    assert np.any(finite)

    print(

        f"Temperature"

        f" "

        f"{temperature[finite].min():.2f}"

        f"°C"

        f" -> "

        f"{temperature[finite].max():.2f}"

        f"°C"

    )


# ==========================================================
# Raw -> Display
# ==========================================================

def test_raw_to_display():

    raw = np.random.randint(

        0,

        65535,

        (480, 640),

        dtype=np.uint16,

    )

    display = manager.raw_to_display(raw)

    assert display.dtype == np.uint8

    assert display.shape == raw.shape

    assert CalibrationProcessor.validate_display_image(
        display
    )

    print(

        "Display Image"

        f" Min={display.min()}"

        f" Max={display.max()}"

    )


# ==========================================================
# Temperature -> Display
# ==========================================================

def test_temperature_to_display():

    temperature = np.random.uniform(

        20,

        100,

        (480, 640),

    ).astype(np.float32)

    display = manager.temperature_to_display(

        temperature

    )

    assert display.dtype == np.uint8

    assert display.shape == temperature.shape

    assert CalibrationProcessor.validate_display_image(

        display

    )

    print(

        "Temperature display generated."

    )


# ==========================================================
# Colormap
# ==========================================================

def test_apply_colormap():

    raw = np.random.randint(

        0,

        65535,

        (480, 640),

        dtype=np.uint16,

    )

    display = manager.raw_to_display(raw)

    colored = manager.apply_colormap(

        display,

        14,      # cv2.COLORMAP_INFERNO

    )

    assert colored.shape[0] == display.shape[0]

    assert colored.shape[1] == display.shape[1]

    assert colored.shape[2] == 3

    print("False-color image generated.")

# ==========================================================
# Temperature Statistics
# ==========================================================

def test_temperature_statistics():

    raw = np.random.randint(

        0,

        65535,

        (480, 640),

        dtype=np.uint16,

    )

    temperature = manager.raw_to_temperature(raw)

    statistics = manager.get_temperature_statistics(
        temperature
    )

    assert isinstance(statistics, dict)

    for key in (

        "minimum",

        "maximum",

        "mean",

        "median",

        "std",

    ):

        assert key in statistics

        assert np.isfinite(statistics[key])

    print(statistics)


# ==========================================================
# ROI Statistics
# ==========================================================

def test_roi_statistics():

    raw = np.random.randint(

        0,

        65535,

        (480, 640),

        dtype=np.uint16,

    )

    temperature = manager.raw_to_temperature(raw)

    mask = np.zeros(

        temperature.shape,

        dtype=bool,

    )

    mask[150:300, 200:450] = True

    statistics = manager.get_roi_statistics(

        temperature,

        mask,

    )

    for key in (

        "minimum",

        "maximum",

        "mean",

        "median",

        "std",

    ):

        assert key in statistics

        assert np.isfinite(statistics[key])

    print(statistics)


# ==========================================================
# Validate Temperature Image
# ==========================================================

def test_validate_temperature_image():

    raw = np.random.randint(

        0,

        65535,

        (100, 100),

        dtype=np.uint16,

    )

    image = manager.raw_to_temperature(raw)

    assert CalibrationProcessor.validate_temperature_image(
        image
    )

    print("Temperature image validation passed.")


# ==========================================================
# Validate Display Image
# ==========================================================

def test_validate_display_image():

    raw = np.random.randint(

        0,

        65535,

        (100, 100),

        dtype=np.uint16,

    )

    image = manager.raw_to_display(raw)

    assert CalibrationProcessor.validate_display_image(
        image
    )

    print("Display image validation passed.")


# ==========================================================
# Clear Lookup Tables
# ==========================================================

def test_clear_lookup_tables():

    manager.clear_lookup_tables()

    calibration = manager.get_calibration()

    assert len(calibration.lookup_tables) == 0

    print("Lookup tables cleared successfully.")


# ==========================================================
# Rebuild After Clear
# ==========================================================

def test_rebuild_after_clear():

    manager.rebuild_lookup_tables()

    assert manager.validate_lookup_tables()

    print("Lookup tables rebuilt successfully.")


# ==========================================================
# Calibration Range Access
# ==========================================================

def test_get_calibration_range():

    calibration = manager.get_calibration()

    calibration_range = CalibrationProcessor.get_calibration_range(
        calibration,
        0,
    )

    assert calibration_range is not None

    assert calibration_range.num_segments > 0

    print(

        f"Calibration Range: "

        f"{calibration_range.calibration_min:.2f}"

        f" -> "

        f"{calibration_range.calibration_max:.2f}"

    )


# ==========================================================
# Invalid Range Test
# ==========================================================

def test_invalid_range():

    calibration = manager.get_calibration()

    try:

        CalibrationProcessor.get_calibration_range(

            calibration,

            999,

        )

        raise AssertionError(
            "Expected IndexError."
        )

    except IndexError:

        print("IndexError correctly raised.")


# ==========================================================
# Empty Image Validation
# ==========================================================

def test_empty_images():

    empty_temperature = np.array(

        [],

        dtype=np.float32,

    )

    empty_display = np.array(

        [],

        dtype=np.uint8,

    )

    assert not CalibrationProcessor.validate_temperature_image(

        empty_temperature

    )

    assert not CalibrationProcessor.validate_display_image(

        empty_display

    )

    print("Empty image validation passed.")


# ==========================================================
# Main
# ==========================================================

def main():

    title("Calibration Subsystem Tests")

    run_test(

        "Initialization",

        test_initialize,

    )

    run_test(

        "Calibration Header",

        test_header,

    )

    run_test(

        "Calibration Ranges",

        test_ranges,

    )

    run_test(

        "Lookup Tables",

        test_lookup_tables,

    )

    run_test(

        "Rebuild Lookup Tables",

        test_rebuild_lookup_tables,

    )

    run_test(

        "Raw -> Temperature",

        test_raw_to_temperature,

    )

    run_test(

        "Raw -> Display",

        test_raw_to_display,

    )

    run_test(

        "Temperature -> Display",

        test_temperature_to_display,

    )

    run_test(

        "Apply Colormap",

        test_apply_colormap,

    )

    run_test(

        "Temperature Statistics",

        test_temperature_statistics,

    )

    run_test(

        "ROI Statistics",

        test_roi_statistics,

    )

    run_test(

        "Temperature Image Validation",

        test_validate_temperature_image,

    )

    run_test(

        "Display Image Validation",

        test_validate_display_image,

    )

    run_test(

        "Clear Lookup Tables",

        test_clear_lookup_tables,

    )

    run_test(

        "Rebuild After Clear",

        test_rebuild_after_clear,

    )

    run_test(

        "Calibration Range Access",

        test_get_calibration_range,

    )

    run_test(

        "Invalid Range",

        test_invalid_range,

    )

    run_test(

        "Empty Image Validation",

        test_empty_images,

    )

    title("Summary")

    print(f"Tests Run    : {tests_run}")

    print(f"Tests Passed : {tests_run - tests_failed}")

    print(f"Tests Failed : {tests_failed}")

    if tests_failed == 0:

        print("\nALL CALIBRATION TESTS PASSED")

    else:

        print("\nSOME TESTS FAILED")


if __name__ == "__main__":

    main()