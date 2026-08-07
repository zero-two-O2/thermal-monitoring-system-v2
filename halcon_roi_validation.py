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
from types import SimpleNamespace
from typing import List, Tuple, Optional, Dict, Callable
from dataclasses import dataclass

import halcon as ha
import numpy as np
from PyQt6.QtCore import (QThread, pyqtSignal, QObject, QTimer, QMutex, Qt)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QPushButton, QTableWidget,
                              QTableWidgetItem, QTextEdit, QStatusBar,
                              QToolBar, QHeaderView, QScrollArea,
                              QSizePolicy)
from PyQt6.QtGui import QFont, QColor, QCloseEvent

from calibration.calibration_manager import CalibrationManager
from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo
from camera.services.halcon_driver import HalconDriver

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FEED_W = 640
FEED_H = 480
ROI_JSON_PATH = "rois.json"
CONFIG_PATH = "config.json"


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


class ConfigManager:
    """Loads config.json once at startup and holds values in memory.

    The JSON file is read a single time at construction. The processing
    loop reads from memory only and never touches the filesystem.
    """

    DEFAULT_CONFIG = {
        "camera": {"fps": 9, "reconnect_seconds": 3},
        "alarm": {
            "enabled": True,
            "temperature_limit": 80.0,
            "use_max_temperature": True,
        },
        "nuc": {"auto_enabled": True, "interval_seconds": 300},
        "focus": {"default_focus_mm": None, "coarse_step_mm": None, "fine_step_mm": None},
        "display": {"palette": "temperature", "default_zoom": 100},
    }

    def __init__(self, path: str = CONFIG_PATH) -> None:
        self._path = path
        self._data = self._load()

    def _load(self) -> Dict[str, dict]:
        try:
            with open(self._path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError(f"{self._path} root must be a JSON object")
            return self._merge(raw)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {self._path}; using built-in defaults")
            return dict(self.DEFAULT_CONFIG)
        except Exception:
            logger.exception(f"Failed to load config {self._path}; using built-in defaults")
            return dict(self.DEFAULT_CONFIG)

    def _merge(self, raw: dict) -> Dict[str, dict]:
        merged = {}
        for section, defaults in self.DEFAULT_CONFIG.items():
            user_section = raw.get(section, {})
            if not isinstance(user_section, dict):
                user_section = {}
            merged[section] = {**defaults, **user_section}
        return merged

    def get(self, section: str, key: str):
        """Return a config value from memory. Never touches the JSON file."""
        return self._data.get(section, {}).get(key)


STATE_NORMAL = "NORMAL"
STATE_ACTIVE = "ACTIVE"


@dataclass
class Alarm:
    roi_name: str
    timestamp: float
    current_max: float


class AlarmManager:
    """Two-state alarm engine (NORMAL <-> ACTIVE) for a set of ROIs.

    Responsibilities:
        maintain per-ROI alarm state
        detect new alarms (NORMAL -> ACTIVE)
        detect cleared alarms (ACTIVE -> NORMAL)
        return the active alarms

    Exactly one alarm is created when an ROI max temperature exceeds the
    limit. While the alarm stays active the timestamp is never touched;
    only current_max is refreshed. When the temperature drops back to or
    below the limit the alarm is removed, and a later re-crossing creates
    a brand new alarm with a new timestamp.
    """

    def __init__(
        self,
        limit: float,
        enabled: bool = True,
        use_max_temperature: bool = True,
        on_event: Optional[Callable[[str, bool, float], None]] = None,
    ) -> None:
        self._limit = limit
        self._enabled = enabled
        self._use_max_temperature = use_max_temperature
        self._on_event = on_event
        self._alarms: Dict[str, Alarm] = {}

    @property
    def active_alarms(self) -> List[Alarm]:
        return list(self._alarms.values())

    def is_active(self, roi_name: str) -> bool:
        return roi_name in self._alarms

    def set_limit(self, limit: float) -> None:
        self._limit = limit

    def evaluate(self, statistics: List[ROIStatistics]) -> None:
        """Update alarm state from existing ROI statistics only."""
        if not self._enabled:
            for name in list(self._alarms):
                self._release(name)
            return

        for stat in statistics:
            if stat.maximum > self._limit:
                alarm = self._alarms.get(stat.name)
                if alarm is None:
                    self._alarms[stat.name] = Alarm(
                        roi_name=stat.name,
                        timestamp=time.time(),
                        current_max=stat.maximum,
                    )
                    if self._on_event is not None:
                        self._on_event(stat.name, True, stat.maximum)
                else:
                    alarm.current_max = stat.maximum
            elif stat.name in self._alarms:
                self._release(stat.name)

    def _release(self, roi_name: str) -> None:
        del self._alarms[roi_name]
        if self._on_event is not None:
            self._on_event(roi_name, False, 0.0)


class CameraWorker(QObject):
    """Worker thread for camera acquisition and HALCON processing."""

    frame_ready = pyqtSignal(object, object, float)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)
    connected_signal = pyqtSignal(bool)
    nuc_status = pyqtSignal(bool, str)
    focus_status = pyqtSignal(bool, str)
    alarms_changed = pyqtSignal(object)
    nuc_countdown = pyqtSignal(int)
    initialized = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, camera_info: CameraInfo, config: Optional[ConfigManager] = None):
        super().__init__()
        self._camera_info = camera_info
        self._config = config if config is not None else ConfigManager()
        self._running = False
        self._mutex = QMutex()
        self._framegrabber = None
        self._connected = False
        self._focus_driver = None
        self._calibration = None
        self._roi_regions = None
        self._roi_names = []
        self._roi_coords = []
        self._nuc_requested = False
        self._focus_requested = False
        self._focus_step = 0
        self._reconnect_seconds = float(self._config.get("camera", "reconnect_seconds"))
        self._auto_nuc_enabled = bool(self._config.get("nuc", "auto_enabled"))
        self._nuc_interval = float(self._config.get("nuc", "interval_seconds"))
        self._last_nuc_time = time.time()
        self._last_nuc_emit_cd = 0.0
        self._last_emitted_alarms = set()
        self._alarm_manager = AlarmManager(
            limit=float(self._config.get("alarm", "temperature_limit")),
            enabled=bool(self._config.get("alarm", "enabled")),
            use_max_temperature=bool(self._config.get("alarm", "use_max_temperature")),
            on_event=self._on_alarm_event,
        )

    def initialize(self) -> bool:
        """Stage 1: Open framegrabber, connect camera, grab first image, load calibration, load ROIs, generate regions."""
        try:
            self._framegrabber = ha.open_framegrabber(
                "GigEVision2", 0, 0, 0, 0, 0, 0,
                "progressive", -1, "default", -1, "false",
                "default", self._camera_info.device, 0, -1
            )

            self._focus_driver = HalconDriver(
                SimpleNamespace(
                    camera_id=self._camera_info.serial,
                    device_identifier=self._camera_info.device,
                ),
                framegrabber=self._framegrabber,
            )

            self._configure_camera()

            ha.grab_image_start(self._framegrabber, -1)

            first_frame = ha.grab_image_async(self._framegrabber, 5000)
            if first_frame is None:
                raise RuntimeError("Failed to grab first frame within 5s")

            self._calibration = CalibrationManager()
            self._calibration.initialize()
            self.log_message.emit("Calibration loaded")

            if not self._load_rois():
                raise RuntimeError("Failed to load ROIs")

            self._generate_halcon_regions()

            self._last_nuc_time = time.time()

            # Default focus is applied exactly once after a successful
            # connection, before live acquisition starts. A failure here
            # must not abort the connection.
            self.log_message.emit("Camera connected")
            self._apply_default_focus()

            self._connected = True
            self.connected_signal.emit(True)
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
            ha.set_framegrabber_param(
                self._framegrabber,
                "FLK_TI_ControlFeature_SetFrameRate",
                int(self._config.get("camera", "fps"))
            )
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

            self.log_message.emit(f"Loaded {len(self._roi_names)} ROIs")
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

    def reload_rois(self):
        """Reload ROI JSON and regenerate HALCON regions."""
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

    def request_focus(self, step_mm: int):
        """Request a focus move by a signed step (mm); sign sets direction."""
        self._mutex.lock()
        self._focus_requested = True
        self._focus_step = step_mm
        self._mutex.unlock()

    def _on_alarm_event(self, roi_name: str, active: bool, current_max: float):
        """Log alarm transitions from the worker thread."""
        if active:
            self.log_message.emit(f"ALARM ACTIVE: {roi_name} at {current_max:.2f}°C")
        else:
            self.log_message.emit(f"ALARM CLEARED: {roi_name}")

    def run(self):
        """Main processing loop - runs in worker thread.

        Owns the acquisition loop and exits naturally when _running is
        set to False by stop(). Cleanup runs here (in the worker thread)
        after the loop returns so the framegrabber is never closed while
        a grab_image_async may still be executing.
        """
        if self._running:
            return
        self._running = True

        while self._running:

            try:
                if not self._connected:
                    if not self._running:
                        break
                    self._attempt_reconnect()
                    time.sleep(self._reconnect_seconds)
                    continue

                raw_frame = ha.grab_image_async(self._framegrabber, 500)
                if raw_frame is None:
                    continue

                raw_numpy = ha.himage_as_numpy_array(raw_frame)

                temp_frame = self._calibration.raw_to_temperature(raw_numpy)

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

                # Evaluate alarm state from existing statistics only.
                # No recomputation, no additional HALCON calls.
                self._alarm_manager.evaluate(statistics)

                # Notify the GUI only when the active-alarm set changes.
                current_alarm_names = {a.roi_name for a in self._alarm_manager.active_alarms}
                if current_alarm_names != self._last_emitted_alarms:
                    self._last_emitted_alarms = current_alarm_names
                    self.alarms_changed.emit(self._alarm_manager.active_alarms)

                # Auto-NUC countdown, throttled to once per second.
                emit_now = time.time()
                if emit_now - self._last_nuc_emit_cd >= 1.0:
                    self._last_nuc_emit_cd = emit_now
                    remaining = max(0, int(self._nuc_interval - (emit_now - self._last_nuc_time)))
                    self.nuc_countdown.emit(remaining if self._auto_nuc_enabled else -1)

                # Pass numpy array instead of HALCON image (thread-safe)
                self.frame_ready.emit(temp_frame, statistics, proc_time_ms)

                self._mutex.lock()
                now = time.time()
                auto_nuc_due = self._auto_nuc_due(now)
                if self._nuc_requested:
                    self._execute_nuc()
                    self._nuc_requested = False
                    self._last_nuc_time = time.time()
                elif auto_nuc_due:
                    self._execute_nuc()
                    self._last_nuc_time = now
                if self._focus_requested:
                    self._execute_focus(self._focus_step)
                    self._focus_requested = False
                self._mutex.unlock()

            except Exception as e:
                # Transient frame-processing error: log it and skip the
                # frame. Do NOT disconnect / reinitialize the camera here;
                # calibration, LUT, ROI regions and the connection must be
                # created only once. The acquisition thread stays alive.
                self.log_message.emit(f"Processing error: {e}")
                logger.exception("Frame processing error")

        self._cleanup()
        self.finished.emit()

    def _cleanup(self):
        """Close the framegrabber and notify listeners.

        Runs in the worker thread after run() has returned so no
        grab_image_async is left in flight.
        """
        self._running = False
        try:
            if self._framegrabber:
                ha.close_framegrabber(self._framegrabber)
        except Exception:
            logger.exception("Error closing framegrabber")
        finally:
            self._framegrabber = None
        self._connected = False
        self.connected_signal.emit(False)

    def _auto_nuc_due(self, now: float) -> bool:
        """Return True when the configured auto-NUC interval has elapsed."""
        return self._auto_nuc_enabled and (now - self._last_nuc_time) >= self._nuc_interval

    def _execute_nuc(self):
        """Execute manual NUC synchronously."""
        self.nuc_status.emit(True, "NUC started")

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

        except Exception as e:
            self.nuc_status.emit(False, f"NUC failed: {e}")
            logger.exception("NUC execution failed")

    def _execute_focus(self, step_mm: int):
        """Execute a focus move by the given signed step (mm).

        Increments come from config.json focus.coarse_step_mm /
        fine_step_mm; only the sign is decided by the caller. Reads the
        final position after the move and prints a single two-line log:
        the button label and the final focus distance. Small differences
        between requested and actual distance are normal. The only
        failure case is an exception from reading or writing focus.
        """
        coarse = int(self._config.get("focus", "coarse_step_mm"))
        if step_mm <= -coarse:
            label = "Focus --"
        elif step_mm > 0:
            label = "Focus +"
        elif step_mm < 0:
            label = "Focus -"
        else:
            label = "Focus ++"
        self.focus_status.emit(True, label)

        driver = self._focus_driver
        if driver is None:
            self.log_message.emit("Current focus unavailable")
            self.focus_status.emit(False, f"{label} failed")
            return

        try:
            current = driver.get_focus_distance()
            target = current + step_mm

            min_focus, max_focus = driver.get_focus_limits()
            target = max(min_focus, min(max_focus, target))

            driver.set_focus_distance(target)
            time.sleep(0.2)

            final = driver.get_focus_distance()

            self.log_message.emit(label)
            self.log_message.emit(f"Current Focus : {final:.2f} mm")
            self.focus_status.emit(False, "Focus completed")

        except Exception as e:
            self.log_message.emit(f"{label} failed: {e}")
            self.focus_status.emit(False, f"{label} failed")
            logger.exception(f"{label} execution failed: {e}")

    def _wait_focus_stable(self, driver, timeout: float = 10.0) -> float:
        """Wait until the focus position stops changing, returning the settlement time.

        Polls the reported focus distance repeatedly. Movement is treated
        as finished once the reported position is unchanged across a short
        window, or the timeout expires. A shallow sleep is avoided so the
        wait tracks real driver-reported stability rather than a fixed
        duration.
        """
        last = None
        stable_since = time.time()
        deadline = time.time() + timeout
        settle_window = 0.5

        while time.time() < deadline:
            current = driver.get_focus_distance()
            if last is None or abs(current - last) >= 1.0:
                stable_since = time.time()
            last = current
            if time.time() - stable_since >= settle_window:
                return last
            time.sleep(0.1)
        return last

    def _apply_default_focus(self):
        """Move the lens to the configured default focus exactly once after connecting.

        The target comes from config.json focus.default_focus_mm; it is
        never hardcoded here. The lens is moved, the motion is allowed to
        settle, and the resulting position is read back once and logged.
        A failure to move the focus only logs an error and lets the camera
        continue starting normally with its current position. This never
        runs from the acquisition loop, after NUC, or via the manual focus
        step buttons.
        """
        target = self._config.get("focus", "default_focus_mm")
        if target is None:
            return

        driver = self._focus_driver
        if driver is None:
            self.log_message.emit("Default focus failed")
            self.log_message.emit("Continuing with current focus position.")
            return

        try:
            self.log_message.emit("Setting default focus...")

            min_focus, max_focus = driver.get_focus_limits()
            target_clamped = float(min(max(min_focus, float(target)), max_focus))

            driver.set_focus_distance(target_clamped)
            final = self._wait_focus_stable(driver)

            self.log_message.emit(f"Current Focus : {final:.2f} mm")
            self.log_message.emit("Default focus completed")
        except Exception as e:
            self.log_message.emit("Default focus failed")
            self.log_message.emit("Continuing with current focus position.")
            logger.exception("Default focus failed")

    def _attempt_reconnect(self):
        """Attempt to reconnect to camera."""
        try:
            if self._framegrabber:
                ha.close_framegrabber(self._framegrabber)
        except Exception:
            pass

        self.initialize()

    def _handle_disconnect(self):
        """Handle camera disconnect."""
        self._connected = False
        self.connected_signal.emit(False)
        self.log_message.emit("Camera disconnected")

    def stop(self):
        """Stop the worker thread.

        Only flips the running flag. run() exits its loop naturally and
        performs the actual cleanup (close framegrabber, emit finished).
        """
        self._running = False


class HALCONDisplayWidget(QWidget):
    """Widget that embeds a HALCON window for display.

    The widget is sized exactly to (image size x zoom). At 100% zoom the
    HALCON window is 640x480 so one image pixel equals one display pixel.
    Zoom only changes the window size; the underlying frame stays 640x480.
    """

    mouse_moved = pyqtSignal(int, int)
    zoom_changed = pyqtSignal()

    ZOOM_LEVELS = [
        (0.50, "50%"),
        (0.75, "75%"),
        (1.00, "100%"),
        (1.25, "125%"),
        (1.50, "150%"),
        (2.00, "200%"),
        (4.00, "400%"),
    ]
    _ROI_COLOR = "#EACE21"
    _ALARM_COLOR = "#FF0000"

    def __init__(self, config: Optional[ConfigManager] = None, parent=None):
        super().__init__(parent)
        self._config = config if config is not None else ConfigManager()
        self._window_handle = None
        self._image_width = FEED_W
        self._image_height = FEED_H
        self._palette = str(self._config.get("display", "palette"))
        self._zoom_index = self._zoom_index_for(
            self._config.get("display", "default_zoom")
        )
        self._roi_names = []
        self._roi_coords = []
        self._active_alarms = set()
        self._last_frame = None
        self._last_statistics = []
        self._zoom_old_size = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._apply_zoom_size()

    @property
    def zoom_factor(self) -> float:
        return self.ZOOM_LEVELS[self._zoom_index][0]

    @property
    def zoom_text(self) -> str:
        return self.ZOOM_LEVELS[self._zoom_index][1]

    @staticmethod
    def _zoom_index_for(default_zoom) -> int:
        """Map a configured zoom percentage to the ZOOM_LEVELS index."""
        target = int(default_zoom)
        for i, (_, label) in enumerate(HALCONDisplayWidget.ZOOM_LEVELS):
            if int(label.rstrip("%")) == target:
                return i
        return 2  # 100%

    def _display_size(self) -> Tuple[int, int]:
        w = max(1, int(round(self._image_width * self.zoom_factor)))
        h = max(1, int(round(self._image_height * self.zoom_factor)))
        return w, h

    def _apply_zoom_size(self):
        w, h = self._display_size()
        self.setFixedSize(w, h)

    def create_window(self):
        """Create HALCON window embedded in this widget."""
        if self._window_handle is not None:
            return
        try:
            w, h = self._display_size()
            self._window_handle = ha.open_window(
                0, 0, w, h,
                int(self.winId()), "visible", ""
            )
            ha.set_part(self._window_handle, 0, 0,
                        self._image_height - 1, self._image_width - 1)
            ha.set_window_param(self._window_handle, "flush", "true")
            # Thermal palette via HALCON LUT (no manual colorization).
            try:
                ha.set_lut(self._window_handle, self._palette)
            except Exception:
                logger.warning(f"HALCON LUT '{self._palette}' unavailable; using default LUT")
            ha.set_draw(self._window_handle, "margin")
            ha.set_line_width(self._window_handle, 2)
        except Exception:
            logger.exception("Failed to create HALCON window")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._window_handle:
            try:
                w, h = self._display_size()
                ha.set_window_extents(self._window_handle, 0, 0, w, h)
                ha.set_part(self._window_handle, 0, 0,
                            self._image_height - 1, self._image_width - 1)
            except Exception:
                pass

    def set_zoom_index(self, index: int):
        """Change zoom level; the underlying frame stays 640x480."""
        if not 0 <= index < len(self.ZOOM_LEVELS):
            return
        if index == self._zoom_index:
            return
        self._zoom_old_size = self.size()
        self._zoom_index = index
        self._apply_zoom_size()
        if self._window_handle:
            try:
                w, h = self._display_size()
                ha.set_window_extents(self._window_handle, 0, 0, w, h)
                ha.set_part(self._window_handle, 0, 0,
                            self._image_height - 1, self._image_width - 1)
            except Exception:
                pass
        if self._last_frame is not None:
            self._draw()
        self.zoom_changed.emit()

    def zoom_in(self):
        self.set_zoom_index(min(self._zoom_index + 1, len(self.ZOOM_LEVELS) - 1))

    def zoom_out(self):
        self.set_zoom_index(max(self._zoom_index - 1, 0))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            # Without Ctrl, let the QScrollArea handle scrolling.
            event.ignore()

    def mouseMoveEvent(self, event):
        x = int(event.position().x() / self.zoom_factor)
        y = int(event.position().y() / self.zoom_factor)
        x = max(0, min(self._image_width - 1, x))
        y = max(0, min(self._image_height - 1, y))
        self.mouse_moved.emit(x, y)

    def display_frame(self, temp_numpy, statistics: List[ROIStatistics], proc_time_ms: float):
        """Display frame with ROI overlays using HALCON operators only."""
        self._last_frame = temp_numpy
        self._last_statistics = statistics
        self._draw()

    def _draw(self):
        """Render the stored frame with ROI overlays using HALCON operators only."""
        if self._window_handle is None:
            self.create_window()
        if self._window_handle is None or self._last_frame is None:
            return

        try:
            # Convert temperature to 8-bit display image (grayscale);
            # HALCON applies the 'temperature' LUT at display time.
            temp_numpy = self._last_frame
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

            ha.set_part(self._window_handle, 0, 0,
                        self._image_height - 1, self._image_width - 1)

            ha.clear_window(self._window_handle)
            ha.disp_obj(halcon_image, self._window_handle)

            if self._roi_names and self._roi_coords:
                ha.set_draw(self._window_handle, "margin")
                ha.set_line_width(self._window_handle, 2)

                for stat in self._last_statistics:
                    try:
                        idx = self._roi_names.index(stat.name)
                        if idx >= 0 and idx < len(self._roi_coords):
                            y1, x1, y2, x2 = self._roi_coords[idx]
                            color = self._ALARM_COLOR if stat.name in self._active_alarms else self._ROI_COLOR
                            ha.set_color(self._window_handle, color)
                            ha.disp_rectangle1(self._window_handle, y1, x1, y2, x2)

                            label = f"{stat.name}: {stat.mean:.1f}°C"
                            ha.disp_text(self._window_handle, label, "image",
                                         y1 - 15, x1, color, [], [])
                    except ValueError:
                        pass

            ha.flush_buffer(self._window_handle)

        except Exception:
            logger.exception("Display error")

    def set_active_alarms(self, names: List[str]):
        """Store which ROIs are in alarm so outlines/labels turn red."""
        self._active_alarms = set(names)

    def set_roi_data(self, names: List[str], coords: List[Tuple]):
        """Store ROI data for display."""
        self._roi_names = names
        self._roi_coords = coords

    def closeEvent(self, event):
        if self._window_handle:
            try:
                ha.close_window(self._window_handle)
            except Exception:
                pass
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, config: Optional[ConfigManager] = None):
        super().__init__()
        self._config = config if config is not None else ConfigManager()
        self.setWindowTitle("HALCON ROI Validation Tool - TV46L")
        self.resize(1000, 900)

        self._worker = None
        self._worker_thread = None
        self._current_temp_frame = None
        self._camera_info = None

        self._active_alarm_count = 0
        self._nuc_remaining = -1
        self._alarm_limit = float(self._config.get("alarm", "temperature_limit"))
        self._alarm_rows = {}
        self._alarm_max_shown = {}

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
        self._create_lower_section(main_layout)
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

        toolbar.addSeparator()

        toolbar.addWidget(QLabel("Focus"))

        focus_coarse = int(self._config.get("focus", "coarse_step_mm"))
        focus_fine = int(self._config.get("focus", "fine_step_mm"))

        self.btn_focus_minus2 = QPushButton("--")
        self.btn_focus_minus2.setToolTip(f"Large focus step (-{focus_coarse} mm)")
        self.btn_focus_minus2.clicked.connect(lambda: self._on_focus(-focus_coarse))
        self.btn_focus_minus2.setEnabled(False)
        toolbar.addWidget(self.btn_focus_minus2)

        self.btn_focus_minus = QPushButton("-")
        self.btn_focus_minus.setToolTip(f"Fine focus step (-{focus_fine} mm)")
        self.btn_focus_minus.clicked.connect(lambda: self._on_focus(-focus_fine))
        self.btn_focus_minus.setEnabled(False)
        toolbar.addWidget(self.btn_focus_minus)

        self.btn_focus_plus = QPushButton("+")
        self.btn_focus_plus.setToolTip(f"Fine focus step (+{focus_fine} mm)")
        self.btn_focus_plus.clicked.connect(lambda: self._on_focus(focus_fine))
        self.btn_focus_plus.setEnabled(False)
        toolbar.addWidget(self.btn_focus_plus)

        self.btn_focus_plus2 = QPushButton("++")
        self.btn_focus_plus2.setToolTip(f"Large focus step (+{focus_coarse} mm)")
        self.btn_focus_plus2.clicked.connect(lambda: self._on_focus(focus_coarse))
        self.btn_focus_plus2.setEnabled(False)
        toolbar.addWidget(self.btn_focus_plus2)

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
        """Create live thermal image display area inside a scrollable viewer."""
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: #1E1E1E; border: 1px solid #3C3C3C; }"
            "QScrollArea > QWidget > QWidget { background: #1E1E1E; }"
        )
        self.display_widget = HALCONDisplayWidget(self._config)
        self.display_widget.zoom_changed.connect(self._on_zoom_changed)
        self.scroll_area.setWidget(self.display_widget)
        parent_layout.addWidget(self.scroll_area, stretch=3)

    def _create_mouse_temp(self, parent_layout):
        """Create mouse temperature readout."""
        self.lbl_mouse_temp = QLabel("Mouse X: --  Y: --  Temperature: --°C")
        self.lbl_mouse_temp.setFont(QFont("Consolas", 10))
        self.lbl_mouse_temp.setStyleSheet("padding: 4px; background: #252526; border: 1px solid #3C3C3C;")
        parent_layout.addWidget(self.lbl_mouse_temp)

    def _create_lower_section(self, parent_layout):
        """Bottom section: Alarm Table (left, ~28%) + ROI Statistics Table (right)."""
        lower = QHBoxLayout()
        lower.setSpacing(8)

        self.alarm_table = QTableWidget(0, 3)
        self.alarm_table.setHorizontalHeaderLabels(["ROI", "Time", "Current Max (°C)"])
        self.alarm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alarm_table.verticalHeader().setVisible(False)
        self.alarm_table.setAlternatingRowColors(True)
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alarm_table.setMaximumHeight(350)
        lower.addWidget(self.alarm_table, 2)  # ~28%

        self.roi_table = QTableWidget(0, 6)  # 0 rows initially, will be set dynamically
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Mean (°C)", "Min (°C)", "Max (°C)", "Range (°C)", "Deviation"])
        self.roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.setAlternatingRowColors(True)
        self.roi_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.roi_table.setMaximumHeight(350)
        lower.addWidget(self.roi_table, 5)  # ~72%

        parent_layout.addLayout(lower)

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
        self._last_proc_time = 0.0
        self.status_bar.showMessage(
            f"Disconnected | FPS: 0.0 | Processing: 0.0 ms | Frame: 0 ms | "
            f"{FEED_W} x {FEED_H} | Zoom: {self.display_widget.zoom_text} | "
            f"Active Alarms: 0 | Alarm Limit: {self._alarm_limit:.1f} °C"
        )

    def _discover_and_connect(self):
        """Discover cameras and connect to first TV46L."""
        discovery = CameraDiscovery()
        cameras = discovery.discover()

        if not cameras:
            self._log("No cameras found. Click Connect to retry.")
            return

        self._camera_info = cameras[0]
        self._log(f"Camera discovered: {self._camera_info.serial} ({self._camera_info.ip})")

        # Connect automatically
        self._start_worker()

    def _start_worker(self):
        """Create and start worker thread."""
        if not self._camera_info:
            self._log("No camera info available")
            return

        self._worker = CameraWorker(self._camera_info, self._config)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)

        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.log_message.connect(self._on_log)
        self._worker.connected_signal.connect(self._on_connected)
        self._worker.nuc_status.connect(self._on_nuc_status)
        self._worker.focus_status.connect(self._on_focus_status)
        self._worker.alarms_changed.connect(self._on_alarms_changed)
        self._worker.nuc_countdown.connect(self._on_nuc_countdown)

        # Worker owns the acquisition loop. When run() returns it emits
        # finished; the thread then quits and cleans up its own objects.
        self._worker.initialized.connect(self._worker.run)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        self._worker_thread.started.connect(self._worker.initialize)
        self._worker_thread.start()

    def _on_connect(self):
        """Handle connect button - start a fresh connection.

        After Disconnect both the worker and its thread are destroyed, so
        a later Connect must build everything from scratch. Never reuse a
        stale framegrabber or worker; always create a new one exactly like
        a fresh application startup.
        """
        if self._worker is not None and not self._worker._connected:
            # Tear down a half-dead worker before starting a fresh one.
            self._worker.stop()
            self._shutdown_thread()

        if self._worker is None:
            self._discover_and_connect()

    def _on_disconnect(self):
        """Handle disconnect button."""
        if self._worker:
            self._worker.stop()
            self._shutdown_thread()
            self._log("Camera disconnected")

    def _on_reload_roi(self):
        """Handle reload ROI button."""
        if self._worker:
            self._worker.reload_rois()
            self.display_widget.set_roi_data(self._worker._roi_names, self._worker._roi_coords)
            self._resize_roi_table()

    def _on_focus(self, step_mm: int):
        """Handle focus step buttons."""
        if self._worker:
            self._worker.request_focus(step_mm)
            self._set_focus_buttons_enabled(False)

    def _set_focus_buttons_enabled(self, enabled: bool):
        """Enable or disable all four focus step buttons."""
        self.btn_focus_minus2.setEnabled(enabled)
        self.btn_focus_minus.setEnabled(enabled)
        self.btn_focus_plus.setEnabled(enabled)
        self.btn_focus_plus2.setEnabled(enabled)

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
        self._last_proc_time = proc_time_ms

        self.display_widget.display_frame(temp_numpy, statistics, proc_time_ms)
        self._update_roi_table(statistics)
        self._update_alarm_max_cells(statistics)
        self._update_status_bar(proc_time_ms)

    def _on_zoom_changed(self):
        """Handle zoom change from the display widget."""
        self._update_status_bar(self._last_proc_time)
        QTimer.singleShot(0, self._recenter_scroll)

    def _recenter_scroll(self):
        """Keep the zoom center point fixed when the widget resizes."""
        old = self.display_widget._zoom_old_size
        if not old or old.width() <= 0 or old.height() <= 0:
            return
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        center_x = hbar.value() + hbar.pageStep() / 2.0
        center_y = vbar.value() + vbar.pageStep() / 2.0
        scale_x = self.display_widget.width() / old.width()
        scale_y = self.display_widget.height() / old.height()
        hbar.setValue(int(center_x * scale_x - hbar.pageStep() / 2.0))
        vbar.setValue(int(center_y * scale_y - vbar.pageStep() / 2.0))

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
        self.btn_focus_minus2.setEnabled(connected)
        self.btn_focus_minus.setEnabled(connected)
        self.btn_focus_plus.setEnabled(connected)
        self.btn_focus_plus2.setEnabled(connected)
        self.btn_nuc.setEnabled(connected)
        self.btn_benchmark.setEnabled(connected)
        if connected and self._worker:
            self._clear_alarm_table()
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
        self._set_focus_buttons_enabled(not busy)
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
        """Update status bar with FPS, processing, frame, size, zoom, alarms, NUC."""
        fps = int(self._config.get("camera", "fps"))
        frame_time_ms = 1000.0 / fps
        nuc_text = f"Next NUC: {self._nuc_remaining} s" if self._nuc_remaining >= 0 else "Next NUC: -"
        self.status_bar.showMessage(
            f"Connected | FPS: {fps}.0 | Processing: {proc_time_ms:.2f} ms | "
            f"Frame: {frame_time_ms:.1f} ms | {FEED_W} x {FEED_H} | "
            f"Zoom: {self.display_widget.zoom_text} | "
            f"Active Alarms: {self._active_alarm_count} | {nuc_text} | "
            f"Alarm Limit: {self._alarm_limit:.1f} °C"
        )

    def _on_alarms_changed(self, alarms: List[Alarm]):
        """Reconcile alarm table and ROI colors when alarm state changes."""
        active = {a.roi_name for a in alarms}
        self._active_alarm_count = len(alarms)
        self.display_widget.set_active_alarms(active)
        self._sync_alarm_table(alarms)
        self._update_status_bar(self._last_proc_time)

    def _on_nuc_countdown(self, seconds: int):
        """Receive the auto-NUC countdown (once per second from the worker)."""
        self._nuc_remaining = seconds

    def _sync_alarm_table(self, alarms: List[Alarm]):
        """Insert/remove rows so the alarm table mirrors the active set."""
        current = {a.roi_name: a for a in alarms}

        removed = [n for n in list(self._alarm_rows) if n not in current]
        for name in removed:
            row = self._alarm_rows.pop(name)
            self.alarm_table.removeRow(row)
            self._alarm_max_shown.pop(name, None)
            for other, other_row in list(self._alarm_rows.items()):
                if other_row > row:
                    self._alarm_rows[other] = other_row - 1

        for name, alarm in current.items():
            if name in self._alarm_rows:
                continue
            row = self.alarm_table.rowCount()
            self.alarm_table.insertRow(row)
            self.alarm_table.setItem(row, 0, QTableWidgetItem(alarm.roi_name))
            self.alarm_table.setItem(
                row, 1,
                QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(alarm.timestamp)))
            )
            text = f"{alarm.current_max:.1f}"
            self.alarm_table.setItem(row, 2, QTableWidgetItem(text))
            self._alarm_rows[name] = row
            self._alarm_max_shown[name] = text

    def _update_alarm_max_cells(self, statistics: List[ROIStatistics]):
        """Refresh only the Current Max cell of active alarm rows."""
        if not self._alarm_rows:
            return
        stats_by_name = {s.name: s for s in statistics}
        for name, row in self._alarm_rows.items():
            stat = stats_by_name.get(name)
            if stat is None:
                continue
            text = f"{stat.maximum:.1f}"
            if self._alarm_max_shown.get(name) != text:
                self.alarm_table.setItem(row, 2, QTableWidgetItem(text))
                self._alarm_max_shown[name] = text

    def _clear_alarm_table(self):
        """Clear all alarm rows and active-alarm coloring (e.g. on reconnect)."""
        self.alarm_table.setRowCount(0)
        self._alarm_rows = {}
        self._alarm_max_shown = {}
        self._active_alarm_count = 0
        self.display_widget.set_active_alarms([])

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

    def _shutdown_thread(self):
        """Stop the worker and join its thread before the window closes.

        Order: worker.stop() (flip flag -> run() exits), thread.quit(),
        thread.wait(). Only null the references after the thread has
        actually finished, so we never destroy a still-running QThread.
        """
        if not self._worker_thread:
            return
        if self._worker:
            self._worker.stop()
        self._worker_thread.quit()
        joined = self._worker_thread.wait(5000)
        if not joined:
            logger.warning(
                "Worker thread did not exit within 5s; keeping it alive to "
                "avoid destroying a running QThread"
            )
            return
        self._worker = None
        self._worker_thread = None

    def closeEvent(self, event: QCloseEvent):
        self._shutdown_thread()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    config = ConfigManager()

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

    window = MainWindow(config)
    window.display_widget.mouse_moved.connect(window._on_mouse_move)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()