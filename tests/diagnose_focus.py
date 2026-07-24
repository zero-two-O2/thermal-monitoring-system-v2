"""
diagnose_focus.py — Root-cause investigation of focus command behaviour.

Phases:
  1. Trace the complete focus call path with microsecond timestamps
  2. Measure raw HALCON set_framegrabber_param() timing in isolation
  3. Read all autofocus / continuous-focus related camera parameters
  4. Monitor focus after command until 5 consecutive identical readings
  5. Document findings, determine whether production changes are needed

Run:
    python tests/diagnose_focus.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import halcon as ha
from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
WARN = "[WARN]"


# ---------------------------------------------------------------------------
# Phase 1 — Trace the complete focus call path
# ---------------------------------------------------------------------------

def phase1_trace_call_path(camera: TV46LCamera, target: float):
    print(f"\n{'='*60}")
    print(f"  Phase 1: Focus Call-Path Trace (target={target} mm)")
    print(f"{'='*60}")

    fc_before = camera.frame_count

    # 1. Time Camera.set_focus_distance()
    t0 = time.perf_counter()
    camera.set_focus_distance(target)
    t1 = time.perf_counter()
    wrapper_ms = (t1 - t0) * 1000
    print(f"  Camera.set_focus_distance()    : {wrapper_ms:>8.2f} ms")

    fc_mid = camera.frame_count

    # 2. Time raw HALCON set_framegrabber_param() directly
    t2 = time.perf_counter()
    ha.set_framegrabber_param(
        camera._acq,
        "FLK_TI_ControlFeature_SetFocusDistanceMm",
        target,
    )
    t3 = time.perf_counter()
    halcon_set_ms = (t3 - t2) * 1000
    print(f"  ha.set_framegrabber_param()    : {halcon_set_ms:>8.2f} ms")
    print(f"  Frames during set_focus: {fc_mid - fc_before}")

    # 3. Time get_parameter (wrapper)
    t4 = time.perf_counter()
    _ = camera.get_focus_distance()
    t5 = time.perf_counter()
    get_wrapper_ms = (t5 - t4) * 1000
    print(f"  Camera.get_focus_distance()    : {get_wrapper_ms:>8.2f} ms")

    # 4. Time raw HALCON get_framegrabber_param()
    t6 = time.perf_counter()
    _ = ha.get_framegrabber_param(
        camera._acq,
        "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
    )
    t7 = time.perf_counter()
    halcon_get_ms = (t7 - t6) * 1000
    print(f"  ha.get_framegrabber_param()    : {halcon_get_ms:>8.2f} ms")

    # 5. Check if _lock contention exists
    with camera._lock:
        t8 = time.perf_counter()
        _ = camera._latest_frame
        t9 = time.perf_counter()
    lock_acquire_ms = (t9 - t8) * 1000
    print(f"  camera._lock acquire + read    : {lock_acquire_ms:>8.2f} ms")

    return {
        "wrapper_ms": wrapper_ms,
        "halcon_set_ms": halcon_set_ms,
        "get_wrapper_ms": get_wrapper_ms,
        "halcon_get_ms": halcon_get_ms,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Read all autofocus / continuous-focus parameters
# ---------------------------------------------------------------------------

AUTOFOCUS_PARAMS = [
    "FLK_TI_ControlFeature_EnableAutomaticFocus",
    "FLK_TI_ControlFeature_ContinuousFocusEnabled",
    "FLK_TI_ControlFeature_FocusMode",
    "FLK_TI_ControlFeature_AutoFocusMode",
    "FLK_TI_ControlFeature_ContinuousLensAdjustment",
    "FLK_TI_ControlFeature_FocusTracking",
    "FLK_TI_ControlFeature_AutomaticLensCalibration",
    "FLK_TI_ControlFeature_FocusMoveStatus",
    "FLK_TI_ControlFeature_LensMoveTimeout",
    "FLK_TI_ControlFeature_FocusDistanceMm_Min",
    "FLK_TI_ControlFeature_FocusDistanceMm_Max",
    "FLK_TI_ControlFeature_SetFocusDistanceMm",
    "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
]

def phase2_read_autofocus_params(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 2: Camera Focus / Autofocus Parameters")
    print(f"{'='*60}")
    for name in AUTOFOCUS_PARAMS:
        try:
            val = ha.get_framegrabber_param(camera._acq, name)
            if isinstance(val, (list, tuple)):
                val = val[0]
            print(f"  {name:.<65s} {repr(val):>20}")
        except Exception as e:
            print(f"  {name:.<65s} ERROR: {e}")


# ---------------------------------------------------------------------------
# Phase 3 — Monitor focus until 5 consecutive identical readings
# ---------------------------------------------------------------------------

def phase3_monitor_settle(camera: TV46LCamera, target: float, label: str = ""):
    print(f"\n{'='*60}")
    print(f"  Phase 3: Focus Settle Monitor — {label} (target={target} mm)")
    print(f"{'='*60}")

    camera.set_focus_distance(target)
    cmd_time = time.perf_counter()

    history = []
    CONSECUTIVE_NEEDED = 5
    MAX_POLLS = 100  # 100 * 0.1s = 10s max

    print(f"  {'Poll#':>5} {'Value':>10} {'Delta':>10} {'Stable':>8}")
    print(f"  {'-----':>5} {'----------':>10} {'----------':>10} {'-------':>8}")

    stable_count = 0
    prev_value = None
    settled = False

    for i in range(MAX_POLLS):
        time.sleep(0.1)
        raw = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
        )
        if isinstance(raw, (list, tuple)):
            raw = raw[0]
        value = float(raw)
        history.append(value)

        if prev_value is not None:
            delta = value - prev_value
        else:
            delta = 0

        if prev_value is not None and abs(delta) < 1.0:
            stable_count += 1
        else:
            stable_count = 0

        stable_mark = "STABLE" if stable_count >= CONSECUTIVE_NEEDED else ""
        print(f"  {i:>5d} {value:>10.0f} {delta:>+10.0f} {stable_mark:>8}")

        if stable_count >= CONSECUTIVE_NEEDED:
            settled = True
            break

        prev_value = value

    settle_time = time.perf_counter() - cmd_time

    print(f"\n  Settled: {'YES' if settled else 'NO'}")
    print(f"  Final value: {history[-1] if history else 'N/A':.0f} mm")
    print(f"  Total settle time: {settle_time:.2f} s")
    print(f"  Values during settle: min={min(history):.0f}  max={max(history):.0f}  "
          f"range={max(history)-min(history):.0f}")

    return {
        "target": target,
        "settled": settled,
        "final_value": history[-1] if history else None,
        "settle_time": settle_time,
        "history": history,
    }


# ---------------------------------------------------------------------------
# Phase 4 — Raw HALCON timing (no wrapper)
# ---------------------------------------------------------------------------

def phase4_raw_halcon_timing(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 4: Raw HALCON Timing (no wrapper)")
    print(f"{'='*60}")

    # Measure set_framegrabber_param with various parameter types
    test_params = [
        ("FocusDistance (int)", "FLK_TI_ControlFeature_SetFocusDistanceMm", 500),
        ("FocusDistance (float)", "FLK_TI_ControlFeature_SetFocusDistanceMm", 500.0),
        ("FrameRate (read)", "FLK_TI_ControlFeature_SetFrameRate", -1),
        ("DeviceTemperature (read)", "FLK_TI_Info_CurrentDeviceTemperatureC", None),
    ]

    for label, name, val in test_params:
        if val is None:
            t0 = time.perf_counter()
            _ = ha.get_framegrabber_param(camera._acq, name)
            t1 = time.perf_counter()
        else:
            t0 = time.perf_counter()
            ha.set_framegrabber_param(camera._acq, name, val)
            t1 = time.perf_counter()
        ms = (t1 - t0) * 1000
        print(f"  {label:.<40s} {ms:>8.3f} ms")


# ---------------------------------------------------------------------------
# Phase 5 — Focus value stability over 30s with no commands
# ---------------------------------------------------------------------------

def phase5_focus_drift(camera: TV46LCamera, duration_s: float = 30.0):
    print(f"\n{'='*60}")
    print(f"  Phase 5: Focus Drift Over {duration_s}s (no commands)")
    print(f"{'='*60}")

    samples = []
    start = time.time()
    while time.time() - start < duration_s:
        raw = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
        )
        if isinstance(raw, (list, tuple)):
            raw = raw[0]
        value = float(raw)
        samples.append((time.time() - start, value))
        time.sleep(0.5)

    values = [s[1] for s in samples]
    print(f"  Samples: {len(values)}")
    print(f"  Start:   {values[0]:.0f} mm")
    print(f"  End:     {values[-1]:.0f} mm")
    print(f"  Min:     {min(values):.0f} mm")
    print(f"  Max:     {max(values):.0f} mm")
    print(f"  Drift:   {values[-1] - values[0]:.0f} mm ({abs(values[-1] - values[0]) / duration_s:.1f} mm/s)")

    return samples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  TV46L Focus Root-Cause Investigation")
    print("=" * 60)

    settings = Settings()

    print(f"\n{INFO} Discovering cameras...")
    discovery = CameraDiscovery()
    cameras = discovery.discover()

    if not cameras:
        print(f"{FAIL} No TV46L cameras discovered.")
        sys.exit(1)

    cam_info = cameras[0]
    print(f"{PASS} Discovered {cam_info.model} (SN={cam_info.serial})")

    camera = TV46LCamera(camera_info=cam_info, settings=settings)

    try:
        camera.connect()
        camera.start()
        if not camera.wait_for_first_frame(timeout=10.0):
            print(f"{FAIL} No frame received")
            sys.exit(1)
        print(f"{PASS} Camera ready")

        # ------------------------------------------------------------------
        # Phase 0 — Initial state
        # ------------------------------------------------------------------
        cur = camera.get_focus_distance()
        lo, hi = camera.get_focus_limits()
        print(f"\n  Initial focus: {cur:.0f} mm  limits: {lo:.0f} – {hi:.0f} mm")
        print(f"  Acquisition is running at ~{camera.get_fps()} FPS")

        # ------------------------------------------------------------------
        # Phase 1 — Call-path trace
        # ------------------------------------------------------------------
        phase1_trace_call_path(camera, 500)

        # ------------------------------------------------------------------
        # Phase 2 — Read all autofocus parameters
        # ------------------------------------------------------------------
        phase2_read_autofocus_params(camera)

        # ------------------------------------------------------------------
        # Phase 3 — Settle monitoring (5 consecutive identical values)
        # ------------------------------------------------------------------
        r1 = phase3_monitor_settle(camera, 1000, "Set 1000 mm")
        r2 = phase3_monitor_settle(camera, 500, "Set 500 mm")
        r3 = phase3_monitor_settle(camera, 300, "Set 300 mm")
        r4 = phase3_monitor_settle(camera, 1000000, "Set 1000000 mm (max)")

        # ------------------------------------------------------------------
        # Phase 4 — Raw HALCON timing
        # ------------------------------------------------------------------
        phase4_raw_halcon_timing(camera)

        # ------------------------------------------------------------------
        # Phase 5 — Long-term drift monitoring
        # ------------------------------------------------------------------
        drift = phase5_focus_drift(camera, 20.0)

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        print(f"\n{'='*60}")
        print("  FINDINGS SUMMARY")
        print(f"{'='*60}")
        print(f"  Focus limits reported:         {lo:.0f} – {hi:.0f} mm")
        print(f"  set_focus_distance wrapper:    ~{r1.get('cmd_time',0):.0f} ms")

        for r in [r1, r2, r3, r4]:
            h = r.get("history", [])
            print(f"  Target {r['target']:>7.0f} mm: "
                  f"settled={r['settled']} "
                  f"final={r['final_value']:.0f} mm "
                  f"in {r['settle_time']:.1f}s "
                  f"(range {min(h):.0f}-{max(h):.0f} mm)")

        print("  Autofocus enabled:            check Phase 2 output above")
        print(f"  Frame timeout count:          {camera.timeout_count}")
        print(f"  Total frames acquired:        {camera.frame_count}")

        # Show live feed
        print(f"\n{INFO} Press Q in the OpenCV window to quit.")
        while True:
            frame = camera.get_latest_frame()
            if frame is not None:
                img = frame.image
                if img.dtype == np.uint16:
                    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                if img.ndim == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                cv2.imshow("Diagnostic", img)
            if (cv2.waitKey(30) & 0xFF) == ord('q'):
                break

    except KeyboardInterrupt:
        print(f"\n{INFO} Interrupted")
    except Exception:
        print(f"\n{FAIL} Diagnostic failed:")
        import traceback
        traceback.print_exc()
        raise
    finally:
        print(f"\n{INFO} Cleaning up...")
        camera.stop()
        camera.disconnect()
        cv2.destroyAllWindows()
        print(f"{PASS} Done")


if __name__ == "__main__":
    main()
