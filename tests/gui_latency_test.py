"""
gui_latency_test.py

Diagnostic application for measuring end-to-end latency from camera
acquisition to Qt painting.

This is NOT the production viewer. It exists solely to identify
which stage of the acquisition pipeline is responsible for latency.

Usage:
    python -m tests.gui_latency_test
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2
import halcon as ha
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from calibration.calibration_manager import CalibrationManager
from camera.camera_info import CameraInfo
from camera.tv46l_camera import TV46LCamera
from configuration import settings

# ==========================================================
# Constants
# ==========================================================

_COLORMAP = cv2.COLORMAP_INFERNO
_FRAME_TIMER_MS = 30
_DIAG_TIMER_MS = 1000

# ==========================================================
# Camera Discovery
# ==========================================================


def _discover_cameras() -> list[CameraInfo]:
    cameras: list[CameraInfo] = []
    try:
        devices = ha.info_framegrabber(
            "GigEVision2", "device"
        )
        device_list: list[str] = []
        if isinstance(devices, tuple) and len(devices) >= 2:
            raw = devices[1]
            if isinstance(raw, (list, tuple)):
                prefix = "device:"
                for entry in raw:
                    s = str(entry)
                    idx = s.find(prefix)
                    if idx >= 0:
                        start = idx + len(prefix)
                        end = s.find(" |", start)
                        if end < 0:
                            end = len(s)
                        dev = s[start:end].strip()
                        if dev:
                            device_list.append(dev)
        for device in device_list:
            cameras.append(
                CameraInfo(
                    device=device,
                    serial=device,
                    model="",
                    vendor="",
                    ip="",
                )
            )
    except Exception:
        pass
    return cameras


# ==========================================================
# Stage Statistics
# ==========================================================


@dataclass
class StageStats:
    latest: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0
    total: float = 0.0
    count: int = 0

    @property
    def average(self) -> float:
        return self.total / self.count if self.count else 0.0

    def update(self, value: float) -> None:
        self.latest = value
        if self.count == 0:
            self.minimum = value
            self.maximum = value
        else:
            if value < self.minimum:
                self.minimum = value
            if value > self.maximum:
                self.maximum = value
        self.total += value
        self.count += 1

    def reset(self) -> None:
        self.latest = 0.0
        self.minimum = 0.0
        self.maximum = 0.0
        self.total = 0.0
        self.count = 0


class LatencyStatistics:
    def __init__(self) -> None:
        self.acquire = StageStats()
        self.numpy_time = StageStats()
        self.publish = StageStats()
        self.gui_delay = StageStats()
        self.display = StageStats()
        self.colormap = StageStats()
        self.qimage = StageStats()
        self.pixmap = StageStats()
        self.update_delay = StageStats()
        self.paint = StageStats()
        self.total = StageStats()

    def reset_all(self) -> None:
        for attr in vars(self).values():
            if isinstance(attr, StageStats):
                attr.reset()


# ==========================================================
# Thermal Widget
# ==========================================================


class ThermalWidget(QWidget):
    def __init__(
        self, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._frame_number: int = 0
        self._grab_start_time: float = 0.0
        self._update_request_time: float = 0.0
        self._overlay_total_latency: float = 0.0
        self._error_message: str | None = None
        self.paint_start_time: float = 0.0
        self.paint_finish_time: float = 0.0
        self.paint_update_delay: float = 0.0
        self.paint_duration: float = 0.0
        self.paint_total_latency: float = 0.0
        self.paint_event_count: int = 0
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: black;")

    def set_image(
        self,
        pixmap: QPixmap,
        frame_number: int,
        grab_start_time: float,
        update_request_time: float,
        overlay_total_latency: float,
    ) -> None:
        self._pixmap = pixmap
        self._frame_number = frame_number
        self._grab_start_time = grab_start_time
        self._update_request_time = update_request_time
        self._overlay_total_latency = overlay_total_latency
        self._error_message = None

    def show_error(self, message: str) -> None:
        self._pixmap = None
        self._error_message = message
        self.update()

    def paintEvent(  # noqa: N802
        self, event
    ) -> None:
        self.paint_start_time = time.perf_counter()
        if self._grab_start_time > 0:
            self.paint_update_delay = (
                self.paint_start_time
                - self._update_request_time
            )
        painter = QPainter(self)
        try:
            if self._error_message is not None:
                painter.setPen(Qt.GlobalColor.red)
                font = QFont("monospace", 12)
                painter.setFont(font)
                painter.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    self._error_message,
                )
            elif (
                self._pixmap is not None
                and not self._pixmap.isNull()
            ):
                scaled = self._pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (self.width() - scaled.width()) // 2
                y = (
                    self.height() - scaled.height()
                ) // 2
                painter.drawPixmap(x, y, scaled)

                painter.setPen(Qt.GlobalColor.green)
                font = QFont("monospace", 12)
                painter.setFont(font)
                painter.drawText(10, 22, f"#{self._frame_number}")

                latency_text = (
                    f"{self._overlay_total_latency:.1f} ms"
                )
                fm = QFontMetrics(font)
                lw = fm.horizontalAdvance(latency_text)
                painter.drawText(
                    self.width() - lw - 10,
                    22,
                    latency_text,
                )
            else:
                painter.setPen(Qt.GlobalColor.white)
                font = QFont("monospace", 14)
                painter.setFont(font)
                painter.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "Waiting for first frame...",
                )
        finally:
            painter.end()
        self.paint_finish_time = time.perf_counter()
        if self._grab_start_time > 0:
            self.paint_duration = (
                self.paint_finish_time
                - self.paint_start_time
            )
            self.paint_total_latency = (
                self.paint_finish_time
                - self._grab_start_time
            )
            self.paint_event_count += 1




# ==========================================================
# Main Window
# ==========================================================


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._camera: TV46LCamera | None = None
        self._calibration = CalibrationManager()
        self._stats = LatencyStatistics()

        self._last_sequence: int = -1
        self._skipped_frames: int = 0
        self._update_requests: int = 0

        self._gui_frame_count: int = 0
        self._gui_fps: int = 0
        self._gui_fps_timer: float = time.time()

        self._labels: dict[str, QLabel] = {}

        self._init_ui()
        self._init_camera()
        if self._camera_error is not None:
            self._thermal_widget.show_error(
                self._camera_error
            )
        self._init_timers()

    # ==========================================================
    # UI Setup
    # ==========================================================

    def _init_ui(self) -> None:
        self.setWindowTitle("GUI Latency Test")
        self.setMinimumSize(800, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._thermal_widget = ThermalWidget()
        layout.addWidget(self._thermal_widget, stretch=1)

        diag_frame = QFrame()
        diag_frame.setFrameStyle(
            QFrame.Shape.StyledPanel
        )
        diag_layout = QGridLayout(diag_frame)
        diag_layout.setSpacing(2)

        entries = [
            ("Frame", "frame"),
            ("Sequence", "sequence"),
            ("Skipped Frames", "skipped"),
            ("Camera FPS", "cam_fps"),
            ("GUI FPS", "gui_fps"),
            (None, None),
            ("Acquire", "acquire"),
            ("NumPy", "numpy"),
            ("Publish", "publish"),
            ("GUI Delay", "gui_delay"),
            ("Display", "display"),
            ("Colormap", "colormap"),
            ("QImage", "qimage"),
            ("Pixmap", "pixmap"),
            ("Update Delay", "update"),
            ("Paint Time", "paint"),
            ("Total", "total"),
            (None, None),
            ("Average Total", "avg_total"),
            ("Maximum Total", "max_total"),
        ]

        row = 0
        for name, key in entries:
            if name is None:
                diag_layout.addWidget(
                    QFrame(), row, 0, 1, 2
                )
                row += 1
                continue
            label_name = QLabel(f"{name}:")
            label_name.setAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )
            label_value = QLabel("--")
            label_value.setFont(QFont("monospace", 10))
            label_value.setAlignment(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
            )
            diag_layout.addWidget(label_name, row, 0)
            diag_layout.addWidget(label_value, row, 1)
            self._labels[key] = label_value
            row += 1

        layout.addWidget(diag_frame)

    # ==========================================================
    # Camera Setup
    # ==========================================================

    def _init_camera(self) -> None:
        self._camera_error: str | None = None
        try:
            print("[INFO] Initializing calibration...")
            self._calibration.initialize()

            print("[INFO] Discovering cameras...")
            cameras = _discover_cameras()
            if not cameras:
                self._camera_error = (
                    "No GigE Vision cameras found."
                )
                print(f"[ERROR] {self._camera_error}")
                return

            cam_info = cameras[0]
            print(
                f"[INFO] Using camera: "
                f"{cam_info.serial} @ {cam_info.ip}"
            )

            self._camera = TV46LCamera(cam_info, settings)
            self._camera.connect()
            self._camera.start()

            if not self._camera.wait_for_first_frame(10):
                self._camera_error = (
                    "No frames received from camera."
                )
                print(f"[ERROR] {self._camera_error}")
                self._camera.disconnect()
                self._camera = None
                return

            print("[INFO] Camera ready.")
        except Exception as exc:
            self._camera_error = str(exc)
            print(f"[ERROR] Camera init failed: {exc}")
            self._camera = None

    # ==========================================================
    # Timers
    # ==========================================================

    def _init_timers(self) -> None:
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(
            self._poll_frame
        )
        self._frame_timer.start(_FRAME_TIMER_MS)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(
            self._update_diagnostics
        )
        self._diag_timer.start(_DIAG_TIMER_MS)

    # ==========================================================
    # Frame Poll (30 ms)
    # ==========================================================

    def _poll_frame(self) -> None:
        if self._camera is None:
            return

        frame = self._camera.get_latest_frame_reference()
        if frame is None:
            return

        if frame.sequence == self._last_sequence:
            return

        if (
            self._last_sequence >= 0
            and frame.sequence != self._last_sequence + 1
        ):
            self._skipped_frames += (
                frame.sequence - self._last_sequence - 1
            )

        self._last_sequence = frame.sequence
        self._gui_frame_count += 1

        gui_poll_time = time.perf_counter()

        display_start = time.perf_counter()
        display_image = self._calibration.raw_to_display(
            frame.image
        )
        display_finish = time.perf_counter()

        colormap_start = time.perf_counter()
        color_image = self._calibration.apply_colormap(
            display_image
        )
        colormap_finish = time.perf_counter()

        qimage_start = time.perf_counter()
        rgb_image = cv2.cvtColor(
            color_image, cv2.COLOR_BGR2RGB
        )
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qimage = QImage(
            rgb_image.data.tobytes(),
            w,
            h,
            bytes_per_line,
            QImage.Format.Format_RGB888,
        )
        qimage_finish = time.perf_counter()

        pixmap_start = time.perf_counter()
        pixmap = QPixmap.fromImage(qimage)
        pixmap_finish = time.perf_counter()

        gst = frame.grab_start_time
        gct = frame.grab_complete_time
        nct = frame.numpy_complete_time
        pt = frame.publish_time

        update_request = time.perf_counter()
        overlay_latency = (update_request - gst) * 1000
        self._thermal_widget.set_image(
            pixmap,
            frame.frame_number,
            gst,
            update_request,
            overlay_latency,
        )
        self._update_requests += 1
        self._thermal_widget.update()

        now = time.time()
        if now - self._gui_fps_timer >= 1.0:
            self._gui_fps = self._gui_frame_count
            self._gui_frame_count = 0
            self._gui_fps_timer = now

        acquire_ms = (gct - gst) * 1000
        numpy_ms = (nct - gct) * 1000
        publish_ms = (pt - nct) * 1000
        gui_delay_ms = (gui_poll_time - pt) * 1000
        display_ms = (display_finish - display_start) * 1000
        colormap_ms = (colormap_finish - colormap_start) * 1000
        qimage_ms = (qimage_finish - qimage_start) * 1000
        pixmap_ms = (pixmap_finish - pixmap_start) * 1000

        self._stats.acquire.update(acquire_ms)
        self._stats.numpy_time.update(numpy_ms)
        self._stats.publish.update(publish_ms)
        self._stats.gui_delay.update(gui_delay_ms)
        self._stats.display.update(display_ms)
        self._stats.colormap.update(colormap_ms)
        self._stats.qimage.update(qimage_ms)
        self._stats.pixmap.update(pixmap_ms)

    # ==========================================================
    # Diagnostics Update (1000 ms)
    # ==========================================================

    def _update_diagnostics(self) -> None:
        w = self._thermal_widget
        if w.paint_event_count > 0:
            self._stats.update_delay.update(
                w.paint_update_delay * 1000
            )
            self._stats.paint.update(
                w.paint_duration * 1000
            )
            self._stats.total.update(
                w.paint_total_latency * 1000
            )

        self._update_labels()
        self._print_report()

    # ==========================================================
    # Label Updates
    # ==========================================================

    def _update_labels(self) -> None:
        seq = self._last_sequence
        seq_str = str(seq) if seq >= 0 else "--"
        self._set_label("frame", seq_str)
        self._set_label("sequence", seq_str)
        self._set_label("skipped", str(self._skipped_frames))
        self._set_label(
            "cam_fps",
            str(
                self._camera.get_fps()
                if self._camera
                else "--"
            ),
        )
        self._set_label("gui_fps", str(self._gui_fps))

        s = self._stats
        if s.acquire.count > 0:
            self._set_label(
                "acquire", f"{s.acquire.latest:.2f}"
            )
            self._set_label(
                "numpy",
                f"{s.numpy_time.latest:.2f}",
            )
            self._set_label(
                "publish", f"{s.publish.latest:.2f}"
            )
            self._set_label(
                "gui_delay",
                f"{s.gui_delay.latest:.2f}",
            )
            self._set_label(
                "display", f"{s.display.latest:.2f}"
            )
            self._set_label(
                "colormap",
                f"{s.colormap.latest:.2f}",
            )
            self._set_label(
                "qimage", f"{s.qimage.latest:.2f}"
            )
            self._set_label(
                "pixmap", f"{s.pixmap.latest:.2f}"
            )
            self._set_label(
                "update",
                f"{s.update_delay.latest:.2f}",
            )
            self._set_label(
                "paint", f"{s.paint.latest:.2f}"
            )
            self._set_label(
                "total", f"{s.total.latest:.2f}"
            )
            self._set_label(
                "avg_total",
                f"{s.total.average:.2f}",
            )
            self._set_label(
                "max_total",
                f"{s.total.maximum:.2f}",
            )

    def _set_label(
        self, key: str, text: str
    ) -> None:
        label = self._labels.get(key)
        if label is not None:
            label.setText(text)

    # ==========================================================
    # Console Report
    # ==========================================================

    def _print_report(self) -> None:
        s = self._stats
        cam_fps = (
            self._camera.get_fps()
            if self._camera
            else 0
        )
        paint_events = (
            self._thermal_widget.paint_event_count
        )
        ratio = (
            paint_events / self._update_requests
            if self._update_requests > 0
            else 0.0
        )

        print("=" * 50)
        print(
            f"Frame           {self._last_sequence}"
        )
        print(
            f"Sequence        {self._last_sequence}"
        )
        print(f"Camera FPS      {cam_fps}")
        print(f"GUI FPS         {self._gui_fps}")
        print(
            f"Skipped Frames  {self._skipped_frames}"
        )
        print(
            f"Update Requests {self._update_requests}"
        )
        print(
            f"Paint Events    {paint_events}"
        )
        print(
            f"Paint/Update    {ratio:.2f}"
        )
        print("-" * 50)
        if s.acquire.count > 0:
            print(
                f"Acquire         "
                f"{s.acquire.latest:8.2f} ms  "
                f"(avg {s.acquire.average:.2f})"
            )
            print(
                f"NumPy           "
                f"{s.numpy_time.latest:8.2f} ms  "
                f"(avg {s.numpy_time.average:.2f})"
            )
            print(
                f"Publish         "
                f"{s.publish.latest:8.2f} ms  "
                f"(avg {s.publish.average:.2f})"
            )
            print(
                f"GUI Delay       "
                f"{s.gui_delay.latest:8.2f} ms  "
                f"(avg {s.gui_delay.average:.2f})"
            )
            print(
                f"Display Conv    "
                f"{s.display.latest:8.2f} ms  "
                f"(avg {s.display.average:.2f})"
            )
            print(
                f"Colormap        "
                f"{s.colormap.latest:8.2f} ms  "
                f"(avg {s.colormap.average:.2f})"
            )
            print(
                f"QImage          "
                f"{s.qimage.latest:8.2f} ms  "
                f"(avg {s.qimage.average:.2f})"
            )
            print(
                f"Pixmap          "
                f"{s.pixmap.latest:8.2f} ms  "
                f"(avg {s.pixmap.average:.2f})"
            )
            print(
                f"Update Delay    "
                f"{s.update_delay.latest:8.2f} ms  "
                f"(avg {s.update_delay.average:.2f})"
            )
            print(
                f"Paint Time      "
                f"{s.paint.latest:8.2f} ms  "
                f"(avg {s.paint.average:.2f})"
            )
            print(
                f"Total           "
                f"{s.total.latest:8.2f} ms  "
                f"(avg {s.total.average:.2f})"
            )
        else:
            print("(no frames processed yet)")
        print("=" * 50)

    # ==========================================================
    # Shutdown
    # ==========================================================

    def closeEvent(self, event) -> None:  # noqa: N802
        self._frame_timer.stop()
        self._diag_timer.stop()
        if self._camera is not None:
            self._camera.stop()
            self._camera.disconnect()
        super().closeEvent(event)


# ==========================================================
# Entry Point
# ==========================================================


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GUI Latency Test")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
