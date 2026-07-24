"""
diagnose_fps.py — Investigate acquisition frame rate and jitter.

Phases:
  1. Measure raw frame rate, configured frame rate, stream statistics
  2. Record frame timestamps over 60s for jitter analysis
  3. Measure FPS impact during focus movement
  4. Check if Phase 4 focus writes caused the "drift" in diagnose_focus.py

Run:
    python tests/diagnose_fps.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import halcon as ha
from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
WARN = "[WARN]"


def phase1_camera_info(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 1: Camera Info & Frame Rate")
    print(f"{'='*60}")

    # Configured frame rate
    try:
        configured = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_ControlFeature_SetFrameRate",
        )
        if isinstance(configured, (list, tuple)):
            configured = configured[0]
        print(f"  Configured frame rate:          {configured}")
    except Exception as e:
        print(f"  Configured frame rate:          ERROR: {e}")

    # Actual acquisition frame rate (read from camera)
    try:
        acquisition_rate = ha.get_framegrabber_param(
            camera._acq,
            "AcquisitionFrameRate",
        )
        if isinstance(acquisition_rate, (list, tuple)):
            acquisition_rate = acquisition_rate[0]
        print(f"  AcquisitionFrameRate:           {acquisition_rate}")
    except Exception as e:
        print(f"  AcquisitionFrameRate:           ERROR: {e}")

    # Resulting frame rate
    try:
        result_rate = ha.get_framegrabber_param(
            camera._acq,
            "AcquisitionFrameRateResult",
        )
        if isinstance(result_rate, (list, tuple)):
            result_rate = result_rate[0]
        print(f"  AcquisitionFrameRateResult:     {result_rate}")
    except Exception as e:
        print(f"  AcquisitionFrameRateResult:     ERROR: {e}")

    # Stream statistics
    stats = camera.get_stream_statistics()
    print("  Stream statistics:")
    for key, val in stats.items():
        print(f"    {key}: {val}")

    # Device temperature
    try:
        temp = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_Info_CurrentDeviceTemperatureC",
        )
        if isinstance(temp, (list, tuple)):
            temp = temp[0]
        print(f"  Device temperature:             {temp} °C")
    except Exception as e:
        print(f"  Device temperature:             ERROR: {e}")


def phase2_jitter_60s(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 2: Frame Jitter Analysis (60 seconds)")
    print(f"{'='*60}")

    timestamps = []
    start = time.perf_counter()
    while time.perf_counter() - start < 60.0:
        frame = camera.get_latest_frame()
        if frame is not None:
            timestamps.append(time.perf_counter())
        time.sleep(0.001)

    if len(timestamps) < 2:
        print(f"  {FAIL} Not enough frames captured ({len(timestamps)})")
        return

    intervals = [
        (timestamps[i+1] - timestamps[i]) * 1000
        for i in range(len(timestamps) - 1)
    ]

    duration = timestamps[-1] - timestamps[0]
    avg_fps = len(timestamps) / duration if duration > 0 else 0
    avg_interval = sum(intervals) / len(intervals)
    min_interval = min(intervals)
    max_interval = max(intervals)
    std_dev = (sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)) ** 0.5

    print(f"  Total frames:                   {len(timestamps)}")
    print(f"  Duration:                       {duration:.2f} s")
    print(f"  Average FPS:                    {avg_fps:.2f}")
    print(f"  Average frame interval:         {avg_interval:.2f} ms")
    print(f"  Min frame interval:             {min_interval:.2f} ms")
    print(f"  Max frame interval:             {max_interval:.2f} ms")
    print(f"  Std deviation:                  {std_dev:.2f} ms")
    print(f"  Longest frame gap:              {max_interval:.2f} ms")

    # Show distribution of intervals
    buckets = {
        "<50ms": 0, "50-100ms": 0, "100-150ms": 0, "150-200ms": 0,
        "200-300ms": 0, "300-500ms": 0, "500ms-1s": 0, ">1s": 0,
    }
    for i in intervals:
        if i < 50:
            buckets["<50ms"] += 1
        elif i < 100:
            buckets["50-100ms"] += 1
        elif i < 150:
            buckets["100-150ms"] += 1
        elif i < 200:
            buckets["150-200ms"] += 1
        elif i < 300:
            buckets["200-300ms"] += 1
        elif i < 500:
            buckets["300-500ms"] += 1
        elif i < 1000:
            buckets["500ms-1s"] += 1
        else:
            buckets[">1s"] += 1

    print("  Interval distribution:")
    for label, count in buckets.items():
        if count > 0:
            pct = count / len(intervals) * 100
            print(f"    {label:>12s}: {count:>5d} ({pct:>5.1f}%)")

    return timestamps, intervals


def phase3_focus_fps_impact(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 3: FPS During Focus Movement")
    print(f"{'='*60}")

    targets = [1000, 1000000, 500, 300, 1000000]
    all_results = []

    for target in targets:
        # Measure baseline FPS (3s)
        ts_before = []
        start = time.perf_counter()
        while time.perf_counter() - start < 3.0:
            frame = camera.get_latest_frame()
            if frame is not None:
                ts_before.append(time.perf_counter())
            time.sleep(0.001)

        before_duration = ts_before[-1] - ts_before[0] if len(ts_before) >= 2 else 1
        before_fps = len(ts_before) / before_duration if before_duration > 0 else 0

        # Issue focus command
        cmd_start = time.perf_counter()
        camera.set_focus_distance(target)
        cmd_ms = (time.perf_counter() - cmd_start) * 1000

        # Measure during movement (5s)
        ts_during = []
        start = time.perf_counter()
        while time.perf_counter() - start < 5.0:
            frame = camera.get_latest_frame()
            if frame is not None:
                ts_during.append(time.perf_counter())
            time.sleep(0.001)

        during_duration = ts_during[-1] - ts_during[0] if len(ts_during) >= 2 else 1
        during_fps = len(ts_during) / during_duration if during_duration > 0 else 0

        # Read settled value
        cur = camera.get_focus_distance()

        print(f"  Target {target:>7.0f} mm: "
              f"cmd={cmd_ms:>7.2f}ms "
              f"fps {before_fps:>5.1f}→{during_fps:>5.1f} "
              f"settled={cur:.0f} mm")

        all_results.append({
            "target": target,
            "cmd_ms": cmd_ms,
            "before_fps": before_fps,
            "during_fps": during_fps,
            "settled_value": cur,
        })

    # Print summary
    print(f"\n  {'Summary':-^60}")
    for r in all_results:
        impact = r["during_fps"] - r["before_fps"]
        print(f"  Target {r['target']:>7.0f} mm: "
              f"{r['before_fps']:.1f} → {r['during_fps']:.1f} FPS "
              f"({'drop' if impact < 0 else 'rise'}: {abs(impact):.1f})")

    return all_results


def phase4_drift_root_cause(camera: TV46LCamera):
    print(f"\n{'='*60}")
    print("  Phase 4: Drift Root-Cause Verification")
    print(f"{'='*60}")
    print("")
    print("  Hypothesis: Phase 4 in diagnose_focus.py writes")
    print("  FLK_TI_ControlFeature_SetFocusDistanceMm = 500")
    print("  immediately before Phase 5 drift monitoring.")
    print("  Focus commands are ASYNCHRONOUS — the HALCON")
    print("  call returns immediately, but the lens takes")
    print("  1-2s to physically reach the target.")
    print("")
    print("  The 'drift' from 1000000→502 is actually the")
    print("  lens responding to the Phase 4 write target=500.")
    print("")

    # Verify: set focus to 1000000, then immediately poll
    print("  Setting focus to 1000000 mm...")
    camera.set_focus_distance(1000000)
    time.sleep(2.0)  # Wait for settle

    cur = camera.get_focus_distance()
    print(f"  Current focus: {cur:.0f} mm")

    # Now poll CurrentFocusDistanceMm every 0.1s without any write
    print("\n  Polling CurrentFocusDistanceMm for 15s (NO writes)...")
    history = []
    for i in range(150):  # 15 seconds
        raw = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
        )
        if isinstance(raw, (list, tuple)):
            raw = raw[0]
        value = float(raw)
        history.append(value)
        if i < 20 or i % 10 == 0 or value != history[-2] if len(history) >= 2 else True:
            if i == 0 or value != history[-2]:
                print(f"    t={i*0.1:>4.1f}s  focus={value:>7.0f} mm")
        time.sleep(0.1)

    drift = history[-1] - history[0]
    print(f"\n  Drift over 15s (no writes): {drift:.0f} mm")
    if abs(drift) > 100:
        print(f"  {FAIL} Focus drifts without commands — investigate further!")
    else:
        print(f"  {PASS} Focus is stable without commands.")

    # Now write focus to 1000000 again, then immediately do Phase 4's
    # writes (as int then float) and verify they trigger the "drift"
    print("\n  Simulating Phase 4 writes:")
    print("    Setting focus to 1000000 mm...")
    camera.set_focus_distance(1000000)
    time.sleep(2.0)
    cur = camera.get_focus_distance()
    print(f"    Current focus before Phase 4 writes: {cur:.0f} mm")

    # Phase 4 writes
    print("    Write SetFocusDistanceMm = 500 (int)...")
    ha.set_framegrabber_param(
        camera._acq, "FLK_TI_ControlFeature_SetFocusDistanceMm", 500
    )
    print("    Write SetFocusDistanceMm = 500 (float)...")
    ha.set_framegrabber_param(
        camera._acq, "FLK_TI_ControlFeature_SetFocusDistanceMm", 500.0
    )

    # Immediately read current focus
    cur = camera.get_focus_distance()
    print(f"    Current focus IMMEDIATELY after writes: {cur:.0f} mm")

    # Now poll to see the drift
    print("\n  Polling for 15s to observe drift from target=500...")
    history2 = []
    for i in range(150):
        raw = ha.get_framegrabber_param(
            camera._acq,
            "FLK_TI_ControlFeature_CurrentFocusDistanceMm",
        )
        if isinstance(raw, (list, tuple)):
            raw = raw[0]
        history2.append(float(raw))
        if i < 20 or i % 10 == 0 or (len(history2) >= 2 and history2[-1] != history2[-2]):
            print(f"    t={i*0.1:>4.1f}s  focus={history2[-1]:>7.0f} mm")
        time.sleep(0.1)

    final = history2[-1]
    print(f"\n  Final value after 15s: {final:.0f} mm")
    print("  Expected (from Phase 4 write): ~500 mm")
    if abs(final - 500) < 50:
        print(f"  {PASS} CONFIRMED: 'Drift' is lens responding to Phase 4 command.")
    else:
        print(f"  {WARN} Final value ({final:.0f}) ≠ 500 — further investigation needed.")
        print(f"  {WARN} (Could be thermal drift or mechanical backlash.)")

    return history, history2


def main():
    print("=" * 60)
    print("  TV46L FPS & Drift Investigation")
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

        # Phase 1: Camera info & frame rate
        phase1_camera_info(camera)

        # Phase 2: Jitter over 60s
        phase2_jitter_60s(camera)

        # Phase 3: FPS during focus movement
        phase3_focus_fps_impact(camera)

        # Phase 4: Drift root-cause verification
        phase4_drift_root_cause(camera)

        # Summary
        print(f"\n{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}")
        print(f"  Frame count:              {camera.frame_count}")
        print(f"  Timeout count:            {camera.timeout_count}")
        print(f"  Stream healthy:           {camera.stream_healthy()}")
        print(f"  Final FPS:                {camera.get_fps()}")

    except KeyboardInterrupt:
        print(f"\n{INFO} Interrupted")
    except Exception:
        print(f"\n{FAIL} Diagnostic failed:")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\n{INFO} Cleaning up...")
        camera.stop()
        camera.disconnect()
        print(f"{PASS} Done")


if __name__ == "__main__":
    main()
