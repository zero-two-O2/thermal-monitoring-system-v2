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
import math
import time
import json
import logging
import threading
from types import SimpleNamespace
from typing import List, Tuple, Optional, Dict, Callable
from dataclasses import dataclass

import halcon as ha
import numpy as np
from PyQt6.QtCore import (QThread, pyqtSignal, QObject, QMutex, Qt)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QGridLayout, QLabel, QPushButton,
                              QTableWidget, QTableWidgetItem, QTextEdit,
                              QStatusBar, QToolBar, QHeaderView,
                              QSizePolicy, QComboBox, QLineEdit, QSplitter)
from PyQt6.QtGui import QFont, QColor, QCloseEvent

from calibration.calibration_manager import CalibrationManager
from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo
from camera.services.halcon_driver import HalconDriver
from database.database_manager import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FEED_W = 640
FEED_H = 480
ROI_JSON_PATH = "rois.json"
CONFIG_PATH = "config.json"

# Grab timeout for grab_image_async. At 9 FPS a frame arrives every ~111 ms,
# so 500 ms tolerates a single skipped frame without wedging the stream.
GRAB_TIMEOUT_MS = 500
# HALCON error code for "image acquisition timeout" on grab_image_async.
GRAB_TIMEOUT_ERROR_CODE = 5322
# Consecutive grab timeouts before the framegrabber is closed and reopened.
CONSECUTIVE_FAIL_LIMIT = 3

# Part 2 regression isolation (TEMPORARY - remove after diagnosis).
# Default: both are DISABLED so the live acquisition loop performs no HALCON
# call other than grab_image_async / grab_image_start.
#
#   ENABLE_AUTO_REASSIGN - when False, _handle_grab_timeout never closes or
#   reopens the framegrabber and run() never calls _attempt_reconnect; a
#   grab timeout is only logged and retried.
#   ENABLE_PACKET_STATS - when False, _read_packet_statistics() returns
#   immediately, so [Stream]GevStream* counters are never polled while the
#   GigEVision2 stream is active.
ENABLE_AUTO_REASSIGN = False
ENABLE_PACKET_STATS = False

# Thermal display palettes. (label, HALCON LUT name). Names were verified
# against the installed HALCON build via set_lut(); anything else is not
# exposed. Display only - never touches temperature data.
PALETTES = (
    ("Temperature", "temperature"),
    ("Jet", "jet"),
    ("Rainbow", "rainbow"),
    ("Grayscale", "default"),
)

# GigE Vision stream packet counters read from the framegrabber. These are
# cumulative counters, never rates. The parameter names are the exact
# HALCON GigEVision2 stream parameters used across the project.
PACKET_PARAMS = (
    ("seen", "[Stream]GevStreamSeenPacketCount"),
    ("lost", "[Stream]GevStreamLostPacketCount"),
    ("delivered", "[Stream]GevStreamDeliveredPacketCount"),
    ("duplicate", "[Stream]GevStreamDuplicatePacketCount"),
    ("resent", "[Stream]GevStreamResendPacketCount"),
)


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


class FrameRateMeter:
    """Sliding-window rate meter with a ~1 second window.

    tick() is a single counter increment plus an elapsed check, so it is
    cheap enough for the per-frame path. Once a second the window rolls
    and the last window's count is reported as the rate. Used for the
    acquisition, processing and display FPS - each measured exactly where
    the event happens, never inferred from configuration.
    """

    def __init__(self) -> None:
        self._count = 0
        self._window_start = time.monotonic()
        self._rate = 0.0

    def tick(self) -> None:
        now = time.monotonic()
        self._count += 1
        elapsed = now - self._window_start
        if elapsed >= 1.0:
            self._rate = self._count / elapsed
            self._count = 0
            self._window_start = now

    @property
    def rate(self) -> float:
        return self._rate


@dataclass
class CameraDiagnostics:
    """Per-camera diagnostic snapshot emitted about once per second.

    acquisition_fps / processing_fps / display_fps are measured rates.
    The GigE packet counters are CUMULATIVE stream counters and are never
    reported as rates. packet_loss_pct is derived from the cumulative
    counters and labelled as such.
    """

    frame_number: int = 0
    acquisition_fps: float = 0.0
    processing_fps: float = 0.0
    display_fps: float = 0.0
    processing_time_ms: float = 0.0
    packets_seen: int = 0
    packets_lost: int = 0
    packets_delivered: int = 0
    packets_duplicate: int = 0
    packets_resent: int = 0
    packet_loss_pct: float = 0.0


class CameraRuntime:
    """Owns all runtime state for one camera instance.

    Every camera in the 2x2 grid gets its own CameraRuntime. It holds the
    independent framegrabber/worker/thread plus the per-camera display
    and live copies of the latest frame and statistics. No state here is
    shared between cameras.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        self.tile_index = index
        self.serial: Optional[str] = None
        self.camera_info = None
        self.worker = None
        self.worker_thread = None
        self.display = None
        self.title_label = None
        self.connected = False
        self.latest_temp = None
        self.latest_statistics: List[ROIStatistics] = []
        self.current_focus = 0.0
        self.fps = 0.0
        self.processing_time_ms = 0.0
        self.latest_alarms: List[Alarm] = []
        self.diagnostics: Optional[CameraDiagnostics] = None


CAMERA_COUNT = 4

# Authoritative camera identity -> GUI tile mapping.
#
# A camera's grid tile is decided ONLY by its serial number. Discovery
# order, connection order, list index, thread creation order and reconnect
# order must NEVER influence which tile a camera occupies. Tile indexes are
# stable for the whole application lifetime: a camera that disconnects
# keeps its tile (reserved), and a camera that reconnects always returns to
# that same tile.
CAMERA_TILE_MAP = {
    "HB25100002": 0,   # Tile 1
    "HB25100004": 1,   # Tile 2
    "HB25100008": 2,   # Tile 3
    "HB25080011": 3,   # Tile 4
}

# Known network addresses for the fixed cameras. The serial number is the
# authoritative identity; IP is additional known information / debugging.
CAMERA_IP_MAP = {
    "HB25100002": "169.254.247.198",
    "HB25100004": "169.254.24.69",
    "HB25100008": "169.254.192.87",
    "HB25080011": "169.254.91.157",
}


class ConfigManager:
    """Loads configuration once at startup and holds values in memory.

    The persistent source is SQLite when a DatabaseManager is supplied;
    otherwise config.json is read a single time at construction. Either
    way the processing loop reads from memory only and never touches the
    filesystem or the database.
    """

    DEFAULT_CONFIG = {
        "camera": {
            "fps": 9,
            "reconnect_seconds": 3,
            "nuc_duration_seconds": 2.5,
            "nuc_grab_retry_interval_ms": 100,
            "grab_timeout_before_reconnect_seconds": 8,
        },
        "alarm": {
            "enabled": True,
            "temperature_limit": 80.0,
            "use_max_temperature": True,
        },
        "nuc": {"auto_enabled": True, "interval_seconds": 300},
        "focus": {"default_focus_mm": None, "coarse_step_mm": None, "fine_step_mm": None},
        "display": {"palette": "temperature", "default_zoom": 100},
    }

    def __init__(self, path: str = CONFIG_PATH, database: Optional[DatabaseManager] = None) -> None:
        self._path = path
        self._database = database
        self._data = self._load()

    def _load(self) -> Dict[str, dict]:
        raw = self._load_file_raw()

        if self._database is not None:
            try:
                db_settings = self._database.get_all_settings()
            except Exception:
                logger.exception("Failed to read configuration from database")
                db_settings = None

            if db_settings:
                # A populated database is authoritative: database values
                # win over the JSON file without replacing defaults.
                raw = self._deep_merge(raw, self._unflatten(db_settings))
            else:
                # Empty database: persist the effective configuration once
                # so later runs restore the same values.
                try:
                    self._database.save_all_settings(self._flatten(raw))
                except Exception:
                    logger.exception("Failed to persist configuration to database")

        return self._merge(raw)

    def _load_file_raw(self) -> Dict[str, dict]:
        try:
            with open(self._path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError(f"{self._path} root must be a JSON object")
            return raw
        except FileNotFoundError:
            logger.warning(f"Config file not found: {self._path}; using built-in defaults")
            return dict(self.DEFAULT_CONFIG)
        except Exception:
            logger.exception(f"Failed to load config {self._path}; using built-in defaults")
            return dict(self.DEFAULT_CONFIG)

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        merged = dict(base)
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = ConfigManager._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _flatten(section: dict, prefix: str = "") -> Dict[str, object]:
        result: Dict[str, object] = {}
        for key, value in section.items():
            dot_key = f"{prefix}{key}"
            if isinstance(value, dict):
                result.update(ConfigManager._flatten(value, f"{dot_key}."))
            else:
                result[dot_key] = value
        return result

    @staticmethod
    def _unflatten(settings: Dict[str, object]) -> dict:
        raw: dict = {}
        for key, value in settings.items():
            parts = key.split(".")
            node = raw
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        return raw

    def _merge(self, raw: dict) -> Dict[str, dict]:
        merged = {}
        for section, defaults in self.DEFAULT_CONFIG.items():
            user_section = raw.get(section, {})
            if not isinstance(user_section, dict):
                user_section = {}
            merged[section] = {**defaults, **user_section}
        return merged

    def get(self, section: str, key: str):
        """Return a config value from memory. Never touches the filesystem."""
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
    diagnostics_changed = pyqtSignal(object)
    initialized = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, camera_info: CameraInfo, config: Optional[ConfigManager] = None,
                 database: Optional[DatabaseManager] = None,
                 tile_index: Optional[int] = None):
        super().__init__()
        self._camera_info = camera_info
        # Camera identity: serial is primary, tile_index is the permanent
        # GUI tile this worker's frames belong to. Never use a list index or
        # thread index as identity.
        self.serial = camera_info.serial.strip()
        self.tile_index = tile_index
        self._config = config if config is not None else ConfigManager()
        self._database = database
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
        self._pending_alarm_limit = None
        self._frame_number = 0
        self._consecutive_failures = 0
        self._reconnect_count = 0
        self._last_proc_ms = 0.0
        # Diagnostics: throttled ~1 Hz per-camera report. Acquisition FPS
        # counts successful grabs, processing FPS counts frames that
        # finished grab -> temperature -> ROI stats -> alarm evaluation.
        self._acq_meter = FrameRateMeter()
        self._proc_meter = FrameRateMeter()
        self._last_diag_emit = 0.0
        # Cumulative GigE stream packet counters (read ~1 Hz).
        self._packets_seen = 0
        self._packets_lost = 0
        self._packets_delivered = 0
        self._packets_duplicate = 0
        self._packets_resent = 0
        self._packet_loss_pct = 0.0
        # NUC recovery state. NUC is requested via _nuc_requested and runs
        # in the acquisition loop. While _nuc_active is True the camera may
        # produce no frames at all (that is normal camera behaviour during
        # NUC), so grab timeouts are not treated as acquisition failures.
        self._nuc_active = False
        self._nuc_wait_started = 0.0
        self._nuc_grab_duration_ms = 0.0
        self._nuc_timeout_count = 0
        self._nuc_skip_next_frame = False
        self._nuc_duration_seconds = float(self._config.get("camera", "nuc_duration_seconds"))
        self._nuc_retry_interval_ms = float(self._config.get("camera", "nuc_grab_retry_interval_ms"))
        self._nuc_recover_timeout_s = float(self._config.get("camera", "grab_timeout_before_reconnect_seconds"))
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

        # Give the receiver enough in-flight buffers so 4 simultaneous
        # streams draining slower than line rate do not overflow the pool.
        try:
            ha.set_framegrabber_param(self._framegrabber, "num_buffers", 8)
        except Exception as e:
            logger.warning(f"Unable to set num_buffers: {e}")

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
        """Load ROI coordinates from SQLite (when available) into memory.

        The database is queried only during initialization/reload. The
        acquisition loop then works from the in-memory parallel arrays and
        never touches the database per frame. Falls back to rois.json when
        no database was supplied.
        """
        if self._database is not None:
            try:
                roi_rows = self._database.get_rois()
            except Exception:
                logger.exception("Failed to load ROIs from database")
                self.log_message.emit("Failed to load ROIs from database")
                return False

            self._roi_names = [row["name"] for row in roi_rows]
            self._roi_coords = [(row["y1"], row["x1"], row["y2"], row["x2"]) for row in roi_rows]
            self.log_message.emit(f"Loaded {len(self._roi_names)} ROIs (database)")
            return True

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

    def set_alarm_limit(self, limit: float):
        """Record a pending alarm-limit change for the acquisition loop.

        Called directly from the GUI thread. The pending value is read
        under the mutex and applied by run() before the next alarm
        evaluation, mirroring request_nuc/request_focus. A queued signal
        would never be delivered because run() blocks the worker thread's
        event loop on grab_image_async.
        """
        self._mutex.lock()
        self._pending_alarm_limit = limit
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

    @staticmethod
    def _thread_id() -> int:
        """Return the calling thread's identifier for diagnostics."""
        return threading.get_ident()

    @staticmethod
    def _is_grab_timeout(exc: Exception) -> bool:
        """Return True when an exception is an image-acquisition timeout.

        HALCON raises HOperatorError whose error_code is 5322 for a grab
        timeout, so numeric detection is authoritative. A string fallback
        covers HALCON builds that only expose the message text.
        """
        code = getattr(exc, "error_code", None)
        if code is not None:
            return int(code) == GRAB_TIMEOUT_ERROR_CODE
        message = str(exc) or ""
        lowered = message.lower()
        return "5322" in message and "timeout" in lowered or (
            "grab" in lowered and "timeout" in lowered
        )

    def _log_buffer_config(self) -> None:
        """Log the stream/buffer parameters the camera reports (diagnostics)."""
        for name in ("num_buffers", "[Stream]GevStreamReceiveSocketSize", "grabbing_timeout"):
            try:
                value = ha.get_framegrabber_param(self._framegrabber, name)
            except Exception:
                continue
            logger.info(
                "Camera %s framegrabber handle=%r %s = %r",
                self._camera_info.serial, self._framegrabber, name, value,
            )

    def _log_periodic_diag(self) -> None:
        """Throttled per-camera timing report to expose any bottleneck.

        Runs on a cadence inside the acquisition thread. It shows grab +
        processing + total loop time vs the ~111 ms frame interval so a
        slowly growing drift (the pre-freeze signature) is visible in the
        log before data is actually lost.
        """
        logger.info(
            "Camera %s frame=%d thread=%d reconnects=%d grab_timeout=%dms "
            "proc=%.1fms framegrabber=%r",
            self._camera_info.serial, self._frame_number, self._thread_id(),
            self._reconnect_count, GRAB_TIMEOUT_MS, self._last_proc_ms,
            self._framegrabber,
        )

    @staticmethod
    def _scalar_htuple(value):
        """Unwrap a single-element HALCON HTuple to a plain value."""
        if isinstance(value, (list, tuple)) and len(value) == 1:
            return value[0]
        return value

    def _read_packet_statistics(self) -> None:
        """Read the cumulative GigE stream counters from the framegrabber.

        Runs in the worker thread (which owns the framegrabber) about once
        per second, never per frame. Counters are cumulative; any parameter
        the HALCON build does not expose is reported as -1.
        """
        # Part 2 isolation: packet-statistics polling disabled. The active
        # GigEVision2 stream must not be touched by get_framegrabber_param
        # while grabbing. Stored counters stay at their defaults.
        if not ENABLE_PACKET_STATS:
            return
        values = {}
        for key, param in PACKET_PARAMS:
            try:
                values[key] = int(self._scalar_htuple(
                    ha.get_framegrabber_param(self._framegrabber, param)
                ))
            except Exception:
                values[key] = -1

        self._packets_seen = values["seen"]
        self._packets_lost = values["lost"]
        self._packets_delivered = values["delivered"]
        self._packets_duplicate = values["duplicate"]
        self._packets_resent = values["resent"]

        # Loss percentage derived from the cumulative counters. Reported
        # only against a reliable baseline (seen > 0); otherwise 0.000%.
        try:
            if self._packets_seen > 0:
                self._packet_loss_pct = self._packets_lost / self._packets_seen * 100.0
            else:
                self._packet_loss_pct = 0.0
        except Exception:
            self._packet_loss_pct = 0.0

    def _emit_diagnostics(self) -> None:
        """Emit the throttled per-camera diagnostics snapshot (~1 Hz)."""
        diag = CameraDiagnostics(
            frame_number=self._frame_number,
            acquisition_fps=self._acq_meter.rate,
            processing_fps=self._proc_meter.rate,
            processing_time_ms=self._last_proc_ms,
            packets_seen=self._packets_seen,
            packets_lost=self._packets_lost,
            packets_delivered=self._packets_delivered,
            packets_duplicate=self._packets_duplicate,
            packets_resent=self._packets_resent,
            packet_loss_pct=self._packet_loss_pct,
        )
        self.diagnostics_changed.emit(diag)

    def _reassign_framegrabber(self) -> bool:
        """Close and reopen only the framegrabber after a persistent timeout.

        Recovery deliberately touches nothing else: calibration LUTs, ROI
        regions and the connection state are all reused. Only this camera's
        framegrabber handle is replaced, so the other three cameras keep
        streaming untouched.
        """
        try:
            if self._framegrabber:
                try:
                    ha.close_framegrabber(self._framegrabber)
                except Exception:
                    logger.exception("Error closing stale framegrabber")
                self._framegrabber = None
                self._focus_driver = None

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
                return False

            self._connected = True
            logger.info(
                "Camera %s framegrabber reopened, acquisition resumed",
                self._camera_info.serial,
            )
            return True
        except Exception:
            logger.exception("Framegrabber reassignment failed")
            self._connected = False
            return False

    def _handle_nuc_wait_timeout(self) -> None:
        """Handle a grab timeout while a NUC is in progress.

        During NUC the camera deliberately stops producing frames. A timeout
        here is expected, so it is never counted as an acquisition failure
        and never triggers a framegrabber close/reopen. The loop keeps
        waiting at a throttled interval so the camera is not flooded with
        grab attempts. Only if the camera still produces no frame after the
        configured NUC recovery timeout (grab_timeout_before_reconnect_seconds)
        is the normal timeout recovery ladder used.
        """
        self._nuc_timeout_count += 1
        elapsed_s = time.time() - self._nuc_wait_started
        logger.info(
            "Camera %s NUC in progress: timeout %d (frame=%d, grab=%.0fms, "
            "waited %.1fs of %.1fs)",
            self._camera_info.serial, self._nuc_timeout_count,
            self._frame_number, self._nuc_grab_duration_ms, elapsed_s,
            self._nuc_recover_timeout_s,
        )

        if elapsed_s >= self._nuc_recover_timeout_s:
            logger.warning(
                "Camera %s did not resume after NUC within %.1fs; "
                "escalating to normal timeout recovery",
                self._camera_info.serial, self._nuc_recover_timeout_s,
            )
            self._nuc_active = False
            self._nuc_timeout_count = 0
            self._handle_grab_timeout()
            return

        # Throttled retry: do not flood the camera with grab attempts while
        # it is still busy with NUC. The acquisition loop naturally returns
        # to the configured frame rate once valid frames are available.
        time.sleep(self._nuc_retry_interval_ms / 1000.0)

    def _handle_grab_timeout(self) -> None:
        """Recovery ladder for a single grab timeout.

        A transient timeout is logged and retried. After a run of
        CONSECUTIVE_FAIL_LIMIT timeouts the framegrabber is closed and
        reopened so the acquisition stream is re-armed; calibration, LUTs
        and ROI regions are intentionally left untouched.
        """
        self._consecutive_failures += 1
        failed = self._consecutive_failures
        logger.warning(
            "Camera %s grab timeout (%d consecutive, frame=%d, thread=%d)",
            self._camera_info.serial, failed, self._frame_number, self._thread_id(),
        )

        if failed >= CONSECUTIVE_FAIL_LIMIT:
            self._consecutive_failures = 0
            if not ENABLE_AUTO_REASSIGN:
                # Part 2 isolation: framegrabber reassignment disabled.
                # Log and retry only; never close/reopen the framegrabber,
                # never touch the GigEVision2 stream.
                logger.warning(
                    "Camera %s auto-reassign disabled; retrying "
                    "(frame=%d, thread=%d)",
                    self._camera_info.serial, self._frame_number, self._thread_id(),
                )
                return
            restored = self._reassign_framegrabber()
            if restored:
                self._reconnect_count += 1
                self.log_message.emit(
                    f"Camera {self._camera_info.serial} acquisition recovered "
                    f"(reconnect #{self._reconnect_count})"
                )
            else:
                self.log_message.emit(
                    f"Camera {self._camera_info.serial} recovery failed"
                )

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

        self._log_buffer_config()

        while self._running:

            if not self._connected:
                if not self._running:
                    break
                if ENABLE_AUTO_REASSIGN:
                    self._attempt_reconnect()
                else:
                    # Part 2 isolation: automatic reconnect disabled.
                    logger.warning(
                        "Camera %s disconnected; auto-reconnect disabled "
                        "(retry in %.0fs)",
                        self._camera_info.serial, self._reconnect_seconds,
                    )
                time.sleep(self._reconnect_seconds)
                continue

            # Grab is isolated so a timeout can trigger targeted recovery
            # without being confused with a processing failure.
            grab_started = time.perf_counter()
            try:
                raw_frame = ha.grab_image_async(self._framegrabber, GRAB_TIMEOUT_MS)
            except Exception as grab_exc:
                self._nuc_grab_duration_ms = (time.perf_counter() - grab_started) * 1000.0
                if self._nuc_active:
                    # The camera is internally performing NUC and is not
                    # producing frames. A timeout here is expected camera
                    # behaviour, not a failure. Keep waiting; never count
                    # it, never reconnect, never reopen the framegrabber.
                    self._handle_nuc_wait_timeout()
                elif self._is_grab_timeout(grab_exc):
                    self._handle_grab_timeout()
                else:
                    self._consecutive_failures = 0
                    self.log_message.emit(f"Grab failed: {grab_exc}")
                    logger.exception("Frame grab failed")
                    time.sleep(0.05)
                continue

            if raw_frame is None:
                continue

            # A successful grab clears the timeout streak and counts towards
            # the real acquisition FPS (the NUC skip below is still a
            # successfully acquired frame, so it is counted here too).
            self._consecutive_failures = 0
            self._acq_meter.tick()

            # NUC recovery: the first valid frame after NUC may still be
            # unstable. Discard exactly one frame, then resume normal
            # acquisition at the configured frame rate. No reconnect.
            if self._nuc_active:
                self._nuc_active = False
                wait_timeouts = self._nuc_timeout_count
                self._nuc_timeout_count = 0
                self._nuc_skip_next_frame = True
                self.log_message.emit(
                    f"NUC finished, first valid frame after {wait_timeouts} "
                    f"timeouts (frame #{self._frame_number})"
                )

            if self._nuc_skip_next_frame:
                self._nuc_skip_next_frame = False
                continue

            self._nuc_grab_duration_ms = (time.perf_counter() - grab_started) * 1000.0

            try:
                self._frame_number += 1
                proc_start = time.perf_counter()

                raw_numpy = ha.himage_as_numpy_array(raw_frame)

                temp_frame = self._calibration.raw_to_temperature(raw_numpy)

                # Convert to HALCON image for ROI statistics
                halcon_temp_image = ha.himage_from_numpy_array(temp_frame.astype(np.float32))

                statistics: List[ROIStatistics] = []
                # ROIs may be absent (empty rois.json): without regions the
                # batch statistics calls would crash, so skip them and emit
                # an empty statistics list instead.
                if self._roi_regions is not None:
                    mean_vals, dev_vals = ha.intensity(self._roi_regions, halcon_temp_image)
                    min_vals, max_vals, range_vals = ha.min_max_gray(self._roi_regions, halcon_temp_image, 0)

                    for i, name in enumerate(self._roi_names):
                        statistics.append(ROIStatistics(
                            name=name,
                            mean=float(mean_vals[i]),
                            deviation=float(dev_vals[i]),
                            minimum=float(min_vals[i]),
                            maximum=float(max_vals[i]),
                            range_val=float(range_vals[i])
                        ))

                proc_time_ms = (time.perf_counter() - proc_start) * 1000.0
                self._last_proc_ms = proc_time_ms

                # Apply any alarm-limit change requested by the GUI since
                # the last frame before evaluating alarms.
                self._mutex.lock()
                pending_limit = self._pending_alarm_limit
                self._pending_alarm_limit = None
                self._mutex.unlock()
                if pending_limit is not None:
                    self._alarm_manager.set_limit(pending_limit)

                # Evaluate alarm state from existing statistics only.
                # No recomputation, no additional HALCON calls.
                self._alarm_manager.evaluate(statistics)

                # Frame reached the end of the pipeline (grab -> temperature
                # -> ROI stats -> alarm evaluation) unscathed: count it
                # toward the real processing FPS.
                self._proc_meter.tick()

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

                # Low-frequency diagnostics: packet counters (read once per
                # second, never per frame) and measured FPS values.
                if emit_now - self._last_diag_emit >= 1.0:
                    self._last_diag_emit = emit_now
                    self._read_packet_statistics()
                    self._emit_diagnostics()

                # Pass numpy array instead of halcon image (thread-safe)
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

                # Periodic drift/timing report (every ~90 frames).
                if self._frame_number % 90 == 0:
                    self._log_periodic_diag()

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
        """Execute manual NUC synchronously.

        During NUC the camera internally stops producing frames. This is
        expected camera behaviour: _nuc_active is set so the acquisition
        loop treats subsequent grab timeouts as NUC-in-progress and keeps
        waiting instead of treating them as failures. The camera resumes
        normal acquisition automatically once the first valid frame
        arrives; no reconnect and no framegrabber reopen are performed.
        """
        logger.info(
            "Camera %s NUC start (frame=%d, thread=%d, expected_duration=%.1fs)",
            self._camera_info.serial, self._frame_number, self._thread_id(),
            self._nuc_duration_seconds,
        )
        self.nuc_status.emit(True, "NUC started")
        self._nuc_active = True
        self._nuc_wait_started = time.time()
        self._nuc_timeout_count = 0

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

            logger.info(
                "Camera %s NUC finish (commands issued, waiting for first "
                "valid frame)", self._camera_info.serial,
            )
            self.nuc_status.emit(False, "NUC completed")

        except Exception as e:
            self._nuc_active = False
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
        except Exception:
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
    camera_clicked = pyqtSignal()

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
        # Measures the actual GUI-side display rate: counted when a frame
        # is pushed to this viewer, i.e. after signal delivery, never at
        # acquisition.
        self._display_meter = FrameRateMeter()
        self.setMouseTracking(True)
        # Expanding lets the 2x2 grid own the space. The HALCON window is
        # resized to the largest 4:3 rect inside the widget on every resize,
        # so each camera fills its cell while keeping the 640x480 aspect.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._sync_window_size()

    @property
    def zoom_factor(self) -> float:
        return self.ZOOM_LEVELS[self._zoom_index][0]

    @property
    def zoom_text(self) -> str:
        return self.ZOOM_LEVELS[self._zoom_index][1]

    @property
    def display_fps(self) -> float:
        """Measured rate of frames actually rendered by this viewer."""
        return self._display_meter.rate

    @staticmethod
    def _zoom_index_for(default_zoom) -> int:
        """Map a configured zoom percentage to the ZOOM_LEVELS index."""
        target = int(default_zoom)
        for i, (_, label) in enumerate(HALCONDisplayWidget.ZOOM_LEVELS):
            if int(label.rstrip("%")) == target:
                return i
        return 2  # 100%

    def _compute_fit_rect(self) -> Tuple[int, int]:
        """Largest 4:3 rectangle that fits the current widget size.

        The widget is Expanding so it fills its grid cell; this returns the
        biggest 640x480-aspect window that fits inside it. Window and image
        share the same aspect, so the frame scales uniformly (no stretch,
        no crop, no zoom of the underlying data).
        """
        aspect = FEED_W / FEED_H
        avail_w = max(1, self.width())
        avail_h = max(1, self.height())
        w = avail_w
        h = int(w / aspect)
        if h > avail_h:
            h = avail_h
            w = int(h * aspect)
        return max(1, w), max(1, h)

    def _display_rect(self) -> Tuple[int, int, int, int]:
        """On-screen image rectangle (x, y, w, h) inside the widget.

        Uses the largest 4:3 fit scaled by the current zoom factor. Zoom at
        100% fills the cell; higher zoom is clamped to the fit so the image
        is never stretched or cropped. The rectangle is centered in the
        widget, matching what the HALCON window extents show.
        """
        fit_w, fit_h = self._compute_fit_rect()
        scale = min(self.zoom_factor, 1.0)
        w = max(1, int(round(fit_w * scale)))
        h = max(1, int(round(fit_h * scale)))
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        return x, y, w, h

    def _apply_window_extents(self, x: int, y: int, w: int, h: int):
        """Size the HALCON window to w x h placed at (x, y) in the widget."""
        if self._window_handle is None:
            return
        try:
            ha.set_window_extents(self._window_handle, y, x, w, h)
            ha.set_part(self._window_handle, 0, 0,
                        self._image_height - 1, self._image_width - 1)
        except Exception:
            pass

    def _sync_window_size(self):
        """Fit the HALCON window inside the widget, preserving 4:3.

        The image display region stays the full 640x480 frame (set_part);
        only the output window extents change. The window is sized to the
        largest 4:3 rectangle (scaled by zoom) that fits the widget and
        centered, so every camera fills its panel on any window resize
        without stretching or cropping.
        """
        if self._window_handle is None:
            return
        x, y, w, h = self._display_rect()
        self._apply_window_extents(x, y, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_window_size()
        # Repaint the stored frame at the new extents so the image tracks
        # the widget immediately instead of waiting for the next grab.
        if self._last_frame is not None:
            self._draw()

    def set_fit_size(self, max_w: int, max_h: int):
        """Resize this viewer to the largest 4:3 rectangle that fits the box.

        Compatibility entry point for the tile layout. Because the widget
        now fills its cell on its own (Expanding policy), this just forces a
        re-fit from the widget's live geometry.
        """
        self._close_window_for_resize()
        self._sync_window_size()
        if self._last_frame is not None:
            self._draw()
        self.zoom_changed.emit()

    def _close_window_for_resize(self):
        """Drop a stale HALCON window so the next _draw recreates it sized to the widget.

        When the widget grows, opening a fresh window at the new size avoids
        any leftover extents from the previous smaller fit.
        """
        if self._window_handle is not None:
            try:
                ha.close_window(self._window_handle)
            except Exception:
                pass
            self._window_handle = None

    def set_zoom_index(self, index: int):
        """Change zoom level; the underlying frame stays 640x480."""
        if not 0 <= index < len(self.ZOOM_LEVELS):
            return
        if index == self._zoom_index:
            return
        self._zoom_old_size = self.size()
        self._zoom_index = index
        self._sync_window_size()
        if self._last_frame is not None:
            self._draw()
        self.zoom_changed.emit()

    def create_window(self):
        """Create a HALCON window that exactly fits the current display rect.

        The window is opened at the current fit size and always maps the
        full 640x480 image (set_part is constant). set_window_extents
        follows the widget geometry, so the frame is scaled uniformly and
        never cropped.
        """
        if self._window_handle is not None:
            return
        try:
            x, y, w, h = self._display_rect()
            self._window_handle = ha.open_window(
                y, x, w, h,
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

    def set_palette(self, lut_name: str, redraw: bool = True):
        """Change the thermal display palette (HALCON LUT).

        Display only: never reacquires a frame and never modifies the
        stored temperature data, statistics or alarms. The LUT is applied
        on the live window (if any) and the currently stored frame is
        redrawn so ROI overlays and alarm colouring are preserved.
        """
        if lut_name not in [name for _, name in PALETTES]:
            logger.warning(f"Ignoring unknown palette LUT '{lut_name}'")
            return
        self._palette = lut_name
        if self._window_handle is not None:
            try:
                ha.set_lut(self._window_handle, self._palette)
            except Exception:
                logger.exception("Failed to apply palette %r", self._palette)
        if redraw and self._last_frame is not None:
            self._draw()

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
        # Map widget pixel to image pixel by the actual on-screen image
        # rect (x, y, w, h), independent of the zoom label, so the mouse
        # temperature stays accurate at any fit/zoom size. Coordinates
        # falling in the centered letterbox margin are ignored.
        x0, y0, w, h = self._display_rect()
        px = event.position().x()
        py = event.position().y()
        if px < x0 or py < y0:
            return
        fit_w = w
        fit_h = h
        if px >= x0 + fit_w or py >= y0 + fit_h:
            return
        x = int((px - x0) * self._image_width / max(1, fit_w))
        y = int((py - y0) * self._image_height / max(1, fit_h))
        x = max(0, min(self._image_width - 1, x))
        y = max(0, min(self._image_height - 1, y))
        self.mouse_moved.emit(x, y)

    def mousePressEvent(self, event):
        """Click anywhere in the viewer selects this camera."""
        super().mousePressEvent(event)
        self.camera_clicked.emit()

    def display_frame(self, temp_numpy, statistics: List[ROIStatistics], proc_time_ms: float):
        """Display frame with ROI overlays using HALCON operators only."""
        self._last_frame = temp_numpy
        self._last_statistics = statistics
        self._draw()
        # Count the update at the real rendering point (post-signal, in the
        # GUI thread) so display FPS reflects the GUI, not acquisition.
        self._display_meter.tick()

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


class CameraPanel(QWidget):
    """One 2x2 grid cell: a title bar plus a fit-sized HALCON viewer.

    Each panel belongs to exactly one camera. The display is sized to the
    largest 4:3 rectangle that fits the panel while keeping the 640x480
    aspect ratio. Panels are independent; resizing one never affects the
    others.
    """

    def __init__(self, index: int, config: ConfigManager):
        super().__init__()
        self.index = index
        self.config = config
        self.serial: Optional[str] = None
        self._connected = False
        self._found = True
        self._selected = False
        # Expanding lets the grid split all available space between the four
        # cells; the display inside fills the rest. No fixed size anywhere
        # in the panel chain, so resizing the window scales every camera.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = QLabel("No Camera")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(QFont("Segoe UI", 10))
        self.title_label.setFixedHeight(22)
        layout.addWidget(self.title_label)

        self.display = HALCONDisplayWidget(config)
        layout.addWidget(self.display, stretch=1)

        self._apply_highlight()

    def _title_text(self) -> str:
        if self._found is False:
            base = f"Camera {self.index + 1} | Serial: {self.serial or '?'} | Not Found"
        else:
            state = "Connected" if self._connected else "Disconnected"
            base = f"Camera {self.index + 1} | Serial: {self.serial or '?'} | {state}"
        if self._selected:
            return f"{base} | SELECTED"
        return base

    def set_serial(self, serial: str) -> None:
        """Store the serial this tile is reserved for (identity, not state)."""
        self.serial = serial
        self.title_label.setText(self._title_text())

    def set_found(self, found: bool) -> None:
        """Mark whether the reserved camera was found on this discovery round.

        Not Found keeps the tile reserved and reserved to its serial; the
        tile is never handed to another camera and never disappears.
        """
        self._found = found
        self.title_label.setText(self._title_text())

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.title_label.setText(self._title_text())

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.title_label.setText(self._title_text())
        self._apply_highlight()

    def is_selected(self) -> bool:
        return self._selected

    def _apply_highlight(self) -> None:
        """Draw a cyan box around the selected camera's panel."""
        if self._selected:
            self.setStyleSheet("CameraPanel { border: 3px solid #00E5FF; }")
        else:
            self.setStyleSheet("")


class MainWindow(QMainWindow):
    """Main application window managing four independent cameras."""

    def __init__(self, config: Optional[ConfigManager] = None,
                 database: Optional[DatabaseManager] = None):
        super().__init__()
        self._config = config if config is not None else ConfigManager()
        self._database = database
        self.setWindowTitle("HALCON ROI Validation Tool - TV46L")
        self.resize(1280, 800)

        self._cameras: List[CameraRuntime] = [
            CameraRuntime(i) for i in range(CAMERA_COUNT)
        ]
        self._panels: List[CameraPanel] = []
        self._selected_index = 0

        self._active_alarm_count = 0
        self._nuc_remaining = -1
        self._alarm_limit = float(self._config.get("alarm", "temperature_limit"))
        self._alarm_rows = {}
        self._alarm_max_shown = {}

        self._setup_ui()
        self._reserve_tile_identities()

    def _reserve_tile_identities(self):
        """Reserve every tile's permanent camera identity at startup.

        Runs before any discovery, so the GUI always shows the four fixed
        tiles (Tile 1 -> HB25100002 ... Tile 4 -> HB25080011). Discovery
        later marks each tile as found or Not Found; the identity itself
        never changes.
        """
        for serial, tile_index in CAMERA_TILE_MAP.items():
            self._cameras[tile_index].serial = serial
            self._panels[tile_index].set_serial(serial)
            self._panels[tile_index].set_found(False)

    def _setup_ui(self):
        """Create the GUI layout.

        Layout:
            Toolbar
            [ 2x2 camera grid  |  Global Alarms / ROI Stats / Event Log ]
            Mouse temperature ............. per-camera diagnostics
            Status bar

        Camera feeds occupy the whole left side; the right side is a
        vertical information panel. The split is resizable.
        """
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(6)

        self._create_toolbar(main_layout)

        # Resizable body: left = camera grid, right = information panel.
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(6)
        body.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self._create_camera_grid(left_layout)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self._create_side_panel(right_layout)

        body.addWidget(left)
        body.addWidget(right)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 2)
        body.setSizes([900, 420])
        main_layout.addWidget(body, stretch=5)

        # Bottom information area: mouse temperature + selected diagnostics.
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)
        self._create_mouse_temp(bottom_bar)
        self._create_diagnostic_area(bottom_bar)
        main_layout.addLayout(bottom_bar)

        self._create_status_bar()

        # Default selection is Camera 1. All widgets above exist by now, so
        # the first highlight and selected-state refresh are safe to run.
        self._apply_selection_highlight()
        self._refresh_selected_state()

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

        toolbar.addWidget(QLabel("Palette:"))
        self.combo_palette = QComboBox()
        self.combo_palette.setToolTip("Thermal display palette (display only, never changes temperature data)")
        for label, _ in PALETTES:
            self.combo_palette.addItem(label)
        configured_lut = str(self._config.get("display", "palette"))
        for i, (_, lut) in enumerate(PALETTES):
            if lut == configured_lut:
                self.combo_palette.setCurrentIndex(i)
                break
        self.combo_palette.currentIndexChanged.connect(self._on_palette_changed)
        toolbar.addWidget(self.combo_palette)

        toolbar.addSeparator()

        toolbar.addWidget(QLabel("Alarm Limit:"))
        self.edit_alarm_limit = QLineEdit(f"{self._alarm_limit:.1f}")
        self.edit_alarm_limit.setFixedWidth(70)
        self.edit_alarm_limit.setToolTip("Global alarm threshold in °C, applied to all connected cameras")
        toolbar.addWidget(self.edit_alarm_limit)
        self.btn_apply_limit = QPushButton("Apply")
        self.btn_apply_limit.setToolTip("Apply the new alarm limit to all connected cameras")
        self.btn_apply_limit.clicked.connect(self._on_alarm_limit_apply)
        toolbar.addWidget(self.btn_apply_limit)

        parent_layout.addWidget(toolbar)

    def _create_camera_grid(self, parent_layout):
        """Create the 2x2 grid of independent camera viewers.

        The grid owns almost all of the available space (stretch 5 in the
        main layout). Panel-to-panel spacing is a small fixed gap; each
        panel is Expanding so every resize grows all four cameras. The
        images inside keep 640x480 aspect and are never stretched/cropped.
        """
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        for i, runtime in enumerate(self._cameras):
            panel = CameraPanel(i, self._config)
            self._panels.append(panel)
            runtime.title_label = panel.title_label
            runtime.display = panel.display
            panel.display.mouse_moved.connect(
                lambda x, y, idx=i: self._on_mouse_move(idx, x, y)
            )
            panel.display.camera_clicked.connect(
                lambda idx=i: self._select_camera(idx)
            )
            grid.addWidget(panel, i // 2, i % 2)

        parent_layout.addLayout(grid, stretch=5)

    def _select_camera(self, index: int) -> None:
        """Make `index` the active camera.

        Only one camera may be selected at a time. Selecting never touches
        the other workers: they keep acquiring, processing ROIs, and
        evaluating alarms independently. This only changes which camera the
        ROI table, mouse readout, status bar, and toolbar controls read.
        The global alarm table is never filtered by selection.
        """
        if index < 0 or index >= CAMERA_COUNT:
            return
        if index == self._selected_index:
            return
        self._selected_index = index
        self._apply_selection_highlight()
        self._refresh_selected_state()
        self._log(f"Selected Camera {index + 1}")

    def _apply_selection_highlight(self) -> None:
        """Sync the cyan selection border across all four panels."""
        for i, panel in enumerate(self._panels):
            panel.set_selected(i == self._selected_index)

    def _refresh_selected_state(self) -> None:
        """Instantly bind the shared widgets to the selected camera.

        Called when the selection changes so the ROI table, alarm table,
        mouse readout, status bar, and focus/NUC buttons reflect the new
        camera immediately instead of waiting for its next frame. Reading
        a camera that has not finished connecting shows empty placeholders.
        """
        runtime = self._cameras[self._selected_index]

        # ROI table is rebuilt from the selected camera's worker.
        self._resize_roi_table()
        self._update_roi_table(runtime.latest_statistics)

        # The alarm table stays globally visible for all cameras regardless
        # of which camera is selected. Selection never filters it.
        self._sync_global_alarm_table()
        runtime.display.set_active_alarms({a.roi_name for a in runtime.latest_alarms})

        # Mouse readout shows the selected camera only.
        self.lbl_mouse_temp.setText(
            f"Camera {self._selected_index + 1} | Mouse X: --  Y: --  Temperature: --°C"
        )

        self._nuc_remaining = -1
        self._update_status_bar(runtime.processing_time_ms)
        self._update_diagnostic_area()
        self._set_selected_controls_enabled()

    def _create_mouse_temp(self, parent_layout):
        """Create mouse temperature readout (bottom information area)."""
        self.lbl_mouse_temp = QLabel("Mouse X: --  Y: --  Temperature: --°C")
        self.lbl_mouse_temp.setFont(QFont("Consolas", 10))
        self.lbl_mouse_temp.setStyleSheet("padding: 4px; background: #252526; border: 1px solid #3C3C3C;")
        parent_layout.addWidget(self.lbl_mouse_temp)

    def _create_diagnostic_area(self, parent_layout):
        """Compact per-camera diagnostics for the selected camera.

        Shows measured FPS values, processing time, cumulative GigE packet
        counters and the current display/alarm state. Refreshed from the
        ~1 Hz per-camera diagnostics signal, never every frame.
        """
        self.lbl_diagnostics = QLabel("Diagnostics: --")
        self.lbl_diagnostics.setFont(QFont("Consolas", 9))
        self.lbl_diagnostics.setStyleSheet("padding: 4px; background: #252526; border: 1px solid #3C3C3C;")
        self.lbl_diagnostics.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        parent_layout.addWidget(self.lbl_diagnostics, 1)

    def _create_side_panel(self, parent_layout):
        """Right-side vertical information panel.

        Order: Global Alarm Table, ROI Statistics, Event Log. The alarm
        table is global across all cameras; the ROI table follows the
        selected camera. Stretch factors keep the panel usable on resize.
        """
        self.alarm_table = QTableWidget(0, 6)
        self.alarm_table.setHorizontalHeaderLabels(
            ["Camera", "ROI", "Time", "Current Max (°C)", "Limit (°C)", "Status"]
        )
        self.alarm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alarm_table.verticalHeader().setVisible(False)
        self.alarm_table.setAlternatingRowColors(True)
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        parent_layout.addWidget(self.alarm_table, 3)

        self.roi_table = QTableWidget(0, 6)  # 0 rows initially, will be set dynamically
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Mean (°C)", "Min (°C)", "Max (°C)", "Range (°C)", "Deviation"])
        self.roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.setAlternatingRowColors(True)
        self.roi_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        parent_layout.addWidget(self.roi_table, 3)

        self._create_event_log(parent_layout, stretch=2)

    def _create_event_log(self, parent_layout, stretch: int = 1):
        """Create event log area."""
        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setFont(QFont("Consolas", 9))
        self.event_log.setStyleSheet("background: #1E1E1E; color: #C8C8C8; border: 1px solid #3C3C3C;")
        parent_layout.addWidget(self.event_log, stretch)

    def _create_status_bar(self):
        """Create status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._last_proc_time = 0.0
        self._update_status_bar(0.0)

    def _discover_and_connect(self):
        """Discover cameras and place each into its serial-defined tile.

        Camera identity is the serial number. Every discovered camera is
        matched against CAMERA_TILE_MAP and opened/dislayed in its permanent
        tile; discovery order, connection order and list index never
        influence placement. A configured-but-missing camera keeps its tile
        reserved (Not Found), and an unknown camera is logged and never
        placed into a free tile.
        """
        discovery = CameraDiscovery()
        cameras = discovery.discover()

        if not cameras:
            self._log("No cameras found. Click Connect to retry.")
            return

        by_serial = {}
        for info in cameras:
            by_serial.setdefault(info.serial.strip(), info)

        for serial, tile_index in CAMERA_TILE_MAP.items():
            runtime = self._cameras[tile_index]
            runtime.serial = serial
            self._panels[tile_index].set_serial(serial)

            info = by_serial.get(serial)
            if info is None:
                runtime.camera_info = None
                self._panels[tile_index].set_found(False)
                self._log(f"Camera {tile_index + 1} not found: Serial {serial}")
                continue

            runtime.camera_info = info
            self._panels[tile_index].set_found(True)
            logger.info(
                "Discovered %s -> Tile %d (IP %s)",
                serial, tile_index + 1, info.ip,
            )
            self._log(
                f"Discovered {serial} -> Tile {tile_index + 1}\n"
                f"    Serial: {serial}\n"
                f"    IP: {info.ip}\n"
                f"    Assigned Tile: {tile_index + 1}"
            )
            self._start_worker(runtime)

        # Unknown cameras are never inserted into a random/free tile and
        # never replace an existing camera. They are logged and left undisplayed.
        for info in cameras:
            serial = info.serial.strip()
            if serial not in CAMERA_TILE_MAP:
                logger.warning(
                    "Unknown TV46L camera:\n"
                    "Serial: %s\n"
                    "IP: %s\n"
                    "No fixed tile configured.",
                    serial,
                    info.ip,
                )
                self._log(
                    f"Unknown TV46L camera: Serial: {serial} | IP: {info.ip}\n"
                    "No fixed tile configured."
                )

    def _start_worker(self, runtime: CameraRuntime):
        """Create and start the worker thread for one camera.

        The worker carries its serial and permanent tile_index; frames are
        routed back to this runtime's tile through that identity, never via
        discovery order or list index.
        """
        if runtime.camera_info is None:
            self._log(f"Camera {runtime.index + 1} has no camera info")
            return

        runtime.worker = CameraWorker(
            runtime.camera_info, self._config, self._database,
            tile_index=runtime.tile_index,
        )
        runtime.worker_thread = QThread()
        runtime.worker.moveToThread(runtime.worker_thread)

        runtime.worker.frame_ready.connect(
            lambda temp, stats, ms, i=runtime.index:
                self._on_frame_ready(i, temp, stats, ms)
        )
        runtime.worker.error_occurred.connect(
            lambda msg, i=runtime.index: self._on_error(i, msg)
        )
        runtime.worker.log_message.connect(self._on_log)
        runtime.worker.connected_signal.connect(
            lambda conn, i=runtime.index: self._on_connected(i, conn)
        )
        runtime.worker.nuc_status.connect(
            lambda busy, msg, i=runtime.index: self._on_nuc_status(i, busy, msg)
        )
        runtime.worker.focus_status.connect(
            lambda busy, msg, i=runtime.index: self._on_focus_status(i, busy, msg)
        )
        runtime.worker.alarms_changed.connect(
            lambda alarms, i=runtime.index: self._on_alarms_changed(i, alarms)
        )
        runtime.worker.nuc_countdown.connect(
            lambda seconds, i=runtime.index: self._on_nuc_countdown(i, seconds)
        )
        runtime.worker.diagnostics_changed.connect(
            lambda diag, i=runtime.index: self._on_diagnostics(i, diag)
        )

        # A worker is always created with the config limit, so re-sync it to
        # the GUI's current global limit whenever a camera connects.
        runtime.worker.set_alarm_limit(self._alarm_limit)

        # Worker owns the acquisition loop. When run() returns it emits
        # finished; the thread then quits and cleans up its own objects.
        runtime.worker.initialized.connect(runtime.worker.run)
        runtime.worker.finished.connect(runtime.worker_thread.quit)
        runtime.worker_thread.finished.connect(runtime.worker.deleteLater)
        runtime.worker_thread.finished.connect(runtime.worker_thread.deleteLater)

        runtime.worker_thread.started.connect(runtime.worker.initialize)
        runtime.worker_thread.start()

    def _on_connect(self):
        """Handle connect button - build fresh workers for all cameras.

        After Disconnect every worker and thread is destroyed, so a later
        Connect rebuilds all cameras from scratch, exactly like a fresh
        application startup.
        """
        self._discover_and_connect()

    def _disconnect_all(self):
        """Stop every camera independently and release its resources."""
        for i, runtime in enumerate(self._cameras):
            self._shutdown_thread(runtime)
            self._panels[i].set_connected(False)
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self._set_selected_controls_enabled()
        self._clear_alarm_table()
        self._log("All cameras disconnected")

    def _on_disconnect(self):
        """Handle disconnect button - stop all four cameras."""
        self._disconnect_all()

    def _on_reload_roi(self):
        """Handle reload ROI button - reload ROIs for the selected camera only."""
        runtime = self._cameras[self._selected_index]
        if runtime.worker is not None:
            runtime.worker.reload_rois()
            runtime.display.set_roi_data(runtime.worker._roi_names, runtime.worker._roi_coords)
            self._resize_roi_table()
        else:
            self._log(f"Camera {self._selected_index + 1}: not connected, cannot reload ROIs")

    def _on_focus(self, step_mm: int):
        """Handle focus step buttons for the selected camera."""
        runtime = self._cameras[self._selected_index]
        if runtime.worker is not None:
            runtime.worker.request_focus(step_mm)
            self._set_focus_buttons_enabled(False)

    def _set_focus_buttons_enabled(self, enabled: bool):
        """Enable or disable all four focus step buttons."""
        self.btn_focus_minus2.setEnabled(enabled)
        self.btn_focus_minus.setEnabled(enabled)
        self.btn_focus_plus.setEnabled(enabled)
        self.btn_focus_plus2.setEnabled(enabled)

    def _on_nuc(self):
        """Handle NUC button for the selected camera."""
        runtime = self._cameras[self._selected_index]
        if runtime.worker is not None:
            runtime.worker.request_nuc()
            self.btn_nuc.setEnabled(False)

    def _on_palette_changed(self, index: int):
        """Apply the selected palette to all camera displays (global).

        Palette affects display only. Each widget reapplies its HALCON LUT
        and redraws the stored frame; no reacquisition and no changes to
        temperature data, statistics or alarms.
        """
        if not 0 <= index < len(PALETTES):
            return
        label, lut_name = PALETTES[index]
        for runtime in self._cameras:
            runtime.display.set_palette(lut_name)
        if self._database is not None:
            try:
                self._database.save_setting("display.palette", lut_name)
            except Exception:
                logger.exception("Failed to persist palette setting")
        self._log(f"Palette changed to {label}")

    def _on_alarm_limit_apply(self):
        """Validate and push a new global alarm limit to all connected workers."""
        raw = self.edit_alarm_limit.text().strip()
        try:
            new_limit = float(raw)
        except ValueError:
            self._log(f"Invalid alarm limit '{raw}': must be a number")
            self.status_bar.showMessage(
                f"Invalid alarm limit '{raw}' - must be a number", 5000
            )
            return
        if not math.isfinite(new_limit) or new_limit <= 0:
            self._log(f"Invalid alarm limit '{raw}': must be a finite positive value")
            self.status_bar.showMessage(
                f"Invalid alarm limit '{raw}' - must be a finite positive value", 5000
            )
            return

        self._alarm_limit = new_limit
        for runtime in self._cameras:
            if runtime.worker is not None and runtime.connected:
                runtime.worker.set_alarm_limit(new_limit)
        if self._database is not None:
            try:
                self._database.save_setting("alarm.temperature_limit", new_limit)
                self._database.save_alarm_settings(
                    new_limit,
                    enabled=bool(self._config.get("alarm", "enabled")),
                    use_max_temperature=bool(self._config.get("alarm", "use_max_temperature")),
                )
            except Exception:
                logger.exception("Failed to persist alarm limit")
        self._sync_global_alarm_table()
        self._update_status_bar(self._last_proc_time)
        self._update_diagnostic_area()
        self._log(f"Alarm limit changed to {new_limit:.1f} °C for all cameras")

    def _on_frame_ready(self, index: int, temp_numpy, statistics: List[ROIStatistics], proc_time_ms: float):
        """Handle a new frame for camera `index`."""
        runtime = self._cameras[index]
        runtime.latest_temp = temp_numpy
        runtime.latest_statistics = statistics
        runtime.processing_time_ms = proc_time_ms
        runtime.display.display_frame(temp_numpy, statistics, proc_time_ms)
        self._update_alarm_max_cells(index, statistics)

        if index == self._selected_index:
            self._last_proc_time = proc_time_ms
            self._update_roi_table(statistics)
            self._update_status_bar(proc_time_ms)

    def _on_zoom_changed(self):
        """Handle zoom change - update status bar for the selected camera."""
        self._update_status_bar(self._last_proc_time)

    def _on_error(self, idx: int, msg: str):
        self._log(f"Camera {idx + 1} ERROR: {msg}")

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

    def _on_connected(self, index: int, connected: bool):
        runtime = self._cameras[index]
        runtime.connected = connected
        if not connected:
            # A disconnected camera no longer has active alarms; drop only
            # this camera's rows from the global alarm table.
            runtime.latest_alarms = []
        self._panels[index].set_connected(connected)
        if connected and runtime.worker is not None:
            serial = runtime.worker.serial
            logger.info(
                "Camera serial %s connected -> Tile %d",
                serial, runtime.tile_index + 1,
            )
            self._log(f"Camera serial {serial} connected -> Tile {runtime.tile_index + 1}")
        any_connected = any(r.connected for r in self._cameras)
        self.btn_connect.setEnabled(not any_connected)
        self.btn_disconnect.setEnabled(any_connected)
        if connected and runtime.worker is not None:
            runtime.display.set_roi_data(runtime.worker._roi_names, runtime.worker._roi_coords)
            if self._database is not None and runtime.camera_info is not None:
                try:
                    self._database.upsert_camera(
                        camera_number=index + 1,
                        serial=runtime.camera_info.serial,
                        ip=runtime.camera_info.ip,
                        model=runtime.camera_info.model,
                        enabled=True,
                    )
                except Exception:
                    logger.exception("Failed to persist camera metadata")
        self._sync_global_alarm_table()
        if index == self._selected_index:
            self._set_selected_controls_enabled()
            self._refresh_selected_state()

    def _set_selected_controls_enabled(self) -> None:
        """Enable per-camera toolbar controls only when the selected camera is connected.

        Connect/Disconnect are global; every other toolbar action (focus,
        NUC, reload ROI) targets only the selected camera, so its
        enabled state follows the selected camera's connection.
        """
        runtime = self._cameras[self._selected_index]
        ready = runtime.connected and runtime.worker is not None
        self.btn_reload_roi.setEnabled(ready)
        self.btn_nuc.setEnabled(ready)
        self._set_focus_buttons_enabled(ready)

    def _resize_roi_table(self):
        """Resize ROI table to match number of loaded ROIs."""
        runtime = self._cameras[self._selected_index]
        if runtime.worker is not None:
            num_rois = len(runtime.worker._roi_names)
            self.roi_table.setRowCount(num_rois)

    def _on_nuc_status(self, index: int, busy: bool, msg: str):
        if index == self._selected_index:
            self.btn_nuc.setEnabled(not busy and self._cameras[index].connected)
            self.btn_nuc.setText("NUC in progress..." if busy else "Manual NUC")
        self._log(f"Camera {index + 1}: {msg}")

    def _on_focus_status(self, index: int, busy: bool, msg: str):
        if index == self._selected_index:
            self._set_focus_buttons_enabled(not busy and self._cameras[index].connected)
        self._log(f"Camera {index + 1}: {msg}")

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
        """Update status bar with the selected camera's real measured rates.

        FPS values come from the ~1 Hz diagnostics snapshot (acquisition /
        processing measured in the worker, display measured by the viewer),
        never from the configured frame rate.
        """
        diag = self._cameras[self._selected_index].diagnostics
        acq = f"{diag.acquisition_fps:.1f}" if diag is not None else "--"
        prc = f"{diag.processing_fps:.1f}" if diag is not None else "--"
        dsp = f"{diag.display_fps:.1f}" if (diag is not None and diag.display_fps > 0.0) else "--"
        connection = "Connected" if self._cameras[self._selected_index].connected else "Disconnected"
        nuc_text = f"Next NUC: {self._nuc_remaining} s" if self._nuc_remaining >= 0 else "Next NUC: -"
        self.status_bar.showMessage(
            f"{connection} | Acq FPS: {acq} | Proc FPS: {prc} | Disp FPS: {dsp} | "
            f"Processing: {proc_time_ms:.2f} ms | {FEED_W} x {FEED_H} | "
            f"Zoom: {self._cameras[self._selected_index].display.zoom_text} | "
            f"Active Alarms: {self._active_alarm_count} | {nuc_text} | "
            f"Alarm Limit: {self._alarm_limit:.1f} °C"
        )

    def _on_diagnostics(self, index: int, diag: CameraDiagnostics):
        """Store the per-camera diagnostics and refresh the selected view.

        Diagnostics arrive ~once per second per camera. Display FPS is
        measured by the GUI-side viewer, so it is combined here; the other
        fields were measured by the worker.
        """
        runtime = self._cameras[index]
        runtime.diagnostics = diag
        if index == self._selected_index:
            self._update_diagnostic_area()
            self._update_status_bar(self._last_proc_time)

    def _update_diagnostic_area(self):
        """Refresh the compact bottom diagnostics for the selected camera."""
        runtime = self._cameras[self._selected_index]
        connection = "Connected" if runtime.connected else "Disconnected"
        camera_text = f"Camera {self._selected_index + 1} | {connection} | {FEED_W}×{FEED_H} | " \
                      f"Zoom: {runtime.display.zoom_text} | " \
                      f"Active Alarms: {self._active_alarm_count} | "
        if self._nuc_remaining >= 0:
            camera_text += f"Next NUC: {self._nuc_remaining} s | "
        camera_text += f"Alarm Limit: {self._alarm_limit:.1f}°C"

        diag = runtime.diagnostics
        display_fps = runtime.display.display_fps
        if diag is None:
            self.lbl_diagnostics.setText(
                f"{camera_text}\n"
                f"Acq FPS: -- | Proc FPS: -- | Disp FPS: -- | Processing: -- ms\n"
                f"Packets Lost: -- | Resent: -- | Loss: --"
            )
            return

        self.lbl_diagnostics.setText(
            f"{camera_text}\n"
            f"Acq FPS: {diag.acquisition_fps:.1f} | Proc FPS: {diag.processing_fps:.1f} | "
            f"Disp FPS: {display_fps:.1f} | Processing: {diag.processing_time_ms:.2f} ms | "
            f"Frame #: {diag.frame_number}\n"
            f"Packets Lost: {diag.packets_lost} | Resent: {diag.packets_resent} | "
            f"Loss: {diag.packet_loss_pct:.3f}% (cumulative)"
        )

    def _on_alarms_changed(self, index: int, alarms: List[Alarm]):
        """Store each camera's alarm set and re-sync the global alarm table.

        Every camera keeps its own alarm state internally. The alarm table
        aggregates all cameras; the selected camera does not filter it.
        Each display keeps only its own active alarms for red colouring.
        """
        runtime = self._cameras[index]
        runtime.latest_alarms = alarms
        active = {a.roi_name for a in alarms}
        runtime.display.set_active_alarms(active)
        self._sync_global_alarm_table()
        self._update_status_bar(self._last_proc_time)
        self._update_diagnostic_area()

    def _on_nuc_countdown(self, index: int, seconds: int):
        """Receive the selected camera's auto-NUC countdown."""
        if index == self._selected_index:
            self._nuc_remaining = seconds
            self._update_diagnostic_area()

    def _sync_global_alarm_table(self):
        """Insert/remove rows so the alarm table mirrors all cameras' alarms.

        Rows are keyed by (camera_index, roi_name) because Camera 1 ROI 5
        and Camera 2 ROI 5 are distinct alarms. The table always shows the
        active alarms of every connected camera regardless of selection.
        """
        all_alarms = []
        for i, runtime in enumerate(self._cameras):
            for alarm in runtime.latest_alarms:
                all_alarms.append((i, alarm))

        current = {(i, a.roi_name): (i, a) for i, a in all_alarms}

        removed = [k for k in list(self._alarm_rows) if k not in current]
        for key in removed:
            row = self._alarm_rows.pop(key)
            self.alarm_table.removeRow(row)
            self._alarm_max_shown.pop(key, None)
            for other, other_row in list(self._alarm_rows.items()):
                if other_row > row:
                    self._alarm_rows[other] = other_row - 1

        limit_text = f"{self._alarm_limit:.1f}"
        for key, (i, alarm) in current.items():
            if key in self._alarm_rows:
                # Refresh the limit cell in case the global limit changed.
                row = self._alarm_rows[key]
                item = self.alarm_table.item(row, 4)
                if item is None or item.text() != limit_text:
                    self.alarm_table.setItem(row, 4, QTableWidgetItem(limit_text))
                continue
            row = self.alarm_table.rowCount()
            self.alarm_table.insertRow(row)
            self.alarm_table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            self.alarm_table.setItem(row, 1, QTableWidgetItem(alarm.roi_name))
            self.alarm_table.setItem(
                row, 2,
                QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(alarm.timestamp)))
            )
            text = f"{alarm.current_max:.1f}"
            self.alarm_table.setItem(row, 3, QTableWidgetItem(text))
            self.alarm_table.setItem(row, 4, QTableWidgetItem(limit_text))
            self.alarm_table.setItem(row, 5, QTableWidgetItem("ACTIVE"))
            self._alarm_rows[key] = row
            self._alarm_max_shown[key] = text

        self._active_alarm_count = len(current)

    def _update_alarm_max_cells(self, camera_index: int, statistics: List[ROIStatistics]):
        """Refresh only the Current Max cell of this camera's active alarm rows."""
        if not self._alarm_rows:
            return
        stats_by_name = {s.name: s for s in statistics}
        for (i, name), row in list(self._alarm_rows.items()):
            if i != camera_index:
                continue
            stat = stats_by_name.get(name)
            if stat is None:
                continue
            text = f"{stat.maximum:.1f}"
            if self._alarm_max_shown.get((i, name)) != text:
                self.alarm_table.setItem(row, 3, QTableWidgetItem(text))
                self._alarm_max_shown[(i, name)] = text

    def _clear_alarm_table(self):
        """Clear all alarm rows and per-table counters (e.g. on reconnect).

        Does not touch the display's active-alarm coloring; that is owned by
        the per-camera set_active_alarms calls in the alarm handlers.
        """
        self.alarm_table.setRowCount(0)
        self._alarm_rows = {}
        self._alarm_max_shown = {}
        self._active_alarm_count = 0

    def _log(self, msg: str):
        """Add message to event log."""
        timestamp = time.strftime("%H:%M:%S")
        self.event_log.append(f"[{timestamp}] {msg}")
        cursor = self.event_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.event_log.setTextCursor(cursor)

    def _on_mouse_move(self, index: int, x: int, y: int):
        """Handle mouse movement over a camera display.

        Only the selected camera reports mouse temperature. Hovering a
        non-selected camera is ignored until that camera is selected.
        """
        if index != self._selected_index:
            return
        runtime = self._cameras[self._selected_index]
        if runtime.latest_temp is not None:
            if 0 <= y < runtime.latest_temp.shape[0] and 0 <= x < runtime.latest_temp.shape[1]:
                temp = runtime.latest_temp[y, x]
                self.lbl_mouse_temp.setText(
                    f"Camera {index + 1} | Mouse X: {x}  Y: {y}  Temperature: {temp:.2f}°C"
                )

    def _shutdown_thread(self, runtime: CameraRuntime):
        """Stop one camera's worker and join its thread.

        Order: worker.stop() (flip flag -> run() exits), thread.quit(),
        thread.wait(). Only null the references after the thread has
        actually finished, so we never destroy a still-running QThread.
        """
        if not runtime.worker_thread:
            return
        if runtime.worker:
            runtime.worker.stop()
        runtime.worker_thread.quit()
        joined = runtime.worker_thread.wait(5000)
        if not joined:
            logger.warning(
                f"Camera {runtime.index + 1} worker thread did not exit within 5s; "
                "keeping it alive to avoid destroying a running QThread"
            )
            return
        runtime.worker = None
        runtime.worker_thread = None
        runtime.connected = False

    def closeEvent(self, event: QCloseEvent):
        for runtime in self._cameras:
            self._shutdown_thread(runtime)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Database layer: created before anything else so schema + one-time
    # JSON migration complete before configuration is read. SQLite is only
    # used at startup / configuration change / ROI reload, never per frame.
    database = DatabaseManager()
    database.migrate_from_json(CONFIG_PATH, ROI_JSON_PATH)
    for cam in database.get_cameras():
        logger.info(
            "Restored camera %s from database: serial=%s ip=%s model=%s",
            cam["camera_number"], cam["serial"], cam["ip"], cam["model"],
        )

    config = ConfigManager(database=database)

    # Fixed camera-to-tile mapping is authoritative; discovery order never
    # influences tile position. Printed once at startup for validation.
    logger.info("FIXED CAMERA TILE MAP")
    for serial in sorted(CAMERA_TILE_MAP, key=CAMERA_TILE_MAP.get):
        logger.info(
            "Tile %d -> %s -> %s",
            CAMERA_TILE_MAP[serial] + 1,
            serial,
            CAMERA_IP_MAP.get(serial, "unknown"),
        )

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

    window = MainWindow(config, database)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()