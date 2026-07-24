"""
analyzer_ui.py -- Phase 2 Multi-Camera Acquisition Pipeline Analyzer UI

Multi-camera dashboard showing up to 8 thermal cameras with per-tile
thermal previews, global bottleneck detection, and per-camera detail tabs.

Usage:
    python -m tests.pipeline_analyzer
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import cv2
import numpy as np

from calibration.calibration_manager import CalibrationManager
from camera.camera_info import CameraInfo
from camera.tv46l_camera import TV46LCamera
from configuration import settings

from tests.pipeline_analyzer.analyzer_core import (
    PipelineAnalyzer,
    AnalyzerSnapshot,
    FreezeType,
    PipelineStage,
    SequenceSnapshot,
    NetworkStats,
    FrameLifecycle,
    CameraPauseEvent,
    MulticameraAnalyzerManager,
    CrossCameraSnapshot,
)

# ==========================================================
# Constants
# ==========================================================

COLORMAP = cv2.COLORMAP_INFERNO
POLL_INTERVAL_MS = 30
DIAG_INTERVAL_MS = 200
NETWORK_INTERVAL_MS = 5000
MAX_STAGE_ROWS = 20
TILE_MIN_WIDTH = 240
TILE_MIN_HEIGHT = 260

MONO_FONT = "Consolas, 'Courier New', monospace"

STYLE_DARK = """
QMainWindow { background-color: #1a1a2e; }
QWidget { background-color: #1a1a2e; color: #e0e0e0; font-size: 11px; }
QGroupBox {
    border: 1px solid #3a3a5e;
    border-radius: 4px;
    margin-top: 12px;
    font-weight: bold;
    color: #88ccff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #2a2a4e;
    color: #e0e0e0;
    border: 1px solid #4a4a6e;
    border-radius: 3px;
    padding: 5px 14px;
}
QPushButton:hover { background-color: #3a3a5e; border: 1px solid #6a6a8e; }
QPushButton:pressed { background-color: #4a4a6e; }
QPushButton:disabled { background-color: #1e1e3e; color: #666688; }
QPushButton#dangerBtn {
    background-color: #6e2020; color: #ff8888;
    border: 1px solid #aa4040;
}
QPushButton#dangerBtn:hover { background-color: #8e3030; }
QPushButton#focusBtn {
    background-color: #2a3a5e; color: #88ccff;
    border: 1px solid #4a6a8e;
}
QPushButton#focusBtn:hover { background-color: #3a4a6e; }
QTableWidget {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #3a3a5e;
    gridline-color: #2a2a4e;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 10px;
}
QTableWidget::item { padding: 2px 6px; }
QHeaderView::section {
    background-color: #0f3460;
    color: #88ccff;
    border: 1px solid #2a2a4e;
    padding: 3px;
    font-weight: bold;
}
QStatusBar { background-color: #0f3460; color: #aaccee; }
QLabel#bigFps { font-size: 28px; font-weight: bold; color: #00ff88; }
QLabel#fpsLabel { font-size: 11px; color: #88aacc; }
QLabel#warningLabel { color: #ff8844; font-weight: bold; }
QLabel#errorLabel { color: #ff4444; font-weight: bold; }
QLabel#okLabel { color: #44ff88; }
QLabel#valueLabel { color: #88ccff; font-family: Consolas, 'Courier New', monospace; font-size: 10px; }
QLabel#tileSerial { font-size: 11px; font-weight: bold; color: #aaccee; }
QLabel#tileFps { font-size: 10px; color: #88ccff; font-family: Consolas, 'Courier New', monospace; }
QLabel#tileFreezeDot { font-size: 16px; }
QLabel#tileLatency { font-size: 11px; color: #ffaa44; font-family: Consolas, 'Courier New', monospace; }
QLabel#tileLoss { font-size: 10px; color: #ff8844; }
QFrame#cameraTile {
    border: 2px solid #3a3a5e;
    border-radius: 6px;
    background-color: #16213e;
    padding: 4px;
}
QFrame#cameraTileSelected {
    border: 2px solid #88ccff;
    border-radius: 6px;
    background-color: #1a2a4e;
    padding: 4px;
}
QLabel#summaryValue { font-size: 13px; font-weight: bold; color: #88ccff; font-family: Consolas, 'Courier New', monospace; }
QLabel#summaryLabel { font-size: 10px; color: #88aacc; }
QLabel#bottleneckLabel { font-size: 14px; font-weight: bold; }
"""


# ==========================================================
# Helpers
# ==========================================================

def format_ms(ms: float) -> str:
    if ms < 0.001:
        return f"{ms*1000:.1f}us"
    if ms < 1.0:
        return f"{ms:.2f}ms"
    if ms < 1000:
        return f"{ms:.1f}ms"
    return f"{ms/1000:.2f}s"


def _shorten_serial(serial: str, max_len: int = 16) -> str:
    if len(serial) <= max_len:
        return serial
    return serial[:max_len - 3] + "..."


def _cols_for_count(n: int) -> int:
    if n <= 1:
        return 1
    if n <= 4:
        return 2
    if n <= 6:
        return 3
    return 4


def _discover_cameras() -> list[CameraInfo]:
    import halcon as ha
    import traceback
    cameras: list[CameraInfo] = []
    try:
        print("[INFO] Querying HALCON for GigE Vision devices...")
        devices = ha.info_framegrabber("GigEVision2", "device")
        print(f"[INFO] HALCON returned: {devices}")
        device_list: list[str] = []
        if isinstance(devices, tuple) and len(devices) >= 2:
            raw = devices[1]
            if isinstance(raw, (list, tuple)):
                for entry in raw:
                    s = str(entry)
                    idx = s.find("device:")
                    if idx >= 0:
                        start = idx + 7
                        end = s.find(" |", start)
                        if end < 0:
                            end = len(s)
                        dev = s[start:end].strip()
                        if dev:
                            device_list.append(dev)
                            print(f"[INFO] Found device: {dev}")
        for device in device_list:
            ip = device.split(":")[0] if ":" in device else device
            serial = device
            cameras.append(CameraInfo(
                device=device,
                serial=serial,
                model="",
                vendor="",
                ip=ip,
            ))
        print(f"[INFO] Total cameras discovered: {len(cameras)}")
    except Exception:
        print("[ERROR] Camera discovery failed:")
        traceback.print_exc()
    return cameras


# ==========================================================
# TileImageWidget -- thermal preview with paint instrumentation
# ==========================================================

class TileImageWidget(QWidget):
    def __init__(self, analyzer: PipelineAnalyzer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._analyzer = analyzer
        self._pixmap: QPixmap | None = None
        self._frame_number: int = 0
        self._latency_ms: float = 0.0
        self._error: str | None = None
        self._last_rgb: np.ndarray | None = None
        self._qimage_ms: float = 0.0
        self._pixmap_ms: float = 0.0
        self.setMinimumSize(160, 120)
        self.setStyleSheet("background-color: #000000; border: none;")

    def set_image(self, rgb: np.ndarray | None, frame_number: int, latency_ms: float) -> None:
        self._last_rgb = rgb
        self._frame_number = frame_number
        self._latency_ms = latency_ms
        self._error = None
        self._rebuild_pixmap()

    def show_error(self, msg: str) -> None:
        self._pixmap = None
        self._error = msg
        self.update()

    def _rebuild_pixmap(self) -> None:
        if self._last_rgb is None:
            return
        t0 = time.perf_counter()
        h, w, ch = self._last_rgb.shape
        bytes_per_line = ch * w
        qimage = QImage(
            self._last_rgb.data.tobytes(),
            w, h, bytes_per_line,
            QImage.Format.Format_RGB888,
        )
        t1 = time.perf_counter()
        self._qimage_ms = (t1 - t0) * 1000
        self._pixmap = QPixmap.fromImage(qimage)
        t2 = time.perf_counter()
        self._pixmap_ms = (t2 - t1) * 1000
        self.update()

    def paintEvent(self, a0) -> None:
        paint_start = self._analyzer.observe_paint_start()
        painter = QPainter(self)
        try:
            if self._error is not None:
                painter.setPen(Qt.GlobalColor.red)
                font = QFont("monospace", 10)
                painter.setFont(font)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._error)
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
                font = QFont("monospace", 9)
                painter.setFont(font)
                painter.drawText(6, 14, f"#{self._frame_number}")
                lat_text = f"{self._latency_ms:.0f}ms"
                fm = QFontMetrics(font)
                lw = fm.horizontalAdvance(lat_text)
                painter.drawText(self.width() - lw - 6, 14, lat_text)
            else:
                painter.setPen(Qt.GlobalColor.white)
                font = QFont("monospace", 11)
                painter.setFont(font)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting...")
        finally:
            painter.end()
        self._analyzer.observe_paint_complete(
            paint_start, self._frame_number,
            self._qimage_ms, self._pixmap_ms,
        )


# ==========================================================
# CameraTile -- clickable tile with image + compact stats
# ==========================================================

class CameraTile(QFrame):
    selected = pyqtSignal(str)
    nuc_requested = pyqtSignal(str)
    focus_near_requested = pyqtSignal(str)
    focus_far_requested = pyqtSignal(str)

    def __init__(self, camera_id: str, analyzer: PipelineAnalyzer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._camera_id = camera_id
        self._analyzer = analyzer
        self._is_selected = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("cameraTile")
        self.setMinimumSize(TILE_MIN_WIDTH, TILE_MIN_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        # Header: serial + status
        header = QHBoxLayout()
        serial_label = QLabel(_shorten_serial(self._camera_id))
        serial_label.setObjectName("tileSerial")
        header.addWidget(serial_label)
        header.addStretch()
        self._status_label = QLabel("●")
        self._status_label.setObjectName("tileFreezeDot")
        self._status_label.setStyleSheet("font-size: 16px; color: #44ff88;")
        header.addWidget(self._status_label)
        self._conn_label = QLabel("Connected")
        self._conn_label.setStyleSheet("font-size: 9px; color: #44ff88;")
        header.addWidget(self._conn_label)
        root.addLayout(header)

        # Body: image + stats side by side
        body = QHBoxLayout()
        body.setSpacing(6)

        self._image_widget = TileImageWidget(self._analyzer)
        self._image_widget.setMinimumSize(160, 120)
        body.addWidget(self._image_widget)

        stats = QVBoxLayout()
        stats.setSpacing(1)

        self._cam_fps_label = QLabel("Cam: --")
        self._cam_fps_label.setObjectName("tileFps")
        stats.addWidget(self._cam_fps_label)

        self._pub_fps_label = QLabel("Pub: --")
        self._pub_fps_label.setObjectName("tileFps")
        stats.addWidget(self._pub_fps_label)

        self._disp_fps_label = QLabel("Dsp: --")
        self._disp_fps_label.setObjectName("tileFps")
        stats.addWidget(self._disp_fps_label)

        self._loss_label = QLabel("Loss: --")
        self._loss_label.setObjectName("tileLoss")
        stats.addWidget(self._loss_label)

        self._latency_label = QLabel("Lat: --")
        self._latency_label.setObjectName("tileLatency")
        stats.addWidget(self._latency_label)

        stats.addStretch()
        body.addLayout(stats)
        root.addLayout(body)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)

        self._nuc_btn = QPushButton("NUC")
        self._nuc_btn.setObjectName("dangerBtn")
        self._nuc_btn.setFixedHeight(22)
        self._nuc_btn.clicked.connect(lambda: self.nuc_requested.emit(self._camera_id))
        btn_row.addWidget(self._nuc_btn)

        focus_avail = self._analyzer.camera.focus_available()
        self._focus_near_btn = QPushButton("<<")
        self._focus_near_btn.setObjectName("focusBtn")
        self._focus_near_btn.setFixedHeight(22)
        self._focus_near_btn.setFixedWidth(28)
        self._focus_near_btn.clicked.connect(lambda: self.focus_near_requested.emit(self._camera_id))
        self._focus_near_btn.setVisible(focus_avail)
        btn_row.addWidget(self._focus_near_btn)

        self._focus_far_btn = QPushButton(">>")
        self._focus_far_btn.setObjectName("focusBtn")
        self._focus_far_btn.setFixedHeight(22)
        self._focus_far_btn.setFixedWidth(28)
        self._focus_far_btn.clicked.connect(lambda: self.focus_far_requested.emit(self._camera_id))
        self._focus_far_btn.setVisible(focus_avail)
        btn_row.addWidget(self._focus_far_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

    # --- Public API ---

    @property
    def camera_id(self) -> str:
        return self._camera_id

    @property
    def analyzer(self) -> PipelineAnalyzer:
        return self._analyzer

    @property
    def image_widget(self) -> TileImageWidget:
        return self._image_widget

    def set_image(self, rgb: np.ndarray | None, frame_number: int, latency_ms: float) -> None:
        if rgb is not None:
            self._image_widget.set_image(rgb, frame_number, latency_ms)

    def update_stats(self, snap: AnalyzerSnapshot) -> None:
        self._set_fps_label(self._cam_fps_label, "Cam", snap.camera_fps)
        self._set_fps_label(self._pub_fps_label, "Pub", snap.published_fps)
        self._set_fps_label(self._disp_fps_label, "Dsp", snap.display_fps)
        self._loss_label.setText(f"Loss: {snap.sequence_loss_pct:.2f}%")
        total_lat = snap.latency_breakdown.get("Total Latency (ms)", 0.0)
        self._latency_label.setText(f"Lat: {format_ms(total_lat)}")

        # Freeze indicator
        f = snap.freeze
        if f is None or not f.is_frozen:
            self._status_label.setText("●")
            self._status_label.setStyleSheet("font-size: 16px; color: #44ff88;")
        else:
            self._status_label.setText("✖")
            color = "#ff4444" if f.freeze_type == FreezeType.ACQUISITION_FREEZE else "#ff8844"
            self._status_label.setStyleSheet(f"font-size: 16px; color: {color};")

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self.setObjectName("cameraTileSelected" if selected else "cameraTile")
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)

    def show_busy(self, busy: bool) -> None:
        self._nuc_btn.setEnabled(not busy)
        self._nuc_btn.setText("NUC" if not busy else "...")
        self._focus_near_btn.setEnabled(not busy)
        self._focus_far_btn.setEnabled(not busy)

    # --- Internal ---

    def _set_fps_label(self, label: QLabel, prefix: str, value: float) -> None:
        label.setText(f"{prefix}: {value:.1f}")
        if value < 4.0:
            label.setStyleSheet("font-size: 10px; color: #ff4444; font-family: Consolas, 'Courier New', monospace;")
        elif value < 7.0:
            label.setStyleSheet("font-size: 10px; color: #ff8844; font-family: Consolas, 'Courier New', monospace;")
        else:
            label.setStyleSheet("font-size: 10px; color: #00ff88; font-family: Consolas, 'Courier New', monospace;")

    def mousePressEvent(self, a0) -> None:
        self.selected.emit(self._camera_id)
        super().mousePressEvent(a0)


# ==========================================================
# GlobalSummaryPanel
# ==========================================================

class GlobalSummaryPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.setMaximumWidth(280)
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Global Summary")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #88ccff; padding: 2px;")
        layout.addWidget(title)

        entries = [
            ("connected", "Connected"),
            ("avg_cam_fps", "Avg Cam FPS"),
            ("avg_disp_fps", "Avg Disp FPS"),
            ("total_gui", "Total GUI FPS"),
            ("total_loss", "Total Loss"),
            ("max_latency", "Max Latency"),
            ("bottleneck", "Bottleneck"),
            ("sync_drift", "Sync Drift"),
        ]

        for key, name in entries:
            row = QHBoxLayout()
            row.setSpacing(4)
            label = QLabel(name + ":")
            label.setObjectName("summaryLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel("--")
            if key == "bottleneck":
                value.setObjectName("bottleneckLabel")
            else:
                value.setObjectName("summaryValue")
            row.addWidget(value)
            self._labels[key] = value
            layout.addLayout(row)

        layout.addStretch()

    def update_data(self, cross: CrossCameraSnapshot) -> None:
        self._labels["connected"].setText(f"{cross.camera_count}")
        self._labels["avg_cam_fps"].setText(f"{cross.avg_camera_fps:.1f}")
        self._labels["avg_disp_fps"].setText(f"{cross.avg_display_fps:.1f}")
        self._labels["total_gui"].setText(f"{cross.total_gui_fps:.1f}")
        self._labels["total_loss"].setText(f"{cross.total_sequence_loss_pct:.2f}%")
        lat_text = f"{cross.max_latency_ms:.1f}ms"
        if cross.worst_camera_id:
            lat_text += f" ({_shorten_serial(cross.worst_camera_id, 12)})"
        self._labels["max_latency"].setText(lat_text)
        self._labels["sync_drift"].setText(f"{cross.sync_drift_ms:.2f}ms")

        # Bottleneck with color coding
        bn = cross.bottleneck
        self._labels["bottleneck"].setText(bn)
        if "Balanced" in bn or "no bottleneck" in bn.lower():
            color = "#44ff88"
        elif "FREEZE" in bn or "stopped" in bn or ">10%" in bn:
            color = "#ff4444"
        elif "Low" in bn or "lagging" in bn or ">3%" in bn:
            color = "#ff8844"
        else:
            color = "#ffaa44"
        self._labels["bottleneck"].setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")


# ==========================================================
# TimelineView -- per-camera stage timing comparison
# ==========================================================

class TimelineView(QTableWidget):
    STAGE_COLUMNS = [
        "Camera",
        "Acquire (ms)",
        "NumPy (ms)",
        "Publish (ms)",
        "GUI Recv (ms)",
        "Calibrate (ms)",
        "Colormap (ms)",
        "Display (ms)",
        "Paint (ms)",
    ]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setColumnCount(len(self.STAGE_COLUMNS))
        self.setHorizontalHeaderLabels(self.STAGE_COLUMNS)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)
        self.setAlternatingRowColors(True)

    def update_data(self, cross: CrossCameraSnapshot) -> None:
        cids = sorted(cross.camera_snapshots.keys())
        self.setRowCount(len(cids))

        stage_keys = [
            "Camera Acquisition",
            "NumPy Conversion",
            "RawFrame Publication",
            "GUI Receive",
            "Calibration",
            "Display Conversion",
            "Display Conversion",
            "Qt Rendering",
        ]


        for row, cid in enumerate(cids):
            snap = cross.camera_snapshots[cid]
            bd = snap.latency_breakdown
            self.setItem(row, 0, QTableWidgetItem(_shorten_serial(cid, 14)))
            for col, skey in enumerate(stage_keys, start=1):
                val = bd.get(skey, 0.0)
                item = QTableWidgetItem(f"{val:.3f}")
                if val > 50:
                    item.setForeground(QColor("#ff4444"))
                elif val > 20:
                    item.setForeground(QColor("#ff8844"))
                self.setItem(row, col, item)


# ==========================================================
# EventLogWidget
# ==========================================================

class EventLogWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Timestamp", "Camera ID", "Message"])
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)
        self.setAlternatingRowColors(True)

    def update_events(self, events: list[str]) -> None:
        self.setRowCount(len(events))
        for row, entry in enumerate(events):
            parts = entry.split("] ", 2)
            if len(parts) == 3:
                self.setItem(row, 0, QTableWidgetItem(parts[0].lstrip("[")))
                self.setItem(row, 1, QTableWidgetItem(parts[1].lstrip("[")))
                self.setItem(row, 2, QTableWidgetItem(parts[2]))
            else:
                self.setItem(row, 0, QTableWidgetItem(""))
                self.setItem(row, 1, QTableWidgetItem(""))
                self.setItem(row, 2, QTableWidgetItem(entry))


# ==========================================================
# StageTimingWidget
# ==========================================================

class StageTimingWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        headers = ["Stage", "Count", "Avg (ms)", "Min", "Max", "P95", "Latest"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        self.setMinimumHeight(200)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)

    def update_data(self, stage_stats: dict) -> None:
        stages = [
            (PipelineStage.CAMERA_EXPOSURE, "Camera Exposure"),
            (PipelineStage.HALCON_GRAB, "HALCON Grab"),
            (PipelineStage.NUMPY_CONVERSION, "NumPy Conversion"),
            (PipelineStage.DISPLAY_CONVERSION, "Display Conversion"),
            (PipelineStage.COLORMAP, "Colormap"),
            (PipelineStage.QIMAGE, "QImage"),
            (PipelineStage.QPIXMAP, "QPixmap"),
            (PipelineStage.QT_PAINT, "Qt Paint"),
        ]
        visible = [(s, name) for s, name in stages if stage_stats.get(s, {}).get("count", 0) > 0]
        self.setRowCount(len(visible))
        for row, (stage, name) in enumerate(visible):
            s = stage_stats.get(stage, {})
            count = s.get("count", 0)
            self.setItem(row, 0, QTableWidgetItem(name))
            self.setItem(row, 1, QTableWidgetItem(str(count)))
            self.setItem(row, 2, QTableWidgetItem(f"{s.get('avg', 0):.3f}"))
            self.setItem(row, 3, QTableWidgetItem(f"{s.get('min', 0):.3f}"))
            self.setItem(row, 4, QTableWidgetItem(f"{s.get('max', 0):.3f}"))
            self.setItem(row, 5, QTableWidgetItem(f"{s.get('p95', 0):.3f}"))
            self.setItem(row, 6, QTableWidgetItem(f"{s.get('latest', 0):.3f}"))


# ==========================================================
# LatencyBreakdownWidget
# ==========================================================

class LatencyBreakdownWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        headers = ["Stage", "Avg (ms)", "Contribution %"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)
        self.setMinimumHeight(150)

    def update_data(self, breakdown: dict[str, float]) -> None:
        groups = [
            "Camera Acquisition",
            "NumPy Conversion",
            "RawFrame Publication",
            "GUI Receive",
            "Calibration",
            "Display Conversion",
            "Qt Rendering",
        ]
        total = breakdown.get("Total Latency (ms)", 0.0)

        rows = []
        for g in groups:
            ms = breakdown.get(g, 0.0)
            pct = breakdown.get(f"{g} %", 0.0)
            if ms > 0.01:
                rows.append((g, ms, pct))
        rows.sort(key=lambda x: x[1], reverse=True)

        self.setRowCount(len(rows) + 1)
        for row, (name, ms, pct) in enumerate(rows):
            self.setItem(row, 0, QTableWidgetItem(name))
            self.setItem(row, 1, QTableWidgetItem(f"{ms:.3f}"))
            self.setItem(row, 2, QTableWidgetItem(f"{pct:.1f}%"))

        self.setItem(len(rows), 0, QTableWidgetItem("TOTAL"))
        self.setItem(len(rows), 1, QTableWidgetItem(f"{total:.3f}"))
        self.setItem(len(rows), 2, QTableWidgetItem("100%"))


# ==========================================================
# SequenceTableWidget
# ==========================================================

class SequenceTableWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        headers = ["Metric", "Value"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)

    def update_data(self, seq: SequenceSnapshot) -> None:
        items = [
            ("Expected Sequence", str(seq.expected)),
            ("Received Sequence", str(seq.received)),
            ("Total Expected", str(seq.total_expected)),
            ("Total Received", str(seq.total_received)),
            ("Total Lost", str(seq.total_lost)),
            ("Loss %", f"{seq.loss_pct:.2f}%"),
            ("Max Consecutive Loss", str(seq.consecutive_loss)),
            ("Duplicate Frames", str(len(seq.duplicates))),
        ]
        self.setRowCount(len(items))
        for row, (name, val) in enumerate(items):
            name_item = QTableWidgetItem(name)
            val_item = QTableWidgetItem(val)
            if "Lost" in name or "Loss" in name:
                try:
                    pct = float(val.strip("%"))
                    if pct > 5:
                        val_item.setForeground(QColor("#ff4444"))
                    elif pct > 1:
                        val_item.setForeground(QColor("#ff8844"))
                except ValueError:
                    pass
            self.setItem(row, 0, name_item)
            self.setItem(row, 1, val_item)


# ==========================================================
# FrameLifecycleWidget
# ==========================================================

class FrameLifecycleWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        headers = ["Stage", "Timestamp", "Delta (ms)"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh = self.verticalHeader()
        if _vh: _vh.setVisible(False)
        _hh = self.horizontalHeader()
        if _hh: _hh.setStretchLastSection(True)

    def update_data(self, lifecycle: FrameLifecycle | None) -> None:
        if lifecycle is None:
            self.setRowCount(1)
            self.setItem(0, 0, QTableWidgetItem("No frame data"))
            return

        stages_order = [
            PipelineStage.CAMERA_EXPOSURE,
            PipelineStage.HALCON_GRAB,
            PipelineStage.GRAB_COMPLETE,
            PipelineStage.NUMPY_CONVERSION,
            PipelineStage.RAWFRAME_CREATE,
            PipelineStage.RAWFRAME_PUBLISH,
            PipelineStage.GUI_RECEIVE,
            PipelineStage.CALIBRATION,
            PipelineStage.DISPLAY_CONVERSION,
            PipelineStage.COLORMAP,
            PipelineStage.QIMAGE,
            PipelineStage.QPIXMAP,
            PipelineStage.QT_PAINT,
            PipelineStage.PAINT_COMPLETE,
        ]

        visible = [(s, lifecycle.stage_times.get(s)) for s in stages_order if s in lifecycle.stage_times]
        if not visible:
            self.setRowCount(1)
            self.setItem(0, 0, QTableWidgetItem("No stages recorded"))
            return

        base_time = visible[0][1]
        self.setRowCount(len(visible))
        for row, (stage, ts) in enumerate(visible):
            self.setItem(row, 0, QTableWidgetItem(stage.name.replace("_", " ").title()))
            time_str = f"{ts:.6f}" if ts else "--"
            self.setItem(row, 1, QTableWidgetItem(time_str))
            delta_ms = (ts - base_time) * 1000 if ts and base_time else 0
            self.setItem(row, 2, QTableWidgetItem(f"{delta_ms:.3f}"))


# ==========================================================
# NetworkStatsWidget
# ==========================================================

class NetworkStatsWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setSpacing(4)

        entries = [
            (0, 0, "Packet Loss %", "pkt_loss"),
            (0, 1, "Resend Count", "resend"),
            (1, 0, "Duplicates", "duplicates"),
            (1, 1, "Seq Loss %", "seq_loss"),
            (2, 0, "Throughput", "throughput"),
            (2, 1, "Frame Size", "frame_size"),
        ]

        for row, col, name, key in entries:
            label_name = QLabel(name)
            label_name.setObjectName("fpsLabel")
            label_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label_name, row * 2, col)

            value = QLabel("--")
            value.setObjectName("valueLabel")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(value, row * 2 + 1, col)
            self._labels[key] = value

    def update_data(self, stats: NetworkStats | None) -> None:
        if stats is None:
            for label in self._labels.values():
                label.setText("--")
            return
        self._labels["pkt_loss"].setText(f"{stats.packet_loss_pct:.4f}%")
        self._labels["resend"].setText(str(stats.resend_count))
        self._labels["duplicates"].setText(str(stats.duplicate_count))
        self._labels["seq_loss"].setText(f"{stats.sequence_loss_pct:.2f}%")
        self._labels["throughput"].setText(f"{stats.throughput_mbps:.1f} Mbps")
        self._labels["frame_size"].setText(f"{stats.frame_size_bytes} bytes")


# ==========================================================
# NucIsolationPanel -- NUC + Focus isolation results
# ==========================================================

class NucIsolationPanel(QWidget):
    nuc_clicked = pyqtSignal()
    focus_near_clicked = pyqtSignal()
    focus_far_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._events: list[CameraPauseEvent] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # NUC section
        nuc_group = QGroupBox("NUC Isolation")
        nuc_layout = QVBoxLayout(nuc_group)

        nuc_btn_layout = QHBoxLayout()
        self._nuc_btn = QPushButton("Execute NUC")
        self._nuc_btn.setObjectName("dangerBtn")
        self._nuc_btn.clicked.connect(self.nuc_clicked.emit)
        nuc_btn_layout.addWidget(self._nuc_btn)
        nuc_btn_layout.addStretch()
        nuc_layout.addLayout(nuc_btn_layout)

        self._nuc_status = QLabel("No NUC executed yet")
        self._nuc_status.setObjectName("valueLabel")
        nuc_layout.addWidget(self._nuc_status)
        layout.addWidget(nuc_group)

        # Focus section
        focus_group = QGroupBox("Focus Isolation")
        focus_layout = QVBoxLayout(focus_group)

        focus_btn_layout = QHBoxLayout()
        self._focus_near_btn = QPushButton("Focus Near (<<)")
        self._focus_near_btn.setObjectName("focusBtn")
        self._focus_near_btn.clicked.connect(self.focus_near_clicked.emit)
        focus_btn_layout.addWidget(self._focus_near_btn)
        self._focus_far_btn = QPushButton("Focus Far (>>)")
        self._focus_far_btn.setObjectName("focusBtn")
        self._focus_far_btn.clicked.connect(self.focus_far_clicked.emit)
        focus_btn_layout.addWidget(self._focus_far_btn)
        focus_btn_layout.addStretch()
        focus_layout.addLayout(focus_btn_layout)

        self._focus_status = QLabel("No focus operation executed yet")
        self._focus_status.setObjectName("valueLabel")
        focus_layout.addWidget(self._focus_status)
        layout.addWidget(focus_group)

        # Pause events table
        self._pause_table = QTableWidget()
        self._pause_table.setColumnCount(4)
        self._pause_table.setHorizontalHeaderLabels(["Camera", "Pause (ms)", "Cause", "Time"])
        self._pause_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        _vh_p = self._pause_table.verticalHeader()
        if _vh_p: _vh_p.setVisible(False)
        _hh_p = self._pause_table.horizontalHeader()
        if _hh_p: _hh_p.setStretchLastSection(True)
        self._pause_table.setMinimumHeight(100)
        layout.addWidget(QLabel("Pause Events:"))
        layout.addWidget(self._pause_table)

    def set_nuc_busy(self, busy: bool) -> None:
        self._nuc_btn.setEnabled(not busy)
        self._nuc_btn.setText("NUC in progress..." if busy else "Execute NUC")

    def set_nuc_status(self, text: str, is_warning: bool = False) -> None:
        self._nuc_status.setText(text)
        color = "#ff8844" if is_warning else "#88ccff"
        self._nuc_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def set_focus_status(self, text: str, is_warning: bool = False) -> None:
        self._focus_status.setText(text)
        color = "#ff8844" if is_warning else "#88ccff"
        self._focus_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def update_events(self, events: list[CameraPauseEvent], clear: bool = False) -> None:
        self._events = events
        if clear:
            self._events = []
        self._pause_table.setRowCount(len(self._events))
        for row, evt in enumerate(self._events):
            self._pause_table.setItem(row, 0, QTableWidgetItem(evt.camera_id))
            self._pause_table.setItem(row, 1, QTableWidgetItem(f"{evt.pause_duration_ms:.0f}"))
            self._pause_table.setItem(row, 2, QTableWidgetItem(evt.cause))
            self._pause_table.setItem(row, 3, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(evt.timestamp))))

    def show_focus_buttons(self, visible: bool) -> None:
        self._focus_near_btn.setVisible(visible)
        self._focus_far_btn.setVisible(visible)


# ==========================================================
# AnalyzerWindow
# ==========================================================

class AnalyzerWindow(QMainWindow):
    def __init__(self, manager: MulticameraAnalyzerManager):
        super().__init__()
        self._manager = manager
        self._tiles: dict[str, CameraTile] = {}
        self._selected_camera_id: str = manager.camera_ids[0] if manager.camera_ids else ""
        self._nuc_in_progress: bool = False
        self._focus_in_progress: bool = False
        self._last_events_len: int = 0

        self._build_ui()
        self._setup_timers()

    def _setup_timers(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frames)
        self._poll_timer.start(POLL_INTERVAL_MS)

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._update_diagnostics)
        self._diag_timer.start(DIAG_INTERVAL_MS)

        self._network_timer = QTimer(self)
        self._network_timer.timeout.connect(self._update_network)
        self._network_timer.start(NETWORK_INTERVAL_MS)

    def _build_ui(self) -> None:
        self.setWindowTitle("Phase 2 -- Multi-Camera Analyzer")
        self.setMinimumSize(1400, 900)
        self.setStyleSheet(STYLE_DARK)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Title
        title = QLabel("Phase 2 -- Multi-Camera Analyzer")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #88ccff; padding: 4px;")
        root.addWidget(title)

        # Top section: tiles + global summary
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Camera tiles in scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #1a1a2e; }")

        tiles_container = QWidget()
        self._tiles_grid = QGridLayout(tiles_container)
        self._tiles_grid.setSpacing(6)
        scroll.setWidget(tiles_container)
        top_splitter.addWidget(scroll)

        # Global summary
        self._summary_panel = GlobalSummaryPanel()
        top_splitter.addWidget(self._summary_panel)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 1)

        root.addWidget(top_splitter, stretch=2)

        # Build tiles (needs _nuc_panel for focus button visibility)
        self._nuc_panel = NucIsolationPanel()
        self._build_tiles()

        # Detail tabs for selected camera + timeline + event log
        self._tabs = QTabWidget()

        # Tab 1: Latency Breakdown
        latency_tab = QWidget()
        latency_layout = QVBoxLayout(latency_tab)
        self._breakdown_widget = LatencyBreakdownWidget()
        latency_layout.addWidget(QLabel("Latency Breakdown (largest contributor first):"))
        latency_layout.addWidget(self._breakdown_widget)
        self._tabs.addTab(latency_tab, "Latency Breakdown")

        # Tab 2: Stage Timing
        timing_tab = QWidget()
        timing_layout = QVBoxLayout(timing_tab)
        self._stage_timing_widget = StageTimingWidget()
        timing_layout.addWidget(QLabel("Per-Stage Timing:"))
        timing_layout.addWidget(self._stage_timing_widget)
        self._tabs.addTab(timing_tab, "Stage Timing")

        # Tab 3: Sequence Integrity
        seq_tab = QWidget()
        seq_layout = QVBoxLayout(seq_tab)
        self._seq_widget = SequenceTableWidget()
        seq_layout.addWidget(QLabel("Sequence Integrity:"))
        seq_layout.addWidget(self._seq_widget)
        self._tabs.addTab(seq_tab, "Sequence Integrity")

        # Tab 4: Frame Lifecycle
        lifecycle_tab = QWidget()
        lifecycle_layout = QVBoxLayout(lifecycle_tab)
        self._lifecycle_widget = FrameLifecycleWidget()
        lifecycle_layout.addWidget(QLabel("Last Completed Frame Lifecycle:"))
        lifecycle_layout.addWidget(self._lifecycle_widget)
        self._tabs.addTab(lifecycle_tab, "Frame Lifecycle")

        # Tab 5: NUC + Focus Isolation
        self._nuc_panel.nuc_clicked.connect(self._on_nuc)
        self._nuc_panel.focus_near_clicked.connect(self._on_focus_near)
        self._nuc_panel.focus_far_clicked.connect(self._on_focus_far)
        self._tabs.addTab(self._nuc_panel, "NUC + Focus")

        # Tab 6: Network
        network_tab = QWidget()
        network_layout = QVBoxLayout(network_tab)
        self._net_widget = NetworkStatsWidget()
        network_layout.addWidget(QLabel("Transport Layer Statistics:"))
        network_layout.addWidget(self._net_widget)
        network_layout.addStretch()
        self._tabs.addTab(network_tab, "Network")

        # Tab 7: Distortion
        dist_tab = QWidget()
        dist_layout = QVBoxLayout(dist_tab)
        self._dist_label = QLabel("No distortion checks run yet.")
        self._dist_label.setObjectName("okLabel")
        self._dist_label.setWordWrap(True)
        dist_layout.addWidget(self._dist_label)
        dist_layout.addStretch()
        self._tabs.addTab(dist_tab, "Distortion")

        # Tab 8: Timeline View
        self._timeline_widget = TimelineView()
        self._tabs.addTab(self._timeline_widget, "Timeline View")

        # Tab 9: Event Log
        self._event_log_widget = EventLogWidget()
        self._tabs.addTab(self._event_log_widget, "Event Log")

        root.addWidget(self._tabs, stretch=3)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(self._status_label)
        self._cam_count_label = QLabel(f"Cameras: {len(self._manager.camera_ids)}")
        self._status_bar.addPermanentWidget(self._cam_count_label)

    def _build_tiles(self) -> None:
        # Clear existing tiles
        for tile in self._tiles.values():
            self._tiles_grid.removeWidget(tile)
            tile.deleteLater()
        self._tiles.clear()

        cids = self._manager.camera_ids
        if not cids:
            return

        cols = _cols_for_count(len(cids))
        for idx, cid in enumerate(cids):
            analyzer = self._manager.get_analyzer(cid)
            if analyzer is None:
                continue
            tile = CameraTile(cid, analyzer)
            tile.selected.connect(self._on_tile_selected)
            tile.nuc_requested.connect(self._on_nuc_for_camera)
            tile.focus_near_requested.connect(self._on_focus_near_for_camera)
            tile.focus_far_requested.connect(self._on_focus_far_for_camera)
            if cid == self._selected_camera_id:
                tile.set_selected(True)
            self._tiles[cid] = tile
            r, c = divmod(idx, cols)
            self._tiles_grid.addWidget(tile, r, c)

        # Update focus button visibility
        has_focus = any(
            (a := self._manager.get_analyzer(cid)) and a.camera.focus_available()
            for cid in cids
        )
        self._nuc_panel.show_focus_buttons(has_focus)

    # --- Tile selection ---

    def _on_tile_selected(self, camera_id: str) -> None:
        if camera_id == self._selected_camera_id:
            return
        # Deselect old
        old_tile = self._tiles.get(self._selected_camera_id)
        if old_tile:
            old_tile.set_selected(False)
        # Select new
        self._selected_camera_id = camera_id
        new_tile = self._tiles.get(camera_id)
        if new_tile:
            new_tile.set_selected(True)

    # --- Frame polling ---

    def _poll_frames(self) -> None:
        results = self._manager.poll_all()
        for cid, lifecycle in results:
            if lifecycle is None:
                continue
            tile = self._tiles.get(cid)
            if tile is None:
                continue
            analyzer = self._manager.get_analyzer(cid)
            if analyzer is None:
                continue

            seq = analyzer.last_sequence
            rgb = analyzer.last_rgb
            if rgb is None:
                continue
            if seq < 0:
                continue

            try:
                fl = analyzer.get_frame_lifecycle(seq)
                ms = fl.total_latency * 1000 if fl else 0.0
                tile.set_image(rgb, seq, ms)
            except Exception as exc:
                print(f"[ERROR] Tile image update failed for {cid}: {exc}")
                tile.image_widget.show_error(f"Error: {exc}")

    # --- Diagnostics ---

    def _update_diagnostics(self) -> None:
        cross = self._manager.get_cross_camera_snapshot()

        # Global summary
        self._summary_panel.update_data(cross)

        # Tile stats
        for cid, snap in cross.camera_snapshots.items():
            tile = self._tiles.get(cid)
            if tile:
                tile.update_stats(snap)

        # Selected camera detail tabs
        if self._selected_camera_id:
            analyzer = self._manager.get_analyzer(self._selected_camera_id)
            if analyzer is not None:
                snap = cross.camera_snapshots.get(self._selected_camera_id)
                if snap is not None:
                    self._breakdown_widget.update_data(snap.latency_breakdown)
                    stage_stats = analyzer.get_stage_timing().get_all_stage_stats()
                    self._stage_timing_widget.update_data(stage_stats)
                    seq = analyzer.get_sequence_analyzer().snapshot()
                    self._seq_widget.update_data(seq)
                    self._lifecycle_widget.update_data(snap.frame_lifecycle)

                    # Distortion
                    if snap.horizontal_distortion[0]:
                        self._dist_label.setText(f"[WARNING] Horizontal distortion detected: {snap.horizontal_distortion[1]}")
                        self._dist_label.setObjectName("errorLabel")
                    else:
                        self._dist_label.setText(f"OK -- {snap.horizontal_distortion[1]}")
                        self._dist_label.setObjectName("okLabel")
                    _dist_style = self._dist_label.style()
                    if _dist_style:
                        _dist_style.unpolish(self._dist_label)
                        _dist_style.polish(self._dist_label)

                    # NUC events
                    events = analyzer.nuc_monitor.get_events(clear=True)
                    if events:
                        for evt in events:
                            self._nuc_panel.update_events([evt])

        # Timeline view
        self._timeline_widget.update_data(cross)

        # Event log
        events = self._manager.event_log.get_recent(200)
        if len(events) != self._last_events_len:
            self._last_events_len = len(events)
            self._event_log_widget.update_events(events)

        # Status bar
        bn = cross.bottleneck
        self._status_label.setText(
            f"Bottleneck: {bn}  |  "
            f"Cameras: {cross.camera_count}  |  "
            f"Avg FPS: {cross.avg_camera_fps:.1f}  |  "
            f"Total Loss: {cross.total_sequence_loss_pct:.2f}%"
        )

    # --- Network ---

    def _update_network(self) -> None:
        if not self._selected_camera_id:
            return
        analyzer = self._manager.get_analyzer(self._selected_camera_id)
        if analyzer is None:
            return
        stats = analyzer.update_network_stats()
        self._net_widget.update_data(stats)

    # --- NUC ---

    def _on_nuc(self) -> None:
        if self._nuc_in_progress or not self._selected_camera_id:
            return
        self._on_nuc_for_camera(self._selected_camera_id)

    def _on_nuc_for_camera(self, camera_id: str) -> None:
        if self._nuc_in_progress:
            return

        self._nuc_in_progress = True
        self._nuc_panel.set_nuc_busy(True)
        self._nuc_panel.set_nuc_status(f"NUC in progress on {camera_id}...")
        tile = self._tiles.get(camera_id)
        if tile:
            tile.show_busy(True)

        QApplication.processEvents()

        result = self._manager.perform_nuc(camera_id)

        if result.passed:
            self._nuc_panel.set_nuc_status(f"NUC completed on {camera_id} -- isolation PASSED")
        else:
            self._nuc_panel.set_nuc_status(
                f"NUC completed -- WARNING: {len(result.affected_cameras)} other camera(s) paused!",
                is_warning=True,
            )

        self._nuc_panel.update_events([
            CameraPauseEvent(camera_id=cid, pause_duration_ms=result.max_pause_ms, cause=f"NUC on {camera_id}")
            for cid in result.affected_cameras
        ])

        self._nuc_in_progress = False
        self._nuc_panel.set_nuc_busy(False)
        if tile:
            tile.show_busy(False)

    # --- Focus ---

    def _on_focus_near(self) -> None:
        if self._focus_in_progress or not self._selected_camera_id:
            return
        self._on_focus_near_for_camera(self._selected_camera_id)

    def _on_focus_far(self) -> None:
        if self._focus_in_progress or not self._selected_camera_id:
            return
        self._on_focus_far_for_camera(self._selected_camera_id)

    def _on_focus_near_for_camera(self, camera_id: str) -> None:
        self._execute_focus(camera_id, "near")

    def _on_focus_far_for_camera(self, camera_id: str) -> None:
        self._execute_focus(camera_id, "far")

    def _execute_focus(self, camera_id: str, direction: str) -> None:
        if self._focus_in_progress:
            return

        self._focus_in_progress = True
        tile = self._tiles.get(camera_id)
        if tile:
            tile.show_busy(True)

        QApplication.processEvents()

        if direction == "near":
            result = self._manager.perform_focus_near(camera_id)
        else:
            result = self._manager.perform_focus_far(camera_id)

        if result.passed:
            self._nuc_panel.set_focus_status(
                f"Focus {direction} completed on {camera_id} -- isolation PASSED",
            )
        else:
            self._nuc_panel.set_focus_status(
                f"Focus {direction} completed -- WARNING: {len(result.affected_cameras)} other camera(s) paused!",
                is_warning=True,
            )

        self._nuc_panel.update_events([
            CameraPauseEvent(camera_id=cid, pause_duration_ms=result.max_pause_ms, cause=f"Focus {direction} on {camera_id}")
            for cid in result.affected_cameras
        ])

        self._focus_in_progress = False
        if tile:
            tile.show_busy(False)

    # --- Shutdown ---

    def closeEvent(self, a0) -> None:
        self._poll_timer.stop()
        self._diag_timer.stop()
        self._network_timer.stop()
        self._manager.shutdown_all()
        super().closeEvent(a0)


# ==========================================================
# Entry Point
# ==========================================================

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Multi-Camera Pipeline Analyzer")

    print("[INFO] Initializing calibration...")
    calibration = CalibrationManager()
    calibration.initialize()

    print("[INFO] Discovering cameras...")
    discovered = _discover_cameras()
    if not discovered:
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("No Cameras Found")
        msg.setText("No GigE Vision cameras could be discovered.\n\nCheck that cameras are connected to the network and powered on.")
        msg.exec()
        print("[ERROR] No cameras found.")
        sys.exit(1)

    camera_data: list[tuple[str, TV46LCamera, CalibrationManager]] = []
    for cam_info in discovered:
        cid = cam_info.serial
        print(f"[INFO] Connecting to {cid}...")
        camera = TV46LCamera(cam_info, settings)
        try:
            camera.connect()
            camera.start()
            if not camera.wait_for_first_frame(timeout=10.0):
                print(f"[ERROR] {cid}: No frame received within 10s")
                camera.disconnect()
                continue
            camera_data.append((cid, camera, calibration))
            print(f"[INFO] {cid} ready.")
        except Exception as exc:
            print(f"[ERROR] Failed to initialize {cid}: {exc}")

    if not camera_data:
        print("[ERROR] No cameras could be initialized.")
        sys.exit(1)

    manager = MulticameraAnalyzerManager(camera_data)
    window = AnalyzerWindow(manager)
    window.show()
    exit_code = app.exec()

    manager.shutdown_all()
    for cid, camera, _cal in camera_data:
        try:
            camera.stop()
            camera.disconnect()
        except Exception:
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
