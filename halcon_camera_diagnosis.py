"""
halcon_camera_diagnosis.py

Camera performance diagnosis / bottleneck tool for the Thermal Monitoring
System v2 (Fluke TV46L, GigE Vision 2).

Goal: answer "where is the bottleneck?" per camera.

    Camera -> Acquisition -> Processing -> Display

Per camera the tool measures:
    - acquisition FPS (IR and visible streams separately, plus combined)
    - processing FPS and per-frame processing time
    - display FPS (measured at the GUI, never assumed equal to camera FPS)
    - IR bandwidth (image payload MB/s, calculated from actual bytes)
    - visible bandwidth (image payload MB/s)
    - GigE stream counters (seen / lost packets) when HALCON exposes them
    - acquisition / processing / display latency
    - dropped frames (HALCON stream packet loss) or N/A when unavailable

ACQUISITION REUSE
=================
The acquisition path mirrors halcon_roi_validation.py exactly
(CameraWorker.initialize + _configure_camera + run loop):

    open_framegrabber("GigEVision2", ...)
    set_framegrabber_param "FLK_TI_StreamDataSourceSelector"  IR_Data/VL_Data
    set_framegrabber_param "bits_per_channel" 16
    negotiate packet size, socket size, num_buffers, frame rate,
    disable automatic fine offsets
    grab_image_start + grab_image_async + himage_as_numpy_array

Camera discovery reuses camera.camera_discovery.CameraDiscovery (HALCON
GigEVision2 scan). NO SQL is used; cameras are found by HALCON discovery.

NOT IMPLEMENTED on purpose (diagnosis tool only): ROI validation, alarms,
temperature calibration, pan/tilt, recording, database, user auth.
"""

import json
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    import halcon as ha
except Exception:
    ha = None

try:
    import psutil
except Exception:
    psutil = None

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QCloseEvent, QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("halcon_camera_diagnosis")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FPS = 9
CONFIG_PATH = "config.json"

# Grab timeout for grab_image_async. At 9 FPS a frame arrives every ~111 ms,
# so 500 ms tolerates a single skipped frame without wedging the stream.
# Matches halcon_roi_validation.GRAB_TIMEOUT_MS.
GRAB_TIMEOUT_MS = 500
# HALCON error code for "image acquisition timeout" on grab_image_async.
GRAB_TIMEOUT_ERROR_CODE = 5322
# Consecutive grab timeouts before the framegrabber is closed and reopened.
CONSECUTIVE_FAIL_LIMIT = 3
# Visible-stream failures before visible acquisition is disabled for a camera.
MAX_CONSECUTIVE_VISIBLE_FAILS = 5

IR_STREAM = "IR_Data"
VISIBLE_STREAM = "VL_Data"

FEED_W = 640
FEED_H = 480
MIN_FEED_W = 160
MAX_FEED_W = 480
DEFAULT_FEED_W = 240

# Rolling FPS measurement window.
METRICS_WINDOW_S = 2.0
# How often the worker emits a metrics snapshot (seconds).
METRICS_PERIOD_S = 1.0
# How often the GUI recomputes display FPS and refreshes statistics labels.
STATS_PERIOD_MS = 1000


def _load_frame_rate() -> int:
    """Read the configured camera FPS from config.json (default 9)."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return int(raw["camera"]["fps"])
    except Exception:
        return DEFAULT_FPS


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------


class FpsMeter:
    """Rolling FPS over a time window using monotonic timestamps.

    FPS is derived from the timestamps that actually landed in the window
    ((n - 1) / span) so a single fast/slow frame cannot make the readout
    jump wildly. This is the "current FPS"; the average since connect is
    computed separately from total frame counts.
    """

    def __init__(self, window_seconds: float = METRICS_WINDOW_S) -> None:
        self._window = window_seconds
        self._times: Deque[float] = deque()

    def tick(self) -> None:
        now = time.perf_counter()
        self._times.append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def fps(self) -> float:
        now = time.perf_counter()
        self._prune(now)
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        if span <= 0.0:
            return 0.0
        return (len(self._times) - 1) / span

    def reset(self) -> None:
        self._times.clear()


class LatencyMeter:
    """Rolling average of the last N per-frame latency samples (ms)."""

    def __init__(self, window: int = 30) -> None:
        self._samples: Deque[float] = deque(maxlen=window)

    def add(self, ms: float) -> None:
        self._samples.append(ms)

    def avg(self) -> float:
        if not self._samples:
            return 0.0
        return sum(self._samples) / len(self._samples)

    def reset(self) -> None:
        self._samples.clear()


# ---------------------------------------------------------------------------
# HALCON acquisition (mirrors halcon_roi_validation.py exactly)
# ---------------------------------------------------------------------------


class HalconAcquisition:
    """Framegrabber lifecycle mirroring halcon_roi_validation.CameraWorker.

    Mirrors the proven TV46L path: open_framegrabber('GigEVision2', ...),
    _configure_camera (IR_Data selector, 16-bit, packet size, socket size,
    num_buffers, frame rate, automatic-NUC off), grab_image_start +
    grab_image_async, himage_as_numpy_array, and GigE stream counters.
    """

    def __init__(self, device: str, frame_rate: int) -> None:
        self.device = device
        self.frame_rate = frame_rate
        self._fg: Any = None

    @property
    def handle(self) -> Any:
        return self._fg

    def open(self) -> None:
        """Open the framegrabber and configure the IR stream (validation path)."""
        if ha is None:
            raise RuntimeError("HALCON runtime not installed")
        self._fg = ha.open_framegrabber(
            "GigEVision2", 0, 0, 0, 0, 0, 0,
            "progressive", -1, "default", -1, "false",
            "default", self.device, 0, -1,
        )
        self._configure()

    def _configure(self) -> None:
        """Configure TV46L parameters exactly as CameraWorker._configure_camera."""
        ha.set_framegrabber_param(self._fg, "FLK_TI_StreamDataSourceSelector", IR_STREAM)
        ha.set_framegrabber_param(self._fg, "bits_per_channel", 16)

        try:
            ha.set_framegrabber_param(self._fg, "[Stream]DeviceStreamChannelNegotiatePacketSize", 1)
        except Exception as exc:
            logger.warning("Camera %s: unable to negotiate packet size: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(self._fg, "[Stream]GevStreamReceiveSocketSize", 1048576)
        except Exception as exc:
            logger.warning("Camera %s: unable to set socket buffer size: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(self._fg, "num_buffers", 8)
        except Exception as exc:
            logger.warning("Camera %s: unable to set num_buffers: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(
                self._fg, "FLK_TI_ControlFeature_SetFrameRate", self.frame_rate
            )
        except Exception as exc:
            logger.warning("Camera %s: unable to set frame rate: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(
                self._fg,
                "FLK_TI_ControlFeature_REControlCmd",
                "FLK_TI_ControlFeature_REControlCmd_DisableAutomaticFineOffsets",
            )
        except Exception as exc:
            logger.warning("Camera %s: unable to disable automatic NUC: %s", self.device, exc)

    def select_stream(self, stream: str) -> None:
        """Switch the framegrabber to the IR_Data or VL_Data stream."""
        ha.set_framegrabber_param(self._fg, "FLK_TI_StreamDataSourceSelector", stream)

    def start_acquisition(self) -> None:
        ha.grab_image_start(self._fg, -1)

    def grab(self, timeout_ms: int = GRAB_TIMEOUT_MS) -> Any:
        """Grab the newest frame (may raise a HALCON timeout)."""
        return ha.grab_image_async(self._fg, timeout_ms)

    def image_to_numpy(self, image: Any) -> np.ndarray:
        return ha.himage_as_numpy_array(image)

    def image_size(self) -> Tuple[int, int]:
        try:
            w = int(ha.get_framegrabber_param(self._fg, "image_width"))
            h = int(ha.get_framegrabber_param(self._fg, "image_height"))
            return w, h
        except Exception:
            return FEED_W, FEED_H

    def pixel_format(self) -> str:
        try:
            return str(ha.get_framegrabber_param(self._fg, "pixel_format"))
        except Exception:
            return ""

    def read_stream_stats(self) -> Dict[str, Any]:
        """Read GigE stream counters (same candidates as the validation tool).

        Reported only when the connected device actually exposes them; a
        percentage is only produced for a valid (seen > 0) ratio.
        """
        stats: Dict[str, Any] = {
            "lost": 0,
            "seen": 0,
            "delivered": 0,
            "resend": 0,
            "packet_loss_percent": None,
            "percentage_available": False,
            "counters_available": False,
        }
        candidates = {
            "lost": ("[Stream]GevStreamLostPacketCount", "GevStreamLostPacketCount"),
            "seen": ("[Stream]GevStreamSeenPacketCount", "GevStreamSeenPacketCount"),
            "delivered": ("[Stream]GevStreamDeliveredPacketCount", "GevStreamDeliveredPacketCount"),
            "resend": ("[Stream]GevStreamResendPacketCount", "GevStreamResendPacketCount"),
        }
        read_any = False
        for key, names in candidates.items():
            for name in names:
                try:
                    stats[key] = int(ha.get_framegrabber_param(self._fg, name))
                    read_any = True
                    break
                except Exception:
                    continue
        stats["counters_available"] = read_any
        if stats["seen"] > 0:
            stats["packet_loss_percent"] = stats["lost"] / stats["seen"] * 100.0
            stats["percentage_available"] = True
        return stats

    def close(self) -> None:
        if self._fg is not None:
            try:
                ha.close_framegrabber(self._fg)
            except Exception:
                logger.exception("Error closing framegrabber (%s)", self.device)
            finally:
                self._fg = None


# ---------------------------------------------------------------------------
# Image helpers (display conversion only; raw data is never modified)
# ---------------------------------------------------------------------------


def _normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
    """Min-max normalize any array to 8-bit grayscale for display.

    Raw thermal data is never modified; this produces a fresh display copy.
    """
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr)
    finite = np.isfinite(arr.astype(np.float64))
    if not np.any(finite):
        return np.zeros(arr.shape, dtype=np.uint8)
    valid = arr[finite]
    vmin = float(valid.min())
    vmax = float(valid.max())
    if vmax <= vmin:
        vmax = vmin + 1.0
    norm = (arr.astype(np.float64) - vmin) / (vmax - vmin)
    norm = np.clip(norm, 0.0, 1.0)
    return (norm * 255.0).astype(np.uint8)


def _decode_yuv422_to_rgb(arr: np.ndarray, width: int, height: int) -> Optional[np.ndarray]:
    """Decode packed YUV422 (YUYV, 2 bytes/pixel) into an RGB8 numpy array.

    HALCON delivers the visible stream as yuv422_8 raw packed bytes. Per
    pixel pair the layout is Y0 U0 Y1 V0 (YUYV): luma sits at even byte
    offsets, U/V are shared between each pair and upsampled horizontally.
    If the buffer cannot be interpreted the caller falls back to luma.
    """
    try:
        raw = np.asarray(arr)
        if raw.dtype == np.uint16:
            raw = raw.view(np.uint8).reshape(height, width * 2)
        else:
            raw = raw.reshape(height, width * 2)
        if raw.shape != (height, width * 2):
            return None
        y = raw[:, 0::2].astype(np.float32)
        u = raw[:, 1::2].astype(np.float32)
        v = raw[:, 3::2].astype(np.float32)
        u = np.repeat(u, 2, axis=1)[:, :width]
        v = np.repeat(v, 2, axis=1)[:, :width]
        r = y + 1.402 * (v - 128.0)
        g = y - 0.344136 * (u - 128.0) - 0.714136 * (v - 128.0)
        b = y + 1.772 * (u - 128.0)
        rgb = np.stack([r, g, b], axis=-1)
        rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
        return rgb
    except Exception:
        return None


def _numpy_to_pixmap(arr: np.ndarray, width: int, height: int) -> QPixmap:
    """Convert a display numpy array to a pixmap scaled to the feed size."""
    if arr.ndim == 3 and arr.shape[2] == 3:
        h, w = arr.shape[:2]
        qimage = QImage(arr.data, w, h, arr.strides[0], QImage.Format.Format_RGB888)
    else:
        h, w = arr.shape[:2]
        qimage = QImage(arr.data, w, h, arr.strides[0], QImage.Format.Format_Grayscale8)
    image = qimage.copy()
    return QPixmap.fromImage(image).scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


# ---------------------------------------------------------------------------
# Camera worker
# ---------------------------------------------------------------------------


@dataclass
class CameraMetrics:
    """Rolling metrics snapshot produced by a CameraWorker once per second."""

    status: str = "Disconnected"
    visible_enabled: bool = False
    ir_fps: float = 0.0
    visible_fps: float = 0.0
    acquisition_fps: float = 0.0
    processing_fps: float = 0.0
    ir_frames: int = 0
    visible_frames: int = 0
    ir_w: int = 0
    ir_h: int = 0
    ir_bytes_per_frame: int = 0
    ir_mbps: float = 0.0
    ir_format: str = ""
    vis_w: int = 0
    vis_h: int = 0
    vis_bytes_per_frame: int = 0
    vis_mbps: float = 0.0
    vis_format: str = ""
    ir_latency_ms: float = 0.0
    vis_latency_ms: float = 0.0
    proc_ms: float = 0.0
    timeouts: int = 0
    errors: int = 0
    packet_lost: int = 0
    packet_seen: int = 0
    packet_loss_percent: Optional[float] = None
    percentage_available: bool = False
    counters_available: bool = False
    uptime_s: float = 0.0
    avg_ir_fps: float = 0.0
    avg_vis_fps: float = 0.0


class CameraWorker(QObject):
    """Per-camera acquisition + metrics worker (runs in its own QThread).

    One worker owns exactly one camera. It measures acquisition FPS,
    processing FPS, bandwidth and latency independently. A failure in this
    worker never affects the other cameras' workers; the GUI keeps the
    remaining cameras running.
    """

    frame_ready = pyqtSignal(int, object, object)  # index, ir_display, visible_display
    metrics_ready = pyqtSignal(int, object)        # index, CameraMetrics
    connected_changed = pyqtSignal(int, bool)
    status_changed = pyqtSignal(int, str)
    error = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(self, index: int, camera_info: Any, frame_rate: int) -> None:
        super().__init__()
        self.index = index
        self._info = camera_info
        self._frame_rate = frame_rate
        self._running = False
        self._connected = False
        self._acq: Optional[HalconAcquisition] = None
        self._visible_enabled = True
        self._status = "Disconnected"

        self._ir_fps = FpsMeter()
        self._vis_fps = FpsMeter()
        self._acq_fps = FpsMeter()
        self._proc_fps = FpsMeter()
        self._ir_latency = LatencyMeter()
        self._vis_latency = LatencyMeter()
        self._proc_latency = LatencyMeter()

        self._ir_frames = 0
        self._vis_frames = 0
        self._processed_frames = 0
        self._timeouts = 0
        self._errors = 0
        self._consecutive_failures = 0
        self._visible_fail_count = 0
        self._start_time = time.perf_counter()

        self._ir_w = 0
        self._ir_h = 0
        self._ir_bytes = 0
        self._ir_format = ""
        self._vis_w = 0
        self._vis_h = 0
        self._vis_bytes = 0
        self._vis_format = ""

        self._last_metrics_at = 0.0

    @property
    def camera_info(self) -> Any:
        return self._info

    @property
    def connected(self) -> bool:
        return self._connected

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def run(self) -> None:
        """Entry point executed on the worker thread (started via signal)."""
        self._running = True
        try:
            if self._connect():
                self._acquisition_loop()
        except Exception as exc:
            self._record_error(f"worker crashed: {exc}")
        finally:
            self._cleanup()
            self.finished.emit()

    def stop(self) -> None:
        """Request a clean stop; run() exits its loop and closes the camera."""
        self._running = False

    def _connect(self) -> bool:
        self._set_status("Connecting")
        try:
            self._acq = HalconAcquisition(self._info.device, self._frame_rate)
            self._acq.open()
            self._acq.select_stream(IR_STREAM)
            self._acq.start_acquisition()
            first = self._acq.grab(5000)
            if first is None:
                raise RuntimeError("No first frame received within 5s")
            self._ingest(first, IR_STREAM)
            self._consecutive_failures = 0
            self._connected = True
            self.connected_changed.emit(self.index, True)
            self._set_status("Acquiring")
            logger.info("Camera %d connected (%s)", self.index + 1, self._info.serial)
            return True
        except Exception as exc:
            logger.exception("Camera %d connect failed", self.index + 1)
            self._record_error(f"connect failed: {exc}")
            return False

    def _acquisition_loop(self) -> None:
        """Main loop: IR grab -> visible grab -> emit -> metrics. Runs in worker thread."""
        while self._running:
            if not self._connected:
                time.sleep(0.1)
                continue

            try:
                ir_started = time.perf_counter()
                ir_image = self._acq.grab(GRAB_TIMEOUT_MS)
            except Exception as grab_exc:
                self._handle_grab_exception(grab_exc)
                continue

            if ir_image is None:
                continue

            self._consecutive_failures = 0
            self._ir_fps.tick()
            self._acq_fps.tick()
            self._ir_frames += 1
            self._ir_latency.add((time.perf_counter() - ir_started) * 1000.0)

            ir_display, _, _ = self._ingest(ir_image, IR_STREAM)

            visible_display: Optional[np.ndarray] = None
            if self._visible_enabled:
                try:
                    self._acq.select_stream(VISIBLE_STREAM)
                    self._acq.start_acquisition()
                    vis_started = time.perf_counter()
                    vis_image = self._acq.grab(GRAB_TIMEOUT_MS)
                    if vis_image is not None:
                        self._visible_fail_count = 0
                        self._vis_fps.tick()
                        self._acq_fps.tick()
                        self._vis_frames += 1
                        self._vis_latency.add((time.perf_counter() - vis_started) * 1000.0)
                        visible_display, _, _ = self._ingest(vis_image, VISIBLE_STREAM)
                    else:
                        self._visible_fail_count += 1
                    # Re-arm the IR stream for the next loop iteration.
                    self._acq.select_stream(IR_STREAM)
                    self._acq.start_acquisition()
                except Exception as vis_exc:
                    self._visible_fail_count += 1
                    logger.debug(
                        "Camera %d visible grab failed (%d): %s",
                        self.index + 1, self._visible_fail_count, vis_exc,
                    )
                    if self._visible_fail_count >= MAX_CONSECUTIVE_VISIBLE_FAILS:
                        self._visible_enabled = False
                        self._set_status("IR only (visible unavailable)")
                        logger.warning(
                            "Camera %d visible stream disabled after %d failures",
                            self.index + 1, self._visible_fail_count,
                        )
                    try:
                        self._acq.select_stream(IR_STREAM)
                        self._acq.start_acquisition()
                    except Exception:
                        pass

            # Latest-frame delivery: the GUI overwrites its previous frame,
            # so a slow GUI simply sees newer frames (never a growing queue).
            self.frame_ready.emit(self.index, ir_display, visible_display)
            self._emit_metrics_if_due()

    def _handle_grab_exception(self, exc: Exception) -> None:
        """Recovery ladder for a single grab failure (mirrors validation tool)."""
        if self._is_grab_timeout(exc):
            self._timeouts += 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
                self._consecutive_failures = 0
                self._reopen_framegrabber()
            return
        self._consecutive_failures = 0
        self._record_error(f"IR grab failed: {exc}")
        time.sleep(0.05)

    def _reopen_framegrabber(self) -> None:
        """Close and reopen only the framegrabber after persistent timeouts.

        Deliberately touches nothing else; a recovery failure marks the
        camera disconnected while the other cameras keep streaming.
        """
        logger.warning(
            "Camera %d: persistent timeout, reopening framegrabber", self.index + 1
        )
        self._set_status("Reconnecting")
        try:
            if self._acq is not None:
                self._acq.close()
            self._acq = HalconAcquisition(self._info.device, self._frame_rate)
            self._acq.open()
            self._acq.select_stream(IR_STREAM)
            self._acq.start_acquisition()
            self._acq.grab(5000)
            self._connected = True
            self._set_status("Acquiring")
        except Exception as exc:
            self._record_error(f"reopen failed: {exc}")
            self._connected = False
            self.connected_changed.emit(self.index, False)

    def _ingest(self, image: Any, stream: str) -> Tuple[np.ndarray, int, int]:
        """Convert a HALCON image and build its display copy (processing stage).

        Returns (display_numpy, width, height). Raw image size / pixel format
        are read from the framegrabber only once per stream and cached, so
        the measurement loop itself stays cheap.
        """
        proc_started = time.perf_counter()
        raw = self._acq.image_to_numpy(image)

        if stream == IR_STREAM:
            if not self._ir_w:
                self._ir_w, self._ir_h = self._acq.image_size()
                self._ir_format = self._acq.pixel_format()
                self._ir_bytes = int(raw.nbytes)
            display = _normalize_to_uint8(raw)
        else:
            if not self._vis_w:
                self._vis_w, self._vis_h = self._acq.image_size()
                self._vis_format = self._acq.pixel_format()
                self._vis_bytes = int(raw.nbytes)
            rgb = _decode_yuv422_to_rgb(raw, self._vis_w or FEED_W, self._vis_h or FEED_H)
            display = rgb if rgb is not None else _normalize_to_uint8(raw)

        proc_ms = (time.perf_counter() - proc_started) * 1000.0
        self._proc_fps.tick()
        self._proc_latency.add(proc_ms)
        self._processed_frames += 1

        w = self._ir_w if stream == IR_STREAM else self._vis_w
        h = self._ir_h if stream == IR_STREAM else self._vis_h
        return display, w, h

    def _emit_metrics_if_due(self) -> None:
        now = time.time()
        if now - self._last_metrics_at < METRICS_PERIOD_S:
            return
        self._last_metrics_at = now

        ir_fps = self._ir_fps.fps()
        vis_fps = self._vis_fps.fps()
        elapsed = max(time.perf_counter() - self._start_time, 1e-9)
        ir_mbps = self._ir_bytes * ir_fps / 1_000_000.0
        vis_mbps = self._vis_bytes * vis_fps / 1_000_000.0

        packet = {"lost": 0, "seen": 0}
        percent = None
        available = False
        counters_available = False
        if self._acq is not None:
            stream_stats = self._acq.read_stream_stats()
            packet = {"lost": stream_stats["lost"], "seen": stream_stats["seen"]}
            percent = stream_stats["packet_loss_percent"]
            available = stream_stats["percentage_available"]
            counters_available = stream_stats["counters_available"]

        metrics = CameraMetrics(
            status=self._status,
            visible_enabled=self._visible_enabled,
            ir_fps=ir_fps,
            visible_fps=vis_fps,
            acquisition_fps=self._acq_fps.fps(),
            processing_fps=self._proc_fps.fps(),
            ir_frames=self._ir_frames,
            visible_frames=self._vis_frames,
            ir_w=self._ir_w,
            ir_h=self._ir_h,
            ir_bytes_per_frame=self._ir_bytes,
            ir_mbps=ir_mbps,
            ir_format=self._ir_format,
            vis_w=self._vis_w,
            vis_h=self._vis_h,
            vis_bytes_per_frame=self._vis_bytes,
            vis_mbps=vis_mbps,
            vis_format=self._vis_format,
            ir_latency_ms=self._ir_latency.avg(),
            vis_latency_ms=self._vis_latency.avg(),
            proc_ms=self._proc_latency.avg(),
            timeouts=self._timeouts,
            errors=self._errors,
            packet_lost=packet["lost"],
            packet_seen=packet["seen"],
            packet_loss_percent=percent,
            percentage_available=available,
            counters_available=counters_available,
            uptime_s=elapsed,
            avg_ir_fps=self._ir_frames / elapsed,
            avg_vis_fps=self._vis_frames / elapsed,
        )
        self.metrics_ready.emit(self.index, metrics)

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(self.index, status)

    def _record_error(self, msg: str) -> None:
        self._errors += 1
        logger.error("Camera %d: %s", self.index + 1, msg)
        self.error.emit(self.index, msg)
        self._set_status("Error")

    def _cleanup(self) -> None:
        self._running = False
        if self._acq is not None:
            self._acq.close()
            self._acq = None
        was_connected = self._connected
        self._connected = False
        if was_connected:
            self.connected_changed.emit(self.index, False)
        self._set_status("Disconnected")

    @staticmethod
    def _is_grab_timeout(exc: Exception) -> bool:
        """Return True when an exception is an image-acquisition timeout.

        HALCON raises HOperatorError with error_code 5322 for a grab timeout;
        a string fallback covers builds that only expose the message text.
        """
        code = getattr(exc, "error_code", None)
        if code is not None:
            try:
                return int(code) == GRAB_TIMEOUT_ERROR_CODE
            except (TypeError, ValueError):
                pass
        message = str(exc) or ""
        lowered = message.lower()
        return "5322" in message and "timeout" in lowered or (
            "grab" in lowered and "timeout" in lowered
        )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


class CameraWidget(QFrame):
    """Compact per-camera panel: title, IR + visible feed, metrics text."""

    def __init__(self, index: int, camera_info: Any, feed_w: int, feed_h: int) -> None:
        super().__init__()
        self.index = index
        self._info = camera_info
        self._feed_w = feed_w
        self._feed_h = feed_h
        self._status = "Disconnected"
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "CameraWidget { background: #252526; border: 1px solid #3C3C3C; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.title = QLabel(self._title_text())
        self.title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.title.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self.title)

        feeds = QHBoxLayout()
        feeds.setSpacing(6)
        self.ir_view = self._make_feed_label("IR")
        self.vis_view = self._make_feed_label("Visible")
        feeds.addWidget(self.ir_view)
        feeds.addWidget(self.vis_view)
        layout.addLayout(feeds)

        self.stats = QLabel("Waiting for data...")
        self.stats.setFont(QFont("Consolas", 9))
        self.stats.setStyleSheet("color: #C8C8C8;")
        self.stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.stats)

    def _make_feed_label(self, placeholder: str) -> QLabel:
        label = QLabel(placeholder)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(self._feed_w, self._feed_h)
        label.setStyleSheet(
            "background: #1E1E1E; color: #C8C8C8; border: 1px solid #3C3C3C;"
        )
        return label

    def _title_text(self) -> str:
        serial = getattr(self._info, "serial", "?")
        model = getattr(self._info, "model", "")
        return f"Camera {self.index + 1} | {serial} | {model} | {self._status}"

    def set_status(self, status: str) -> None:
        self._status = status
        self.title.setText(self._title_text())

    def set_feed_size(self, feed_w: int, feed_h: int) -> None:
        self._feed_w = feed_w
        self._feed_h = feed_h
        self.ir_view.setFixedSize(feed_w, feed_h)
        self.vis_view.setFixedSize(feed_w, feed_h)

    def update_frames(self, ir_display: Optional[np.ndarray], visible_display: Optional[np.ndarray]) -> float:
        """Render the newest IR and visible frames; returns display time (ms)."""
        started = time.perf_counter()
        if ir_display is not None:
            self.ir_view.setPixmap(_numpy_to_pixmap(ir_display, self._feed_w, self._feed_h))
            self.ir_view.setText("")
        if visible_display is not None:
            self.vis_view.setPixmap(_numpy_to_pixmap(visible_display, self._feed_w, self._feed_h))
            self.vis_view.setText("")
        else:
            self.vis_view.setPixmap(QPixmap())
            self.vis_view.setText("Visible\nN/A")
        return (time.perf_counter() - started) * 1000.0

    def update_stats(self, m: CameraMetrics, display_fps: float, display_ms: float) -> None:
        """Refresh the statistics block (called a few times per second)."""
        vis_label = (
            f"{m.visible_fps:.1f} FPS | {m.vis_mbps:.2f} MB/s"
            if m.visible_enabled
            else "N/A"
        )
        loss = (
            f"{m.packet_loss_percent:.2f}%"
            if m.percentage_available
            else "N/A"
        )
        if m.counters_available:
            pkt_label = (
                f"Lost pkt: {m.packet_lost} | Seen pkt: {m.packet_seen} ({loss})"
            )
        else:
            pkt_label = "Lost pkt: N/A | Seen pkt: N/A"
        text = (
            f"IR:  {m.ir_fps:.1f} FPS | {m.ir_mbps:.2f} MB/s (payload)\n"
            f"VIS: {vis_label} (payload)\n"
            f"Acq: {m.acquisition_fps:.1f} | Proc: {m.processing_fps:.1f} | "
            f"Disp: {display_fps:.1f}\n"
            f"IR  {m.ir_w}x{m.ir_h}  {m.ir_bytes_per_frame} B/f ({m.ir_format})\n"
            f"VIS {m.vis_w}x{m.vis_h}  {m.vis_bytes_per_frame} B/f ({m.vis_format})\n"
            f"Acq: {m.ir_latency_ms:.1f} ms | Proc: {m.proc_ms:.1f} ms | "
            f"Disp: {display_ms:.1f} ms\n"
            f"Frames IR {m.ir_frames} / VIS {m.visible_frames} | "
            f"Timeouts {m.timeouts} | Errors {m.errors}\n"
            f"Avg IR {m.avg_ir_fps:.1f} / VIS {m.avg_vis_fps:.1f} FPS | "
            f"{pkt_label} | {m.status}"
        )
        self.stats.setText(text)


class DiscoveryWorker(QObject):
    """Background HALCON discovery (never blocks the GUI thread)."""

    discovered = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def run(self) -> None:
        try:
            cameras, err = discover_cameras()
            if cameras:
                self.discovered.emit(cameras)
            else:
                self.failed.emit(err or "No cameras found")
        except Exception as exc:
            logger.exception("Camera discovery worker failed")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class DiagnosisWindow(QMainWindow):
    """Main window: scrollable grid of camera panels + global statistics."""

    def __init__(self, frame_rate: int = DEFAULT_FPS) -> None:
        super().__init__()
        self.setWindowTitle("HALCON Camera Diagnosis")
        self.resize(1280, 800)
        self._frame_rate = frame_rate
        self._feed_w = DEFAULT_FEED_W
        self._feed_h = int(DEFAULT_FEED_W * FEED_H / FEED_W)

        self._cameras: List[Any] = []
        self._workers: Dict[int, CameraWorker] = {}
        self._worker_threads: Dict[int, QThread] = {}
        self._widgets: Dict[int, CameraWidget] = {}
        self._metrics: Dict[int, CameraMetrics] = {}
        self._display_counts: Dict[int, int] = {}
        self._display_fps: Dict[int, float] = {}
        self._display_ms: Dict[int, float] = {}

        self._discovering = False
        self._discovery_thread: Optional[QThread] = None
        self._discovery_worker: Optional[DiscoveryWorker] = None

        self._setup_ui()
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._stats_tick)
        self._stats_timer.start(STATS_PERIOD_MS)

        # Open the window even with no camera connected, then discover.
        QTimer.singleShot(300, self.refresh_cameras)

    # ---------------------------------------------------------------
    # UI construction
    # ---------------------------------------------------------------

    def _setup_ui(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.btn_refresh = QPushButton("Refresh Cameras")
        self.btn_refresh.clicked.connect(self.refresh_cameras)
        toolbar.addWidget(self.btn_refresh)

        self.btn_connect_all = QPushButton("Connect All")
        self.btn_connect_all.clicked.connect(self._connect_all)
        toolbar.addWidget(self.btn_connect_all)

        self.btn_disconnect_all = QPushButton("Disconnect All")
        self.btn_disconnect_all.clicked.connect(self._disconnect_all)
        toolbar.addWidget(self.btn_disconnect_all)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Feed Size"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(MIN_FEED_W, MAX_FEED_W)
        self.slider.setValue(DEFAULT_FEED_W)
        self.slider.setFixedWidth(160)
        self.slider.valueChanged.connect(self._on_feed_size)
        toolbar.addWidget(self.slider)
        self.lbl_feed = QLabel(f"{DEFAULT_FEED_W} px")
        toolbar.addWidget(self.lbl_feed)

        self.addToolBar(toolbar)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(6)

        self.lbl_global = QLabel("Connected: 0   |   Total IR FPS: 0.0   |   "
                                "Total VIS FPS: 0.0   |   IR Data: 0.00 MB/s   |   "
                                "VIS Data: 0.00 MB/s   |   Image Data: 0.00 MB/s (payload)   |   "
                                "CPU: 0.0%   |   RAM: 0 MB")
        self.lbl_global.setFont(QFont("Consolas", 10))
        self.lbl_global.setStyleSheet(
            "padding: 4px; background: #252526; border: 1px solid #3C3C3C; color: #FFFFFF;"
        )
        self.lbl_global.setToolTip(
            "MB/s values are image payload (bytes per frame x FPS), not raw network bandwidth."
        )
        main_layout.addWidget(self.lbl_global)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_container = QWidget()
        self._grid = QGridLayout(self.scroll_container)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.scroll_container)
        main_layout.addWidget(self.scroll, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready - scanning for cameras...")

    # ---------------------------------------------------------------
    # Discovery
    # ---------------------------------------------------------------

    def refresh_cameras(self) -> None:
        """Re-discover cameras in the background, then connect to what is found."""
        if self._discovering:
            return
        self._disconnect_all()
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Scanning...")
        self.statusBar().showMessage("Scanning for GigE Vision cameras...")
        self._discovering = True

        self._discovery_thread = QThread()
        self._discovery_worker = DiscoveryWorker()
        self._discovery_worker.moveToThread(self._discovery_thread)
        self._discovery_worker.discovered.connect(self._on_discovered)
        self._discovery_worker.failed.connect(self._on_discovery_failed)
        self._discovery_worker.finished.connect(self._discovery_thread.quit)
        self._discovery_thread.finished.connect(self._on_discovery_done)
        self._discovery_thread.finished.connect(self._discovery_worker.deleteLater)
        self._discovery_thread.finished.connect(self._discovery_thread.deleteLater)
        self._discovery_thread.started.connect(self._discovery_worker.run)
        self._discovery_thread.start()

    def _on_discovery_done(self) -> None:
        self._discovering = False
        self._discovery_thread = None
        self._discovery_worker = None
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Refresh Cameras")

    def _on_discovered(self, cameras: List[Any]) -> None:
        self._cameras = list(cameras)
        self._rebuild_grid()
        self.statusBar().showMessage(f"Discovered {len(cameras)} camera(s)", 5000)
        if cameras:
            self._connect_all()
        else:
            self.statusBar().showMessage("No cameras found", 5000)

    def _on_discovery_failed(self, msg: str) -> None:
        self._cameras = []
        self._rebuild_grid()
        self.statusBar().showMessage(msg, 7000)
        logger.error("Discovery failed: %s", msg)

    # ---------------------------------------------------------------
    # Grid
    # ---------------------------------------------------------------

    def _rebuild_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._widgets.clear()

        count = len(self._cameras)
        if count == 0:
            empty = QLabel("No cameras discovered.\nClick 'Refresh Cameras' to rescan.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #C8C8C8; font-size: 14px;")
            self._grid.addWidget(empty, 0, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setRowStretch(0, 1)
            return

        cols = 2 if count <= 4 else (3 if count <= 9 else 4)
        for i in range(cols):
            self._grid.setColumnStretch(i, 1)
        for i, info in enumerate(self._cameras):
            widget = CameraWidget(i, info, self._feed_w, self._feed_h)
            self._widgets[i] = widget
            self._grid.addWidget(widget, i // cols, i % cols)
            self._grid.setRowStretch(i // cols, 1)

    # ---------------------------------------------------------------
    # Worker lifecycle
    # ---------------------------------------------------------------

    def _connect_all(self) -> None:
        for index, info in enumerate(self._cameras):
            thread = self._worker_threads.get(index)
            if thread is not None and thread.isRunning():
                continue
            self._start_worker(index, info)

    def _start_worker(self, index: int, info: Any) -> None:
        worker = CameraWorker(index, info, self._frame_rate)
        thread = QThread()
        worker.moveToThread(thread)

        worker.frame_ready.connect(self._on_frame_ready)
        worker.metrics_ready.connect(self._on_metrics_ready)
        worker.connected_changed.connect(self._on_connected_changed)
        worker.status_changed.connect(self._on_status_changed)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._workers[index] = worker
        self._worker_threads[index] = thread
        thread.started.connect(worker.run)
        thread.start()

    def _stop_worker(self, index: int) -> None:
        worker = self._workers.get(index)
        thread = self._worker_threads.get(index)
        if worker is not None:
            worker.stop()
        if thread is not None:
            thread.quit()
            joined = thread.wait(5000)
            if not joined:
                logger.warning(
                    "Camera %d worker thread did not exit within 5s; keeping it alive",
                    index + 1,
                )
        widget = self._widgets.get(index)
        if widget is not None:
            widget.set_status("Disconnected")

    def _disconnect_all(self) -> None:
        for index in list(self._workers):
            self._stop_worker(index)
        self._workers.clear()
        self._worker_threads.clear()
        self._metrics.clear()
        self._display_counts.clear()
        self._display_fps.clear()
        self._display_ms.clear()
        self.statusBar().showMessage("All cameras disconnected", 5000)

    # ---------------------------------------------------------------
    # Signal handlers
    # ---------------------------------------------------------------

    def _on_frame_ready(self, index: int, ir_display: object, visible_display: object) -> None:
        widget = self._widgets.get(index)
        if widget is None:
            return
        started = time.perf_counter()
        widget.update_frames(ir_display, visible_display)
        self._display_ms[index] = (time.perf_counter() - started) * 1000.0
        self._display_counts[index] = self._display_counts.get(index, 0) + 1

    def _on_metrics_ready(self, index: int, metrics: CameraMetrics) -> None:
        self._metrics[index] = metrics

    def _on_connected_changed(self, index: int, connected: bool) -> None:
        widget = self._widgets.get(index)
        if widget is not None and not connected:
            widget.set_status("Disconnected")

    def _on_status_changed(self, index: int, status: str) -> None:
        widget = self._widgets.get(index)
        if widget is not None:
            widget.set_status(status)

    def _on_worker_error(self, index: int, msg: str) -> None:
        logger.error("Camera %d: %s", index + 1, msg)
        self.statusBar().showMessage(
            f"Camera {index + 1} ERROR: {msg}", 7000
        )

    # ---------------------------------------------------------------
    # Statistics refresh (throttled; never per frame)
    # ---------------------------------------------------------------

    def _stats_tick(self) -> None:
        for index in list(self._display_counts):
            self._display_fps[index] = float(self._display_counts[index])
            self._display_counts[index] = 0

        for index, widget in self._widgets.items():
            metrics = self._metrics.get(index)
            if metrics is None:
                continue
            widget.update_stats(
                metrics,
                self._display_fps.get(index, 0.0),
                self._display_ms.get(index, 0.0),
            )
        self._update_global_stats()

    def _update_global_stats(self) -> None:
        active = sum(
            1
            for metrics in self._metrics.values()
            if metrics.status in ("Acquiring", "Reconnecting", "IR only (visible unavailable)")
        )
        total_ir_fps = sum(m.ir_fps for m in self._metrics.values())
        total_vis_fps = sum(m.visible_fps for m in self._metrics.values())
        total_ir_mbps = sum(m.ir_mbps for m in self._metrics.values())
        total_vis_mbps = sum(m.vis_mbps for m in self._metrics.values())
        total_image_mbps = total_ir_mbps + total_vis_mbps
        cpu, ram = _system_load()
        self.lbl_global.setText(
            f"Connected: {active}   |   Total IR FPS: {total_ir_fps:.1f}   |   "
            f"Total VIS FPS: {total_vis_fps:.1f}   |   "
            f"IR Data: {total_ir_mbps:.2f} MB/s   |   "
            f"VIS Data: {total_vis_mbps:.2f} MB/s   |   "
            f"Image Data: {total_image_mbps:.2f} MB/s (payload)   |   "
            f"CPU: {cpu:.1f}%   |   RAM: {ram:.0f} MB"
        )

    def _on_feed_size(self, value: int) -> None:
        self._feed_w = value
        self._feed_h = int(value * FEED_H / FEED_W)
        self.lbl_feed.setText(f"{value} px")
        for widget in self._widgets.values():
            widget.set_feed_size(self._feed_w, self._feed_h)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stats_timer.stop()
        self._disconnect_all()
        event.accept()


# ---------------------------------------------------------------------------
# Discovery entry point (HALCON, no SQL)
# ---------------------------------------------------------------------------


def discover_cameras() -> Tuple[List[Any], str]:
    """Discover cameras using the project's HALCON CameraDiscovery.

    Returns (cameras, error). Cameras may be empty with a non-empty error
    when HALCON is missing or the network scan fails; the GUI stays open.
    """
    if ha is None:
        return [], "HALCON runtime not installed; cannot scan for cameras"
    try:
        from camera.camera_discovery import CameraDiscovery

        discovery = CameraDiscovery()
        cameras = discovery.discover()
        return cameras, ""
    except Exception as exc:
        logger.exception("Camera discovery failed")
        return [], f"Camera discovery failed: {exc}"


def _system_load() -> Tuple[float, float]:
    """Return (cpu_percent, ram_used_mb). Returns zeros when psutil is absent."""
    if psutil is None:
        return 0.0, 0.0
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        return float(cpu), float(mem.used / (1024.0 * 1024.0))
    except Exception:
        return 0.0, 0.0


def _apply_dark_palette(app: QApplication) -> None:
    """Dark theme matching the project design system (DESIGN.md)."""
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(0x1E, 0x1E, 0x1E))
    palette.setColor(palette.ColorRole.WindowText, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(palette.ColorRole.Base, QColor(0x25, 0x25, 0x26))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(0x2D, 0x2D, 0x2D))
    palette.setColor(palette.ColorRole.ToolTipBase, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(palette.ColorRole.ToolTipText, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(palette.ColorRole.Text, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(palette.ColorRole.Button, QColor(0x3C, 0x3C, 0x3C))
    palette.setColor(palette.ColorRole.ButtonText, QColor(0xFF, 0xFF, 0xFF))
    palette.setColor(palette.ColorRole.BrightText, QColor(0xFF, 0x00, 0x00))
    palette.setColor(palette.ColorRole.Highlight, QColor(0x00, 0x78, 0xD7))
    palette.setColor(palette.ColorRole.HighlightedText, QColor(0xFF, 0xFF, 0xFF))
    app.setPalette(palette)


def main() -> int:
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    if psutil is not None:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    window = DiagnosisWindow(frame_rate=_load_frame_rate())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
