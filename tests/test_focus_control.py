"""
test_focus_control.py

Live hardware test for TV46L motorized focus control.

Run:
    python tests/test_focus_control.py

Controls:
    +   Increase focus by 100 mm
    -   Decrease focus by 100 mm
    0   Set maximum focus
    1   Set 300 mm
    2   Set 500 mm
    3   Set 1000 mm
    R   Read current focus
    Q   Quit
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings


PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


def display_frame(camera: TV46LCamera) -> bool:
    frame = camera.get_latest_frame()
    if frame is None:
        return False
    img = frame.image
    if img.dtype == np.uint16:
        normalized = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    else:
        normalized = img
    if normalized.ndim == 2:
        bgr = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
    else:
        bgr = normalized
    cv2.imshow("Focus Control Test", bgr)
    return True


def set_and_verify(camera: TV46LCamera, requested: float) -> None:
    camera.set_focus_distance(requested)
    time.sleep(0.2)
    actual = camera.get_focus_distance()
    print(
        f"  Requested: {requested:.0f} mm  |  "
        f"Actual: {actual:.0f} mm  |  "
        + (f"{PASS} Match" if abs(actual - requested) < 10 else f"{FAIL} Mismatch")
    )


def main():
    print("=" * 60)
    print("  TV46L Focus Control Test")
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
        print(f"{PASS} Camera connected")

        camera.start()
        print(f"{PASS} Acquisition started")

        if not camera.wait_for_first_frame(timeout=10.0):
            print(f"{FAIL} No frame received")
            sys.exit(1)
        print(f"{PASS} First frame received")

        # ------------------------------------------------------------------
        # Read initial focus state
        # ------------------------------------------------------------------
        current = camera.get_focus_distance()
        lim_min, lim_max = camera.get_focus_limits()
        print(f"\n  Current focus: {current:.0f} mm")
        print(f"  Focus limits:  {lim_min:.0f} mm – {lim_max:.0f} mm")
        print(f"{PASS} Focus state read")

        # ------------------------------------------------------------------
        # Main loop
        # ------------------------------------------------------------------
        focus_step = 100

        print(f"\n{INFO} Controls:")
        print(f"  {INFO}   + / -   Adjust focus by {focus_step} mm")
        print(f"  {INFO}   0       Set maximum focus ({lim_max:.0f} mm)")
        print(f"  {INFO}   1       Set 300 mm")
        print(f"  {INFO}   2       Set 500 mm")
        print(f"  {INFO}   3       Set 1000 mm")
        print(f"  {INFO}   R       Read current focus")
        print(f"  {INFO}   Q       Quit\n")

        while True:
            display_frame(camera)

            key = cv2.waitKey(50) & 0xFF

            if key == ord('q') or key == ord('Q'):
                print(f"\n{INFO} Q pressed – quitting")
                break

            elif key == ord('r') or key == ord('R'):
                current = camera.get_focus_distance()
                print(f"  Current focus: {current:.0f} mm")

            elif key == ord('+') or key == ord('='):
                current = camera.get_focus_distance()
                _, lim_max = camera.get_focus_limits()
                new_val = min(current + focus_step, lim_max)
                print(f"\n  Increasing focus: {current:.0f} -> {new_val:.0f} mm")
                set_and_verify(camera, new_val)

            elif key == ord('-') or key == ord('_'):
                current = camera.get_focus_distance()
                lim_min, _ = camera.get_focus_limits()
                new_val = max(current - focus_step, lim_min)
                print(f"\n  Decreasing focus: {current:.0f} -> {new_val:.0f} mm")
                set_and_verify(camera, new_val)

            elif key == ord('0'):
                _, lim_max = camera.get_focus_limits()
                print(f"\n  Setting maximum focus: {lim_max:.0f} mm")
                set_and_verify(camera, lim_max)

            elif key == ord('1'):
                print("\n  Setting focus to 300 mm")
                set_and_verify(camera, 300.0)

            elif key == ord('2'):
                print("\n  Setting focus to 500 mm")
                set_and_verify(camera, 500.0)

            elif key == ord('3'):
                print("\n  Setting focus to 1000 mm")
                set_and_verify(camera, 1000.0)

    except KeyboardInterrupt:
        print(f"\n{INFO} Interrupted")
    except Exception:
        print(f"\n{FAIL} Focus control failed:")
        import traceback
        traceback.print_exc()
        raise
    finally:
        print(f"\n{INFO} Cleaning up...")
        camera.stop()
        camera.disconnect()
        cv2.destroyAllWindows()
        print(f"{PASS} Camera disconnected and windows closed")


if __name__ == "__main__":
    main()
