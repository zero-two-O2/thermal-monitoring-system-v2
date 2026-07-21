"""
camera_viewer.py — Interactive live camera viewer.

PyQt5 GUI showing:
  - Live thermal feed with color palette
  - Temperature readout at mouse position
  - Focus controls (+1, +10, +100, -1, -10, -100, presets)
  - Manual NUC button
  - Auto-ranging brightness/contrast toggle

Keyboard:
  Q / Esc  -> Quit
  N        -> Manual NUC

Run:
    python tests/camera_viewer.py
"""

from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt5.QtGui import (
    QImage,
    QPainter,
    QPixmap,
    QFont,
    QColor,
    QPen,
    QBrush,
    QCursor,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QGridLayout,
    QCheckBox,
    QSizePolicy,
)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

import halcon as ha
from calibration.calibration_manager import CalibrationManager
from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings


PALETTE_WIDTH = 40
PALETTE_MARGIN = 10
TEMP_FONT_SIZE = 11
STATUS_FONT_SIZE = 12


# ---------------------------------------------------------------------------
# Palette widget — vertical color bar with temperature labels
# ---------------------------------------------------------------------------

class PaletteWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_temp = 20.0
        self._max_temp = 40.0
        self.setFixedWidth(PALETTE_WIDTH + 60)
        self.setMinimumHeight(200)

    def set_range(self, tmin: float, tmax: float):
        self._min_temp = tmin
        self._max_temp = tmax
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        r = self.rect()
        bar_left = PALETTE_MARGIN
        bar_top = 20
        bar_w = PALETTE_WIDTH
        bar_h = r.height() - 40

        steps = 256
        for i in range(steps):
            frac = i / (steps - 1)
            temp = self._min_temp + frac * (self._max_temp - self._min_temp)
            display = int(255 * frac)
            bgr = cv2.applyColorMap(
                np.uint8([[display]]), cv2.COLORMAP_INFERNO
            )[0, 0]
            y0 = int(bar_top + bar_h * (1 - frac))
            y1 = int(bar_top + bar_h * (1 - (i + 1) / (steps - 1)))
            painter.fillRect(
                bar_left, y0, bar_w, max(y1 - y0, 1),
                QColor(bgr[2], bgr[1], bgr[0]),
            )

        pen = QPen(QColor(200, 200, 200))
        painter.setPen(pen)
        painter.drawRect(bar_left, bar_top, bar_w, bar_h)

        font = QFont("Consolas", 8)
        painter.setFont(font)
        labels = [
            (self._max_temp, bar_top),
            ((self._min_temp + self._max_temp) / 2, bar_top + bar_h // 2),
            (self._min_temp, bar_top + bar_h),
        ]
        for val, y in labels:
            painter.drawText(
                bar_left + bar_w + 4, y + 4,
                f"{val:.1f}°C",
            )


# ---------------------------------------------------------------------------
# Thermal view — displays camera frames with temperature overlay
# ---------------------------------------------------------------------------

class ThermalView(QWidget):
    def __init__(self, calibration_mgr: CalibrationManager, parent=None):
        super().__init__(parent)
        self._calibration = calibration_mgr
        self._pixmap: QPixmap | None = None
        self._temperature_map: np.ndarray | None = None
        self._auto_range = True
        self._fixed_min = 20.0
        self._fixed_max = 40.0
        self._mouse_x = -1
        self._mouse_y = -1
        self._displayed_frame = -1
        self._frames_set = 0
        self._set_frame_time = 0.0
        self._paint_time = 0.0
        self._paint_call_count = 0
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

    def set_frame(self, raw_image: np.ndarray, frame_number: int = -1):
        t0 = time.perf_counter()
        self._displayed_frame = frame_number
        self._frames_set += 1

        temp = self._calibration.raw_to_temperature(raw_image)
        self._temperature_map = temp

        if self._auto_range:
            tmin = float(temp.min())
            tmax = float(temp.max())
            if tmax > tmin:
                self._fixed_min = tmin
                self._fixed_max = tmax

        display = self._calibration.raw_to_display(
            raw_image,
            minimum=self._fixed_min,
            maximum=self._fixed_max,
        )
        color = self._calibration.apply_colormap(display)
        h, w = color.shape[:2]
        qimg = QImage(
            color.data, w, h, 3 * w,
            QImage.Format_RGB888,
        ).rgbSwapped()
        self._pixmap = QPixmap.fromImage(qimg)
        self._set_frame_time = (time.perf_counter() - t0) * 1000
        self.update()

    def set_auto_range(self, enabled: bool):
        self._auto_range = enabled
        if not enabled:
            self._fixed_min = 20.0
            self._fixed_max = 40.0

    def set_fixed_range(self, tmin: float, tmax: float):
        self._fixed_min = tmin
        self._fixed_max = tmax
        self._auto_range = False

    def temp_range(self):
        return self._fixed_min, self._fixed_max

    def paintEvent(self, event):
        t0 = time.perf_counter()
        self._paint_call_count += 1
        if self._pixmap is None:
            return
        painter = QPainter(self)
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

        if self._mouse_x >= 0 and self._mouse_y >= 0:
            font = QFont("Consolas", TEMP_FONT_SIZE, QFont.Bold)
            painter.setFont(font)

            if self._pixmap.width() > 0 and self._pixmap.height() > 0:
                sx = self._pixmap.width() / scaled.width()
                sy = self._pixmap.height() / scaled.height()

                if self._temperature_map is not None:
                    img_x = int((self._mouse_x - x) * sx)
                    img_y = int((self._mouse_y - y) * sy)
                    if 0 <= img_x < self._temperature_map.shape[1] and 0 <= img_y < self._temperature_map.shape[0]:
                        temp_val = float(self._temperature_map[img_y, img_x])
                    else:
                        temp_val = float("nan")
                else:
                    temp_val = float("nan")

                text = f"{temp_val:.1f} °C"
                tw = painter.fontMetrics().horizontalAdvance(text) + 12
                th = painter.fontMetrics().height() + 6

                tx = self._mouse_x + 12
                ty = self._mouse_y - th - 8
                if tx + tw > self.width():
                    tx = self._mouse_x - tw - 12
                if ty < 0:
                    ty = self._mouse_y + 12

                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
                painter.drawRoundedRect(tx, ty, tw, th, 4, 4)

                painter.setPen(QColor(255, 255, 100))
                painter.drawText(
                    tx + 6, ty + th - 6, f"{temp_val:.1f} °C"
                )

                cross = QPen(QColor(255, 255, 100, 160), 1)
                painter.setPen(cross)
                cs = 10
                painter.drawLine(
                    self._mouse_x - cs, self._mouse_y,
                    self._mouse_x + cs, self._mouse_y,
                )
                painter.drawLine(
                    self._mouse_x, self._mouse_y - cs,
                    self._mouse_x, self._mouse_y + cs,
                )

        self._paint_time = (time.perf_counter() - t0) * 1000

    def mouseMoveEvent(self, event):
        self._mouse_x = event.x()
        self._mouse_y = event.y()
        self.update()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class CameraViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = Settings()
        self._camera: TV46LCamera | None = None
        self._calibration = CalibrationManager()
        self._update_frame_time = 0.0
        self._start_time = time.time()
        self._current_latency = 0.0
        self._latency_sum = 0.0
        self._latency_count = 0
        self._max_latency = 0.0

        self._init_ui()
        self._init_camera()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_frame)
        self._timer.start(33)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._print_diagnostics)
        self._diag_timer.start(1000)

    def _init_ui(self):
        self.setWindowTitle("TV46L Thermal Viewer")
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Left: view + controls
        left = QVBoxLayout()

        self._thermal_view = ThermalView(self._calibration)
        left.addWidget(self._thermal_view, 1)

        left.addLayout(self._build_control_bar())
        main_layout.addLayout(left, 1)

        # Right: palette + info
        right = QVBoxLayout()
        self._palette = PaletteWidget()
        right.addWidget(self._palette)
        right.addStretch()
        main_layout.addLayout(right)

        self._status_label = QLabel("Initializing...")
        self._status_label.setFont(QFont("Consolas", STATUS_FONT_SIZE))
        right.addWidget(self._status_label)

    def _build_control_bar(self):
        layout = QHBoxLayout()

        # Focus group
        focus_group = QGroupBox("Focus")
        fg = QGridLayout()
        fg.addWidget(QLabel("Current:"), 0, 0)
        self._focus_label = QLabel("--- mm")
        self._focus_label.setFont(QFont("Consolas", 10))
        fg.addWidget(self._focus_label, 0, 1, 1, 2)

        steps = [("-100", -100), ("-10", -10), ("-1", -1),
                 ("+1", 1), ("+10", 10), ("+100", 100)]
        for i, (label, step) in enumerate(steps):
            btn = QPushButton(label)
            btn.setFixedWidth(44)
            btn.clicked.connect(
                lambda checked, s=step: self._adjust_focus(s)
            )
            fg.addWidget(btn, 1 + i // 6, i % 6)

        fg.addWidget(QLabel("Presets:"), 2, 0)
        presets = [300, 500, 1000, 5000, 1000000]
        for i, preset in enumerate(presets):
            btn = QPushButton(f"{preset}")
            btn.setFixedWidth(56)
            btn.clicked.connect(
                lambda checked, p=preset: self._set_focus(p)
            )
            fg.addWidget(btn, 3, i)

        focus_group.setLayout(fg)
        layout.addWidget(focus_group)

        # NUC button
        nuc_group = QGroupBox("NUC")
        ng = QVBoxLayout()
        nuc_btn = QPushButton("Manual NUC")
        nuc_btn.clicked.connect(self._do_nuc)
        ng.addWidget(nuc_btn)
        nuc_group.setLayout(ng)
        layout.addWidget(nuc_group)

        # Display group
        display_group = QGroupBox("Display")
        dg = QVBoxLayout()
        self._auto_range_cb = QCheckBox("Auto range")
        self._auto_range_cb.setChecked(True)
        self._auto_range_cb.toggled.connect(
            self._thermal_view.set_auto_range
        )
        dg.addWidget(self._auto_range_cb)

        self._fixed_min_label = QLabel("Min: ---")
        self._fixed_max_label = QLabel("Max: ---")
        dg.addWidget(self._fixed_min_label)
        dg.addWidget(self._fixed_max_label)

        display_group.setLayout(dg)
        layout.addWidget(display_group)

        return layout

    def _init_camera(self):
        self._status_label.setText("Discovering...")
        discovery = CameraDiscovery()
        cameras = discovery.discover()
        if not cameras:
            self._status_label.setText("ERROR: No cameras found")
            return

        cam_info = cameras[0]
        self._camera = TV46LCamera(
            camera_info=cam_info, settings=self._settings
        )
        self._camera.connect()
        self._camera.start()
        if not self._camera.wait_for_first_frame(timeout=10.0):
            self._status_label.setText("ERROR: No frames")
            return

        self._calibration.initialize()

        print("\n  === HALCON Buffer / Stream Parameters ===")
        self._dump_halcon_buffer_params()
        print("  === End ===\n")

        self._status_label.setText(
            f"{cam_info.model} SN={cam_info.serial}  "
            f"FPS: ---"
        )

    def _update_frame(self):
        t0 = time.perf_counter()
        if self._camera is None:
            return
        frame = self._camera.get_latest_frame()
        if frame is None:
            return

        now = time.perf_counter()
        self._current_latency = (now - frame.acquisition_timestamp) * 1000
        self._latency_sum += self._current_latency
        self._latency_count += 1
        if self._current_latency > self._max_latency:
            self._max_latency = self._current_latency

        self._thermal_view.set_frame(
            frame.image, frame.frame_number
        )

        self._update_frame_time = (time.perf_counter() - t0) * 1000

        # Update palette
        tmin, tmax = self._thermal_view.temp_range()
        self._palette.set_range(tmin, tmax)
        self._fixed_min_label.setText(f"Min: {tmin:.1f}°C")
        self._fixed_max_label.setText(f"Max: {tmax:.1f}°C")

        # Update status
        try:
            cur_focus = self._camera.get_focus_distance()
            self._focus_label.setText(f"{cur_focus:.0f}")
        except Exception:
            pass

        fps = self._camera.get_fps()
        temp = self._camera.device_temperature()
        self._status_label.setText(
            f"FPS: {fps}  Camera: {temp:.0f}°C  "
            f"Frames: {self._camera.frame_count}"
        )

    def _print_diagnostics(self):
        cam_frames = self._camera.frame_count if self._camera else 0
        d = self._thermal_view
        diff = cam_frames - d._displayed_frame

        avg_lat = (
            self._latency_sum / self._latency_count
            if self._latency_count > 0 else 0.0
        )

        mem_rss = 0.0
        if _HAS_PSUTIL:
            try:
                mem_rss = psutil.Process(os.getpid()).memory_info().rss
                mem_rss /= 1024 * 1024
            except Exception:
                pass

        gc_count = gc.get_count()
        obj_count = len(gc.get_objects())

        print("-" * 55)
        print(f"  Camera frame counter:     {cam_frames}")
        print(f"  Displayed frame number:   {d._displayed_frame}")
        print(f"  Difference:               {diff}")
        print(f"  Current latency:          {self._current_latency:.1f} ms")
        print(f"  Average latency:          {avg_lat:.1f} ms")
        print(f"  Maximum latency:          {self._max_latency:.1f} ms")
        print(f"  _update_frame() time:     {self._update_frame_time:.2f} ms")
        print(f"  set_frame() time:         {d._set_frame_time:.2f} ms")
        print(f"  paintEvent() time:        {d._paint_time:.2f} ms")
        print(f"  Resident memory:          {mem_rss:.1f} MB")
        print(f"  Python GC objects:        {obj_count}")
        print(f"  GC counts (gen0/1/2):     {gc_count}")
        print("-" * 55)

        if diff > 0:
            print(
                f"  WARNING: GUI falling behind by {diff} frames"
            )

        if self._latency_count % 10 == 1:
            self._dump_halcon_buffer_params()

    def _dump_halcon_buffer_params(self):
        if self._camera is None:
            return
        params = [
            "num_buffers",
            "buffer_mode",
            "buffer_strategy",
            "grab_timeout",
            "newest_image_only",
            "AcquisitionMode",
            "AcquisitionFrameCount",
            "AcquisitionBurstFrameCount",
            "TriggerMode",
            "TriggerSource",
            "[Stream]GevStreamSeenPacketCount",
            "[Stream]GevStreamLostPacketCount",
            "[Stream]GevStreamDeliveredPacketCount",
            "[Stream]GevStreamUnavailablePacketCount",
            "[Stream]GevStreamDuplicatePacketCount",
            "[Stream]GevStreamResendPacketCount",
        ]
        print("  --- HALCON Buffer / Stream Params ---")
        for name in params:
            try:
                val = ha.get_framegrabber_param(
                    self._camera._acq, name
                )
                print(f"    {name:.<50s} {repr(val)}")
            except Exception as e:
                print(f"    {name:.<50s} ERROR: {e}")

    def _adjust_focus(self, delta: int):
        if self._camera is None:
            return
        try:
            cur = self._camera.get_focus_distance()
            self._camera.set_focus_distance(cur + delta)
        except Exception:
            pass

    def _set_focus(self, target: float):
        if self._camera is None:
            return
        try:
            self._camera.set_focus_distance(target)
        except Exception:
            pass

    def _do_nuc(self):
        if self._camera is None:
            return
        self._camera.manual_nuc()
        self._status_label.setText("NUC requested...")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Q, Qt.Key_Escape):
            self.close()
        elif event.key() == Qt.Key_N:
            self._do_nuc()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._timer.stop()
        if self._camera is not None:
            self._camera.stop()
            self._camera.disconnect()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CameraViewerWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
