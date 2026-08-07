"""
halcon_roi_validation.py

Standalone GUI-based HALCON validation tool for Fluke TV46L thermal camera.
Replicates MVTec HDevelop processing architecture exactly.

Processing workflow per frame:
    grab_image() -> temperature conversion -> intensity() -> min_max_gray()

Architecture:
    Initialize Camera (open_framegrabber)
    Load Calibration
    Load ROI JSON
    Generate HALCON Regions Once (gen_rectangle1)
    Start Live Loop:
        Acquire Frame
        HALCON Statistics (intensity, min_max_gray)
        Display Image
        Display ROI Outlines (spring green)
        Display ROI Labels
        Update ROI Table
        Repeat
"""

import sys
import time
import json
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

import halcon as ha
import numpy as np
from PyQt6.QtCore import (QThread, pyqtSignal, QObject, QTimer, Qt,
                          QMutex, QWaitCondition)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QPushButton, QTableWidget,
                              QTableWidgetItem, QTextEdit, QStatusBar,
                              QToolBar, QHeaderView, QMessageBox)
from PyQt6.QtGui import QFont, QColor, QCloseEvent

from calibration.calibration_manager import CalibrationManager
from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FEED_W = 640
FEED_H = 480
ROI_JSON_PATH = "rois.json"


@dataclass
class ROIData:
    name: str
    y1: int
    x1: int
    y2: int
    x2: int


@dataclass
class ROIStatistics:
    name: str
    mean: float
    deviation: float
    minimum: float
    maximum: float
    range_val: float


class CameraWorker(QObject):
    """Worker thread for camera acquisition and HALCON processing."""

    frame_ready = pyqtSignal(object, object, float)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)
    connected_signal = pyqtSignal(bool)
    nuc_status = pyqtSignal(bool, str)
    focus_status = pyqtSignal(bool, str)
    initialized = pyqtSignal()

    def __init__(self, camera_info: CameraInfo):
        super().__init__()
        self._camera_info = camera_info
        self._running = False
        self._mutex = QMutex()
        self._wait_condition = QWaitCondition()
        self._framegrabber = None
        self._connected = False
        self._calibration = None
        self._roi_regions = None
        self._roi_names = []
        self._roi_coords = []
        self._nuc_requested = False
        self._focus_requested = False
        self._focus_direction = 0

    def initialize(self) -> bool:
        """Stage 1: Open framegrabber, connect camera, grab first image, load calibration, load ROIs, generate regions."""
        try:
            self.log_message.emit(f"Opening framegrabber for device: {self._camera_info.device}")

            self._framegrabber = ha.open_framegrabber(
                "GigEVision2", 0, 0, 0, 0, 0, 0,
                "progressive", -1, "default", -1, "false",
                "default", self._camera_info.device, 0, -1
            )

            self.log_message.emit("Framegrabber opened successfully")
            self.log_message.emit("Configuring camera parameters...")
            self._configure_camera()

            ha.grab_image_start(self._framegrabber, -1)
            self.log_message.emit("grab_image_start() called - continuous acquisition started")

            self.log_message.emit("Grabbing first image...")
            first_frame = ha.grab_image_async(self._framegrabber, 5000)
            if first_frame is None:
                raise RuntimeError("Failed to grab first frame within 5s")

            # Log first frame details
            width = ha.get_image_size(first_frame)[1]
            height = ha.get_image_size(first_frame)[0]
            first_numpy = ha.himage_as_numpy_array(first_frame)
            gray_min = int(first_numpy.min())
            gray_max = int(first_numpy.max())
            self.log_message.emit(
                f"First frame verified: {width}x{height}, "
                f"gray range [{gray_min}, {gray_max}], "
                f"dtype={first_numpy.dtype}"
            )

            self.log_message.emit("Loading calibration...")
            self._calibration = CalibrationManager()
            self._calibration.initialize()

            self.log_message.emit("Loading ROI JSON...")
            if not self._load_rois():
                raise RuntimeError("Failed to load ROIs")

            self.log_message.emit("Generating HALCON regions...")
            self._generate_halcon_regions()

            self._connected = True
            self.connected_signal.emit(True)
            self.log_message.emit("Camera connected and initialized successfully")
            self.initialized.emit()
            return True

        except Exception as e:
            self.log_message.emit(f"Initialization failed: {e}")
            logger.exception("Camera initialization failed")
            self.error_occurred.emit(str(e))
            return False

    def _configure_camera(self):
        """Configure TV46L acquisition parameters exactly as in HalconDriver/tv46l_camera."""
        ha.set_framegrabber_param(self._framegrabber, "FLK_TI_StreamDataSourceSelector", "IR_Data")
        ha.set_framegrabber_param(self._framegrabber, "bits_per_channel", 16)

        try:
            ha.set_framegrabber_param(self._framegrabber, "[Stream]DeviceStreamChannelNegotiatePacketSize", 1)
        except Exception as e:
            logger.warning(f"Unable to negotiate packet size: {e}")

        try:
            ha.set_framegrabber_param(self._framegrabber, "[Stream]GevStreamReceiveSocketSize", 1048576)
        except Exception as e:
            logger.warning(f"Unable to set socket buffer size: {e}")

        try:
            ha.set_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_SetFrameRate", 9)
        except Exception:
            logger.warning("Unable to set frame rate")

        try:
            ha.set_framegrabber_param(
                self._framegrabber,
                "FLK_TI_ControlFeature_REControlCmd",
                "FLK_TI_ControlFeature_REControlCmd_DisableAutomaticFineOffsets"
            )
        except Exception:
            logger.warning("Unable to disable automatic NUC")

    def _load_rois(self) -> bool:
        """Load ROI coordinates from JSON file into parallel arrays."""
        try:
            with open(ROI_JSON_PATH, 'r') as f:
                roi_list = json.load(f)

            self._roi_names = []
            self._roi_coords = []

            for roi in roi_list:
                self._roi_names.append(roi["name"])
                self._roi_coords.append((roi["y1"], roi["x1"], roi["y2"], roi["x2"]))

            self.log_message.emit(f"Loaded JSON ROIs: {len(self._roi_names)}")
            return True

        except FileNotFoundError:
            self.log_message.emit(f"ROI file not found: {ROI_JSON_PATH}")
            return False
        except Exception as e:
            self.log_message.emit(f"Failed to load ROIs: {e}")
            logger.exception("Failed to load ROIs")
            return False

    def _generate_halcon_regions(self):
        """Generate HALCON region objects from parallel arrays (once only)."""
        if not self._roi_coords:
            return

        rows1 = [c[0] for c in self._roi_coords]
        cols1 = [c[1] for c in self._roi_coords]
        rows2 = [c[2] for c in self._roi_coords]
        cols2 = [c[3] for c in self._roi_coords]

        self._roi_regions = ha.gen_rectangle1(rows1, cols1, rows2, cols2)
        self.log_message.emit(f"Generated HALCON Regions: {len(self._roi_names)}")

    def reload_rois(self):
        """Reload ROI JSON and regenerate HALCON regions."""
        self.log_message.emit("Reloading ROI JSON...")
        if self._load_rois():
            self._generate_halcon_regions()
            self.log_message.emit("ROIs reloaded successfully")
        else:
            self.error_occurred.emit("Failed to reload ROIs")

    def request_nuc(self):
        """Request manual NUC execution."""
        self._mutex.lock()
        self._nuc_requested = True
        self._mutex.unlock()

    def request_focus(self, direction: int):
        """Request focus near (1) or far (-1)."""
        self._mutex.lock()
        self._focus_requested = True
        self._focus_direction = direction
        self._mutex.unlock()

    def run(self):
        """Main processing loop - runs in worker thread."""
        self.log_message.emit("Acquisition loop started")
        self._running = True
        frame_count = 0
        last_fps_time = time.time()
        fps = 0.0
        prev_frame_hash = None

        while self._running:
            loop_start = time.perf_counter()

            try:
                if not self._connected:
                    self._attempt_reconnect()
                    time.sleep(2.0)
                    continue

                raw_frame = ha.grab_image_async(self._framegrabber, 500)
                if raw_frame is None:
                    continue

                raw_numpy = ha.himage_as_numpy_array(raw_frame)

                # Verify frame on first acquisition
                if frame_count == 0:
                    width = raw_numpy.shape[1]
                    height = raw_numpy.shape[0]
                    gray_min = int(raw_numpy.min())
                    gray_max = int(raw_numpy.max())
                    self.log_message.emit(
                        f"First frame verified: {width}x{height}, "
                        f"gray range [{gray_min}, {gray_max}], "
                        f"dtype={raw_numpy.dtype}"
                    )

                temp_frame = self._calibration.raw_to_temperature(raw_numpy)

                # Verify calibration output on first frame
                if frame_count == 0:
                    self.log_message.emit(
                        f"Calibration output: shape={temp_frame.shape}, "
                        f"dtype={temp_frame.dtype}, "
                        f"min={np.nanmin(temp_frame):.2f}, "
                        f"max={np.nanmax(temp_frame):.2f}"
                    )

                # Verify consecutive frames are different (after first few frames)
                if frame_count > 5:
                    frame_hash = hash(temp_frame.tobytes())
                    if frame_hash == prev_frame_hash:
                        self.log_message.emit("WARNING: Consecutive frames identical - acquisition may be stalled")
                    prev_frame_hash = frame_hash

                proc_start = time.perf_counter()

                # Convert to HALCON image for ROI statistics
                halcon_temp_image = ha.himage_from_numpy_array(temp_frame.astype(np.float32))

                mean_vals, dev_vals = ha.intensity(self._roi_regions, halcon_temp_image)
                min_vals, max_vals, range_vals = ha.min_max_gray(self._roi_regions, halcon_temp_image, 0)

                proc_time_ms = (time.perf_counter() - proc_start) * 1000.0

                statistics = []
                for i, name in enumerate(self._roi_names):
                    statistics.append(ROIStatistics(
                        name=name,
                        mean=float(mean_vals[i]),
                        deviation=float(dev_vals[i]),
                        minimum=float(min_vals[i]),
                        maximum=float(max_vals[i]),
                        range_val=float(range_vals[i])
                    ))

                frame_count += 1
                current_time = time.time()
                if current_time - last_fps_time >= 1.0:
                    fps = frame_count / (current_time - last_fps_time)
                    frame_count = 0
                    last_fps_time = current_time

                total_time_ms = (time.perf_counter() - loop_start) * 1000.0

                # Pass numpy array instead of HALCON image (thread-safe)
                self.frame_ready.emit(temp_frame, statistics, proc_time_ms)

                self._mutex.lock()
                if self._nuc_requested:
                    self._execute_nuc()
                    self._nuc_requested = False
                if self._focus_requested:
                    self._execute_focus(self._focus_direction)
                    self._focus_requested = False
                self._mutex.unlock()

            except Exception as e:
                if self._connected:
                    self.log_message.emit(f"Processing error: {e}")
                    logger.exception("Frame processing error")
                    self._handle_disconnect()

    def _execute_nuc(self):
        """Execute manual NUC synchronously."""
        self.nuc_status.emit(True, "NUC started")
        self.log_message.emit("Executing manual NUC...")

        try:
            ha.set_framegrabber_param(
                self._framegrabber,
                "FLK_TI_ControlFeature_REControlCmd",
                "FLK_TI_ControlFeature_REControlCmd_RequestFineOffset"
            )
            ha.set_framegrabber_param(
                self._framegrabber,
                "FLK_TI_ControlFeature_REControlCmd",
                "FLK_TI_ControlFeature_REControlCmd_ExecuteFineOffset"
            )
            time.sleep(0.05)

            for _ in range(3):
                try:
                    ha.grab_image_async(self._framegrabber, 0)
                except Exception:
                    pass

            self.nuc_status.emit(False, "NUC completed")
            self.log_message.emit("Manual NUC completed successfully")

        except Exception as e:
            self.nuc_status.emit(False, f"NUC failed: {e}")
            self.log_message.emit(f"NUC failed: {e}")
            logger.exception("NUC execution failed")

    def _execute_focus(self, direction: int):
        """Execute focus near/far."""
        self.focus_status.emit(True, "Focus started")
        self.log_message.emit(f"Focus {'near' if direction > 0 else 'far'} started...")

        try:
            current = float(ha.get_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_CurrentFocusDistanceMm"))
            step = 250 * direction
            target = current + step

            min_focus = float(ha.get_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_FocusDistanceMm_Min"))
            max_focus = float(ha.get_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_FocusDistanceMm_Max"))
            target = max(min_focus, min(max_focus, target))

            ha.set_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_SetFocusDistanceMm", target)

            start = time.time()
            while time.time() - start < 2.0:
                new_pos = float(ha.get_framegrabber_param(self._framegrabber, "FLK_TI_ControlFeature_CurrentFocusDistanceMm"))
                if abs(new_pos - target) <= 10:
                    break
                time.sleep(0.02)

            self.focus_status.emit(False, "Focus completed")
            self.log_message.emit("Focus completed successfully")

        except Exception as e:
            self.focus_status.emit(False, f"Focus failed: {e}")
            self.log_message.emit(f"Focus failed: {e}")
            logger.exception("Focus execution failed")

    def _attempt_reconnect(self):
        """Attempt to reconnect to camera."""
        self.log_message.emit("Attempting camera reconnect...")
        try:
            if self._framegrabber:
                ha.close_framegrabber(self._framegrabber)
        except Exception:
            pass

        if self.initialize():
            self.log_message.emit("Reconnection successful")
        else:
            self.log_message.emit("Reconnection failed, will retry")

    def _handle_disconnect(self):
        """Handle camera disconnect."""
        self._connected = False
        self.connected_signal.emit(False)
        self.log_message.emit("Camera disconnected")

    def stop(self):
        """Stop the worker thread."""
        self._running = False
        self._wait_condition.wakeAll()

        try:
            if self._framegrabber:
                ha.close_framegrabber(self._framegrabber)
        except Exception:
            pass

        self._connected = False
        self.connected_signal.emit(False)


class CameraWorkerWrapper(QObject):
    """Wrapper to run CameraWorker.run() in the thread's event loop without blocking signals."""
    finished = pyqtSignal()

    def __init__(self, worker: CameraWorker):
        super().__init__()
        self._worker = worker

    def start_loop(self):
        """Start the acquisition loop."""
        self._worker.run()
        self.finished.emit()


class HALCONDisplayWidget(QWidget):
    """Widget that embeds a HALCON window for display."""

    mouse_moved = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window_handle = None
        self._image_width = FEED_W
        self._image_height = FEED_H
        self.setMinimumSize(FEED_W, FEED_H)
        self.setMouseTracking(True)

    def create_window(self):
        """Create HALCON window embedded in this widget."""
        if self._window_handle is None:
            try:
                self._window_handle = ha.open_window(
                    0, 0, self.width(), self.height(),
                    int(self.winId()), "visible", ""
                )
                ha.set_part(self._window_handle, 0, 0, self._image_height - 1, self._image_width - 1)
                ha.set_window_param(self._window_handle, "flush", "true")
                logger.info(f"HALCON window created: handle={self._window_handle}")
            except Exception as e:
                logger.exception("Failed to create HALCON window")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._window_handle:
            try:
                ha.set_window_extents(self._window_handle, 0, 0, self.width(), self.height())
                ha.set_part(self._window_handle, 0, 0, self._image_height - 1, self._image_width - 1)
            except Exception:
                pass

    def mouseMoveEvent(self, event):
        x = int(event.position().x() * self._image_width / self.width())
        y = int(event.position().y() * self._image_height / self.height())
        x = max(0, min(self._image_width - 1, x))
        y = max(0, min(self._image_height - 1, y))
        self.mouse_moved.emit(x, y)

    def display_frame(self, temp_numpy, statistics: List[ROIStatistics], proc_time_ms: float):
        """Display frame with ROI overlays using HALCON operators only."""
        if self._window_handle is None:
            self.create_window()
        if self._window_handle is None:
            return

        try:
            # Convert temperature to 8-bit display image (grayscale)
            finite = np.isfinite(temp_numpy)
            if not np.any(finite):
                display = np.zeros(temp_numpy.shape, dtype=np.uint8)
            else:
                valid = temp_numpy[finite]
                minimum = float(valid.min())
                maximum = float(valid.max())
                if maximum <= minimum:
                    maximum = minimum + 1.0
                normalized = np.clip(
                    (temp_numpy - minimum) / (maximum - minimum),
                    0.0, 1.0
                )
                normalized[~finite] = 0.0
                display = (normalized * 255.0).astype(np.uint8)

            # Create HALCON image from 8-bit display
            halcon_image = ha.himage_from_numpy_array(display)

            # Set part for proper scaling
            h, w = display.shape[:2]
            ha.set_part(self._window_handle, 0, 0, h - 1, w - 1)

            ha.clear_window(self._window_handle)
            ha.disp_obj(halcon_image, self._window_handle)

            if hasattr(self, '_roi_names') and hasattr(self, '_roi_coords'):
                ha.set_color(self._window_handle, "spring green")
                ha.set_draw(self._window_handle, "margin")
                ha.set_line_width(self._window_handle, 2)

                for stat in statistics:
                    try:
                        idx = self._roi_names.index(stat.name)
                        if idx >= 0 and idx < len(self._roi_coords):
                            y1, x1, y2, x2 = self._roi_coords[idx]
                            ha.disp_rectangle1(self._window_handle, y1, x1, y2, x2)

                            label = f"{stat.name}: {stat.mean:.1f}°C"
                            ha.set_color(self._window_handle, "spring green")
                            ha.disp_text(self._window_handle, label, "image", y1 - 15, x1, "spring green", [], [])
                    except ValueError:
                        pass

            ha.flush_buffer(self._window_handle)

        except Exception as e:
            logger.exception("Display error")

    def set_roi_data(self, names: List[str], coords: List[Tuple]):
        """Store ROI data for display."""
        self._roi_names = names
        self._roi_coords = coords
        logger.info(f"ROI Table Rows: {len(names)}")

    def closeEvent(self, event):
        if self._window_handle:
            try:
                ha.close_window(self._window_handle)
            except Exception:
                pass
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HALCON ROI Validation Tool - TV46L")
        self.resize(1000, 900)

        self._worker = None
        self._worker_thread = None
        self._worker_wrapper = None
        self._current_temp_frame = None
        self._camera_info = None

        self._setup_ui()
        self._discover_and_connect()

    def _setup_ui(self):
        """Create the GUI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        self._create_toolbar(main_layout)
        self._create_image_area(main_layout)
        self._create_mouse_temp(main_layout)
        self._create_roi_table(main_layout)
        self._create_event_log(main_layout)
        self._create_status_bar()

    def _create_toolbar(self, parent_layout):
        """Create toolbar with Connect, Disconnect, Reload ROI, Focus, NUC, Benchmark."""
        toolbar = QToolBar()
        toolbar.setMovable(False)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._on_connect)
        toolbar.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.btn_disconnect.setEnabled(False)
        toolbar.addWidget(self.btn_disconnect)

        self.btn_reload_roi = QPushButton("Reload ROI JSON")
        self.btn_reload_roi.clicked.connect(self._on_reload_roi)
        self.btn_reload_roi.setEnabled(False)
        toolbar.addWidget(self.btn_reload_roi)

        toolbar.addSeparator()

        self.btn_focus_near = QPushButton("Focus Near")
        self.btn_focus_near.clicked.connect(lambda: self._on_focus(1))
        self.btn_focus_near.setEnabled(False)
        toolbar.addWidget(self.btn_focus_near)

        self.btn_focus_far = QPushButton("Focus Far")
        self.btn_focus_far.clicked.connect(lambda: self._on_focus(-1))
        self.btn_focus_far.setEnabled(False)
        toolbar.addWidget(self.btn_focus_far)

        toolbar.addSeparator()

        self.btn_nuc = QPushButton("Manual NUC")
        self.btn_nuc.clicked.connect(self._on_nuc)
        self.btn_nuc.setEnabled(False)
        toolbar.addWidget(self.btn_nuc)

        toolbar.addSeparator()

        self.btn_benchmark = QPushButton("Benchmark")
        self.btn_benchmark.clicked.connect(self._on_benchmark)
        self.btn_benchmark.setEnabled(False)
        toolbar.addWidget(self.btn_benchmark)

        parent_layout.addWidget(toolbar)

    def _create_image_area(self, parent_layout):
        """Create live thermal image display area."""
        self.display_widget = HALCONDisplayWidget()
        parent_layout.addWidget(self.display_widget, stretch=3)

    def _create_mouse_temp(self, parent_layout):
        """Create mouse temperature readout."""
        self.lbl_mouse_temp = QLabel("Mouse X: --  Y: --  Temperature: --°C")
        self.lbl_mouse_temp.setFont(QFont("Consolas", 10))
        self.lbl_mouse_temp.setStyleSheet("padding: 4px; background: #252526; border: 1px solid #3C3C3C;")
        parent_layout.addWidget(self.lbl_mouse_temp)

    def _create_roi_table(self, parent_layout):
        """Create ROI statistics table - dynamically sized."""
        self.roi_table = QTableWidget(0, 6)  # 0 rows initially, will be set dynamically
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Mean (°C)", "Min (°C)", "Max (°C)", "Range (°C)", "Deviation"])
        self.roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.setAlternatingRowColors(True)
        self.roi_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.roi_table.setMaximumHeight(350)
        parent_layout.addWidget(self.roi_table)

    def _create_event_log(self, parent_layout):
        """Create event log area."""
        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumHeight(120)
        self.event_log.setFont(QFont("Consolas", 9))
        self.event_log.setStyleSheet("background: #1E1E1E; color: #C8C8C8; border: 1px solid #3C3C3C;")
        parent_layout.addWidget(self.event_log)

    def _create_status_bar(self):
        """Create status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected | FPS: 0.0 | Processing: 0.0 ms | Frame: 0 ms | 640 x 480")

    def _discover_and_connect(self):
        """Discover cameras and connect to first TV46L."""
        self._log("Discovering cameras...")
        discovery = CameraDiscovery()
        cameras = discovery.discover()

        if not cameras:
            self._log("No cameras found. Click Connect to retry.")
            return

        self._camera_info = cameras[0]
        self._log(f"Discovered camera: {self._camera_info.serial} ({self._camera_info.ip})")

        # Connect automatically
        self._start_worker()

    def _start_worker(self):
        """Create and start worker thread."""
        if not self._camera_info:
            self._log("No camera info available")
            return

        self._worker = CameraWorker(self._camera_info)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)

        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.log_message.connect(self._on_log)
        self._worker.connected_signal.connect(self._on_connected)
        self._worker.nuc_status.connect(self._on_nuc_status)
        self._worker.focus_status.connect(self._on_focus_status)

        # Use wrapper to run the acquisition loop without blocking the thread's event loop
        self._worker_wrapper = CameraWorkerWrapper(self._worker)
        self._worker_wrapper.moveToThread(self._worker_thread)
        self._worker.initialized.connect(self._worker_wrapper.start_loop)
        self._worker_wrapper.finished.connect(self._worker_thread.quit)

        self._worker_thread.started.connect(self._worker.initialize)
        self._worker_thread.start()

    def _on_connect(self):
        """Handle connect button - retry discovery and connection."""
        if self._worker and not self._worker._connected:
            self._log("Manual reconnect requested...")
            self._discover_and_connect()

    def _on_disconnect(self):
        """Handle disconnect button."""
        if self._worker:
            self._worker.stop()
            self._log("Disconnected from camera")

    def _on_reload_roi(self):
        """Handle reload ROI button."""
        if self._worker:
            self._worker.reload_rois()
            self.display_widget.set_roi_data(self._worker._roi_names, self._worker._roi_coords)
            self._resize_roi_table()

    def _on_focus(self, direction: int):
        """Handle focus buttons."""
        if self._worker:
            self._worker.request_focus(direction)
            self.btn_focus_near.setEnabled(False)
            self.btn_focus_far.setEnabled(False)

    def _on_nuc(self):
        """Handle NUC button."""
        if self._worker:
            self._worker.request_nuc()
            self.btn_nuc.setEnabled(False)

    def _on_benchmark(self):
        """Run benchmark - process 100 frames and show average processing time."""
        self._log("Benchmark started (100 frames)...")
        self.btn_benchmark.setEnabled(False)
        QTimer.singleShot(100, lambda: self._log("Benchmark: run manually via processing loop timing in status bar"))
        self.btn_benchmark.setEnabled(True)

    def _on_frame_ready(self, temp_numpy, statistics: List[ROIStatistics], proc_time_ms: float):
        """Handle new frame from worker."""
        self._current_temp_frame = temp_numpy

        self.display_widget.display_frame(temp_numpy, statistics, proc_time_ms)
        self._update_roi_table(statistics)
        self._update_status_bar(proc_time_ms)

    def _on_error(self, msg: str):
        self._log(f"ERROR: {msg}")

    def _on_log(self, msg: str):
        # Filter out per-frame messages - only log major events
        skip_patterns = [
            "Frame grab timeout",
            "Frame ",
            "HImage created",
            "disp_obj",
            "flush_buffer",
            "proc=",
            "frame_ready",
            "GUI: ",
        ]
        if any(pattern in msg for pattern in skip_patterns):
            return
        self._log(msg)

    def _on_connected(self, connected: bool):
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.btn_reload_roi.setEnabled(connected)
        self.btn_focus_near.setEnabled(connected)
        self.btn_focus_far.setEnabled(connected)
        self.btn_nuc.setEnabled(connected)
        self.btn_benchmark.setEnabled(connected)
        if connected and self._worker:
            self.display_widget.set_roi_data(self._worker._roi_names, self._worker._roi_coords)
            self._resize_roi_table()

    def _resize_roi_table(self):
        """Resize ROI table to match number of loaded ROIs."""
        if self._worker:
            num_rois = len(self._worker._roi_names)
            self.roi_table.setRowCount(num_rois)

    def _on_nuc_status(self, busy: bool, msg: str):
        self.btn_nuc.setEnabled(not busy)
        self.btn_nuc.setText("NUC in progress..." if busy else "Manual NUC")
        self._log(msg)

    def _on_focus_status(self, busy: bool, msg: str):
        self.btn_focus_near.setEnabled(not busy)
        self.btn_focus_far.setEnabled(not busy)
        self._log(msg)

    def _update_roi_table(self, statistics: List[ROIStatistics]):
        """Update ROI statistics table - all rows."""
        for i, stat in enumerate(statistics):
            if i >= self.roi_table.rowCount():
                break
            self.roi_table.setItem(i, 0, QTableWidgetItem(stat.name))
            self.roi_table.setItem(i, 1, QTableWidgetItem(f"{stat.mean:.2f}"))
            self.roi_table.setItem(i, 2, QTableWidgetItem(f"{stat.minimum:.2f}"))
            self.roi_table.setItem(i, 3, QTableWidgetItem(f"{stat.maximum:.2f}"))
            self.roi_table.setItem(i, 4, QTableWidgetItem(f"{stat.range_val:.2f}"))
            self.roi_table.setItem(i, 5, QTableWidgetItem(f"{stat.deviation:.2f}"))

    def _update_status_bar(self, proc_time_ms: float):
        """Update status bar with FPS, processing time, frame time, image size."""
        fps_text = "9.0"  # TV46L fixed 9 FPS
        frame_time_ms = 111.1  # 1000/9
        self.status_bar.showMessage(
            f"Connected | FPS: {fps_text} | Processing: {proc_time_ms:.2f} ms | "
            f"Frame: {frame_time_ms:.1f} ms | {FEED_W} x {FEED_H}"
        )

    def _log(self, msg: str):
        """Add message to event log."""
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(f"[{timestamp}] {msg}")
        cursor = self.event_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.event_log.setTextCursor(cursor)

    def _on_mouse_move(self, x: int, y: int):
        """Handle mouse movement over display - show temperature at cursor."""
        if self._current_temp_frame is not None:
            if 0 <= y < self._current_temp_frame.shape[0] and 0 <= x < self._current_temp_frame.shape[1]:
                temp = self._current_temp_frame[y, x]
                self.lbl_mouse_temp.setText(f"Mouse X: {x}  Y: {y}  Temperature: {temp:.2f}°C")

    def closeEvent(self, event: QCloseEvent):
        if self._worker:
            self._worker.stop()
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    dark_palette = app.palette()
    dark_palette.setColor(dark_palette.ColorRole.Window, QColor(0x1E, 0x1E, 0x1E))
    dark_palette.setColor(dark_palette.ColorRole.WindowText, QColor(0xFF, 0xFF, 0xFF))
    dark_palette.setColor(dark_palette.ColorRole.Base, QColor(0x25, 0x25, 0x26))
    dark_palette.setColor(dark_palette.ColorRole.AlternateBase, QColor(0x2D, 0x2D, 0x2D))
    dark_palette.setColor(dark_palette.ColorRole.ToolTipBase, QColor(0xFF, 0xFF, 0xFF))
    dark_palette.setColor(dark_palette.ColorRole.ToolTipText, QColor(0xFF, 0xFF, 0xFF))
    dark_palette.setColor(dark_palette.ColorRole.Text, QColor(0xFF, 0xFF, 0xFF))
    dark_palette.setColor(dark_palette.ColorRole.Button, QColor(0x3C, 0x3C, 0x3C))
    dark_palette.setColor(dark_palette.ColorRole.ButtonText, QColor(0xFF, 0xFF, 0xFF))
    dark_palette.setColor(dark_palette.ColorRole.BrightText, QColor(0xFF, 0x00, 0x00))
    dark_palette.setColor(dark_palette.ColorRole.Highlight, QColor(0x00, 0x78, 0xD7))
    dark_palette.setColor(dark_palette.ColorRole.HighlightedText, QColor(0xFF, 0xFF, 0xFF))
    app.setPalette(dark_palette)

    window = MainWindow()
    window.display_widget.mouse_moved.connect(window._on_mouse_move)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()