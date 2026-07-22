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
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
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
    QStatusBar,
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
# CameraTileWidget
# ==========================================================


class CameraTileWidget(QWidget):
    """
    Compact selectable camera tile for multi-camera grid.

    Displays thermal image (~80%) + compact stats bar.
    Click to select — emits selected(camera_serial).
    """

    selected = pyqtSignal(str)

    TILE_STYLE_DEFAULT = """
    QWidget#cameraTile {
        background-color: #F5F5F5;
        border: 2px solid #CCCCCC;
        border-radius: 4px;
    }
    QWidget#cameraTile:hover {
        border: 2px solid #999999;
    }
    """

    TILE_STYLE_SELECTED = """
    QWidget#cameraTile {
        background-color: #E8F0FE;
        border: 3px solid #1A73E8;
        border-radius: 4px;
    }
    """

    def __init__(
        self,
        serial: str,
        camera_name: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._serial = serial
        self._camera_name = camera_name
        self._selected = False
        self._pixmap: QPixmap | None = None
        self._frame_number: int = 0
        self._fps: int = 0
        self._latency_ms: float = 0.0
        self._timeouts: int = 0
        self._overall_status: str = "UNKNOWN"
        self._error_message: str | None = None
        self._paint_start: float = 0.0
        self._paint_finish: float = 0.0
        self._paint_events: deque[float] = deque(maxlen=128)

        self.setObjectName("cameraTile")
        self.setMinimumSize(200, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self.TILE_STYLE_DEFAULT)

        self._build_ui()

    # ── properties ──────────────────────────────────────────

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setStyleSheet(
            self.TILE_STYLE_SELECTED if selected else self.TILE_STYLE_DEFAULT
        )
        self._selected_label.setVisible(selected)

    # ── ui ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(4)

        name = QLabel(self._camera_name)
        name.setStyleSheet(
            "color: #1A1A1A; font-size: 11px; font-weight: bold;"
        )
        header.addWidget(name)
        header.addStretch()

        self._selected_label = QLabel("SELECTED")
        self._selected_label.setStyleSheet(
            "color: #1A73E8; font-weight: bold; font-size: 9px;"
        )
        self._selected_label.setVisible(False)
        header.addWidget(self._selected_label)

        layout.addLayout(header)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            "background-color: #E0E0E0; border: 1px solid #CCCCCC;"
        )
        layout.addWidget(self._image_label, stretch=1)

        stats = QHBoxLayout()
        stats.setSpacing(6)

        self._stat_labels: dict[str, QLabel] = {}
        for key, fmt in [
            ("frame", "F:0"),
            ("latency", "L:0ms"),
            ("status", "S:??"),
        ]:
            label = QLabel(fmt)
            label.setStyleSheet(
                "color: #333333; font-size: 10px;"
                "font-family: 'Consolas', 'Courier New', monospace;"
            )
            stats.addWidget(label)
            self._stat_labels[key] = label

        layout.addLayout(stats)

    # ── update ──────────────────────────────────────────────

    def set_image(
        self,
        pixmap: QPixmap,
        frame_number: int,
        fps: int,
        latency_ms: float,
        timeouts: int,
        status: str,
    ) -> None:
        self._pixmap = pixmap
        self._frame_number = frame_number
        self._fps = fps
        self._latency_ms = latency_ms
        self._timeouts = timeouts
        self._overall_status = status
        self._error_message = None
        self._update_display()

    def show_error(self, message: str) -> None:
        self._pixmap = None
        self._error_message = message
        self._update_display()

    def _update_display(self) -> None:
        if self._error_message is not None:
            self._image_label.setText(self._error_message)
            self._image_label.setStyleSheet(
                "color: #CC0000; background-color: #E0E0E0;"
                "border: 1px solid #CCCCCC; font-size: 10px;"
            )
            return

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_label.setPixmap(scaled)
            self._image_label.setStyleSheet(
                "background-color: #E0E0E0; border: 1px solid #CCCCCC;"
            )
        else:
            self._image_label.setText("No frame")
            self._image_label.setStyleSheet(
                "color: #999999; background-color: #E0E0E0;"
                "border: 1px solid #CCCCCC; font-size: 10px;"
            )

        self._stat_labels["frame"].setText(
            f"F:{self._frame_number}"
        )
        self._stat_labels["latency"].setText(
            f"L:{self._latency_ms:.0f}ms"
        )
        status_text = self._overall_status[:4]
        self._stat_labels["status"].setText(
            f"S:{status_text}"
        )

    def drain_paint_events(self) -> list[float]:
        events = list(self._paint_events)
        self._paint_events.clear()
        return events

    # ── events ──────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        self._paint_start = time.perf_counter()
        super().paintEvent(event)
        self._paint_finish = time.perf_counter()
        paint_ms = (self._paint_finish - self._paint_start) * 1000
        self._paint_events.append(paint_ms)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_display()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self._serial)
        super().mousePressEvent(event)


# ==========================================================
# CameraControlPanel
# ==========================================================


class CameraControlPanel(QFrame):
    """
    Single control panel for the selected camera.

    Manual NUC button + Focus Near/Far buttons + focus distance.
    """

    nuc_clicked = pyqtSignal()
    focus_near_clicked = pyqtSignal()
    focus_far_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setObjectName("controlPanel")
        self.setStyleSheet("""
        QFrame#controlPanel {
            background-color: #FAFAFA;
            border: 1px solid #D0D0D0;
            border-radius: 4px;
        }
        """)

        self._build_ui()
        self.clear_selection()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        title = QLabel("Camera Control")
        title.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #1A1A1A;"
        )
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #D0D0D0;")
        layout.addWidget(sep)

        self._selected_label = QLabel("No camera selected")
        self._selected_label.setStyleSheet(
            "color: #1A73E8; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self._selected_label)

        layout.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #D0D0D0;")
        layout.addWidget(sep2)

        nuc_label = QLabel("NUC:")
        nuc_label.setStyleSheet(
            "color: #555555; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(nuc_label)

        self._nuc_button = QPushButton("Execute NUC")
        self._nuc_button.setStyleSheet("""
        QPushButton {
            background-color: #E8F0FE; color: #1A73E8;
            border: 1px solid #1A73E8; border-radius: 3px;
            padding: 4px 16px; font-size: 11px; font-weight: bold;
        }
        QPushButton:hover { background-color: #D2E3FC; }
        QPushButton:disabled {
            background-color: #F0F0F0; color: #AAAAAA;
            border: 1px solid #CCCCCC;
        }
        """)
        self._nuc_button.clicked.connect(self._on_nuc)
        layout.addWidget(self._nuc_button)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet("color: #D0D0D0;")
        layout.addWidget(sep3)

        focus_label = QLabel("Focus:")
        focus_label.setStyleSheet(
            "color: #555555; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(focus_label)

        self._focus_near_btn = QPushButton("<< Near")
        self._focus_near_btn.setStyleSheet("""
        QPushButton {
            background-color: #F0F0F0; color: #333333;
            border: 1px solid #CCCCCC; border-radius: 3px;
            padding: 4px 12px; font-size: 11px; font-weight: bold;
        }
        QPushButton:hover { background-color: #E0E0E0; }
        QPushButton:disabled {
            background-color: #F0F0F0; color: #AAAAAA;
            border: 1px solid #CCCCCC;
        }
        """)
        self._focus_near_btn.clicked.connect(self._on_focus_near)
        layout.addWidget(self._focus_near_btn)

        self._focus_far_btn = QPushButton("Far >>")
        self._focus_far_btn.setStyleSheet(self._focus_near_btn.styleSheet())
        self._focus_far_btn.clicked.connect(self._on_focus_far)
        layout.addWidget(self._focus_far_btn)

        self._focus_value_label = QLabel("--- mm")
        self._focus_value_label.setStyleSheet(
            "color: #1A1A1A; font-size: 13px; font-weight: bold;"
            "font-family: 'Consolas', 'Courier New', monospace;"
        )
        layout.addWidget(self._focus_value_label)

    # ── selection ──────────────────────────────────────────

    def show_selection(
        self,
        serial: str,
        focus_distance: float | None = None,
    ) -> None:
        self._selected_label.setText(f"Selected: {serial}")
        self._nuc_button.setEnabled(True)
        self._focus_near_btn.setEnabled(True)
        self._focus_far_btn.setEnabled(True)
        if focus_distance is not None:
            self._focus_value_label.setText(f"{focus_distance:.0f} mm")
        else:
            self._focus_value_label.setText("--- mm")

    def update_focus_distance(self, distance_mm: float) -> None:
        self._focus_value_label.setText(f"{distance_mm:.0f} mm")

    def clear_selection(self) -> None:
        self._selected_label.setText("No camera selected")
        self._nuc_button.setEnabled(False)
        self._focus_near_btn.setEnabled(False)
        self._focus_far_btn.setEnabled(False)
        self._focus_value_label.setText("--- mm")

    def set_nuc_busy(self, busy: bool) -> None:
        self._nuc_button.setEnabled(not busy)
        self._nuc_button.setText(
            "NUC..." if busy else "Execute NUC"
        )

    def set_focus_busy(self, busy: bool) -> None:
        self._focus_near_btn.setEnabled(not busy)
        self._focus_far_btn.setEnabled(not busy)

    # ── slots ──────────────────────────────────────────────

    def _on_nuc(self) -> None:
        self.nuc_clicked.emit()

    def _on_focus_near(self) -> None:
        self.focus_near_clicked.emit()

    def _on_focus_far(self) -> None:
        self.focus_far_clicked.emit()


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
            seen = int(stats.get("[Stream]GevStreamSeenPacketCount", 0))
            # On TV46L, "Lost" may include expected UDP drops.
            # Use ratio relative to total seen packets for context.
            loss_ratio = lost / max(seen, 1)
            resend_ratio = resend / max(seen, 1)
            if loss_ratio > 0.01 or resend_ratio > 0.01:
                return "FAIL"
            if loss_ratio > 0.001 or resend_ratio > 0.001:
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
                seen = int(stats.get("[Stream]GevStreamSeenPacketCount", -1))
                lost = int(stats.get("[Stream]GevStreamLostPacketCount", -1))
                resend = int(stats.get("[Stream]GevStreamResendPacketCount", -1))
                dup = int(stats.get("[Stream]GevStreamDuplicatePacketCount", -1))
                summaries["transport"] = (
                    f"Seen: {seen}, Lost: {lost}, "
                    f"Resend: {resend}, Dup: {dup}"
                )
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

        # ── Per-stage latency breakdown ──
        stage_keys = ["acquire", "numpy", "publish", "gui_delay",
                      "display", "colormap", "qimage", "pixmap"]
        has_stage_data = any(self._per_stage.get(k) for k in stage_keys)
        if has_stage_data:
            lines.append("  --- Per-Stage Latency (ms) ---")
            lines.append(f"  {'Stage':14s} {'Count':>6s} {'Avg':>8s} "
                         f"{'95th':>8s} {'Min':>8s} {'Max':>8s}")
            for k in stage_keys:
                vals = self._per_stage.get(k, [])
                if vals:
                    avg = self._mean(vals)
                    p95 = self._percentile(vals, 95)
                    mn = min(vals)
                    mx = max(vals)
                    lines.append(
                        f"  {k:14s} {len(vals):>6d} {avg:>8.2f} "
                        f"{p95:>8.2f} {mn:>8.2f} {mx:>8.2f}"
                    )
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


# ==========================================================
# PerCameraData
# ==========================================================


@dataclass
class PerCameraData:
    """Runtime data for one camera in the multi-camera viewer."""

    camera: TV46LCamera
    calibration: CalibrationManager
    timing: TimingMonitor
    frame_history: FrameHistory
    graph_manager: GraphManager
    session: QualificationSession
    monitor: QualificationMonitor

    last_sequence: int = -1
    skipped_frames: int = 0
    acquisition_drops: int = 0
    gui_drops: int = 0
    rendering_drops: int = 0
    update_requests: int = 0
    paint_event_count: int = 0
    gui_frame_count: int = 0
    gui_fps: int = 0
    gui_fps_timer: float = field(default_factory=time.time)
    last_timeout_count: int = 0
    last_error: str | None = None


# ==========================================================
# Light Theme
# ==========================================================

LIGHT_THEME = """
QMainWindow { background-color: #FFFFFF; }
QWidget {
    background-color: #FFFFFF;
    color: #1A1A1A;
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 11px;
}
QPushButton {
    background-color: #F0F0F0; color: #333333;
    border: 1px solid #CCCCCC; border-radius: 3px;
    padding: 5px 14px; font-size: 11px;
}
QPushButton:hover { background-color: #E0E0E0; border: 1px solid #999999; }
QPushButton:pressed { background-color: #D0D0D0; }
QPushButton:disabled {
    background-color: #F5F5F5; color: #AAAAAA;
    border: 1px solid #DDDDDD;
}
QTabWidget::pane {
    background-color: #FAFAFA; border: 1px solid #D0D0D0;
}
QTabBar::tab {
    background-color: #F0F0F0; color: #555555;
    border: 1px solid #D0D0D0; padding: 4px 12px;
}
QTabBar::tab:selected {
    background-color: #FAFAFA; color: #1A1A1A;
    border-bottom: 2px solid #1A73E8;
}
QTableWidget {
    background-color: #FAFAFA; border: 1px solid #D0D0D0;
    gridline-color: #E0E0E0;
}
QHeaderView::section {
    background-color: #F0F0F0; color: #333333;
    border: 1px solid #D0D0D0; padding: 2px 6px;
}
QListWidget {
    background-color: #FAFAFA; border: 1px solid #D0D0D0;
    color: #333333;
}
QCheckBox { color: #333333; }
QGroupBox { color: #333333; }
QSplitter::handle { background-color: #D0D0D0; }
QStatusBar {
    background-color: #F5F5F5; border-top: 1px solid #D0D0D0;
    color: #555555; font-size: 10px;
}
"""


# ==========================================================
# MainWindow
# ==========================================================


class MainWindow(QMainWindow):
    """
    Multi-camera qualification tool main window.

    Layout:
      Top: Toolbar
      Middle: Tile grid (responsive) + Detail panels (selected cam)
      Bottom: CameraControlPanel (NUC, Focus)
      Status Bar
    """

    def __init__(self) -> None:
        super().__init__()

        self._camera_data: dict[str, PerCameraData] = {}
        self._tiles: dict[str, CameraTileWidget] = {}
        self._cam_order: list[str] = []
        self._selected_serial: str | None = None
        self._process = psutil.Process()

        self._nuc_busy: bool = False
        self._focus_busy: bool = False
        self._stress_test_enabled: bool = False

        self._graph_widgets: list[GraphWidget] = []
        self._event_logger = EventLogger()

        self._init_ui()
        self._init_cameras()
        self._init_timers()

    # ==========================================================
    # UI Setup
    # ==========================================================

    def _init_ui(self) -> None:
        self.setWindowTitle("TV46L Camera Viewer — Multi-Camera Qualification")
        self.setMinimumSize(1280, 860)
        self.setStyleSheet(LIGHT_THEME)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ── Toolbar ──────────────────────────────────────────

        toolbar = QFrame()
        toolbar.setStyleSheet(
            "background-color: #F5F5F5; border: 1px solid #D0D0D0;"
            "border-radius: 3px;"
        )
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 4, 8, 4)
        tb.setSpacing(6)

        title = QLabel("Multi-Camera Qualification Tool")
        title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #1A1A1A;"
        )
        tb.addWidget(title)
        tb.addSpacing(12)

        self._stress_checkbox = QCheckBox("Stress Test")
        self._stress_checkbox.toggled.connect(self._on_stress_toggled)
        tb.addWidget(self._stress_checkbox)
        tb.addStretch()

        self._qual_button = QPushButton("Qualification Report")
        self._qual_button.clicked.connect(self._show_qualification_report)
        tb.addWidget(self._qual_button)

        root.addWidget(toolbar)

        # ── Splitter: Tile Grid + Detail Panels ──────────────

        hsplitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Tile grid
        tile_container = QWidget()
        self._tile_grid = QGridLayout(tile_container)
        self._tile_grid.setContentsMargins(0, 0, 0, 0)
        self._tile_grid.setSpacing(4)
        self._empty_label = QLabel("No cameras detected.\n\nConnect cameras and restart.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #999999; font-size: 14px;")
        self._tile_grid.addWidget(self._empty_label, 0, 0)
        hsplitter.addWidget(tile_container)

        # Right: Detail panels for selected camera
        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)

        self._tab_widget = QTabWidget()
        self._acquisition_panel = AcquisitionPanel()
        self._processing_panel = ProcessingPanel()
        self._system_panel = SystemPanel()
        self._health_panel = HealthPanel()
        self._tab_widget.addTab(self._acquisition_panel, "Acquisition")
        self._tab_widget.addTab(self._processing_panel, "Processing")
        self._tab_widget.addTab(self._system_panel, "System")
        self._tab_widget.addTab(self._health_panel, "Health")
        detail_layout.addWidget(self._tab_widget)

        self._timing_table = TimingTable()
        self._timing_table.setMaximumHeight(180)
        detail_layout.addWidget(self._timing_table)

        # Graphs + Event log
        gsplitter = QSplitter(Qt.Orientation.Horizontal)
        graph_container = QWidget()
        graph_layout = QGridLayout(graph_container)
        graph_layout.setSpacing(1)
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
            gw.set_series(
                key, [],
                GraphWidget.COLORS.get(key, QColor(255, 255, 255)),
            )
            graph_layout.addWidget(gw, idx // 3, idx % 3)
            self._graph_widgets.append(gw)
        gsplitter.addWidget(graph_container)

        self._event_list = QListWidget()
        self._event_list.setFont(QFont("monospace", 9))
        self._event_list.setMinimumWidth(180)
        self._event_logger.attach(self._event_list)
        gsplitter.addWidget(self._event_list)
        detail_layout.addWidget(gsplitter, stretch=1)

        hsplitter.addWidget(detail_panel)
        hsplitter.setStretchFactor(0, 2)
        hsplitter.setStretchFactor(1, 3)
        root.addWidget(hsplitter, stretch=1)

        # ── Camera Control Panel ─────────────────────────────

        self._control_panel = CameraControlPanel()
        self._control_panel.nuc_clicked.connect(self._on_nuc_clicked)
        self._control_panel.focus_near_clicked.connect(self._on_focus_near)
        self._control_panel.focus_far_clicked.connect(self._on_focus_far)
        root.addWidget(self._control_panel)

        # ── Status Bar ───────────────────────────────────────

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label)
        self._cam_count_label = QLabel("Cameras: 0")
        self._status_bar.addPermanentWidget(self._cam_count_label)
        self._sel_label = QLabel("")
        self._status_bar.addPermanentWidget(self._sel_label)

    # ==========================================================
    # Camera Initialization (multi-camera)
    # ==========================================================

    def _init_cameras(self) -> None:
        try:
            cal = CalibrationManager()
            cal.initialize()
            print("[INFO] Calibration loaded.")
        except Exception as exc:
            print(f"[WARN] Calibration init failed: {exc}")
            cal = CalibrationManager()
            cal._initialized = False

        try:
            print("[INFO] Discovering cameras...")
            infos = _discover_cameras()
        except Exception as exc:
            print(f"[ERROR] Discovery failed: {exc}")
            infos = []

        if not infos:
            print("[WARN] No GigE Vision cameras found.")
            self._status_label.setText("No cameras found")
            return

        for info in infos:
            self._add_camera(info, cal)

        self._rebuild_grid()
        self._cam_count_label.setText(
            f"Cameras: {len(self._camera_data)}"
        )
        print(
            f"[INFO] {len(self._camera_data)} camera(s) initialized."
        )

    def _add_camera(
        self,
        info: CameraInfo,
        cal: CalibrationManager,
    ) -> None:
        serial = info.serial
        if serial in self._camera_data:
            return

        try:
            camera = TV46LCamera(info, settings)
            camera.connect()
            camera.start()

            if not camera.wait_for_first_frame(10):
                print(f"[WARN] {serial}: No frames received")
                camera.disconnect()
                return

            data = PerCameraData(
                camera=camera,
                calibration=cal,
                timing=TimingMonitor(),
                frame_history=FrameHistory(),
                graph_manager=GraphManager(),
                session=QualificationSession(),
                monitor=QualificationMonitor(),
            )
            self._camera_data[serial] = data
            self._cam_order.append(serial)

            tile = CameraTileWidget(serial, f"SN:{serial}")
            tile.selected.connect(self._on_tile_selected)
            self._tiles[serial] = tile

            self._event_logger.log(f"{serial}: Camera connected")
            print(f"[INFO] {serial}: Camera ready.")

        except Exception as exc:
            msg = f"{serial}: Init failed: {exc}"
            print(f"[ERROR] {msg}")
            self._event_logger.log(msg)
            tile = CameraTileWidget(serial, f"SN:{serial}")
            tile.show_error(msg)
            tile.selected.connect(self._on_tile_selected)
            self._tiles[serial] = tile

    # ==========================================================
    # Grid Layout
    # ==========================================================

    def _rebuild_grid(self) -> None:
        while self._tile_grid.count():
            item = self._tile_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        count = len(self._tiles)
        if count == 0:
            self._empty_label = QLabel(
                "No cameras detected."
            )
            self._empty_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            self._empty_label.setStyleSheet(
                "color: #999999; font-size: 14px;"
            )
            self._tile_grid.addWidget(self._empty_label, 0, 0)
            return

        cols = 1 if count == 1 else (2 if count <= 4 else (3 if count <= 6 else (4 if count <= 8 else 5)))
        for i, serial in enumerate(self._cam_order):
            tile = self._tiles.get(serial)
            if tile is None:
                continue
            self._tile_grid.addWidget(tile, i // cols, i % cols)

    # ==========================================================
    # Camera Selection
    # ==========================================================

    def _on_tile_selected(self, serial: str) -> None:
        self._select_camera(serial)

    def _select_camera(self, serial: str | None) -> None:
        if serial == self._selected_serial:
            return

        for s, tile in self._tiles.items():
            tile.set_selected(s == serial)

        self._selected_serial = serial

        if serial is not None and serial in self._camera_data:
            data = self._camera_data[serial]
            fd = data.camera.get_focus_distance_or_none()
            self._control_panel.show_selection(serial, fd)
            if fd is None:
                self._control_panel._focus_near_btn.setEnabled(False)
                self._control_panel._focus_far_btn.setEnabled(False)
                self._control_panel._focus_value_label.setText("N/A mm")
            self._sel_label.setText(f"Selected: {serial}")
            self._status_label.setText(f"Selected: {serial}")
        else:
            self._control_panel.clear_selection()
            self._sel_label.setText("")
            self._status_label.setText("No camera selected")

    # ==========================================================
    # Timers
    # ==========================================================

    def _init_timers(self) -> None:
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._poll_all_frames)
        self._frame_timer.start(_FRAME_TIMER_MS)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._update_diagnostics)
        self._diag_timer.start(_DIAG_TIMER_MS)

        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._update_graphs)
        self._graph_timer.start(_GRAPH_TIMER_MS)

    # ==========================================================
    # Frame Poll (30 ms) — all cameras
    # ==========================================================

    def _poll_all_frames(self) -> None:
        for serial, data in list(self._camera_data.items()):
            self._poll_one_camera(serial, data)

    def _poll_one_camera(
        self,
        serial: str,
        data: PerCameraData,
    ) -> None:
        camera = data.camera
        tile = self._tiles.get(serial)
        if tile is None:
            return

        frame = camera.get_latest_frame_reference()
        if frame is None:
            data.acquisition_drops += 1
            return

        if frame.sequence == data.last_sequence:
            data.rendering_drops += 1
            return

        if (
            data.last_sequence >= 0
            and frame.sequence != data.last_sequence + 1
        ):
            gap = frame.sequence - data.last_sequence - 1
            data.skipped_frames += gap
            data.acquisition_drops += gap
            self._event_logger.log(
                f"{serial}: Camera gap — skipped {gap} frame(s)"
            )
        else:
            gap = 0

        data.last_sequence = frame.sequence
        data.gui_frame_count += 1
        data.session.record_frame(gap)
        gui_poll_time = time.perf_counter()

        gst = frame.grab_start_time
        gct = frame.grab_complete_time
        nct = frame.numpy_complete_time
        pt = frame.publish_time

        # ── Stage timing: display → colormap → QImage → QPixmap ──
        t0 = time.perf_counter()
        try:
            display_image = data.calibration.raw_to_display(frame.image)
        except Exception:
            return
        t1 = time.perf_counter()
        try:
            color_image = data.calibration.apply_colormap(display_image)
        except Exception:
            return
        t2 = time.perf_counter()

        rgb_image = cv2.cvtColor(color_image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        t3 = time.perf_counter()
        qimage = QImage(
            rgb_image.data.tobytes(),
            w, h, ch * w,
            QImage.Format.Format_RGB888,
        )
        t4 = time.perf_counter()
        pixmap = QPixmap.fromImage(qimage)
        t5 = time.perf_counter()

        display_ms = (t1 - t0) * 1000
        colormap_ms = (t2 - t1) * 1000
        qimage_ms = (t4 - t3) * 1000
        pixmap_ms = (t5 - t4) * 1000
        total_ms = (t5 - gst) * 1000

        overlay_latency = (gui_poll_time - gst) * 1000
        tile.set_image(
            pixmap,
            frame.frame_number,
            camera.get_fps(),
            overlay_latency,
            camera.timeout_count,
            "PASS" if camera.stream_healthy() else "WARNING",
        )

        now = time.time()
        if now - data.gui_fps_timer >= 1.0:
            data.gui_fps = data.gui_frame_count
            data.session.record_fps(float(data.gui_fps))
            data.gui_frame_count = 0
            data.gui_fps_timer = now

        acquire_ms = (gct - gst) * 1000
        numpy_ms = (nct - gct) * 1000
        publish_ms = (pt - nct) * 1000
        gui_delay_ms = (gui_poll_time - pt) * 1000
        display_colormap_ms = display_ms + colormap_ms
        qimage_pixmap_ms = qimage_ms + pixmap_ms

        ld = {
            "acquire": acquire_ms,
            "numpy": numpy_ms,
            "publish": publish_ms,
            "gui_delay": gui_delay_ms,
            "display": display_ms,
            "colormap": colormap_ms,
            "qimage": qimage_ms,
            "pixmap": pixmap_ms,
            "total": total_ms,
        }
        data.timing.update_all(ld)
        for stage, val in ld.items():
            data.session.record_per_stage(stage, val)

        data.graph_manager.add_point("acquire", acquire_ms)
        data.graph_manager.add_point("gui_delay", gui_delay_ms)
        data.graph_manager.add_point("display_colormap", display_colormap_ms)
        data.graph_manager.add_point("qimage_pixmap", qimage_pixmap_ms)
        data.graph_manager.add_point("total", total_ms)
        data.graph_manager.add_point(
            "fps", float(camera.get_fps())
        )

        record = FrameRecord(
            sequence=frame.sequence,
            frame_number=frame.frame_number,
            grab_start=gst,
            grab_complete=gct,
            numpy_complete=nct,
            publish_time=pt,
            gui_poll_time=gui_poll_time,
        )
        data.frame_history.append(record)

        if frame.frame_number % 5 == 0:
            tc = camera.timeout_count
            if tc > data.last_timeout_count:
                for _ in range(tc - data.last_timeout_count):
                    data.session.record_timeout()
                data.last_timeout_count = tc

    # ==========================================================
    # Diagnostics Update (1000 ms) — selected camera
    # ==========================================================

    def _update_diagnostics(self) -> None:
        if (
            self._selected_serial is None
            or self._selected_serial not in self._camera_data
        ):
            return

        data = self._camera_data[self._selected_serial]
        camera = data.camera
        tile = self._tiles.get(self._selected_serial)

        cpu = self._process.cpu_percent()
        memory = self._process.memory_info().rss / 1024 / 1024
        data.session.record_cpu(cpu)
        data.session.record_memory(memory)
        data.graph_manager.add_point("cpu", cpu)
        data.graph_manager.add_point("update_rate", float(data.gui_fps))

        # Drain paint events from the selected tile
        if tile is not None:
            paint_events = tile.drain_paint_events()
            for paint_ms in paint_events:
                data.timing.paint.update(paint_ms)
                data.graph_manager.add_point("paint", paint_ms)
                data.session.record_paint(paint_ms)
            data.paint_event_count += len(paint_events)

        self._acquisition_panel.refresh(
            camera,
            camera.get_stream_statistics() if camera.connected else None,
        )
        self._processing_panel.refresh(
            data.timing,
            data.calibration.is_initialized,
            0,
        )
        self._system_panel.refresh(
            cpu, memory, data.gui_fps,
            data.update_requests, data.paint_event_count,
            (self.width(), self.height()),
            (0, 0),
        )

        statuses = {
            "camera": HealthEvaluator.evaluate_camera(camera),
            "acquisition": HealthEvaluator.evaluate_acquisition(camera),
            "calibration": HealthEvaluator.evaluate_calibration(
                data.calibration.is_initialized
            ),
            "rendering": HealthEvaluator.evaluate_rendering(
                data.timing.paint.latest, data.timing.paint.count
            ),
            "memory": HealthEvaluator.evaluate_memory(memory),
            "timing": HealthEvaluator.evaluate_timing(
                data.timing.total.latest, data.timing.total.count
            ),
        }
        self._health_panel.refresh_panel(statuses)
        self._timing_table.refresh_table(data.timing.get_stats())

        data.monitor.poll(
            camera,
            data.calibration.is_initialized,
            self._event_logger,
        )
        data.session.record_camera_state(
            camera.connected, camera.running
        )

        # Update selected tile status
        if tile is not None:
            overall = HealthEvaluator.overall(statuses)
            tile._stat_labels["status"].setText(f"S:{overall[:4]}")

        # Update selected cam focus — handle sentinel
        fd = camera.get_focus_distance_or_none()
        if fd is not None:
            self._control_panel.update_focus_distance(fd)
            self._control_panel._focus_near_btn.setEnabled(True)
            self._control_panel._focus_far_btn.setEnabled(True)
        else:
            self._control_panel._focus_value_label.setText("N/A mm")
            self._control_panel._focus_near_btn.setEnabled(False)
            self._control_panel._focus_far_btn.setEnabled(False)

    # ==========================================================
    # Graph Update (200 ms) — selected camera
    # ==========================================================

    def _update_graphs(self) -> None:
        if (
            self._selected_serial is None
            or self._selected_serial not in self._camera_data
        ):
            return

        data = self._camera_data[self._selected_serial]
        all_series = data.graph_manager.get_all_series()

        for gw in self._graph_widgets:
            title = gw._title
            key_map = {
                "Total Latency": "total",
                "Acquire Time": "acquire",
                "Display+Colormap": "display_colormap",
                "QImage+Pixmap": "qimage_pixmap",
                "GUI Delay": "gui_delay",
                "Paint Time": "paint",
                "FPS": "fps",
                "CPU %": "cpu",
                "Update Rate": "update_rate",
            }
            key = key_map.get(title)
            if key is None:
                continue
            sdata = all_series.get(key, [])
            gw.set_series(key, sdata, GraphWidget.COLORS.get(key))
            if sdata:
                gw.set_range(0, max(sdata) * 1.2 + 1)

    # ==========================================================
    # NUC Control
    # ==========================================================

    def _on_nuc_clicked(self) -> None:
        if self._nuc_busy:
            return
        if (
            self._selected_serial is None
            or self._selected_serial not in self._camera_data
        ):
            return

        data = self._camera_data[self._selected_serial]
        self._nuc_busy = True
        self._control_panel.set_nuc_busy(True)
        self._status_label.setText(
            f"NUC in progress on {self._selected_serial}..."
        )
        QApplication.processEvents()

        try:
            data.camera.manual_nuc()
            self._event_logger.log(
                f"{self._selected_serial}: NUC executed"
            )
            self._status_label.setText(
                f"NUC completed on {self._selected_serial}."
            )
        except Exception as exc:
            self._event_logger.log(
                f"{self._selected_serial}: NUC failed: {exc}"
            )
            self._status_label.setText(f"NUC failed: {exc}")
        finally:
            self._nuc_busy = False
            self._control_panel.set_nuc_busy(False)

    # ==========================================================
    # Focus Control
    # ==========================================================

    FOCUS_STEP_MM = 250

    def _on_focus_near(self) -> None:
        self._execute_focus(-self.FOCUS_STEP_MM)

    def _on_focus_far(self) -> None:
        self._execute_focus(self.FOCUS_STEP_MM)

    def _execute_focus(self, step_mm: int) -> None:
        if self._focus_busy:
            return
        if (
            self._selected_serial is None
            or self._selected_serial not in self._camera_data
        ):
            return

        data = self._camera_data[self._selected_serial]
        camera = data.camera

        self._focus_busy = True
        self._control_panel.set_focus_busy(True)
        dir_str = "near" if step_mm < 0 else "far"
        self._status_label.setText(
            f"Focus {dir_str} on {self._selected_serial}..."
        )
        QApplication.processEvents()

        try:
            current = camera.get_focus_distance()
            limits = camera.get_focus_limits()
            target = max(limits[0], min(current + step_mm, limits[1]))

            camera.set_focus_distance(target)
            camera.wait_for_focus(target)

            actual = camera.get_focus_distance()
            self._control_panel.update_focus_distance(actual)
            self._event_logger.log(
                f"{self._selected_serial}: Focus {dir_str} "
                f"{current:.0f}->{actual:.0f}mm"
            )
            self._status_label.setText(
                f"Focus {dir_str}: {actual:.0f} mm"
            )
        except Exception as exc:
            self._event_logger.log(
                f"{self._selected_serial}: Focus {dir_str} failed: {exc}"
            )
            self._status_label.setText(
                f"Focus {dir_str} failed: {exc}"
            )
        finally:
            self._focus_busy = False
            self._control_panel.set_focus_busy(False)

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
        if self._selected_serial is None:
            QMessageBox.information(
                self, "No Camera",
                "Select a camera first to view its qualification report."
            )
            return

        data = self._camera_data.get(self._selected_serial)
        if data is None:
            return

        data.session.stop()
        report = data.session.generate_report(
            data.camera, data.calibration.is_initialized
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Qualification Report — {self._selected_serial}"
        )
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
    # Shutdown
    # ==========================================================

    def closeEvent(self, event) -> None:  # noqa: N802
        self._frame_timer.stop()
        self._diag_timer.stop()
        self._graph_timer.stop()
        for serial, data in self._camera_data.items():
            try:
                data.camera.stop()
                data.camera.disconnect()
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
