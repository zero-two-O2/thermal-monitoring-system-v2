"""
camera_viewer.py

Diagnostic application for qualifying the TV46L thermal camera pipeline.

Measures end-to-end latency from camera acquisition through Qt painting,
with per-stage statistics, scrolling graphs, health evaluation, and
qualification reporting.

Usage:
    python -m tests.camera_viewer
"""

from __future__ import annotations

import math
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2
import halcon as ha
import numpy as np
import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
_GRAPH_TIMER_MS = 200
_CONSOLE_INTERVAL = 5.0
_MAX_GRAPH_POINTS = 300
_MAX_FRAME_HISTORY = 500
_MAX_EVENT_LOG = 1000
_MAX_PERCENTILE_SAMPLES = 1000

# ==========================================================
# Camera Discovery
# ==========================================================


def _discover_cameras() -> list[CameraInfo]:
    cameras: list[CameraInfo] = []
    try:
        devices = ha.info_framegrabber("GigEVision2", "device")
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
# StageStats
# ==========================================================


class StageStats:
    def __init__(self) -> None:
        self.latest: float = 0.0
        self.minimum: float = 0.0
        self.maximum: float = 0.0
        self.total: float = 0.0
        self.total_sq: float = 0.0
        self.count: int = 0
        self._recent: deque[float] = deque(maxlen=_MAX_PERCENTILE_SAMPLES)

    @property
    def average(self) -> float:
        return self.total / self.count if self.count else 0.0

    @property
    def stddev(self) -> float:
        if self.count < 2:
            return 0.0
        mean = self.average
        variance = (self.total_sq / self.count) - (mean * mean)
        return math.sqrt(max(variance, 0.0))

    @property
    def percentile_95(self) -> float:
        if not self._recent:
            return 0.0
        sorted_vals = sorted(self._recent)
        idx = int(len(sorted_vals) * 0.95)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

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
        self.total_sq += value * value
        self.count += 1
        self._recent.append(value)


# ==========================================================
# FrameRecord (dataclass)
# ==========================================================


EmittedEvent = tuple[float, float, float]
"""
(paint_duration_ms, total_latency_ms, update_delay_ms)
"""


@dataclass
class FrameRecord:
    sequence: int = -1
    frame_number: int = 0
    grab_start: float = 0.0
    grab_complete: float = 0.0
    numpy_complete: float = 0.0
    publish_time: float = 0.0
    gui_poll_time: float = 0.0
    display_start: float = 0.0
    display_finish: float = 0.0
    colormap_start: float = 0.0
    colormap_finish: float = 0.0
    qimage_start: float = 0.0
    qimage_finish: float = 0.0
    pixmap_start: float = 0.0
    pixmap_finish: float = 0.0
    update_request: float = 0.0
    paint_start: float = 0.0
    paint_finish: float = 0.0


# ==========================================================
# FrameHistory
# ==========================================================


class FrameHistory:
    def __init__(self, maxlen: int = _MAX_FRAME_HISTORY) -> None:
        self._records: deque[FrameRecord] = deque(maxlen=maxlen)

    def append(self, record: FrameRecord) -> None:
        self._records.append(record)

    @property
    def latest(self) -> FrameRecord | None:
        return self._records[-1] if self._records else None

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index: int) -> FrameRecord:
        return self._records[index]


# ==========================================================
# EventLogger
# ==========================================================


class EventLogger:
    def __init__(self, maxlen: int = _MAX_EVENT_LOG) -> None:
        self._entries: deque[str] = deque(maxlen=maxlen)
        self._widget: QListWidget | None = None
        self._last_log_time: dict[str, float] = {}

    def attach(self, widget: QListWidget) -> None:
        self._widget = widget

    def log(self, message: str) -> None:
        now = time.time()
        tag = message.split(":")[0] if ":" in message else message
        last_time = self._last_log_time.get(tag, 0.0)
        if now - last_time < 1.0:
            return
        self._last_log_time[tag] = now
        timestamp = time.strftime("%H:%M:%S", time.localtime(now))
        entry = f"[{timestamp}] {message}"
        self._entries.append(entry)
        if self._widget is not None:
            self._widget.addItem(entry)
            self._widget.scrollToBottom()

    def get_entries(self) -> list[str]:
        return list(self._entries)


# ==========================================================
# TimingMonitor
# ==========================================================


class TimingMonitor:
    def __init__(self) -> None:
        self.acquire = StageStats()
        self.numpy = StageStats()
        self.publish = StageStats()
        self.gui_delay = StageStats()
        self.display = StageStats()
        self.colormap = StageStats()
        self.qimage = StageStats()
        self.pixmap = StageStats()
        self.update_delay = StageStats()
        self.paint = StageStats()
        self.total = StageStats()

    def update_all(self, latency_dict: dict[str, float]) -> None:
        for key, value in latency_dict.items():
            stat = getattr(self, key, None)
            if stat is not None:
                stat.update(value)

    def get_stats(self) -> dict[str, StageStats]:
        return {
            "acquire": self.acquire,
            "numpy": self.numpy,
            "publish": self.publish,
            "gui_delay": self.gui_delay,
            "display": self.display,
            "colormap": self.colormap,
            "qimage": self.qimage,
            "pixmap": self.pixmap,
            "update_delay": self.update_delay,
            "paint": self.paint,
            "total": self.total,
        }


# ==========================================================
# GraphManager
# ==========================================================


class GraphManager:
    def __init__(self, max_points: int = _MAX_GRAPH_POINTS) -> None:
        self._series: dict[str, deque[float]] = {}
        self._max_points = max_points

    def add_point(self, name: str, value: float) -> None:
        if name not in self._series:
            self._series[name] = deque(maxlen=self._max_points)
        self._series[name].append(value)

    def get_series(self, name: str) -> list[float]:
        return list(self._series.get(name, []))

    def get_all_series(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._series.items()}


# ==========================================================
# GraphWidget
# ==========================================================


class GraphWidget(QWidget):
    COLORS = {
        "total": QColor(231, 76, 60),
        "acquire": QColor(52, 152, 219),
        "numpy": QColor(46, 204, 113),
        "publish": QColor(155, 89, 182),
        "gui_delay": QColor(243, 156, 18),
        "display": QColor(26, 188, 156),
        "colormap": QColor(230, 126, 34),
        "qimage": QColor(149, 165, 166),
        "pixmap": QColor(142, 68, 173),
        "update_delay": QColor(241, 196, 15),
        "paint": QColor(231, 76, 60),
        "fps": QColor(0, 255, 255),
    }

    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._series_data: dict[str, list[float]] = {}
        self._series_colors: dict[str, QColor] = {}
        self._min_range: float = 0.0
        self._max_range: float = 100.0
        self.setMinimumSize(160, 120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setStyleSheet("background-color: #1a1a2e;")

    def set_series(
        self, name: str, data: list[float], color: QColor | None = None
    ) -> None:
        self._series_data[name] = data
        if color is not None:
            self._series_colors[name] = color
        elif name in self.COLORS:
            self._series_colors[name] = self.COLORS[name]
        else:
            self._series_colors[name] = QColor(255, 255, 255)
        self.update()

    def set_range(self, min_val: float, max_val: float) -> None:
        self._min_range = min_val
        self._max_range = max_val
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            margin = 8
            plot_w = w - 2 * margin
            plot_h = h - 24 - margin
            plot_y = margin + 16

            painter.setPen(QColor(100, 100, 100))
            painter.drawRect(margin, plot_y, plot_w, plot_h)

            painter.setPen(QColor(200, 200, 200))
            font = QFont("monospace", 8)
            painter.setFont(font)
            painter.drawText(margin, 12, self._title)

            rng = self._max_range - self._min_range
            if rng <= 0:
                rng = 1.0

            for grid_y in range(5):
                y = plot_y + (plot_h * grid_y // 4)
                painter.setPen(QColor(60, 60, 60))
                painter.drawLine(margin, y, margin + plot_w, y)
                val = self._max_range - (rng * grid_y / 4)
                painter.setPen(QColor(150, 150, 150))
                painter.drawText(2, y + 3, f"{val:.0f}")

            for name, data in self._series_data.items():
                if len(data) < 2:
                    continue
                color = self._series_colors.get(name, QColor(255, 255, 255))
                painter.setPen(color)
                n = len(data)
                step = plot_w / max(n - 1, 1)
                for i in range(n - 1):
                    x1 = margin + int(i * step)
                    x2 = margin + int((i + 1) * step)
                    y1 = plot_y + plot_h - int(
                        ((data[i] - self._min_range) / rng) * plot_h
                    )
                    y2 = plot_y + plot_h - int(
                        ((data[i + 1] - self._min_range) / rng) * plot_h
                    )
                    y1 = max(plot_y, min(plot_y + plot_h, y1))
                    y2 = max(plot_y, min(plot_y + plot_h, y2))
                    painter.drawLine(x1, y1, x2, y2)

            if self._series_data:
                latest_val = list(self._series_data.values())[0]
                if latest_val:
                    val_str = f"{latest_val[-1]:.1f}"
                    painter.setPen(QColor(200, 200, 200))
                    fm = QFontMetrics(font)
                    tw = fm.horizontalAdvance(val_str)
                    painter.drawText(
                        margin + plot_w - tw - 2, plot_y + plot_h + 12, val_str
                    )
        finally:
            painter.end()


# ==========================================================
# ThermalWidget
# ==========================================================


class ThermalWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._frame_number: int = 0
        self._overlay_latency: float = 0.0
        self._error_message: str | None = None
        self._grab_start_time: float = 0.0
        self._update_request_time: float = 0.0
        self.paint_start_time: float = 0.0
        self.paint_finish_time: float = 0.0
        self.paint_duration: float = 0.0
        self.paint_update_delay: float = 0.0
        self.paint_total_latency: float = 0.0
        self._paint_events: deque[EmittedEvent] = deque()
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: black;")

    def set_image(
        self,
        pixmap: QPixmap,
        frame_number: int,
        grab_start_time: float,
        update_request_time: float,
        overlay_latency: float,
    ) -> None:
        self._pixmap = pixmap
        self._frame_number = frame_number
        self._grab_start_time = grab_start_time
        self._update_request_time = update_request_time
        self._overlay_latency = overlay_latency
        self._error_message = None

    def drain_paint_events(self) -> list[EmittedEvent]:
        events = list(self._paint_events)
        self._paint_events.clear()
        return events

    def show_error(self, message: str) -> None:
        self._pixmap = None
        self._error_message = message
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        self.paint_start_time = time.perf_counter()
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
            elif self._pixmap is not None and not self._pixmap.isNull():
                scaled = self._pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)

                painter.setPen(Qt.GlobalColor.green)
                font = QFont("monospace", 12)
                painter.setFont(font)
                painter.drawText(10, 22, f"#{self._frame_number}")

                latency_text = f"{self._overlay_latency:.1f} ms"
                fm = QFontMetrics(font)
                lw = fm.horizontalAdvance(latency_text)
                painter.drawText(
                    self.width() - lw - 10, 22, latency_text
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
                self.paint_finish_time - self.paint_start_time
            )
            self.paint_total_latency = (
                self.paint_finish_time - self._grab_start_time
            ) * 1000
            self.paint_update_delay = (
                self.paint_start_time - self._update_request_time
            ) * 1000
            self._paint_events.append((
                self.paint_duration * 1000,
                self.paint_total_latency,
                self.paint_update_delay,
            ))


# ==========================================================
# QualificationMonitor
# ==========================================================


class QualificationMonitor:
    """
    Passive pipeline observer. Tracks camera state and logs events
    without ever modifying camera state.
    """

    def __init__(self) -> None:
        self._disconnection_logged: bool = False
        self._connection_logged: bool = False
        self._calibration_logged: bool = False

    def poll(self, camera: TV46LCamera | None, calibration_loaded: bool, event_logger: EventLogger) -> None:
        if camera is None:
            if not self._disconnection_logged:
                event_logger.log("Camera disconnected")
                self._disconnection_logged = True
                self._connection_logged = False
            return

        self._disconnection_logged = False

        if camera.connected and not self._connection_logged:
            event_logger.log("Camera connected")
            self._connection_logged = True

        if not camera.connected and not self._disconnection_logged:
            event_logger.log("Camera disconnected")
            self._disconnection_logged = True
            self._connection_logged = False

        if not self._calibration_logged and calibration_loaded:
            event_logger.log("Calibration loaded")
            self._calibration_logged = True

    def track_timeout(self, timeout_count: int, event_logger: EventLogger) -> None:
        if timeout_count > 0:
            event_logger.log(f"Timeout #{timeout_count}")


# ==========================================================
# HealthEvaluator
# ==========================================================


class HealthEvaluator:
    """
    Evaluates subsystem health. Returns UNKNOWN when insufficient
    data is available, never FAIL on missing measurements.
    """

    @staticmethod
    def evaluate_camera(
        camera: TV46LCamera | None,
    ) -> str:
        if camera is None:
            return "FAIL"
        if not camera.connected:
            return "FAIL"
        if not camera.running:
            return "WARNING"
        if not camera.is_alive():
            return "WARNING"
        if camera.frame_count == 0:
            return "WARNING"
        return "PASS"

    @staticmethod
    def evaluate_acquisition(
        camera: TV46LCamera | None,
    ) -> str:
        if camera is None or not camera.connected:
            return "FAIL"
        if camera.frame_count == 0:
            return "UNKNOWN"
        if camera.timeout_count == 0:
            return "PASS"
        if camera.timeout_count < 5:
            return "WARNING"
        return "FAIL"

    @staticmethod
    def evaluate_calibration(
        initialized: bool,
    ) -> str:
        return "PASS" if initialized else "FAIL"

    @staticmethod
    def evaluate_rendering(
        paint_latest: float,
        paint_count: int,
    ) -> str:
        if paint_count == 0:
            return "UNKNOWN"
        if paint_latest < 5:
            return "PASS"
        if paint_latest < 10:
            return "WARNING"
        return "FAIL"

    @staticmethod
    def evaluate_memory(
        memory_mb: float,
    ) -> str:
        if memory_mb < 200:
            return "PASS"
        if memory_mb < 500:
            return "WARNING"
        return "FAIL"

    @staticmethod
    def evaluate_timing(
        total_latest: float,
        total_count: int,
    ) -> str:
        if total_count == 0:
            return "UNKNOWN"
        if total_latest < 250:
            return "PASS"
        if total_latest < 350:
            return "WARNING"
        return "FAIL"

    @staticmethod
    def overall(statuses: dict[str, str]) -> str:
        has_unknown = False
        for s in statuses.values():
            if s == "FAIL":
                return "FAIL"
            if s == "UNKNOWN":
                has_unknown = True
        if has_unknown:
            return "UNKNOWN"
        for s in statuses.values():
            if s == "WARNING":
                return "WARNING"
        return "PASS"


# ==========================================================
# QualificationSession
# ==========================================================


_PER_STAGE_KEYS = [
    "acquire", "numpy", "publish", "gui_delay", "display",
    "colormap", "qimage", "pixmap", "update_delay",
]


class QualificationSession:
    """
    Collects qualification data from run start to stop.
    Generates a comprehensive engineering acceptance report
    where each subsystem evaluates independently from full-session statistics.
    """

    TIMEOUT_WARN: int = 5
    TIMEOUT_FAIL: int = 20
    LATENCY_WARN_95: float = 250.0
    LATENCY_FAIL_95: float = 350.0
    PAINT_WARN_95: float = 8.0
    PAINT_FAIL_95: float = 15.0
    MEMORY_WARN: float = 500.0
    MEMORY_FAIL: float = 1000.0
    CPU_AVG_WARN: float = 50.0
    CPU_AVG_FAIL: float = 80.0
    CPU_PEAK_WARN: float = 80.0
    CPU_PEAK_FAIL: float = 95.0
    SKIP_RATIO_WARN: float = 0.01
    SKIP_RATIO_FAIL: float = 0.05
    FPS_MIN: float = 8.0
    FPS_STDDEV_WARN: float = 3.0
    FPS_STDDEV_FAIL: float = 5.0

    def __init__(self) -> None:
        self._start_time: float = time.time()
        self._stop_time: float | None = None
        self._frame_count: int = 0
        self._skipped_frames: int = 0
        self._timeout_count: int = 0
        self._camera_was_connected: bool = False
        self._camera_was_running: bool = False
        self._camera_disconnected: bool = False
        self._camera_stopped: bool = False
        self._fps_values: list[float] = []
        self._cpu_values: list[float] = []
        self._memory_values: list[float] = []
        self._paint_values: list[float] = []
        self._total_latency_values: list[float] = []
        self._per_stage: dict[str, list[float]] = {
            k: [] for k in _PER_STAGE_KEYS
        }

    def stop(self) -> None:
        self._stop_time = time.time()

    @property
    def duration(self) -> float:
        end = self._stop_time or time.time()
        return end - self._start_time

    def record_frame(self, skipped: int) -> None:
        self._frame_count += 1
        self._skipped_frames += skipped

    def record_timeout(self) -> None:
        self._timeout_count += 1

    def record_fps(self, fps: float) -> None:
        self._fps_values.append(fps)

    def record_cpu(self, cpu: float) -> None:
        self._cpu_values.append(cpu)

    def record_memory(self, memory_mb: float) -> None:
        self._memory_values.append(memory_mb)

    def record_paint(self, paint_ms: float) -> None:
        self._paint_values.append(paint_ms)

    def record_total_latency(self, total_ms: float) -> None:
        self._total_latency_values.append(total_ms)

    def record_per_stage(self, stage: str, value_ms: float) -> None:
        vals = self._per_stage.get(stage)
        if vals is not None:
            vals.append(value_ms)

    def record_camera_state(self, connected: bool, running: bool) -> None:
        if connected:
            self._camera_was_connected = True
        else:
            self._camera_disconnected = True
        if running:
            self._camera_was_running = True
        else:
            self._camera_stopped = True

    # ── helpers ──────────────────────────────────────────

    @staticmethod
    def _percentile(data: list[float], pct: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = int(len(sorted_data) * pct / 100.0)
        return sorted_data[min(idx, len(sorted_data) - 1)]

    @staticmethod
    def _mean(data: list[float]) -> float:
        return sum(data) / len(data) if data else 0.0

    @staticmethod
    def _stddev(data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        m = sum(data) / len(data)
        var = sum((x - m) ** 2 for x in data) / (len(data) - 1)
        return math.sqrt(var)

    # ── subsystem evaluation ─────────────────────────────

    def evaluate_camera_connection(self, camera: TV46LCamera | None) -> str:
        if camera is None:
            return "FAIL"
        if not camera.connected:
            return "FAIL"
        if self._camera_disconnected:
            return "FAIL"
        if self._frame_count == 0 and self.duration > 10:
            return "FAIL"
        return "PASS"

    def evaluate_acquisition_thread(self, camera: TV46LCamera | None) -> str:
        if camera is None:
            return "FAIL"
        if self._camera_stopped:
            return "FAIL"
        if not camera.running:
            return "WARNING"
        if self._frame_count == 0 and self.duration > 10:
            return "FAIL"
        return "PASS"

    def evaluate_frame_acquisition(self) -> str:
        if self._frame_count == 0:
            return "UNKNOWN"
        if self._timeout_count >= self.TIMEOUT_FAIL:
            return "FAIL"
        if self._timeout_count >= self.TIMEOUT_WARN:
            return "WARNING"
        avg_fps = self._mean(self._fps_values)
        if avg_fps < self.FPS_MIN:
            return "WARNING"
        if len(self._fps_values) >= 5:
            fps_std = self._stddev(self._fps_values)
            if fps_std > self.FPS_STDDEV_FAIL:
                return "FAIL"
            if fps_std > self.FPS_STDDEV_WARN:
                return "WARNING"
        return "PASS"

    def evaluate_transport(self, camera: TV46LCamera | None) -> str:
        if camera is None or not camera.connected:
            return "UNKNOWN"
        try:
            stats = camera.get_stream_statistics()
            lost = int(stats.get("[Stream]GevStreamLostPacketCount", 0))
            resend = int(stats.get("[Stream]GevStreamResendPacketCount", 0))
            if lost > 100 or resend > 100:
                return "FAIL"
            if lost > 10 or resend > 10:
                return "WARNING"
        except Exception:
            return "UNKNOWN"
        return "PASS"

    def evaluate_timing(self) -> str:
        if not self._total_latency_values:
            return "UNKNOWN"
        p95 = self._percentile(self._total_latency_values, 95)
        if p95 > self.LATENCY_FAIL_95:
            return "FAIL"
        if p95 > self.LATENCY_WARN_95:
            return "WARNING"
        return "PASS"

    def evaluate_rendering(self) -> str:
        if not self._paint_values:
            return "UNKNOWN"
        p95 = self._percentile(self._paint_values, 95)
        if p95 > self.PAINT_FAIL_95:
            return "FAIL"
        if p95 > self.PAINT_WARN_95:
            return "WARNING"
        return "PASS"

    def evaluate_memory(self) -> str:
        if not self._memory_values:
            return "UNKNOWN"
        peak = max(self._memory_values)
        if peak > self.MEMORY_FAIL:
            return "FAIL"
        if peak > self.MEMORY_WARN:
            return "WARNING"
        return "PASS"

    def evaluate_cpu(self) -> str:
        if not self._cpu_values:
            return "UNKNOWN"
        avg = self._mean(self._cpu_values)
        peak = max(self._cpu_values)
        if avg > self.CPU_AVG_FAIL or peak > self.CPU_PEAK_FAIL:
            return "FAIL"
        if avg > self.CPU_AVG_WARN or peak > self.CPU_PEAK_WARN:
            return "WARNING"
        return "PASS"

    def evaluate_frame_integrity(self) -> str:
        if self._frame_count == 0:
            return "UNKNOWN"
        ratio = self._skipped_frames / max(self._frame_count, 1)
        if ratio > self.SKIP_RATIO_FAIL:
            return "FAIL"
        if ratio > self.SKIP_RATIO_WARN:
            return "WARNING"
        return "PASS"

    def evaluate_calibration(self, initialized: bool) -> str:
        return "PASS" if initialized else "FAIL"

    def _overall(self, statuses: dict[str, str]) -> str:
        has_unknown = False
        for s in statuses.values():
            if s == "FAIL":
                return "FAIL"
            if s == "UNKNOWN":
                has_unknown = True
        if has_unknown:
            return "UNKNOWN"
        for s in statuses.values():
            if s == "WARNING":
                return "WARNING"
        return "PASS"

    # ── report ───────────────────────────────────────────

    def generate_report(
        self, camera: TV46LCamera | None, calibration_loaded: bool
    ) -> str:
        statuses: dict[str, str] = {}
        summaries: dict[str, str] = {}

        statuses["camera_connection"] = self.evaluate_camera_connection(camera)
        if camera is not None and camera.connected:
            summaries["camera_connection"] = (
                f"Serial: {camera.serial}, Connected"
            )
        else:
            summaries["camera_connection"] = "No camera"

        statuses["acquisition_thread"] = self.evaluate_acquisition_thread(camera)
        summaries["acquisition_thread"] = (
            f"Running: {camera is not None and camera.running}, "
            f"Frames: {self._frame_count}"
        )

        statuses["frame_acquisition"] = self.evaluate_frame_acquisition()
        summaries["frame_acquisition"] = (
            f"Frames: {self._frame_count}, "
            f"Timeouts: {self._timeout_count}, "
            f"Avg FPS: {self._mean(self._fps_values):.1f}"
        )

        statuses["transport"] = self.evaluate_transport(camera)
        if camera is not None and camera.connected:
            try:
                stats = camera.get_stream_statistics()
                lost = int(stats.get("[Stream]GevStreamLostPacketCount", -1))
                resend = int(stats.get("[Stream]GevStreamResendPacketCount", -1))
                summaries["transport"] = f"Lost: {lost}, Resend: {resend}"
            except Exception:
                summaries["transport"] = "Unavailable"

        statuses["timing"] = self.evaluate_timing()
        if self._total_latency_values:
            summaries["timing"] = (
                f"95th: {self._percentile(self._total_latency_values, 95):.1f}ms, "
                f"Avg: {self._mean(self._total_latency_values):.1f}ms, "
                f"Min: {min(self._total_latency_values):.1f}ms, "
                f"Max: {max(self._total_latency_values):.1f}ms, "
                f"Samples: {len(self._total_latency_values)}"
            )
        else:
            summaries["timing"] = "No data"

        statuses["rendering"] = self.evaluate_rendering()
        if self._paint_values:
            summaries["rendering"] = (
                f"95th: {self._percentile(self._paint_values, 95):.2f}ms, "
                f"Avg: {self._mean(self._paint_values):.2f}ms, "
                f"Samples: {len(self._paint_values)}"
            )
        else:
            summaries["rendering"] = "No data"

        statuses["memory"] = self.evaluate_memory()
        if self._memory_values:
            summaries["memory"] = (
                f"Peak: {max(self._memory_values):.1f} MB, "
                f"Avg: {self._mean(self._memory_values):.1f} MB"
            )
        else:
            summaries["memory"] = "No data"

        statuses["cpu"] = self.evaluate_cpu()
        if self._cpu_values:
            summaries["cpu"] = (
                f"Avg: {self._mean(self._cpu_values):.1f}%, "
                f"Peak: {max(self._cpu_values):.1f}%"
            )
        else:
            summaries["cpu"] = "No data"

        statuses["frame_integrity"] = self.evaluate_frame_integrity()
        ratio = self._skipped_frames / max(self._frame_count, 1) * 100
        summaries["frame_integrity"] = (
            f"Skipped: {self._skipped_frames} ({ratio:.2f}%), "
            f"Total frames: {self._frame_count}"
        )

        statuses["calibration"] = self.evaluate_calibration(calibration_loaded)
        summaries["calibration"] = "Loaded" if calibration_loaded else "Not loaded"

        overall = self._overall(statuses)
        duration = self.duration

        report_keys = [
            "camera_connection", "acquisition_thread", "frame_acquisition",
            "transport", "timing", "rendering", "memory", "cpu",
            "frame_integrity", "calibration",
        ]

        lines: list[str] = []
        lines.append("=" * 68)
        lines.append("  CAMERA QUALIFICATION REPORT")
        lines.append("=" * 68)
        lines.append("")
        lines.append(f"  Duration: {duration:.1f}s")
        lines.append("")
        for key in report_keys:
            s = statuses.get(key, "UNKNOWN")
            summary = summaries.get(key, "")
            lines.append(f"  {key:22s}  {s:10s}  {summary}")
        lines.append("")
        lines.append("-" * 68)
        passed = sum(1 for v in statuses.values() if v == "PASS")
        warned = sum(1 for v in statuses.values() if v == "WARNING")
        failed = sum(1 for v in statuses.values() if v == "FAIL")
        unknown = sum(1 for v in statuses.values() if v == "UNKNOWN")
        total = len(statuses)
        lines.append(
            f"  Total: {total}  Pass: {passed}  "
            f"Warning: {warned}  Fail: {failed}  Unknown: {unknown}"
        )
        if failed > 0:
            lines.append("  Result: FAIL")
        elif warned > 0:
            lines.append("  Result: PASS (with warnings)")
        elif unknown > 0:
            lines.append("  Result: PASS (with unknowns)")
        else:
            lines.append("  Result: PASS")
        lines.append("=" * 68)
        return "\n".join(lines)


# ==========================================================
# QualificationEngine
# ==========================================================


class QualificationEngine:
    DEFAULT_THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
        "acquire": (100.0, 120.0, 130.0, 150.0),
        "numpy": (0.0, 3.0, 5.0, 10.0),
        "publish": (0.0, 5.0, 10.0, 20.0),
        "gui_delay": (0.0, 10.0, 25.0, 50.0),
        "display": (0.0, 5.0, 10.0, 20.0),
        "colormap": (0.0, 5.0, 10.0, 20.0),
        "qimage": (0.0, 2.0, 5.0, 10.0),
        "pixmap": (0.0, 2.0, 5.0, 10.0),
        "update_delay": (0.0, 5.0, 15.0, 30.0),
        "paint": (0.0, 2.0, 5.0, 10.0),
        "total": (100.0, 200.0, 250.0, 350.0),
    }

    def __init__(self) -> None:
        self.thresholds: dict[str, tuple[float, float, float, float]] = {
            k: v for k, v in self.DEFAULT_THRESHOLDS.items()
        }

    def set_threshold(
        self,
        subsystem: str,
        expected_min: float,
        expected_max: float,
        warning: float,
        fail: float,
    ) -> None:
        self.thresholds[subsystem] = (expected_min, expected_max, warning, fail)

    def evaluate(self, subsystem: str, value: float) -> str:
        threshold = self.thresholds.get(subsystem)
        if threshold is None:
            return "PASS"
        _expected_min, _expected_max, warn, fail = threshold
        if value > fail:
            return "FAIL"
        elif value > warn:
            return "WARNING"
        else:
            return "PASS"

    def generate_report(self, all_statuses: dict[str, str]) -> str:
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  CAMERA QUALIFICATION REPORT")
        lines.append("=" * 60)
        lines.append("")
        passed = 0
        warned = 0
        failed = 0
        for subsystem, status in sorted(all_statuses.items()):
            lines.append(f"  {subsystem:20s}  {status}")
            if status == "PASS":
                passed += 1
            elif status == "WARNING":
                warned += 1
            else:
                failed += 1
        lines.append("")
        lines.append("-" * 60)
        total = passed + warned + failed
        lines.append(f"  Total: {total}  Pass: {passed}  Warning: {warned}  Fail: {failed}")
        if failed > 0:
            lines.append("  Result: FAIL")
        elif warned > 0:
            lines.append("  Result: PASS (with warnings)")
        else:
            lines.append("  Result: PASS")
        lines.append("=" * 60)
        return "\n".join(lines)


# ==========================================================
# AcquisitionPanel
# ==========================================================


class AcquisitionPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setSpacing(4)
        entries = [
            ("Connection", "connection"),
            ("Camera Serial", "serial"),
            ("Thread Alive", "alive"),
            ("Thread State", "state"),
            ("Frame Number", "frame"),
            ("Sequence", "sequence"),
            ("Camera FPS", "fps"),
            ("Dropped Frames", "dropped"),
            ("Timeout Count", "timeouts"),
            ("Acquisition Runtime", "runtime"),
        ]
        for row, (name, key) in enumerate(entries):
            label_name = QLabel(f"{name}:")
            label_name.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            label_value = QLabel("--")
            label_value.setFont(QFont("monospace", 10))
            label_value.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(label_name, row, 0)
            layout.addWidget(label_value, row, 1)
            self._labels[key] = label_value

    def refresh(
        self,
        camera: TV46LCamera | None,
        stats: dict | None,
    ) -> None:
        if camera is not None:
            self._labels["connection"].setText(
                "Connected" if camera.connected else "Disconnected"
            )
            self._labels["serial"].setText(camera.serial)
            self._labels["alive"].setText(
                "Yes" if camera.is_alive() else "No"
            )
            self._labels["state"].setText(
                "Running" if camera.running else "Stopped"
            )
            self._labels["frame"].setText(str(camera.frame_count))
            self._labels["sequence"].setText(str(camera.frame_count))
            self._labels["fps"].setText(str(camera.get_fps()))
            self._labels["timeouts"].setText(str(camera.timeout_count))
        if stats is not None:
            self._labels["dropped"].setText(
                str(stats.get("dropped_frames", "--"))
            )
            self._labels["runtime"].setText(
                f"{stats.get('runtime', 0):.1f}s"
            )


# ==========================================================
# ProcessingPanel
# ==========================================================


class ProcessingPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setSpacing(4)
        entries = [
            ("Current Range", "range"),
            ("Calibration Loaded", "cal_loaded"),
            ("Display Conversion", "display"),
            ("Color Map Time", "colormap"),
            ("QImage Time", "qimage"),
            ("QPixmap Time", "pixmap"),
            ("Paint Time", "paint"),
            ("Total Pipeline Time", "total"),
        ]
        for row, (name, key) in enumerate(entries):
            label_name = QLabel(f"{name}:")
            label_name.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            label_value = QLabel("--")
            label_value.setFont(QFont("monospace", 10))
            label_value.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(label_name, row, 0)
            layout.addWidget(label_value, row, 1)
            self._labels[key] = label_value

    def refresh(
        self,
        timing: TimingMonitor,
        calibration_loaded: bool,
        range_index: int,
    ) -> None:
        self._labels["range"].setText(str(range_index))
        self._labels["cal_loaded"].setText(
            "Yes" if calibration_loaded else "No"
        )
        if timing.display.count > 0:
            self._labels["display"].setText(f"{timing.display.latest:.3f} ms")
            self._labels["colormap"].setText(f"{timing.colormap.latest:.3f} ms")
            self._labels["qimage"].setText(f"{timing.qimage.latest:.3f} ms")
            self._labels["pixmap"].setText(f"{timing.pixmap.latest:.3f} ms")
            self._labels["paint"].setText(f"{timing.paint.latest:.3f} ms")
            self._labels["total"].setText(f"{timing.total.latest:.3f} ms")


# ==========================================================
# SystemPanel
# ==========================================================


class SystemPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setSpacing(4)
        entries = [
            ("CPU %", "cpu"),
            ("Memory MB", "memory"),
            ("GUI FPS", "gui_fps"),
            ("Update Rate", "update_rate"),
            ("Paint Rate", "paint_rate"),
            ("Window Size", "window_size"),
            ("Image Size", "image_size"),
        ]
        for row, (name, key) in enumerate(entries):
            label_name = QLabel(f"{name}:")
            label_name.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            label_value = QLabel("--")
            label_value.setFont(QFont("monospace", 10))
            label_value.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(label_name, row, 0)
            layout.addWidget(label_value, row, 1)
            self._labels[key] = label_value

    def refresh(
        self,
        cpu: float,
        memory: float,
        gui_fps: int,
        update_count: int,
        paint_count: int,
        window_size: tuple[int, int],
        image_size: tuple[int, int],
    ) -> None:
        self._labels["cpu"].setText(f"{cpu:.1f}%")
        self._labels["memory"].setText(f"{memory:.1f} MB")
        self._labels["gui_fps"].setText(str(gui_fps))
        self._labels["update_rate"].setText(str(update_count))
        self._labels["paint_rate"].setText(str(paint_count))
        self._labels["window_size"].setText(f"{window_size[0]}x{window_size[1]}")
        self._labels["image_size"].setText(f"{image_size[0]}x{image_size[1]}")


# ==========================================================
# HealthPanel
# ==========================================================


class HealthPanel(QWidget):
    COLOR_PASS = "#2ecc71"
    COLOR_WARN = "#f1c40f"
    COLOR_FAIL = "#e74c3c"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setSpacing(4)
        entries = [
            "Camera",
            "Acquisition",
            "Calibration",
            "Rendering",
            "Memory",
            "Timing",
        ]
        for row, name in enumerate(entries):
            label_name = QLabel(f"{name}:")
            label_name.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            label_value = QLabel("PASS")
            label_value.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            label_value.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            label_value.setStyleSheet(
                f"background-color: {self.COLOR_PASS}; color: white; "
                f"border-radius: 4px; padding: 2px 8px;"
            )
            layout.addWidget(label_name, row, 0)
            layout.addWidget(label_value, row, 1)
            self._labels[name.lower()] = label_value

    def refresh_panel(self, statuses: dict[str, str]) -> None:
        for key, status in statuses.items():
            label = self._labels.get(key)
            if label is None:
                continue
            if status == "PASS":
                color = self.COLOR_PASS
            elif status == "WARNING":
                color = self.COLOR_WARN
            else:
                color = self.COLOR_FAIL
            label.setText(status)
            label.setStyleSheet(
                f"background-color: {color}; color: white; "
                f"border-radius: 4px; padding: 2px 8px;"
            )


# ==========================================================
# TimingTable
# ==========================================================


_STAGE_NAMES = [
    "acquire", "numpy", "publish", "gui_delay", "display",
    "colormap", "qimage", "pixmap", "update_delay", "paint", "total",
]


class TimingTable(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(len(_STAGE_NAMES), 7)
        self._table.setHorizontalHeaderLabels(
            ["Stage", "Latest (ms)", "Min", "Max", "Avg", "StdDev", "95th"]
        )
        self._table.setVerticalHeaderLabels(_STAGE_NAMES)
        self._table.setFont(QFont("monospace", 9))
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

    def refresh_table(self, stats: dict[str, StageStats]) -> None:
        for row, name in enumerate(_STAGE_NAMES):
            s = stats.get(name)
            if s is None or s.count == 0:
                continue
            items = [
                name,
                f"{s.latest:.3f}",
                f"{s.minimum:.3f}",
                f"{s.maximum:.3f}",
                f"{s.average:.3f}",
                f"{s.stddev:.3f}",
                f"{s.percentile_95:.3f}",
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()


# ==========================================================
# MainWindow
# ==========================================================


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._camera: TV46LCamera | None = None
        self._calibration = CalibrationManager()
        self._timing = TimingMonitor()
        self._frame_history = FrameHistory()
        self._graph_manager = GraphManager()
        self._event_logger = EventLogger()
        self._qualification = QualificationEngine()
        self._monitor = QualificationMonitor()
        self._session = QualificationSession()
        self._process = psutil.Process()

        self._last_sequence: int = -1
        self._skipped_frames: int = 0
        self._update_requests: int = 0
        self._paint_event_count: int = 0
        self._gui_frame_count: int = 0
        self._gui_fps: int = 0
        self._gui_fps_timer: float = time.time()
        self._last_console_time: float = time.time()
        self._stress_test_enabled: bool = False
        self._stress_paint_count: int = 0
        self._acquisition_start_time: float = 0.0
        self._last_timeout_count: int = 0

        self._graph_widgets: list[GraphWidget] = []

        self._init_ui()
        self._init_camera()
        if self._camera_error is not None:
            self._thermal_widget.show_error(self._camera_error)
            self._event_logger.log(f"Camera init failed: {self._camera_error}")
        self._init_timers()

    # ==========================================================
    # UI Setup
    # ==========================================================

    def _init_ui(self) -> None:
        self.setWindowTitle("TV46L Camera Viewer — Qualification Mode")
        self.setMinimumSize(1024, 768)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self._thermal_widget = ThermalWidget()
        main_layout.addWidget(self._thermal_widget, stretch=1)

        overlay = QFrame()
        overlay.setFrameStyle(QFrame.Shape.StyledPanel)
        overlay_layout = QHBoxLayout(overlay)
        overlay_layout.setContentsMargins(8, 2, 8, 2)
        self._overlay_labels: dict[str, QLabel] = {}
        for key, text in [
            ("frame", "Frame: --"),
            ("fps", "FPS: --"),
            ("latency", "Lat: -- ms"),
            ("status", "Status: --"),
        ]:
            label = QLabel(text)
            label.setFont(QFont("monospace", 10, QFont.Weight.Bold))
            overlay_layout.addWidget(label)
            self._overlay_labels[key] = label
        overlay_layout.addStretch()
        self._status_indicator = QLabel("●")
        self._status_indicator.setFont(QFont("monospace", 14))
        self._status_indicator.setStyleSheet("color: gray;")
        overlay_layout.addWidget(self._status_indicator)
        main_layout.addWidget(overlay)

        self._tab_widget = QTabWidget()
        self._acquisition_panel = AcquisitionPanel()
        self._processing_panel = ProcessingPanel()
        self._system_panel = SystemPanel()
        self._health_panel = HealthPanel()
        self._tab_widget.addTab(self._acquisition_panel, "Acquisition")
        self._tab_widget.addTab(self._processing_panel, "Processing")
        self._tab_widget.addTab(self._system_panel, "System")
        self._tab_widget.addTab(self._health_panel, "Health")
        main_layout.addWidget(self._tab_widget)

        self._timing_table = TimingTable()
        self._timing_table.setMaximumHeight(220)
        main_layout.addWidget(self._timing_table)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        graph_container = QWidget()
        graph_layout = QGridLayout(graph_container)
        graph_layout.setSpacing(2)
        graph_titles = [
            "Total Latency", "Acquire Time", "Display+Colormap",
            "QImage+Pixmap", "GUI Delay", "Paint Time",
            "FPS", "CPU %", "Update Rate",
        ]
        graph_keys = [
            "total", "acquire", "display_colormap",
            "qimage_pixmap", "gui_delay", "paint",
            "fps", "cpu", "update_rate",
        ]
        self._graph_widgets = []
        for idx, (title, key) in enumerate(zip(graph_titles, graph_keys)):
            gw = GraphWidget(title)
            gw.set_range(0, 100)
            gw.set_series(key, [], GraphWidget.COLORS.get(key, QColor(255, 255, 255)))
            graph_layout.addWidget(gw, idx // 3, idx % 3)
            self._graph_widgets.append(gw)
        splitter.addWidget(graph_container)

        self._event_list = QListWidget()
        self._event_list.setFont(QFont("monospace", 9))
        self._event_list.setMinimumWidth(200)
        self._event_logger.attach(self._event_list)
        splitter.addWidget(self._event_list)
        main_layout.addWidget(splitter, stretch=1)

        bottom_bar = QFrame()
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(4, 2, 4, 2)
        self._stress_checkbox = QCheckBox("Stress Test")
        self._stress_checkbox.toggled.connect(self._on_stress_toggled)
        bottom_layout.addWidget(self._stress_checkbox)
        bottom_layout.addStretch()
        self._qual_button = QPushButton("Qualification Report")
        self._qual_button.clicked.connect(self._show_qualification_report)
        bottom_layout.addWidget(self._qual_button)
        main_layout.addWidget(bottom_bar)

    # ==========================================================
    # Camera Setup
    # ==========================================================

    def _init_camera(self) -> None:
        self._camera_error: str | None = None
        try:
            print("[INFO] Initializing calibration...")
            self._calibration.initialize()
            self._event_logger.log("Calibration loaded")

            print("[INFO] Discovering cameras...")
            cameras = _discover_cameras()
            if not cameras:
                self._camera_error = "No GigE Vision cameras found."
                print(f"[ERROR] {self._camera_error}")
                return

            cam_info = cameras[0]
            print(f"[INFO] Using camera: {cam_info.serial} @ {cam_info.ip}")

            self._camera = TV46LCamera(cam_info, settings)
            self._camera.connect()
            self._camera.start()
            self._acquisition_start_time = time.time()

            if not self._camera.wait_for_first_frame(10):
                self._camera_error = "No frames received from camera."
                print(f"[ERROR] {self._camera_error}")
                self._camera.disconnect()
                self._camera = None
                return

            self._event_logger.log("Camera connected")
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
        self._frame_timer.timeout.connect(self._poll_frame)
        self._frame_timer.start(_FRAME_TIMER_MS)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._update_diagnostics)
        self._diag_timer.start(_DIAG_TIMER_MS)

        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._update_graphs)
        self._graph_timer.start(_GRAPH_TIMER_MS)

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
            gap = frame.sequence - self._last_sequence - 1
            self._skipped_frames += gap
            self._event_logger.log(f"Skipped frame: seq {frame.sequence}")
        else:
            gap = 0

        self._last_sequence = frame.sequence
        self._gui_frame_count += 1
        self._session.record_frame(gap)

        gui_poll_time = time.perf_counter()

        display_start = time.perf_counter()
        display_image = self._calibration.raw_to_display(frame.image)
        display_finish = time.perf_counter()

        colormap_start = time.perf_counter()
        color_image = self._calibration.apply_colormap(display_image)
        colormap_finish = time.perf_counter()

        qimage_start = time.perf_counter()
        rgb_image = cv2.cvtColor(color_image, cv2.COLOR_BGR2RGB)
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

        now_time = time.time()
        if now_time - self._gui_fps_timer >= 1.0:
            self._gui_fps = self._gui_frame_count
            self._session.record_fps(float(self._gui_fps))
            self._gui_frame_count = 0
            self._gui_fps_timer = now_time

        acquire_ms = (gct - gst) * 1000
        numpy_ms = (nct - gct) * 1000
        publish_ms = (pt - nct) * 1000
        gui_delay_ms = (gui_poll_time - pt) * 1000
        display_ms = (display_finish - display_start) * 1000
        colormap_ms = (colormap_finish - colormap_start) * 1000
        qimage_ms = (qimage_finish - qimage_start) * 1000
        pixmap_ms = (pixmap_finish - pixmap_start) * 1000

        latency_dict = {
            "acquire": acquire_ms,
            "numpy": numpy_ms,
            "publish": publish_ms,
            "gui_delay": gui_delay_ms,
            "display": display_ms,
            "colormap": colormap_ms,
            "qimage": qimage_ms,
            "pixmap": pixmap_ms,
        }
        self._timing.update_all(latency_dict)
        for stage, val in latency_dict.items():
            self._session.record_per_stage(stage, val)

        self._graph_manager.add_point("acquire", acquire_ms)
        self._graph_manager.add_point("display_colormap", display_ms + colormap_ms)
        self._graph_manager.add_point("qimage_pixmap", qimage_ms + pixmap_ms)
        self._graph_manager.add_point("gui_delay", gui_delay_ms)
        self._graph_manager.add_point("fps", float(self._camera.get_fps() if self._camera else 0))

        record = FrameRecord(
            sequence=frame.sequence,
            frame_number=frame.frame_number,
            grab_start=gst,
            grab_complete=gct,
            numpy_complete=nct,
            publish_time=pt,
            gui_poll_time=gui_poll_time,
            display_start=display_start,
            display_finish=display_finish,
            colormap_start=colormap_start,
            colormap_finish=colormap_finish,
            qimage_start=qimage_start,
            qimage_finish=qimage_finish,
            pixmap_start=pixmap_start,
            pixmap_finish=pixmap_finish,
            update_request=update_request,
        )
        self._frame_history.append(record)

        if frame.frame_number % 5 == 0:
            timeout_count = self._camera.timeout_count if self._camera else 0
            if timeout_count > self._last_timeout_count:
                self._monitor.track_timeout(timeout_count, self._event_logger)
                for _ in range(timeout_count - self._last_timeout_count):
                    self._session.record_timeout()
                self._last_timeout_count = timeout_count

        if self._stress_test_enabled:
            for _ in range(3):
                self._thermal_widget.update()
                self._stress_paint_count += 1

        self._update_console()

    # ==========================================================
    # Diagnostics Update (1000 ms)
    # ==========================================================

    def _update_diagnostics(self) -> None:
        tw = self._thermal_widget
        paint_events = tw.drain_paint_events()
        for paint_ms, total_ms, delay_ms in paint_events:
            self._timing.paint.update(paint_ms)
            self._timing.total.update(total_ms)
            self._timing.update_delay.update(delay_ms)
            self._graph_manager.add_point("paint", paint_ms)
            self._session.record_paint(paint_ms)
            self._session.record_total_latency(total_ms)
            self._paint_event_count += 1

            latest = self._frame_history.latest
            if latest is not None:
                latest.paint_start = tw.paint_start_time
                latest.paint_finish = tw.paint_finish_time

        cpu = self._process.cpu_percent()
        memory = self._process.memory_info().rss / 1024 / 1024
        self._session.record_cpu(cpu)
        self._session.record_memory(memory)
        self._graph_manager.add_point("cpu", cpu)
        self._graph_manager.add_point("update_rate", float(self._gui_fps))

        window_size = (self.width(), self.height())
        img_w, img_h = 0, 0
        if tw._pixmap is not None:
            img_w = tw._pixmap.width()
            img_h = tw._pixmap.height()

        self._acquisition_panel.refresh(
            self._camera,
            self._camera.get_stream_statistics() if self._camera else None,
        )
        self._processing_panel.refresh(
            self._timing,
            self._calibration.is_initialized,
            0,
        )
        self._system_panel.refresh(
            cpu,
            memory,
            self._gui_fps,
            self._update_requests,
            self._paint_event_count,
            window_size,
            (img_w, img_h),
        )

        statuses = self._evaluate_health()
        self._health_panel.refresh_panel(statuses)

        overall = HealthEvaluator.overall(statuses)
        self._update_overlay(
            self._last_sequence,
            self._gui_fps,
            self._timing.total.latest,
            overall,
        )
        self._update_status_indicator(overall)

        self._timing_table.refresh_table(self._timing.get_stats())

        self._check_camera_state()

    # ==========================================================
    # Health Evaluation
    # ==========================================================

    def _evaluate_health(self) -> dict[str, str]:
        statuses: dict[str, str] = {}

        statuses["camera"] = HealthEvaluator.evaluate_camera(self._camera)
        statuses["acquisition"] = HealthEvaluator.evaluate_acquisition(self._camera)
        statuses["calibration"] = HealthEvaluator.evaluate_calibration(self._calibration.is_initialized)
        statuses["rendering"] = HealthEvaluator.evaluate_rendering(
            self._timing.paint.latest, self._timing.paint.count
        )
        memory_mb = self._process.memory_info().rss / 1024 / 1024
        statuses["memory"] = HealthEvaluator.evaluate_memory(memory_mb)
        statuses["timing"] = HealthEvaluator.evaluate_timing(
            self._timing.total.latest, self._timing.total.count
        )

        return statuses

    def _check_camera_state(self) -> None:
        self._monitor.poll(self._camera, self._calibration.is_initialized, self._event_logger)
        if self._camera is None:
            self._session.record_camera_state(False, False)
        else:
            self._session.record_camera_state(self._camera.connected, self._camera.running)

    # ==========================================================
    # Graph Update (200 ms)
    # ==========================================================

    def _update_graphs(self) -> None:
        all_series = self._graph_manager.get_all_series()
        for gw in self._graph_widgets:
            title = gw._title
            if title == "Total Latency":
                data = all_series.get("total", [])
                gw.set_series("total", data, GraphWidget.COLORS.get("total"))
                if data:
                    rng = max(data) - min(data) if data else 100
                    gw.set_range(max(0, min(data) - rng * 0.1), max(data) + rng * 0.1 + 1)
            elif title == "Acquire Time":
                data = all_series.get("acquire", [])
                gw.set_series("acquire", data, GraphWidget.COLORS.get("acquire"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "Display+Colormap":
                data = all_series.get("display_colormap", [])
                gw.set_series("display_colormap", data, GraphWidget.COLORS.get("display"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "QImage+Pixmap":
                data = all_series.get("qimage_pixmap", [])
                gw.set_series("qimage_pixmap", data, GraphWidget.COLORS.get("qimage"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "GUI Delay":
                data = all_series.get("gui_delay", [])
                gw.set_series("gui_delay", data, GraphWidget.COLORS.get("gui_delay"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "Paint Time":
                data = all_series.get("paint", [])
                gw.set_series("paint", data, GraphWidget.COLORS.get("paint"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "FPS":
                data = all_series.get("fps", [])
                gw.set_series("fps", data, GraphWidget.COLORS.get("fps"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "CPU %":
                data = all_series.get("cpu", [])
                gw.set_series("cpu", data, GraphWidget.COLORS.get("total"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)
            elif title == "Update Rate":
                data = all_series.get("update_rate", [])
                gw.set_series("update_rate", data, GraphWidget.COLORS.get("gui_delay"))
                if data:
                    gw.set_range(0, max(data) * 1.2 + 1)

    # ==========================================================
    # Overlay Update
    # ==========================================================

    def _update_overlay(
        self,
        frame_num: int,
        fps: int,
        latency: float,
        status: str,
    ) -> None:
        self._overlay_labels["frame"].setText(f"Frame: {frame_num if frame_num >= 0 else '--'}")
        self._overlay_labels["fps"].setText(f"FPS: {fps}")
        self._overlay_labels["latency"].setText(f"Lat: {latency:.1f} ms")
        self._overlay_labels["status"].setText(f"Status: {status}")

    def _update_status_indicator(self, status: str) -> None:
        if status == "PASS":
            self._status_indicator.setStyleSheet("color: #2ecc71;")
        elif status == "WARNING":
            self._status_indicator.setStyleSheet("color: #f1c40f;")
        else:
            self._status_indicator.setStyleSheet("color: #e74c3c;")

    # ==========================================================
    # Stress Test
    # ==========================================================

    def _on_stress_toggled(self, checked: bool) -> None:
        self._stress_test_enabled = checked
        self._event_logger.log(
            f"Stress test {'enabled' if checked else 'disabled'}"
        )

    # ==========================================================
    # Qualification Report
    # ==========================================================

    def _show_qualification_report(self) -> None:
        self._session.stop()
        report = self._session.generate_report(self._camera, self._calibration.is_initialized)
        dialog = QDialog(self)
        dialog.setWindowTitle("Qualification Report")
        dialog.setMinimumSize(700, 500)
        layout = QVBoxLayout(dialog)
        label = QLabel(report)
        label.setFont(QFont("monospace", 9))
        label.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    # ==========================================================
    # Console Output
    # ==========================================================

    def _update_console(self) -> None:
        now = time.time()
        if now - self._last_console_time < _CONSOLE_INTERVAL:
            return
        self._last_console_time = now
        frame = self._last_sequence
        seq = self._last_sequence
        fps = self._camera.get_fps() if self._camera else 0
        timeouts = self._camera.timeout_count if self._camera else 0
        total_lat = self._timing.total.latest
        statuses = self._evaluate_health()
        overall = HealthEvaluator.overall(statuses)
        print(
            f"[CAMQUAL] F:{frame} S:{seq} FPS:{fps} "
            f"T:{timeouts} Lat:{total_lat:.1f}ms Health:{overall}"
        )

    # ==========================================================
    # Shutdown
    # ==========================================================

    def closeEvent(self, event) -> None:  # noqa: N802
        self._frame_timer.stop()
        self._diag_timer.stop()
        self._graph_timer.stop()
        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.disconnect()
            except Exception:
                pass
        super().closeEvent(event)


# ==========================================================
# Entry Point
# ==========================================================


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("TV46L Camera Viewer")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
