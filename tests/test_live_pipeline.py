"""
test_live_pipeline.py

Live hardware integration test:
TV46LCamera -> RawFrame -> ProcessingPipeline -> FrameResult

Run:
    python tests/test_live_pipeline.py

Controls:
    Q -> Quit
    N -> Manual NUC
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from calibration.calibration_manager import CalibrationManager
from calibration.calibration_models import CameraCalibration, CalibrationRange, UniverseSegment
from calibration.calibration_processor import CalibrationProcessor
from configuration.settings import Settings
from processing.pipeline.processing_pipeline import ProcessingPipeline
from processing.roi_processor import ROIProcessor
from processing.alarm_processor import AlarmProcessor

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


def setup_calibration() -> CalibrationManager:
    cal_file = Path("assets/calibration/calibration_blob.txt")
    mgr = CalibrationManager()
    if cal_file.exists():
        mgr.initialize()
        print(f"{PASS} Calibration loaded from {cal_file}")
    else:
        cal = CameraCalibration()
        cal.add_range(CalibrationRange(
            calibration_min=-20.0, calibration_max=350.0,
            display_min=0.0, display_max=255.0,
            manual_palette_span=100.0, auto_palette_span=100.0,
            num_segments=1,
            segments=[UniverseSegment(u0=1000, u1=-2, u2=0.005, start_temp=-50, end_temp=500)]
        ))
        CalibrationProcessor.build_lookup_tables(cal)
        object.__setattr__(mgr, '_calibration', cal)
        object.__setattr__(mgr, '_initialized', True)
        print(f"{PASS} Minimal calibration built inline")
    return mgr


def main():
    print("=" * 60)
    print("  Live Camera -> ProcessingPipeline Integration Test")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    calibration_manager = setup_calibration()
    print(f"{PASS} CalibrationManager initialized")

    # ------------------------------------------------------------------
    # Camera Discovery
    # ------------------------------------------------------------------
    print(f"\n{INFO} Discovering cameras...")
    discovery = CameraDiscovery()
    cameras = discovery.discover()

    if not cameras:
        print(f"{FAIL} No TV46L cameras discovered on the network.")
        print(f"{INFO} Ensure the camera is connected and powered on.")
        sys.exit(1)

    cam_info = cameras[0]
    print(f"{PASS} Camera discovered: {cam_info.model} "
          f"(SN={cam_info.serial}, IP={cam_info.ip})")

    # ------------------------------------------------------------------
    # Camera Connection
    # ------------------------------------------------------------------
    settings = Settings()
    camera = TV46LCamera(camera_info=cam_info, settings=settings)

    try:
        camera.connect()
        print(f"{PASS} Camera Connected")

        # ------------------------------------------------------------------
        # Start Acquisition
        # ------------------------------------------------------------------
        camera.start()
        print(f"{PASS} Acquisition Started")

        # ------------------------------------------------------------------
        # Wait For First Frame
        # ------------------------------------------------------------------
        print(f"{INFO} Waiting for first frame...")
        if not camera.wait_for_first_frame(timeout=10.0):
            print(f"{FAIL} No frame received within 10 seconds.")
            sys.exit(1)
        print(f"{PASS} First Frame Received")

        # ------------------------------------------------------------------
        # Processing Pipeline
        # ------------------------------------------------------------------
        roi_processor = ROIProcessor()
        alarm_processor = AlarmProcessor()
        pipeline = ProcessingPipeline(
            calibration_manager,
            roi_processor,
            alarm_processor,
        )
        print(f"{PASS} ProcessingPipeline Created")

        # ------------------------------------------------------------------
        # Main Loop
        # ------------------------------------------------------------------
        last_frame_number = -1
        last_print_time = time.time()
        processed_count = 0
        camera_id_str = str(cam_info.camera_id) if cam_info.camera_id is not None else "0"
        position_id = "live_test"

        print(f"\n{INFO} Processing frames. Press Q to quit, N for NUC.\n")

        while True:
            frame = camera.get_latest_frame()

            if frame is None:
                time.sleep(0.001)
                continue

            if frame.frame_number == last_frame_number:
                time.sleep(0.001)
                continue

            last_frame_number = frame.frame_number

            # ----- Process Through Pipeline -----
            result = pipeline.process(
                camera_id=camera_id_str,
                position_id=position_id,
                raw_frame=frame,
            )
            processed_count += 1

            # ----- Verification -----
            checks = [
                ("FrameResult", result is not None),
                ("RawFrame Preserved", result.raw_frame is not None),
                ("ProcessedFrame Exists", result.processed_frame is not None),
                ("CameraStatistics Exists", result.statistics is not None),
                ("ROI List Exists", result.roi_results is not None),
                ("Alarm List Exists", result.alarms is not None),
            ]
            for label, ok in checks:
                if not ok:
                    print(f"{FAIL} Stage failed: {label}")

            # ----- Display -----
            display_img = result.processed_frame.display_image
            if display_img is not None and display_img.size > 0:
                if display_img.ndim == 2:
                    bgr = cv2.cvtColor(display_img, cv2.COLOR_GRAY2BGR)
                else:
                    bgr = display_img
                cv2.imshow("Live Pipeline Test", bgr)

            # ----- Periodic Printout (1 Hz) -----
            now = time.time()
            if now - last_print_time >= 1.0:
                stats = result.statistics
                cam_fps = camera.get_fps()
                print(
                    f"[{now:.1f}]  "
                    f"Camera FPS: {cam_fps}  |  "
                    f"Processed FPS: {processed_count}  |  "
                    f"Frame: {frame.frame_number}  |  "
                    f"Min: {stats.minimum:.1f}  |  "
                    f"Max: {stats.maximum:.1f}  |  "
                    f"Mean: {stats.mean:.1f}  |  "
                    f"Median: {stats.median:.1f}  |  "
                    f"Std: {stats.standard_deviation:.1f}  |  "
                    f"ROIs: {len(result.roi_results)}  |  "
                    f"Alarms: {len(result.alarms)}"
                )
                last_print_time = now

            # ----- Keyboard Controls -----
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == ord('Q'):
                print(f"\n{INFO} Q pressed - quitting")
                break
            elif key == ord('n') or key == ord('N'):
                print(f"{INFO} N pressed - requesting NUC")
                camera.manual_nuc()

    except KeyboardInterrupt:
        print(f"\n{INFO} Interrupted")
    except Exception:
        print(f"{FAIL} Pipeline stage failed:")
        traceback.print_exc()
        raise
    finally:
        print(f"\n{INFO} Cleaning up...")
        camera.stop()
        camera.disconnect()
        cv2.destroyAllWindows()
        print(f"{PASS} Camera disconnected and windows closed")
        print(f"{INFO} Total frames processed: {processed_count}")


if __name__ == "__main__":
    main()
