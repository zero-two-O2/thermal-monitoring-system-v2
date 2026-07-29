"""
halcon_roi_validation.py

Standalone HALCON Drawing Object validation tool.

Purpose
-------
Independent verification that every HALCON drawing object,
callback, parameter query, and iconic extraction works correctly
before integrating into the main application.

Reuses production camera code (CameraDiscovery, TV46LCamera,
CalibrationManager) but communicates directly with HALCON
for all drawing object operations.

No ROI subsystem code is used.
"""

from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import halcon as ha

from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo
from calibration.calibration_manager import CalibrationManager

FEED_W = 640
FEED_H = 480
POLL_MS = 33

_HALCON_CALLBACK_REFS: list[Any] = []


# ==========================================================
# Signals object — thread-safe cross-thread communication
# ==========================================================


class ValidationSignals(QObject):
    log = pyqtSignal(str)
    params_updated = pyqtSignal(str, list)
    iconic_updated = pyqtSignal(str, str, object)
    window_info_updated = pyqtSignal(int, int, str)


# ==========================================================
# Embedded HALCON Window
# ==========================================================


class HalconView(QFrame):
    def __init__(self, log_fn: Any = None, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._handle: Any = None
        self._log = log_fn
        self.setMinimumSize(FEED_W, FEED_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def create_window(self) -> None:
        if self._handle is not None:
            return
        try:
            self._log("Creating HALCON window...")
            self._log(f"  widget.winId() = {self.winId()} (type={type(self.winId()).__name__})")
            self._log(f"  widget size = {self.width()}x{self.height()}")
            self._handle = ha.open_window(
                0, 0, self.width(), self.height(),
                int(self.winId()), "visible", "",
            )
            self._log(f"  ha.open_window returned: handle={self._handle} (type={type(self._handle).__name__})")
            ha.set_window_param(self._handle, "flush", "true")
            self._log("  flush=auto set")
            test = np.full((100, 200), 128, dtype=np.uint8)
            self._log("  Displaying test gray patch...")
            self.display_halcon_image(test)
        except Exception as e:
            self._log(f"  FAILED to create HALCON window: {e}")

    @property
    def handle(self) -> Any:
        return self._handle

    def is_handle_valid(self) -> bool:
        return self._handle is not None

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self._handle is not None:
            try:
                ha.set_window_extents(
                    self._handle, 0, 0, self.width(), self.height()
                )
            except Exception:
                pass

    def _numpy_to_halcon(self, arr: np.ndarray) -> Any:
        arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        if arr.ndim == 2:
            return ha.gen_image1("byte", w, h, int(arr.ctypes.data))
        rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        r = np.ascontiguousarray(rgb[:, :, 0])
        g = np.ascontiguousarray(rgb[:, :, 1])
        b = np.ascontiguousarray(rgb[:, :, 2])
        return ha.gen_image3("byte", w, h,
                             int(r.ctypes.data),
                             int(g.ctypes.data),
                             int(b.ctypes.data))

    def display_halcon_image(self, image: Any) -> None:
        if self._handle is None:
            return
        try:
            if isinstance(image, np.ndarray):
                orig_h, orig_w = image.shape[:2]
                image = self._numpy_to_halcon(image)
            else:
                orig_w, orig_h = ha.get_image_size(image)
            ha.clear_window(self._handle)
            ha.set_part(self._handle, 0, 0, orig_h - 1, orig_w - 1)
            ha.disp_obj(image, self._handle)
            ha.flush_buffer(self._handle)
        except Exception as e:
            self._log(f"display error: {e}")

    def clear_display(self) -> None:
        if self._handle is not None:
            try:
                ha.clear_window(self._handle)
            except Exception:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._handle is not None:
            try:
                ha.close_window(self._handle)
            except Exception:
                pass
            self._handle = None
        super().closeEvent(event)


# ==========================================================
# Main Validation Application
# ==========================================================


class HalconROIValidation(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self._signals = ValidationSignals()
        self._signals.log.connect(self._append_log)
        self._signals.params_updated.connect(self._update_params_display)
        self._signals.window_info_updated.connect(self._update_window_info)

        self._camera: Any = None
        self._calibration: CalibrationManager | None = None
        self._camera_infos: list[CameraInfo] = []

        self._draw_objects: dict[str, Any] = {}
        self._selected_roi: str | None = None
        self._roi_counter = 0

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frame)

        self._build_ui()

    # ==========================================================
    # UI Construction
    # ==========================================================

    def _build_ui(self) -> None:
        self.setWindowTitle("HALCON ROI Validation Tool")
        self.resize(1280, 900)

        root = QVBoxLayout(self.centralWidget() if self.centralWidget() else None)
        if self.centralWidget() is None:
            cw = QWidget()
            self.setCentralWidget(cw)
            root = QVBoxLayout(cw)
        else:
            root = QVBoxLayout(self.centralWidget())

        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Camera Controls ---
        cam_group = QGroupBox("Camera Controls")
        cam_layout = QHBoxLayout(cam_group)
        self._discover_btn = QPushButton("Discover")
        self._discover_btn.clicked.connect(self._on_discover)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect)
        self._connect_btn.setEnabled(False)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        self._camera_combo = QComboBox()
        self._camera_combo.setMinimumWidth(300)
        cam_layout.addWidget(self._discover_btn)
        cam_layout.addWidget(self._connect_btn)
        cam_layout.addWidget(self._disconnect_btn)
        cam_layout.addWidget(QLabel("Camera:"))
        cam_layout.addWidget(self._camera_combo, 1)
        root.addWidget(cam_group)

        # --- Thermal Feed + Window Info ---
        feed_row = QHBoxLayout()
        feed_row.setSpacing(6)

        self._halcon_view = HalconView(log_fn=self._log_direct, parent=self)
        self._halcon_view.setFrameShape(QFrame.StyledPanel)
        feed_row.addWidget(self._halcon_view, 3)

        info_panel = QVBoxLayout()
        info_panel.setSpacing(4)

        winfo_group = QGroupBox("Window Info")
        winfo_layout = QVBoxLayout(winfo_group)
        self._handle_label = QLabel("Handle: ---")
        self._obj_count_label = QLabel("Objects: 0")
        self._selected_label = QLabel("Selected: ---")
        winfo_layout.addWidget(self._handle_label)
        winfo_layout.addWidget(self._obj_count_label)
        winfo_layout.addWidget(self._selected_label)
        info_panel.addWidget(winfo_group)

        # --- Appearance Controls ---
        app_group = QGroupBox("Appearance")
        app_layout = QVBoxLayout(app_group)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self._color_btn = QPushButton("Yellow")
        self._color_btn.setStyleSheet("background-color: yellow; color: black;")
        self._color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._color_btn)

        lw_row = QHBoxLayout()
        lw_row.addWidget(QLabel("Line Width:"))
        self._line_width_slider = QSlider(Qt.Horizontal)
        self._line_width_slider.setRange(1, 10)
        self._line_width_slider.setValue(2)
        self._line_width_slider.valueChanged.connect(self._on_appearance_changed)
        lw_row.addWidget(self._line_width_slider)
        lw_row.addWidget(QLabel("2"))

        ms_row = QHBoxLayout()
        ms_row.addWidget(QLabel("Marker Size:"))
        self._marker_slider = QSlider(Qt.Horizontal)
        self._marker_slider.setRange(1, 20)
        self._marker_slider.setValue(5)
        self._marker_slider.valueChanged.connect(self._on_appearance_changed)
        ms_row.addWidget(self._marker_slider)
        ms_row.addWidget(QLabel("5"))

        app_layout.addLayout(color_row)
        app_layout.addLayout(lw_row)
        app_layout.addLayout(ms_row)
        info_panel.addWidget(app_group)
        info_panel.addStretch()

        feed_row.addLayout(info_panel, 1)
        root.addLayout(feed_row, 3)

        # --- ROI Controls ---
        roi_group = QGroupBox("ROI Controls")
        roi_layout = QHBoxLayout(roi_group)

        shapes = [
            ("Rectangle1", self._on_rect1),
            ("Rotated Rect", self._on_rect2),
            ("Circle", self._on_circle),
            ("Ellipse", self._on_ellipse),
            ("Polygon", self._on_polygon),
            ("Clear Current", self._on_clear_current),
            ("Clear All", self._on_clear_all),
        ]
        for text, cb in shapes:
            btn = QPushButton(text)
            btn.clicked.connect(cb)
            roi_layout.addWidget(btn)

        root.addWidget(roi_group)

        # --- Parameters Display ---
        params_group = QGroupBox("Current ROI Parameters")
        params_layout = QVBoxLayout(params_group)
        self._params_text = QTextEdit()
        self._params_text.setReadOnly(True)
        self._params_text.setMaximumHeight(120)
        self._params_text.setPlaceholderText(
            "Select or drag a drawing object to see parameters..."
        )
        params_layout.addWidget(self._params_text)
        root.addWidget(params_group)

        # --- Event Log ---
        log_group = QGroupBox("Live Event Log")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setPlaceholderText("Events will appear here...")
        log_layout.addWidget(self._log_text)

        btn_row = QHBoxLayout()
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self._log_text.clear)
        btn_row.addStretch()
        btn_row.addWidget(clear_log_btn)
        log_layout.addLayout(btn_row)

        root.addWidget(log_group, 2)

    # ==========================================================
    # Camera Operations
    # ==========================================================

    def _on_discover(self) -> None:
        self._log("Discovering cameras...")
        self._discover_btn.setEnabled(False)
        self._camera_combo.clear()
        QApplication.processEvents()

        try:
            discovery = CameraDiscovery()
            self._camera_infos = discovery.discover()
            for info in self._camera_infos:
                label = f"{info.model} (SN:{info.serial}, IP:{info.ip})"
                self._camera_combo.addItem(label, info.device)
            self._log(
                f"Discovered {len(self._camera_infos)} camera(s)."
            )
        except Exception as e:
            self._log(f"Discovery error: {e}")
            traceback.print_exc()
        finally:
            self._discover_btn.setEnabled(True)
            self._connect_btn.setEnabled(len(self._camera_infos) > 0)

    def _on_connect(self) -> None:
        idx = self._camera_combo.currentIndex()
        if idx < 0 or idx >= len(self._camera_infos):
            return

        info = self._camera_infos[idx]
        self._log(f"Connecting to {info.model} ({info.serial})...")
        self._connect_btn.setEnabled(False)

        try:
            from camera.tv46l_camera import TV46LCamera
            from configuration.settings import Settings

            settings = Settings()
            self._camera = TV46LCamera(info, settings)
            self._camera.connect()
            self._camera.start()

            ok = self._camera.wait_for_first_frame(timeout=10.0)
            if not ok:
                raise RuntimeError("No frames received within 10s timeout")

            self._log("Camera connected and streaming.")

            try:
                self._calibration = CalibrationManager()
                self._calibration.initialize()
                self._log("Calibration loaded.")
            except Exception as e:
                self._calibration = None
                self._log(f"Calibration unavailable (displaying raw): {e}")

            self._disconnect_btn.setEnabled(True)
            self._connect_btn.setEnabled(False)

            QApplication.processEvents()
            self._halcon_view.create_window()
            if self._halcon_view.handle is None:
                raise RuntimeError("Failed to create HALCON window")
            self._log(f"HALCON window handle={self._halcon_view.handle}")
            self._update_window_info_static()
            self._poll_timer.start(POLL_MS)
            self._log("Frame polling started.")

        except Exception as e:
            self._log(f"Connection failed: {e}")
            traceback.print_exc()
            self._connect_btn.setEnabled(True)

    def _on_disconnect(self) -> None:
        self._poll_timer.stop()
        self._log("Disconnecting camera...")

        self._clear_all_objects()

        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.disconnect()
            except Exception as e:
                self._log(f"Disconnect error: {e}")
            self._camera = None

        self._calibration = None
        self._halcon_view.clear_display()
        self._disconnect_btn.setEnabled(False)
        self._connect_btn.setEnabled(len(self._camera_infos) > 0)
        self._log("Camera disconnected.")

    # ==========================================================
    # Frame Polling
    # ==========================================================

    def _poll_frame(self) -> None:
        if self._camera is None:
            return
        if self._halcon_view.handle is None:
            return

        try:
            frame = self._camera.grab_frame()
            if frame is None:
                return

            raw = frame.image

            if self._calibration is not None and self._calibration.is_initialized:
                display = self._calibration.raw_to_display(raw)
                rgb = self._calibration.apply_colormap(display)
                self._halcon_view.display_halcon_image(rgb)
            else:
                normalized = raw.astype(np.float32)
                lo, hi = normalized.min(), normalized.max()
                if hi > lo:
                    normalized = (normalized - lo) / (hi - lo) * 255.0
                else:
                    normalized = np.zeros_like(normalized)
                gray = normalized.astype(np.uint8)
                self._halcon_view.display_halcon_image(gray)

        except Exception as e:
            self._log(f"poll_frame error: {e}")

    # ==========================================================
    # ROI / Drawing Object Creation
    # ==========================================================

    def _next_roi_name(self, shape: str) -> str:
        self._roi_counter += 1
        return f"{shape}_{self._roi_counter}"

    def _create_and_attach(self, name: str, draw_obj: Any) -> None:
        if self._halcon_view.handle is None:
            self._log("Cannot create ROI: no HALCON window.")
            return

        old = self._draw_objects.get(name)
        if old is not None:
            self._detach_and_destroy(name)

        self._draw_objects[name] = draw_obj

        try:
            ha.attach_drawing_object_to_window(
                self._halcon_view.handle, draw_obj
            )
            self._log(f"{name} created and attached.")
        except Exception as e:
            self._log(f"Attach failed for {name}: {e}")
            del self._draw_objects[name]
            return

        self._register_callbacks(name, draw_obj)
        self._update_window_info_static()

    def _register_callbacks(self, name: str, draw_obj: Any) -> None:
        self._log(f"  Callbacks not supported in this HALCON build (requires int IDs, no Python fn support)")

    def _select_roi(self, name: str) -> None:
        self._selected_roi = name
        self._update_window_info_static()

    def _make_cb(self, name: str, event: str) -> Any:
        signals = self._signals
        _log = self._log_direct
        get_objects = lambda: self._draw_objects
        select_roi = lambda: self._select_roi(name)

        def cb(draw_id: Any, win_handle: Any, halcon_event: str) -> int:
            try:
                now = datetime.now().strftime("%H:%M:%S")
                signals.log.emit(f"[{now}] {name}  {event}")

                if event in ("on_drag", "on_resize"):
                    signals.log.emit(
                        f"[{now}] {name}  querying parameters..."
                    )
                    objs = get_objects()
                    obj = objs.get(name)
                    if obj is not None:
                        signals.params_updated.emit(name, [obj])
                        _query_iconic_and_emit(name, obj, signals)

                elif event == "on_select":
                    select_roi()
                    signals.log.emit(f"[{now}] {name}  SELECTED")
                    objs = get_objects()
                    obj = objs.get(name)
                    if obj is not None:
                        signals.params_updated.emit(name, [obj])
                        _query_iconic_and_emit(name, obj, signals)

                elif event == "on_detach":
                    signals.log.emit(f"[{now}] {name}  DETACHED")

                elif event == "on_attach":
                    pass

            except Exception:
                pass
            return 0

        return cb

    # ==========================================================
    # Shape Creation Handlers
    # ==========================================================

    def _on_rect1(self) -> None:
        if self._halcon_view.handle is None:
            self._log("Open camera feed first.")
            return
        name = self._next_roi_name("Rect1")
        try:
            draw_obj = ha.create_drawing_object_rectangle1(
                150.0, 150.0, 350.0, 450.0
            )
            self._create_and_attach(name, draw_obj)
        except Exception as e:
            self._log(f"Rectangle1 creation failed: {e}")

    def _on_rect2(self) -> None:
        if self._halcon_view.handle is None:
            self._log("Open camera feed first.")
            return
        name = self._next_roi_name("Rect2")
        try:
            draw_obj = ha.create_drawing_object_rectangle2(
                240.0, 320.0, 0.0, 100.0, 60.0
            )
            self._create_and_attach(name, draw_obj)
        except Exception as e:
            self._log(f"Rectangle2 creation failed: {e}")

    def _on_circle(self) -> None:
        if self._halcon_view.handle is None:
            self._log("Open camera feed first.")
            return
        name = self._next_roi_name("Circle")
        try:
            draw_obj = ha.create_drawing_object_circle(
                240.0, 320.0, 60.0
            )
            self._create_and_attach(name, draw_obj)
        except Exception as e:
            self._log(f"Circle creation failed: {e}")

    def _on_ellipse(self) -> None:
        if self._halcon_view.handle is None:
            self._log("Open camera feed first.")
            return
        name = self._next_roi_name("Ellipse")
        try:
            draw_obj = ha.create_drawing_object_ellipse(
                240.0, 320.0, 0.0, 90.0, 50.0
            )
            self._create_and_attach(name, draw_obj)
        except Exception as e:
            self._log(f"Ellipse creation failed: {e}")

    def _on_polygon(self) -> None:
        if self._halcon_view.handle is None:
            self._log("Open camera feed first.")
            return
        name = self._next_roi_name("Polygon")
        try:
            rows = [160.0, 160.0, 320.0, 320.0]
            cols = [160.0, 480.0, 480.0, 160.0]
            draw_obj = ha.create_drawing_object_xld(rows, cols)
            self._create_and_attach(name, draw_obj)
        except Exception as e:
            self._log(f"Polygon creation failed: {e}")

    # ==========================================================
    # Clear Operations
    # ==========================================================

    def _on_clear_current(self) -> None:
        if self._selected_roi is None:
            self._log("No current selection to clear.")
            return
        self._detach_and_destroy(self._selected_roi)
        self._selected_roi = None
        self._params_text.clear()
        self._update_window_info_static()

    def _on_clear_all(self) -> None:
        self._clear_all_objects()

    def _clear_all_objects(self) -> None:
        names = list(self._draw_objects.keys())
        for name in names:
            self._detach_and_destroy(name)
        self._selected_roi = None
        self._params_text.clear()
        self._update_window_info_static()
        self._log("All drawing objects cleared.")

    def _detach_and_destroy(self, name: str) -> None:
        obj = self._draw_objects.pop(name, None)
        if obj is None:
            return
        try:
            ha.detach_drawing_object_from_window(
                obj, self._halcon_view.handle
            )
            self._log(f"{name} detached.")
        except Exception as e:
            self._log(f"Detach failed for {name}: {e}")
        try:
            ha.clear_drawing_object(obj)
            self._log(f"{name} destroyed.")
        except Exception as e:
            self._log(f"Destroy failed for {name}: {e}")

    # ==========================================================
    # Appearance
    # ==========================================================

    _current_color: str = "yellow"

    def _on_pick_color(self) -> None:
        from PyQt5.QtWidgets import QColorDialog

        color = QColorDialog.getColor(QColor(self._current_color), self, "Pick ROI Color")
        if color.isValid():
            self._current_color = color.name()
            self._color_btn.setStyleSheet(
                f"background-color: {self._current_color}; color: black;"
            )
            self._color_btn.setText(color.name())
            self._on_appearance_changed()

    def _on_appearance_changed(self) -> None:
        color = self._current_color
        lw = self._line_width_slider.value()
        ms = self._marker_slider.value()

        for name, obj in self._draw_objects.items():
            try:
                ha.set_drawing_object_params(
                    obj, ["color", "line_width", "marker_size"],
                    [color, lw, ms],
                )
            except Exception as e:
                self._log(f"Appearance update failed for {name}: {e}")

    # ==========================================================
    # Parameter Display Update
    # ==========================================================

    def _update_params_display(self, name: str, args: list) -> None:
        obj = args[0]
        text = self._query_params_text(name, obj)
        self._params_text.setText(text)

    def _query_params_text(self, name: str, obj: Any) -> str:
        lines: list[str] = []
        lines.append(f"=== {name} ===")
        lines.append("")

        parts = name.split("_")
        shape_base = parts[0].lower() if parts else ""

        param_names = self._param_names_for_shape(shape_base)
        if param_names:
            try:
                values = ha.get_drawing_object_params(obj, param_names)
                lines.append("-- Geometry --")
                for p, v in zip(param_names, values):
                    val_str = f"{v:.2f}" if isinstance(v, float) else str(v)
                    lines.append(f"  {p} = {val_str}")
            except Exception as e:
                lines.append(f"  (params error: {e})")

        lines.append("")
        lines.append("-- Appearance --")
        for attr in ("color", "line_width", "marker_size", "line_style"):
            try:
                val = ha.get_drawing_object_params(obj, attr)
                lines.append(f"  {attr} = {val}")
            except Exception:
                pass

        lines.append("")
        lines.append("-- Iconic Object --")
        try:
            iconic = ha.get_drawing_object_iconic(obj)
            obj_type = type(iconic).__name__
            lines.append(f"  Type = {obj_type}")

            try:
                area = ha.region_features(iconic, "area")
                lines.append(f"  Area = {area[0]:.1f}")
            except Exception:
                pass

            try:
                num_points = None
                if shape_base == "polygon":
                    try:
                        r, c = ha.get_contour_xld(iconic)
                        num_points = len(r)
                    except Exception:
                        pass
                if num_points is not None:
                    lines.append(f"  Points = {num_points}")

                try:
                    row, col, _ = ha.get_region_polygon(iconic)
                    if len(row) > 0:
                        lines.append(f"  Region rows = {len(row)}")
                except Exception:
                    pass

            except Exception:
                pass

            try:
                box = ha.region_features(iconic, ["row1", "column1", "row2", "column2"])
                if len(box) >= 4:
                    lines.append(
                        f"  BBox = ({box[0]:.1f}, {box[1]:.1f}, "
                        f"{box[2]:.1f}, {box[3]:.1f})"
                    )
            except Exception:
                pass

        except Exception as e:
            lines.append(f"  (iconic error: {e})")

        return "\n".join(lines)

    @staticmethod
    def _param_names_for_shape(shape: str) -> list[str]:
        shape_map = {
            "rect1": ["row1", "column1", "row2", "column2"],
            "rectangle1": ["row1", "column1", "row2", "column2"],
            "rect2": ["row", "column", "phi", "length1", "length2"],
            "rectangle2": ["row", "column", "phi", "length1", "length2"],
            "circle": ["row", "column", "radius"],
            "ellipse": ["row", "column", "phi", "radius1", "radius2"],
            "polygon": [],
        }
        return shape_map.get(shape, ["row", "column"])

    # ==========================================================
    # Window Info
    # ==========================================================

    def _update_window_info_static(self) -> None:
        handle = self._halcon_view.handle
        count = len(self._draw_objects)
        sel = self._selected_roi or "---"
        self._signals.window_info_updated.emit(
            handle if handle is not None else 0, count, sel
        )

    def _update_window_info(self, handle: int, count: int, selected: str) -> None:
        hstr = f"0x{handle:X}" if handle else "---"
        self._handle_label.setText(f"Handle: {hstr}")
        self._obj_count_label.setText(f"Objects: {count}")
        self._selected_label.setText(f"Selected: {selected}")

    # ==========================================================
    # Logging
    # ==========================================================

    def _log_direct(self, msg: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._log_text.append(f"[{now}] {msg}")
        sb = self._log_text.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _append_log(self, msg: str) -> None:
        self._log_text.append(msg)
        sb = self._log_text.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _log(self, msg: str) -> None:
        self._log_direct(msg)

    # ==========================================================
    # Cleanup
    # ==========================================================

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        self._clear_all_objects()
        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.disconnect()
            except Exception:
                pass
        event.accept()

    # Debug: list all objects
    def _debug_list_objects(self) -> None:
        names = list(self._draw_objects.keys())
        self._log(f"Active objects ({len(names)}): {', '.join(names) if names else 'none'}")


# ==========================================================
# Module-Level Helpers
# ==========================================================


def _query_iconic_and_emit(
    name: str, obj: Any, signals: ValidationSignals
) -> None:
    try:
        iconic = ha.get_drawing_object_iconic(obj)
        signals.iconic_updated.emit(name, type(iconic).__name__, iconic)
    except Exception as e:
        signals.log.emit(f"  Iconic query failed for {name}: {e}")


# ==========================================================
# Entry Point
# ==========================================================


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = HalconROIValidation()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
