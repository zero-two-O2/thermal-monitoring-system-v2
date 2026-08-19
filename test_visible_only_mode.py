"""
test_visible_only_mode.py

Headless tests for the Visible Only (VL_ONLY) acquisition mode in
halcon_camera_diagnosis.py. The HALCON runtime is stubbed, so no camera and
no HALCON license are required.

Run (any interpreter with numpy + PyQt6):

    python test_visible_only_mode.py

The module under test imports `halcon` and `PyQt6` at module level, so the
stub must be installed into sys.modules before that import happens. This file
declares its own `halcon` stub for exactly that reason.
"""

import os
import sys
import types

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# HALCON stub
# ---------------------------------------------------------------------------


class StubError(Exception):
    error_code = 0


def _timeout_error() -> StubError:
    err = StubError("grab timeout 5322")
    err.error_code = 5322
    return err


class FakeFG:
    def __init__(self, name: int) -> None:
        self.name = name


class FakeHalcon:
    """Records every call so tests can assert what the strategy did."""

    def __init__(self) -> None:
        self.calls = []
        self._count = 0
        self.fail_selector = None
        self.timeout_visible = False
        self._frame = object()

    def open_framegrabber(self, *args: object) -> FakeFG:
        self._count += 1
        return FakeFG(self._count)

    def set_framegrabber_param(self, fg: FakeFG, name: str, value: object) -> None:
        if name == "FLK_TI_StreamDataSourceSelector" and value == self.fail_selector:
            raise StubError("unsupported stream source value")
        self.calls.append(("set_param", name, value))

    def get_framegrabber_param(self, fg: FakeFG, name: str) -> object:
        return {
            "image_width": 640,
            "image_height": 480,
            "pixel_format": "yuv422_8",
        }.get(name, 0)

    def grab_image_start(self, fg: FakeFG, *args: object) -> None:
        self.calls.append(("grab_image_start", fg.name))

    def grab_image_async(self, fg: FakeFG, timeout: int) -> object:
        self.calls.append(("grab_image_async", fg.name, timeout))
        if self.timeout_visible:
            raise _timeout_error()
        return self._frame

    def himage_as_numpy_array(self, image: object) -> object:
        return np.zeros((480, 640), dtype=np.uint16)

    def close_framegrabber(self, fg: FakeFG) -> None:
        self.calls.append(("close", fg.name))


def _install_halcon_stub() -> FakeHalcon:
    fake = FakeHalcon()
    module = types.ModuleType("halcon")
    for name in (
        "open_framegrabber",
        "set_framegrabber_param",
        "get_framegrabber_param",
        "grab_image_start",
        "grab_image_async",
        "himage_as_numpy_array",
        "close_framegrabber",
    ):
        setattr(module, name, getattr(fake, name))
    sys.modules["halcon"] = module
    return fake


FAKE = _install_halcon_stub()
import halcon_camera_diagnosis as m  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal test harness (project style: PASS/FAIL counters)
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"

tests_run = 0
tests_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global tests_run, tests_failed
    tests_run += 1
    if condition:
        print(f"{PASS} {name}")
    else:
        tests_failed += 1
        print(f"{FAIL} {name} {detail}")


def _set_params(*names: str):
    return [
        c for c in FAKE.calls if c[0] == "set_param" and c[1] in names
    ]


def _selectors():
    return [
        c[2]
        for c in FAKE.calls
        if c[0] == "set_param" and c[1] == "FLK_TI_StreamDataSourceSelector"
    ]


def _make_visible_only():
    strategy = m._make_strategy(
        m.STRATEGY_VISIBLE_ONLY, "device-id", 9, "192.168.0.10"
    )
    return strategy


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_factory_wiring() -> None:
    strategy = _make_visible_only()
    check("factory returns VisibleOnlyStrategy", isinstance(strategy, m.VisibleOnlyStrategy))
    check("single-handle acquisition", strategy.acq.single_handle is True)
    check("primary stream is VL_Data", strategy.primary_stream == m.VISIBLE_STREAM)
    check("visible capable", strategy.visible_capable is True)


def test_visible_only_open() -> None:
    FAKE.calls.clear()
    strategy = _make_visible_only()
    strategy.open()
    check("selector set to VL_Data only", _selectors() == [m.VISIBLE_STREAM])
    check("bits_per_channel is -1", _set_params("bits_per_channel") == [("set_param", "bits_per_channel", -1)])
    ir_params = _set_params(
        "FLK_TI_ControlFeature_SetFrameRate", "FLK_TI_ControlFeature_REControlCmd"
    )
    check("no IR-only params set", not ir_params, f"got {ir_params}")
    check("acquisition started", ("grab_image_start", 1) in FAKE.calls)
    check("dual_mode disabled", strategy.acq.dual_mode is False)
    check("visible_only flagged", strategy.acq._visible_only is True)


def test_visible_only_step() -> None:
    FAKE.calls.clear()
    strategy = _make_visible_only()
    strategy.open()
    result = strategy.step()
    check("step returns visible frame", result.visible_image is not None)
    check("step never returns IR frame", result.ir_image is None)
    grabbed = [c for c in FAKE.calls if c[0] == "grab_image_async"]
    check("step grabbed non-blocking visible frame", grabbed != [] and grabbed[0][2] == 0)


def test_visible_only_no_ir_path() -> None:
    FAKE.calls.clear()
    strategy = _make_visible_only()
    strategy.open()
    for _ in range(3):
        strategy.step()
    check("IR_Data selector never requested", "IR_Data" not in _selectors())
    check("IR-only params never set", not _set_params("FLK_TI_ControlFeature_SetFrameRate"))


def test_visible_only_open_failure() -> None:
    FAKE.calls.clear()
    FAKE.fail_selector = m.VISIBLE_STREAM
    strategy = _make_visible_only()
    try:
        strategy.open()
        check("open raised on selector failure", False, "no exception raised")
    except RuntimeError as exc:
        check("open failure is clear", "Visible-only acquisition failed:" in str(exc), str(exc))
    finally:
        FAKE.fail_selector = None


def test_visible_only_missing_stream() -> None:
    FAKE.calls.clear()
    FAKE.timeout_visible = True
    strategy = _make_visible_only()
    strategy.open()
    try:
        strategy.grab_first_frame()
        check("first frame raised on timeout", False, "no exception raised")
    except RuntimeError as exc:
        check(
            "missing stream reported",
            "Visible/VL stream is not available on this camera." in str(exc),
            str(exc),
        )
    finally:
        FAKE.timeout_visible = False


def test_ir_only_regression() -> None:
    FAKE.calls.clear()
    strategy = m._make_strategy(m.STRATEGY_BASELINE, "device-id", 9, "192.168.0.10")
    strategy.open()
    check("baseline selects IR_Data", _selectors() == [m.IR_STREAM])
    check("baseline uses 16-bit", _set_params("bits_per_channel") == [("set_param", "bits_per_channel", 16)])
    check("baseline keeps IR-only params", bool(_set_params("FLK_TI_ControlFeature_SetFrameRate")))


def test_time_sliced_regression() -> None:
    FAKE.calls.clear()
    strategy = m._make_strategy(m.STRATEGY_TIME_SLICED, "device-id", 9, "192.168.0.10")
    strategy.open()
    result = strategy.step()
    check("time-sliced still delivers IR first", result.ir_image is not None)


def test_strategy_registry() -> None:
    check("visible only in strategy labels", m.STRATEGY_VISIBLE_ONLY in m.STRATEGY_LABELS)
    check("visible only in strategy order", m.STRATEGY_VISIBLE_ONLY in m.STRATEGY_ORDER)
    check("label is clear", "Visible Only" in m.STRATEGY_LABELS[m.STRATEGY_VISIBLE_ONLY])


def test_close() -> None:
    FAKE.calls.clear()
    strategy = _make_visible_only()
    strategy.open()
    strategy.close()
    closed = [c for c in FAKE.calls if c[0] == "close"]
    check("close closed the VL handle", len(closed) >= 1, f"got {closed}")


def main() -> None:
    print("=" * 70)
    print("Visible Only (VL_ONLY) mode tests")
    print("=" * 70)
    for test in (
        test_factory_wiring,
        test_visible_only_open,
        test_visible_only_step,
        test_visible_only_no_ir_path,
        test_visible_only_open_failure,
        test_visible_only_missing_stream,
        test_ir_only_regression,
        test_time_sliced_regression,
        test_strategy_registry,
        test_close,
    ):
        test()
    print()
    print(f"Tests run: {tests_run} | Passed: {tests_run - tests_failed} | Failed: {tests_failed}")
    print("=" * 70)
    if tests_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()