"""
halcon_camera_diagnosis.py

"""

import json
import logging
import sys
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    import halcon as ha
except Exception as exc:
    print(f"HALCON import failed: {exc}")
    raise

try:
    import psutil
except Exception:
    psutil = None

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QCloseEvent, QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
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

# HALCON error code for "image acquisition timeout" on grab_image_async.
# With two continuously-streaming framegrabber handles the loop uses
# non-blocking (0 ms) grabs, so a timeout simply means "no new frame yet".
GRAB_TIMEOUT_ERROR_CODE = 5322
# First-frame grab timeout during connect / framegrabber reopen (ms).
FIRST_FRAME_TIMEOUT_MS = 5000
# No IR frame for this long triggers a framegrabber close+reopen. At 9 FPS
# the interval is ~111 ms, so 3 s covers roughly 27 missed frames without
# reacting to the normal gap between frames.
WEDGE_RECOVERY_S = 3.0

# ---------------------------------------------------------------------------
# Acquisition strategies (experimental)
# ---------------------------------------------------------------------------
# Test A - reproduce halcon_roi_validation.py exactly: one handle, IR_Data.
STRATEGY_BASELINE = "baseline"
# Two GigE connections to the camera (device string + IP), both streaming.
STRATEGY_DUAL_HANDLE = "dual_handle"
# One handle, alternate IR_Data / VL_Data at a configurable hold interval.
STRATEGY_RAPID_SWITCH = "rapid_switch"
# One handle; probe the payload for a combined IR + visible frame.
STRATEGY_DUAL_COMPONENT = "dual_component"
# One handle; IR streams continuously, visible is sampled in short bursts.
STRATEGY_TIME_SLICED = "time_sliced"

STRATEGY_LABELS = {
    STRATEGY_BASELINE: "Baseline (IR only)",
    STRATEGY_DUAL_HANDLE: "Dual Handle (IR + VIS)",
    STRATEGY_RAPID_SWITCH: "Rapid Source Switching",
    STRATEGY_DUAL_COMPONENT: "Dual Component / Payload",
    STRATEGY_TIME_SLICED: "Time-sliced (IR priority)",
}
STRATEGY_ORDER = [
    STRATEGY_TIME_SLICED,
    STRATEGY_DUAL_HANDLE,
    STRATEGY_BASELINE,
    STRATEGY_RAPID_SWITCH,
    STRATEGY_DUAL_COMPONENT,
]
DEFAULT_STRATEGY = STRATEGY_TIME_SLICED

# Time-sliced strategy: IR streams this long at full rate, then the camera
# switches to VL_Data for a short visible burst and back. Only two switches
# per cycle, so the IR feed stays smooth and the visible feed updates
# periodically instead of flapping.
TIME_SLICE_IR_HOLD_S = 2.0
TIME_SLICE_VIS_HOLD_S = 0.6

# Rapid source switching: hold each source this long (ms) before switching.
RAPID_SWITCH_HOLD_MS = 250
# Automated experiment: hold intervals swept from longest to shortest.
SWEEP_INTERVALS_MS = [1000, 500, 250, 100, 50, 25, 10]
# Each swept interval runs this long (s) before statistics are captured.
SWEEP_PER_INTERVAL_S = 5.0
# Block this long (ms) for the first frame after switching sources.
SWITCH_FIRST_FRAME_TIMEOUT_MS = 2000

# Parameters probed by the Dual Component strategy to detect combined feeds.
COMPONENT_PROBE_PARAMS = [
    "PayloadSize",
    "payload_size",
    "GevCurrentPayloadSize",
    "image_channels",
    "image_type",
    "image_width",
    "image_height",
    "available_components",
    "[Component]ComponentSelector",
    "[Component]ComponentID",
    "[Stream]StreamSelector",
    "StreamChannelIndex",
    "GevStreamChannelSelector",
    "DeviceStreamChannelCount",
    "SensorWidth",
    "SensorHeight",
]


def _is_grab_timeout(exc: Exception) -> bool:
    """Return True when an exception is an image-acquisition timeout.

    HALCON raises HOperatorError with error_code 5322 for a grab timeout; a
    string fallback covers builds that only expose the message text.
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


def _dotted_ip(value: str) -> str:
    """Convert a GigE IP value to dotted-quad form.

    HALCON reports [Device]GevDeviceIPAddress as an integer; discovery may
    stringify it as a plain decimal, 0x hex, or an already-dotted address.
    Returns "" when the value cannot be interpreted as an IPv4 address.
    """
    text = (value or "").strip()
    if not text:
        return ""
    if "." in text:
        return text
    try:
        num = int(text, 0)
    except ValueError:
        return text
    if num < 0 or num > 0xFFFFFFFF:
        return text
    return ".".join(str((num >> shift) & 0xFF) for shift in (24, 16, 8, 0))

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
    """IR + visible acquisition for the TV46L single-stream GigE camera.

    HALCON's GigEVision2 interface opens only one stream channel per camera,
    and the TV46L selects IR_Data or VL_Data as that channel's source via
    the camera-global FLK_TI_StreamDataSourceSelector. Two strategies are
    therefore supported:

    * Dual mode: a second connection to the same camera is attempted using
      its IP address. When the camera accepts a second connection, both
      feeds run at their native rate concurrently. This mirrors the smooth
      single-stream path of halcon_roi_validation.py for each feed.
    * Single mode (fallback): one handle stays IR-primary; the worker
      switches the shared stream to VL_Data at a throttled cadence and back,
      so the visible feed updates occasionally while the IR feed stays
      smooth. Switching the source on this camera costs roughly a second,
      so per-frame switching (the old behaviour) capped the loop at ~0.8 FPS.
    """

    def __init__(
        self,
        device: str,
        frame_rate: int,
        visible_device: str = "",
        single_handle: bool = False,
    ) -> None:
        self.device = device
        self.frame_rate = frame_rate
        self.visible_device = visible_device
        self.single_handle = single_handle
        self._ir_fg: Any = None
        self._vis_fg: Any = None

    @property
    def handle(self) -> Any:
        return self._ir_fg

    @property
    def visible_handle(self) -> Any:
        return self._vis_fg

    @property
    def dual_mode(self) -> bool:
        return self._vis_fg is not None

    def open(self) -> None:
        """Open the IR handle; optionally attempt a second IP connection."""
        if ha is None:
            raise RuntimeError("HALCON runtime not installed")
        self._open_handle(IR_STREAM, self.device)
        if self.single_handle:
            return
        for device in self._visible_device_candidates():
            try:
                self._open_handle(VISIBLE_STREAM, device)
                break
            except Exception as exc:
                self._vis_fg = None
                logger.warning(
                    "Camera %s: visible stream open via '%s' failed: %s",
                    self.device, device, exc,
                )
        if self._vis_fg is None:
            logger.warning(
                "Camera %s: no second connection available; visible feed will "
                "be time-sliced on the shared stream", self.device,
            )

    def _visible_device_candidates(self) -> List[str]:
        """Device strings to try for the second (visible) handle.

        A fresh IP connection may be accepted even though HALCON will not
        re-open the already-in-use discovery device ID.
        """
        candidates = []
        ip = _dotted_ip(self.visible_device)
        if ip:
            candidates.append(ip)
        candidates.append(self.device)
        return candidates

    def _open_handle(self, stream: str, device: str) -> None:
        """Open one framegrabber for the given stream on the given device."""
        fg = ha.open_framegrabber(
            "GigEVision2", 0, 0, 0, 0, 0, 0,
            "progressive", -1, "default", -1, "false",
            "default", device, 0, -1,
        )
        ha.set_framegrabber_param(fg, "FLK_TI_StreamDataSourceSelector", stream)
        # The bit depth follows the stream: 16-bit mono for thermal data and
        # the HALCON default (-1) for the visible stream.
        bits = 16 if stream == IR_STREAM else -1
        try:
            ha.set_framegrabber_param(fg, "bits_per_channel", bits)
        except Exception as exc:
            logger.warning(
                "Camera %s: unable to set bits_per_channel for %s: %s",
                self.device, stream, exc,
            )

        try:
            ha.set_framegrabber_param(fg, "[Stream]DeviceStreamChannelNegotiatePacketSize", 1)
        except Exception as exc:
            logger.warning("Camera %s: unable to negotiate packet size: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(fg, "[Stream]GevStreamReceiveSocketSize", 1048576)
        except Exception as exc:
            logger.warning("Camera %s: unable to set socket buffer size: %s", self.device, exc)

        try:
            ha.set_framegrabber_param(fg, "num_buffers", 8)
        except Exception as exc:
            logger.warning("Camera %s: unable to set num_buffers: %s", self.device, exc)

        if stream == IR_STREAM:
            try:
                ha.set_framegrabber_param(
                    fg, "FLK_TI_ControlFeature_SetFrameRate", self.frame_rate
                )
            except Exception as exc:
                logger.warning("Camera %s: unable to set frame rate: %s", self.device, exc)
            try:
                ha.set_framegrabber_param(
                    fg,
                    "FLK_TI_ControlFeature_REControlCmd",
                    "FLK_TI_ControlFeature_REControlCmd_DisableAutomaticFineOffsets",
                )
            except Exception as exc:
                logger.warning("Camera %s: unable to disable automatic NUC: %s", self.device, exc)

        ha.grab_image_start(fg, -1)
        if stream == IR_STREAM:
            self._ir_fg = fg
        else:
            self._vis_fg = fg

    def grab_ir(self, timeout_ms: int = 0) -> Any:
        """Grab the newest IR frame (raises a HALCON timeout when none buffered)."""
        return ha.grab_image_async(self._ir_fg, timeout_ms)

    def grab_visible(self, timeout_ms: int = 0) -> Any:
        """Grab the newest visible frame (raises a HALCON timeout when none buffered)."""
        return ha.grab_image_async(self._vis_fg, timeout_ms)

    def grab(self, timeout_ms: int = 0) -> Any:
        """Grab the newest frame from the shared (single-mode) handle."""
        return ha.grab_image_async(self._ir_fg, timeout_ms)

    def switch_stream(self, stream: str) -> None:
        """Switch the shared stream source cleanly (single-mode fallback)."""
        self.abort()
        self.select_stream(stream)
        self.start_acquisition()
        self.drain()

    def abort(self) -> None:
        """Abort any pending grab so a stream switch starts cleanly."""
        try:
            ha.set_framegrabber_param(self._ir_fg, "do_abort_grab", 1)
        except Exception:
            pass

    def select_stream(self, stream: str) -> None:
        """Select the shared stream source, matching bit depth to the stream."""
        ha.set_framegrabber_param(self._ir_fg, "FLK_TI_StreamDataSourceSelector", stream)
        bits = 16 if stream == IR_STREAM else -1
        try:
            ha.set_framegrabber_param(self._ir_fg, "bits_per_channel", bits)
        except Exception as exc:
            logger.warning(
                "Camera %s: unable to set bits_per_channel for %s: %s",
                self.device, stream, exc,
            )

    def start_acquisition(self) -> None:
        ha.grab_image_start(self._ir_fg, -1)

    def drain(self, max_frames: int = 3) -> None:
        """Drop frames still queued from the previously selected stream."""
        for _ in range(max_frames):
            try:
                image = ha.grab_image_async(self._ir_fg, 0)
                if image is None:
                    break
            except Exception:
                break

    def image_to_numpy(self, image: Any) -> np.ndarray:
        return ha.himage_as_numpy_array(image)

    def ir_image_size(self) -> Tuple[int, int]:
        return self._image_size_for(self._ir_fg)

    def visible_image_size(self) -> Tuple[int, int]:
        return self._image_size_for(self._vis_fg)

    def _image_size_for(self, fg: Any) -> Tuple[int, int]:
        try:
            w = int(ha.get_framegrabber_param(fg, "image_width"))
            h = int(ha.get_framegrabber_param(fg, "image_height"))
            return w, h
        except Exception:
            return FEED_W, FEED_H

    def ir_pixel_format(self) -> str:
        return self._pixel_format_for(self._ir_fg)

    def visible_pixel_format(self) -> str:
        return self._pixel_format_for(self._vis_fg)

    def _pixel_format_for(self, fg: Any) -> str:
        try:
            return str(ha.get_framegrabber_param(fg, "pixel_format"))
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
                    stats[key] = int(ha.get_framegrabber_param(self._ir_fg, name))
                    read_any = True
                    break
                except Exception:
                    continue
        stats["counters_available"] = read_any
        if stats["seen"] > 0:
            stats["packet_loss_percent"] = stats["lost"] / stats["seen"] * 100.0
            stats["percentage_available"] = True
        return stats

    def payload_probe(self, param_names: List[str]) -> Dict[str, Any]:
        """Read a set of framegrabber parameters for payload inspection.

        Returns a param-name -> value map; parameters the device does not
        expose are reported as "<unavailable>". Used by the Dual Component
        strategy to determine whether a single frame can carry both feeds.
        """
        probe: Dict[str, Any] = {}
        for name in param_names:
            try:
                probe[name] = ha.get_framegrabber_param(self._ir_fg, name)
            except Exception:
                probe[name] = "<unavailable>"
        return probe

    def close_visible(self) -> None:
        """Close only the visible handle (dual mode rejected at runtime)."""
        if self._vis_fg is not None:
            try:
                ha.close_framegrabber(self._vis_fg)
            except Exception:
                logger.exception("Error closing visible framegrabber (%s)", self.device)
        self._vis_fg = None

    def close(self) -> None:
        for fg in (self._ir_fg, self._vis_fg):
            if fg is not None:
                try:
                    ha.close_framegrabber(fg)
                except Exception:
                    logger.exception("Error closing framegrabber (%s)", self.device)
        self._ir_fg = None
        self._vis_fg = None


# ---------------------------------------------------------------------------
# Image helpers (display conversion only; raw data is never modified)
# ---------------------------------------------------------------------------


@dataclass
class StrategyResult:
    """One iteration of an acquisition strategy."""

    ir_image: Any = None
    visible_image: Any = None
    payload: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Strategy base class: one acquisition mechanism per subclass.

    Each strategy wraps a HalconAcquisition and defines how the feeds are
    obtained each loop iteration (step()). Diagnostics expose measurements
    like per-direction source-switch latency.
    """

    name = "base"
    visible_capable = False
    # How long without an IR frame before the worker reopens the camera.
    # Strategies that pause IR by design (time-sliced visible bursts) need
    # a longer window than continuous strategies.
    wedge_recovery_s = WEDGE_RECOVERY_S

    def __init__(self, acq: HalconAcquisition) -> None:
        self.acq = acq

    @abstractmethod
    def open(self) -> None:
        """Open the framegrabber(s) and start acquisition."""

    @abstractmethod
    def step(self) -> StrategyResult:
        """Produce the newest available frames for this strategy."""

    def diagnostics(self) -> Dict[str, Any]:
        return {}

    def close(self) -> None:
        if self.acq is not None:
            self.acq.close()


class BaselineStrategy(BaseStrategy):
    """Test A: reproduce halcon_roi_validation.py exactly.

    One framegrabber handle locked to IR_Data, non-blocking newest-frame
    grab per iteration (grab_image_async). No visible feed: this is the
    known-good reference used to measure the camera ceiling.
    """

    name = STRATEGY_BASELINE
    visible_capable = False

    def open(self) -> None:
        self.acq.open()

    def step(self) -> StrategyResult:
        image = self.acq.grab_ir(0)
        return StrategyResult(ir_image=image)


class DualHandleStrategy(BaseStrategy):
    """Test C: two GigE connections, both streaming concurrently.

    The IR handle connects via the discovery device string; the visible
    handle is opened via the camera IP address, which HALCON accepts even
    when it refuses to re-open the in-use device string. Both stream
    continuously; step() pops the newest frame from each non-blockingly.
    """

    name = STRATEGY_DUAL_HANDLE
    visible_capable = True

    def open(self) -> None:
        self.acq.open()

    def step(self) -> StrategyResult:
        ir_image = self.acq.grab_ir(0)
        visible_image = None
        if self.acq.dual_mode:
            visible_image = self.acq.grab_visible(0)
        return StrategyResult(ir_image=ir_image, visible_image=visible_image)

    def diagnostics(self) -> Dict[str, Any]:
        return {"dual_mode": self.acq.dual_mode}


class RapidSwitchStrategy(BaseStrategy):
    """Test B: one handle alternating IR_Data / VL_Data at a hold interval.

    The source is held for `hold_ms` (0 disables the hold timer, so the
    source flips every step). After each switch a blocking first-frame grab
    absorbs the re-sync delay; the rest of the hold uses non-blocking grabs.
    Switch latency is measured per direction and exposed via diagnostics().
    """

    name = STRATEGY_RAPID_SWITCH
    visible_capable = True

    def __init__(self, acq: HalconAcquisition, hold_ms: int = RAPID_SWITCH_HOLD_MS) -> None:
        super().__init__(acq)
        self.hold_ms = hold_ms
        self._source = IR_STREAM
        self._hold_started = 0.0
        self._switch_vis = LatencyMeter()
        self._switch_ir = LatencyMeter()
        self._switch_count = 0

    def open(self) -> None:
        self.acq.open()
        self._source = IR_STREAM
        self._hold_started = time.perf_counter()

    def step(self) -> StrategyResult:
        now = time.perf_counter()
        frame = None
        if self.hold_ms <= 0 or now - self._hold_started >= self.hold_ms / 1000.0:
            self._do_switch()
            frame = self.acq.grab(SWITCH_FIRST_FRAME_TIMEOUT_MS)
            # The hold timer starts once the new source is delivering frames,
            # so the blocking first-frame grab does not consume the hold.
            self._hold_started = time.perf_counter()
        else:
            try:
                frame = self.acq.grab(0)
            except Exception as exc:
                if not _is_grab_timeout(exc):
                    raise
                frame = None
        if self._source == IR_STREAM:
            return StrategyResult(ir_image=frame)
        return StrategyResult(visible_image=frame)

    def _do_switch(self) -> None:
        started = time.perf_counter()
        target = VISIBLE_STREAM if self._source == IR_STREAM else IR_STREAM
        self.acq.switch_stream(target)
        duration_ms = (time.perf_counter() - started) * 1000.0
        if target == VISIBLE_STREAM:
            self._switch_vis.add(duration_ms)
        else:
            self._switch_ir.add(duration_ms)
        self._switch_count += 1
        self._source = target

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "hold_ms": self.hold_ms,
            "switch_count": self._switch_count,
            "switch_to_visible_ms": self._switch_vis.avg(),
            "switch_to_ir_ms": self._switch_ir.avg(),
        }


class TimeSlicedStrategy(BaseStrategy):
    """Time-sliced dual feed: IR priority with periodic visible bursts.

    The camera streams one source at a time (camera-global source selector,
    DeviceStreamChannelCount=1), and switching the source is disruptive, so
    this strategy switches as rarely as possible: IR runs continuously at
    full rate for TIME_SLICE_IR_HOLD_S, then the camera flips to VL_Data for
    a short visible burst (several frames at the visible rate), then back.
    Only two switches per cycle means the IR feed stays smooth while the
    visible feed updates periodically. This mirrors the earlier single-handle
    fallback that produced a stable IR feed.
    """

    name = STRATEGY_TIME_SLICED
    visible_capable = True
    wedge_recovery_s = 6.0

    def __init__(
        self,
        acq: HalconAcquisition,
        ir_hold_s: float = TIME_SLICE_IR_HOLD_S,
        vis_hold_s: float = TIME_SLICE_VIS_HOLD_S,
    ) -> None:
        super().__init__(acq)
        self.ir_hold_s = ir_hold_s
        self.vis_hold_s = vis_hold_s
        self._source = IR_STREAM
        self._phase_started = 0.0
        self._switch_vis = LatencyMeter()
        self._switch_ir = LatencyMeter()
        self._switch_count = 0

    def open(self) -> None:
        self.acq.open()
        self._source = IR_STREAM
        self._phase_started = time.perf_counter()

    def step(self) -> StrategyResult:
        now = time.perf_counter()
        if self._source == IR_STREAM and now - self._phase_started >= self.ir_hold_s:
            self._do_switch(VISIBLE_STREAM)
            self._phase_started = now
            frame = self.acq.grab(SWITCH_FIRST_FRAME_TIMEOUT_MS)
            return StrategyResult(visible_image=frame)
        if self._source == VISIBLE_STREAM and now - self._phase_started >= self.vis_hold_s:
            self._do_switch(IR_STREAM)
            self._phase_started = now
            frame = self.acq.grab(SWITCH_FIRST_FRAME_TIMEOUT_MS)
            return StrategyResult(ir_image=frame)
        try:
            frame = self.acq.grab(0)
        except Exception as exc:
            if not _is_grab_timeout(exc):
                raise
            frame = None
        if self._source == IR_STREAM:
            return StrategyResult(ir_image=frame)
        return StrategyResult(visible_image=frame)

    def _do_switch(self, target: str) -> None:
        started = time.perf_counter()
        self.acq.switch_stream(target)
        duration_ms = (time.perf_counter() - started) * 1000.0
        if target == VISIBLE_STREAM:
            self._switch_vis.add(duration_ms)
        else:
            self._switch_ir.add(duration_ms)
        self._switch_count += 1
        self._source = target

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "hold_ms": int(self.ir_hold_s * 1000),
            "switch_count": self._switch_count,
            "switch_to_visible_ms": self._switch_vis.avg(),
            "switch_to_ir_ms": self._switch_ir.avg(),
        }


class DualComponentStrategy(BaseStrategy):
    """Test D: probe whether one payload can carry IR + visible together.

    Opens a single handle and inspects the camera's payload-related
    parameters plus the acquired frame structure (dimensions, channels,
    byte size). The diagnostics record the evidence: a multi-channel frame
    or a "components" parameter would indicate both feeds arrive in one
    acquisition and the global source selector is not the only mechanism.
    """

    name = STRATEGY_DUAL_COMPONENT
    visible_capable = False

    def open(self) -> None:
        self.acq.open()
        self._probe = self.acq.payload_probe(COMPONENT_PROBE_PARAMS)
        self._combined_feed = "unknown"

    def step(self) -> StrategyResult:
        image = self.acq.grab_ir(0)
        payload: Dict[str, Any] = {}
        if image is not None:
            try:
                raw = self.acq.image_to_numpy(image)
                payload["shape"] = list(raw.shape)
                payload["nbytes"] = int(raw.nbytes)
                payload["ndim"] = int(raw.ndim)
                channels = str(self._probe.get("image_channels", "<unavailable>"))
                multi_channel = raw.ndim >= 3 or (
                    channels.isdigit() and int(channels) > 1
                )
                self._combined_feed = (
                    "yes (multi-channel frame)" if multi_channel else "no (single-channel)"
                )
            except Exception as exc:
                payload["inspect_error"] = str(exc)
        return StrategyResult(ir_image=image, payload=payload)

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "probe": getattr(self, "_probe", {}),
            "combined_feed": getattr(self, "_combined_feed", "unknown"),
        }


def _make_strategy(
    name: str,
    device: str,
    frame_rate: int,
    ip: str,
    hold_ms: int = RAPID_SWITCH_HOLD_MS,
) -> BaseStrategy:
    """Build the strategy + its HalconAcquisition for a camera."""
    if name == STRATEGY_BASELINE:
        acq = HalconAcquisition(device, frame_rate, ip, single_handle=True)
        return BaselineStrategy(acq)
    if name == STRATEGY_RAPID_SWITCH:
        acq = HalconAcquisition(device, frame_rate, ip, single_handle=True)
        return RapidSwitchStrategy(acq, hold_ms)
    if name == STRATEGY_TIME_SLICED:
        acq = HalconAcquisition(device, frame_rate, ip, single_handle=True)
        return TimeSlicedStrategy(acq)
    if name == STRATEGY_DUAL_COMPONENT:
        acq = HalconAcquisition(device, frame_rate, ip, single_handle=True)
        return DualComponentStrategy(acq)
    acq = HalconAcquisition(device, frame_rate, ip)
    return DualHandleStrategy(acq)


def _format_payload(payload: Dict[str, Any]) -> str:
    """Compact one-line summary of a grabbed frame's structure."""
    parts = []
    for key in ("shape", "nbytes", "ndim"):
        if key in payload:
            parts.append(f"{key}={payload[key]}")
    return " ".join(parts)


def _format_probe(probe: Dict[str, Any]) -> str:
    """Compact one-line summary of the Dual Component payload probe."""
    parts = []
    for key, value in probe.items():
        text = str(value)
        if text != "<unavailable>":
            parts.append(f"{key}={text}")
    return " | ".join(parts)


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


def _visible_to_display(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Convert the visible stream numpy array to RGB for display.

    HALCON delivers the VL_Data stream as an RGB8 3-channel array on this
    camera (640x480x3 = 921600 B/f), so the array is used directly. Other
    builds / code paths return packed YUYV; fall back to the decoder and
    finally to luma normalization when neither interpretation applies.
    """
    if arr.ndim == 3 and arr.shape[2] == 3:
        return np.ascontiguousarray(arr)
    rgb = _decode_yuv422_to_rgb(arr, width, height)
    if rgb is not None:
        return rgb
    return _normalize_to_uint8(arr)


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
    strategy: str = STRATEGY_BASELINE
    switch_to_visible_ms: float = 0.0
    switch_to_ir_ms: float = 0.0
    payload_info: str = ""


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
    strategy_applied = pyqtSignal(int, str)
    experiment_result = pyqtSignal(int, object)    # index, List[Dict] rows
    finished = pyqtSignal()

    def __init__(self, index: int, camera_info: Any, frame_rate: int) -> None:
        super().__init__()
        self.index = index
        self._info = camera_info
        self._frame_rate = frame_rate
        self._running = False
        self._connected = False
        self._acq: Optional[HalconAcquisition] = None
        self._strategy: Optional[BaseStrategy] = None
        self._strategy_name = DEFAULT_STRATEGY
        self._hold_ms = RAPID_SWITCH_HOLD_MS
        self._strategy_restart = False
        self._experiment_requested = False
        self._experiment_running = False
        self._payload_info = ""
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
        self._last_ir_frame_at = 0.0
        self._start_time = time.perf_counter()

        self._ir_w = 0
        self._ir_h = 0
        self._ir_bytes = 0
        self._ir_format = ""
        self._vis_w = 0
        self._vis_h = 0
        self._vis_bytes = 0
        self._vis_format = ""

        # Latest display copy per stream. Grabs are non-blocking, so one
        # stream can produce a frame while the other has none ready; the
        # loop emits the newest known copy of each so the GUI never blanks.
        self._last_ir_display: Optional[np.ndarray] = None
        self._last_visible_display: Optional[np.ndarray] = None

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
            self._apply_current_strategy()
            result = self._strategy.step()
            if result.ir_image is None:
                # A first frame may need a moment after acquisition starts.
                first = self._strategy.acq.grab_ir(FIRST_FRAME_TIMEOUT_MS)
                if first is None:
                    raise RuntimeError("No first IR frame received within 5s")
                self._ingest(first, IR_STREAM)
            else:
                self._ingest(result.ir_image, IR_STREAM)
            self._verify_visible_stream()
            self._last_ir_frame_at = time.perf_counter()
            self._connected = True
            self.connected_changed.emit(self.index, True)
            self.strategy_applied.emit(self.index, self._strategy_name)
            self._set_status("Acquiring")
            logger.info("Camera %d connected (%s)", self.index + 1, self._info.serial)
            return True
        except Exception as exc:
            logger.exception("Camera %d connect failed", self.index + 1)
            self._record_error(f"connect failed: {exc}")
            return False

    def set_strategy(self, name: str) -> None:
        """Request a strategy change; the loop applies it on its next pass."""
        if name not in STRATEGY_LABELS:
            return
        self._strategy_name = name
        self._strategy_restart = True

    def set_hold_ms(self, hold_ms: int) -> None:
        """Set the rapid-switch hold interval (ms) for the next restart."""
        self._hold_ms = max(0, int(hold_ms))

    def run_experiment(self) -> None:
        """Request the automated source-switch sweep; loop picks it up."""
        if not self._connected or self._experiment_running:
            return
        self._experiment_requested = True

    def _apply_current_strategy(self) -> None:
        """(Re)build the active strategy and open its framegrabber(s)."""
        if self._acq is not None:
            self._acq.close()
        strategy = _make_strategy(
            self._strategy_name, self._info.device, self._frame_rate, self._info.ip,
            hold_ms=self._hold_ms,
        )
        strategy.open()
        self._strategy = strategy
        self._acq = strategy.acq
        self._visible_enabled = strategy.visible_capable

    def _apply_rapid_switch(self, hold_ms: int) -> None:
        """(Re)build a RapidSwitchStrategy at the given hold interval (ms)."""
        if self._acq is not None:
            self._acq.close()
        strategy = _make_strategy(
            STRATEGY_RAPID_SWITCH, self._info.device, self._frame_rate,
            self._info.ip, hold_ms=hold_ms,
        )
        strategy.open()
        self._strategy = strategy
        self._acq = strategy.acq
        self._visible_enabled = True

    def _verify_visible_stream(self) -> None:
        """Confirm the visible handle really delivers a second source.

        A second GigE connection to the same camera may still present the
        same single stream (camera-global source selector). Detect that by
        comparing the visible frame byte size to the IR frame byte size
        (IR is 16-bit mono, visible is RGB/YUV) and, when identical, drop
        the second handle so the single-handle time-sliced fallback is used.
        """
        if not self._acq.dual_mode:
            return
        try:
            frame = self._acq.grab_visible(2000)
            if frame is None:
                raise RuntimeError("no visible frame")
            raw = self._acq.image_to_numpy(frame)
            if int(raw.nbytes) == self._ir_bytes:
                raise RuntimeError("visible handle echoes the IR source")
        except Exception as exc:
            logger.warning(
                "Camera %d: visible dual-stream unavailable (%s); falling back "
                "to time-sliced visible sampling",
                self.index + 1, exc,
            )
            self._acq.close_visible()

    def _disable_visible(self, reason: str) -> None:
        """Disable visible acquisition and reflect it in the status."""
        if not self._visible_enabled:
            return
        self._visible_enabled = False
        self._last_visible_display = None
        self._set_status(f"IR only ({reason})")
        logger.warning("Camera %d visible stream disabled (%s)", self.index + 1, reason)

    def _acquisition_loop(self) -> None:
        """Main loop: delegate to the active acquisition strategy.

        Each iteration first polls for a strategy change or an experiment
        request, then asks the strategy for its newest frames and routes
        them through metrics/ingest/display. A real stall (no IR frame for
        WEDGE_RECOVERY_S) reopens the camera.
        """
        while self._running:
            if not self._connected:
                time.sleep(0.1)
                continue

            if self._experiment_requested:
                self._run_switch_experiment()
                continue

            if self._strategy_restart:
                self._strategy_restart = False
                self._reopen_framegrabber()
                continue

            if time.perf_counter() - self._last_ir_frame_at > self._strategy.wedge_recovery_s:
                self._reopen_framegrabber()
                continue

            try:
                result = self._strategy.step()
            except Exception as step_exc:
                if not self._is_grab_timeout(step_exc):
                    self._record_error(f"strategy step failed: {step_exc}")
                    time.sleep(0.05)
                else:
                    time.sleep(0.005)
                continue

            if not self._route_result(result):
                time.sleep(0.005)

    def _route_result(self, result: StrategyResult) -> bool:
        """Route one strategy result through metrics, ingest and display.

        Returns True when at least one feed produced a new frame this pass.
        The Dual Component strategy's per-frame payload diagnostics are
        carried into the metrics snapshot.
        """
        ir_display: Optional[np.ndarray] = None
        visible_display: Optional[np.ndarray] = None

        if result.ir_image is not None:
            self._last_ir_frame_at = time.perf_counter()
            self._ir_fps.tick()
            self._acq_fps.tick()
            self._ir_frames += 1
            ir_display, _, _ = self._ingest(result.ir_image, IR_STREAM)

        if result.visible_image is not None and self._visible_enabled:
            self._vis_fps.tick()
            self._acq_fps.tick()
            self._vis_frames += 1
            visible_display, _, _ = self._ingest(result.visible_image, VISIBLE_STREAM)

        if result.payload:
            self._payload_info = _format_payload(result.payload)

        if ir_display is not None:
            self._last_ir_display = ir_display
        if visible_display is not None:
            self._last_visible_display = visible_display

        # Latest-frame delivery: the GUI overwrites its previous frame, so a
        # slow GUI simply sees newer frames (never a growing queue). Each
        # stream reports its newest known copy, so a frame arriving on only
        # one stream never blanks the other feed.
        if ir_display is not None or visible_display is not None:
            self.frame_ready.emit(
                self.index, self._last_ir_display, self._last_visible_display
            )
            self._emit_metrics_if_due()
            return True
        return False

    def _run_switch_experiment(self) -> None:
        """Sweep rapid-switch hold intervals and report measured results.

        For each interval in SWEEP_INTERVALS_MS the camera is re-opened in
        rapid-switch mode, runs for SWEEP_PER_INTERVAL_S, and per-interval
        IR/VIS FPS, frame counts, errors and switch latencies are captured.
        The selected interactive strategy is restored afterwards.
        """
        self._experiment_requested = False
        self._experiment_running = True
        self._set_status("Experiment running")
        rows: List[Dict[str, Any]] = []
        try:
            saved = self._strategy_name
            for interval in SWEEP_INTERVALS_MS:
                if not self._running:
                    break
                logger.info(
                    "Camera %d: experiment interval %d ms", self.index + 1, interval
                )
                self._apply_rapid_switch(interval)
                self._reset_rate_meters()
                ir_before = self._ir_frames
                vis_before = self._vis_frames
                errors = 0
                started = time.perf_counter()
                while self._running and time.perf_counter() - started < SWEEP_PER_INTERVAL_S:
                    try:
                        result = self._strategy.step()
                    except Exception as step_exc:
                        if not self._is_grab_timeout(step_exc):
                            errors += 1
                        time.sleep(0.005)
                        continue
                    self._route_result(result)
                diag = self._strategy.diagnostics()
                rows.append({
                    "interval_ms": interval,
                    "ir_fps": self._ir_fps.fps(),
                    "vis_fps": self._vis_fps.fps(),
                    "ir_frames": self._ir_frames - ir_before,
                    "vis_frames": self._vis_frames - vis_before,
                    "errors": errors,
                    "switch_to_visible_ms": diag.get("switch_to_visible_ms", 0.0),
                    "switch_to_ir_ms": diag.get("switch_to_ir_ms", 0.0),
                })
            self._strategy_name = saved
            self._apply_current_strategy()
            self._last_ir_frame_at = time.perf_counter()
        except Exception as exc:
            self._record_error(f"experiment failed: {exc}")
        finally:
            self._experiment_running = False
            if self._connected:
                self._set_status("Acquiring")
        self.experiment_result.emit(self.index, rows)

    def _reset_rate_meters(self) -> None:
        self._ir_fps.reset()
        self._vis_fps.reset()
        self._acq_fps.reset()
        self._proc_fps.reset()
        self._ir_latency.reset()
        self._vis_latency.reset()
        self._proc_latency.reset()

    def _reopen_framegrabber(self) -> None:
        """Close and reopen the active strategy's framegrabber after a stall.

        Applies the currently selected strategy (including a pending change
        requested from the GUI). Deliberately touches nothing else; a
        recovery failure marks the camera disconnected while the other
        cameras keep streaming.
        """
        logger.warning(
            "Camera %d: IR stream stalled, reopening framegrabber", self.index + 1
        )
        self._set_status("Reconnecting")
        try:
            self._apply_current_strategy()
            result = self._strategy.step()
            if result.ir_image is None:
                first = self._strategy.acq.grab_ir(FIRST_FRAME_TIMEOUT_MS)
                if first is None:
                    raise RuntimeError("No first IR frame after reopen")
                self._ingest(first, IR_STREAM)
            else:
                self._ingest(result.ir_image, IR_STREAM)
            self._verify_visible_stream()
            self._last_ir_frame_at = time.perf_counter()
            self._timeouts += 1
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
                self._ir_w, self._ir_h = self._acq.ir_image_size()
                self._ir_format = self._acq.ir_pixel_format()
                self._ir_bytes = int(raw.nbytes)
            display = _normalize_to_uint8(raw)
            # In dual mode the camera-global source selector is shared: if
            # the visible handle flips the whole camera to VL_Data, the IR
            # handle suddenly delivers RGB instead of 16-bit mono. The byte
            # size change is the tell, so disable the conflicting dual-stream.
            if (
                self._acq.dual_mode
                and self._ir_bytes
                and int(raw.nbytes) != self._ir_bytes
            ):
                logger.warning(
                    "Camera %d: IR frame size changed; stream source conflict, "
                    "disabling visible dual-stream",
                    self.index + 1,
                )
                self._acq.close_visible()
                self._disable_visible("stream source conflict")
                try:
                    self._acq.select_stream(IR_STREAM)
                    self._acq.start_acquisition()
                except Exception:
                    pass
        else:
            if not self._vis_w:
                self._vis_w, self._vis_h = self._acq.visible_image_size()
                self._vis_format = self._acq.visible_pixel_format()
                self._vis_bytes = int(raw.nbytes)
            display = _visible_to_display(raw, self._vis_w or FEED_W, self._vis_h or FEED_H)

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

        strategy_diag: Dict[str, Any] = {}
        if self._strategy is not None:
            strategy_diag = self._strategy.diagnostics()
        switch_vis_ms = float(strategy_diag.get("switch_to_visible_ms") or 0.0)
        switch_ir_ms = float(strategy_diag.get("switch_to_ir_ms") or 0.0)
        payload_info = self._payload_info
        probe = strategy_diag.get("probe")
        if probe:
            probe_text = _format_probe(probe)
            payload_info = probe_text if not payload_info else f"{payload_info} | {probe_text}"

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
            strategy=self._strategy_name,
            switch_to_visible_ms=switch_vis_ms,
            switch_to_ir_ms=switch_ir_ms,
            payload_info=payload_info,
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
        if self._strategy is not None:
            self._strategy.close()
            self._strategy = None
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
        return _is_grab_timeout(exc)


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
            f"Switch VIS {m.switch_to_visible_ms:.0f} ms | IR {m.switch_to_ir_ms:.0f} ms\n"
            f"Strategy: {m.strategy}\n"
            f"Frames IR {m.ir_frames} / VIS {m.visible_frames} | "
            f"Timeouts {m.timeouts} | Errors {m.errors}\n"
            f"Avg IR {m.avg_ir_fps:.1f} / VIS {m.avg_vis_fps:.1f} FPS | "
            f"{pkt_label} | {m.status}"
        )
        if m.payload_info:
            text += f"\nPayload: {m.payload_info}"
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

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Strategy"))
        self.combo_strategy = QComboBox()
        for strategy in STRATEGY_ORDER:
            self.combo_strategy.addItem(STRATEGY_LABELS[strategy], strategy)
        index = STRATEGY_ORDER.index(DEFAULT_STRATEGY)
        self.combo_strategy.setCurrentIndex(index)
        self.combo_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        toolbar.addWidget(self.combo_strategy)

        self.btn_experiment = QPushButton("Run Switch Experiment")
        self.btn_experiment.clicked.connect(self._on_run_experiment)
        toolbar.addWidget(self.btn_experiment)

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

        self.experiment_view = QPlainTextEdit()
        self.experiment_view.setReadOnly(True)
        self.experiment_view.setMaximumHeight(150)
        self.experiment_view.setFont(QFont("Consolas", 9))
        self.experiment_view.setPlaceholderText(
            "Switch-interval experiment results will appear here."
        )
        self.experiment_view.setStyleSheet(
            "background: #1E1E1E; color: #C8C8C8; border: 1px solid #3C3C3C;"
        )
        main_layout.addWidget(self.experiment_view)

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
        worker.strategy_applied.connect(self._on_strategy_applied)
        worker.experiment_result.connect(self._on_experiment_result)
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
    # Strategy / experiment controls
    # ---------------------------------------------------------------

    def _on_strategy_changed(self, index: int) -> None:
        strategy = self.combo_strategy.itemData(index)
        for worker in list(self._workers.values()):
            worker.set_strategy(strategy)

    def _on_run_experiment(self) -> None:
        self.experiment_view.clear()
        self.statusBar().showMessage("Running switch-interval experiment...", 5000)
        for worker in list(self._workers.values()):
            worker.run_experiment()

    def _on_strategy_applied(self, index: int, strategy: str) -> None:
        logger.info("Camera %d strategy applied: %s", index + 1, strategy)

    def _on_experiment_result(self, index: int, rows: object) -> None:
        lines = [f"Camera {index + 1} switch-interval experiment"]
        header = (
            "Interval     IR FPS     VIS FPS   IR frm  VIS frm  Errors  "
            "VIS sw(ms)  IR sw(ms)"
        )
        lines.append(header)
        lines.append("-" * len(header))
        for row in rows:
            lines.append(
                f"{row['interval_ms']:>6} ms   {row['ir_fps']:>7.2f}   "
                f"{row['vis_fps']:>7.2f}   {row['ir_frames']:>6}   "
                f"{row['vis_frames']:>6}   {row['errors']:>6}   "
                f"{row['switch_to_visible_ms']:>8.1f}   {row['switch_to_ir_ms']:>8.1f}"
            )
        text = "\n".join(lines)
        self.experiment_view.setPlainText(text)
        logger.info("Camera %d experiment:\n%s", index + 1, text)

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
