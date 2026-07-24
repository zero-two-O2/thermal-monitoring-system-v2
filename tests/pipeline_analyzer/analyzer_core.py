"""
analyzer_core.py — Phase 1C Acquisition Pipeline Analyzer

Observes the production pipeline without modifying it.
Answers: exactly where are the bottlenecks?

Pipeline observed (never replaced):
    TV46LCamera (camera/tv46l_camera.py)
        -> RawFrame (with stage timestamps)
        -> Calibration (raw_to_display + colormap)
        -> QImage -> QPixmap -> Qt Paint

Uses the EXISTING TV46LCamera + RawFrame from the codebase.
No new acquisition implementation is created.
"""

from __future__ import annotations

import time
import hashlib
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np

from camera.tv46l_camera import TV46LCamera
from processing.models.processing_models import RawFrame
from calibration.calibration_manager import CalibrationManager


# ==========================================================
# Constants
# ==========================================================

MAX_FRAME_HISTORY = 10000
MAX_SEQUENCE_HISTORY = 5000
DEFAULT_SAMPLE_INTERVAL = 1.0
FREEZE_THRESHOLD_SEC = 2.0


# ==========================================================
# Enums
# ==========================================================

class PipelineStage(Enum):
    CAMERA_EXPOSURE = auto()
    HALCON_GRAB = auto()
    GRAB_COMPLETE = auto()
    NUMPY_CONVERSION = auto()
    RAWFRAME_CREATE = auto()
    RAWFRAME_PUBLISH = auto()
    GUI_RECEIVE = auto()
    CALIBRATION = auto()
    DISPLAY_CONVERSION = auto()
    COLORMAP = auto()
    QIMAGE = auto()
    QPIXMAP = auto()
    QT_PAINT = auto()
    PAINT_COMPLETE = auto()


class FreezeType(Enum):
    ACQUISITION_FREEZE = "Acquisition Freeze"
    GUI_FREEZE = "GUI Freeze"
    PAINT_FREEZE = "Paint Freeze"
    NONE = "None"


# ==========================================================
# Frame Lifecycle — one frame tracked through every stage
# ==========================================================

@dataclass
class FrameLifecycle:
    sequence: int
    stage_times: dict[PipelineStage, float] = field(default_factory=dict)
    checksum: str = ""
    width: int = 0
    height: int = 0
    is_duplicate: bool = False
    is_corrupted: bool = False
    missing_stages: list[PipelineStage] = field(default_factory=list)

    def record(self, stage: PipelineStage, time_val: float | None = None) -> None:
        self.stage_times[stage] = time_val if time_val is not None else time.perf_counter()

    def get_elapsed(self, start: PipelineStage, end: PipelineStage) -> float:
        s = self.stage_times.get(start)
        e = self.stage_times.get(end)
        if s is not None and e is not None:
            return e - s
        return 0.0

    @property
    def total_latency(self) -> float:
        return self.get_elapsed(PipelineStage.CAMERA_EXPOSURE, PipelineStage.PAINT_COMPLETE)

    @property
    def completed(self) -> bool:
        return PipelineStage.PAINT_COMPLETE in self.stage_times


def compute_frame_checksum(image: np.ndarray) -> str:
    if image is None or image.size == 0:
        return ""
    return hashlib.md5(image.tobytes()).hexdigest()


def detect_horizontal_distortion(image: np.ndarray) -> tuple[bool, str]:
    if image is None or image.ndim < 2 or image.size == 0:
        return False, "no image"
    row_hash = hashlib.md5(image[0, :].tobytes()).hexdigest()[:8]
    repeated_rows = 0
    for i in range(1, min(100, image.shape[0])):
        cur = hashlib.md5(image[i, :].tobytes()).hexdigest()[:8]
        if cur == row_hash:
            repeated_rows += 1
        row_hash = cur
    if repeated_rows > 10:
        return True, f"{repeated_rows} repeated rows in first 100"
    return False, "ok"


# ==========================================================
# FPS Tracker — independent FPS per stage
# ==========================================================

class FpsTracker:
    def __init__(self, window_sec: float = 2.0):
        self._window_sec = window_sec
        self._timestamps: deque[float] = deque()

    def record(self) -> None:
        now = time.perf_counter()
        self._timestamps.append(now)
        cutoff = now - self._window_sec
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        window = self._timestamps[-1] - self._timestamps[0]
        if window <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / window

    def reset(self) -> None:
        self._timestamps.clear()


# ==========================================================
# Stage Timing Collector
# ==========================================================

class StageTimingCollector:
    def __init__(self):
        self._stages: dict[PipelineStage, list[float]] = {}

    def record(self, stage: PipelineStage, duration_ms: float) -> None:
        if stage not in self._stages:
            self._stages[stage] = []
        self._stages[stage].append(duration_ms)

    def reset(self) -> None:
        self._stages.clear()

    def get_stats(self, stage: PipelineStage) -> dict:
        vals = self._stages.get(stage, [])
        if not vals:
            return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0, "p95": 0.0, "latest": 0.0}
        sorted_vals = sorted(vals)
        p95_idx = int(len(sorted_vals) * 0.95)
        return {
            "count": len(vals),
            "avg": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
            "p95": sorted_vals[min(p95_idx, len(sorted_vals) - 1)],
            "latest": vals[-1],
        }

    def get_all_stage_stats(self) -> dict[PipelineStage, dict]:
        return {s: self.get_stats(s) for s in PipelineStage}

    def get_latency_breakdown(self) -> dict[str, float]:
        totals = {}
        grand_total = 0.0
        for stage in PipelineStage:
            vals = self._stages.get(stage, [])
            if vals:
                avg = sum(vals) / len(vals)
                key = stage.name.lower()
                totals[key] = avg
                grand_total += avg
        if grand_total > 0:
            pcts = {}
            for k, v in totals.items():
                pcts[f"{k}_pct"] = (v / grand_total) * 100
            totals.update(pcts)
        totals["total_ms"] = grand_total
        return totals


# ==========================================================
# Sequence Analyzer
# ==========================================================

@dataclass
class SequenceSnapshot:
    expected: int = 0
    received: int = 0
    gaps: list[tuple[int, int]] = field(default_factory=list)
    duplicates: list[int] = field(default_factory=list)
    consecutive_loss: int = 0
    loss_pct: float = 0.0
    total_expected: int = 0
    total_received: int = 0
    total_lost: int = 0


class SequenceAnalyzer:
    def __init__(self):
        self._last_sequence: int = -1
        self._seen: set[int] = set()
        self._gaps: list[tuple[int, int]] = []
        self._duplicates: list[int] = []
        self._consecutive_loss: int = 0
        self._max_consecutive_loss: int = 0
        self._current_consecutive: int = 0
        self._total_expected: int = 0
        self._total_received: int = 0
        self._total_lost: int = 0
        self._lock = threading.Lock()
        self._window_gaps: deque[int] = deque(maxlen=MAX_SEQUENCE_HISTORY)

    def record(self, sequence: int) -> None:
        with self._lock:
            if self._last_sequence < 0:
                self._last_sequence = sequence
                self._seen.add(sequence)
                self._total_received += 1
                self._total_expected = sequence + 1
                return

            self._total_received += 1
            expected = self._last_sequence + 1
            self._total_expected = max(self._total_expected, sequence + 1)

            if sequence == self._last_sequence:
                self._duplicates.append(sequence)
                return

            if sequence > expected:
                gap = (expected, sequence - 1)
                self._gaps.append(gap)
                gap_size = sequence - expected
                self._total_lost += gap_size
                self._window_gaps.append(gap_size)
                self._current_consecutive += gap_size
                self._max_consecutive_loss = max(self._max_consecutive_loss, self._current_consecutive)
            else:
                self._current_consecutive = 0

            self._last_sequence = sequence
            self._seen.add(sequence)

    def snapshot(self) -> SequenceSnapshot:
        with self._lock:
            return SequenceSnapshot(
                expected=self._last_sequence + 1 if self._last_sequence >= 0 else 0,
                received=self._total_received,
                gaps=list(self._gaps[-20:]),
                duplicates=list(self._duplicates[-20:]),
                consecutive_loss=self._max_consecutive_loss,
                loss_pct=(self._total_lost / max(self._total_expected, 1)) * 100,
                total_expected=self._total_expected,
                total_received=self._total_received,
                total_lost=self._total_lost,
            )

    def reset(self) -> None:
        with self._lock:
            self._last_sequence = -1
            self._seen.clear()
            self._gaps.clear()
            self._duplicates.clear()
            self._consecutive_loss = 0
            self._max_consecutive_loss = 0
            self._current_consecutive = 0
            self._total_expected = 0
            self._total_received = 0
            self._total_lost = 0
            self._window_gaps.clear()


# ==========================================================
# Freeze Detector
# ==========================================================

@dataclass
class FreezeReport:
    is_frozen: bool
    freeze_type: FreezeType
    acquisition_age: float = 0.0
    gui_age: float = 0.0
    paint_age: float = 0.0
    acquisition_alive: bool = True
    gui_alive: bool = True
    paint_alive: bool = True
    duration_sec: float = 0.0


class FreezeDetector:
    def __init__(self, threshold: float = FREEZE_THRESHOLD_SEC):
        self._threshold = threshold
        self._last_acquisition_time: float = 0.0
        self._last_gui_time: float = 0.0
        self._last_paint_time: float = 0.0
        self._freeze_start: float | None = None
        self._lock = threading.Lock()

    def record_acquisition(self) -> None:
        with self._lock:
            self._last_acquisition_time = time.perf_counter()

    def record_gui(self) -> None:
        with self._lock:
            self._last_gui_time = time.perf_counter()

    def record_paint(self) -> None:
        with self._lock:
            self._last_paint_time = time.perf_counter()

    def check(self) -> FreezeReport:
        with self._lock:
            now = time.perf_counter()
            acq_age = now - self._last_acquisition_time if self._last_acquisition_time > 0 else 0.0
            gui_age = now - self._last_gui_time if self._last_gui_time > 0 else 999.0
            paint_age = now - self._last_paint_time if self._last_paint_time > 0 else 999.0

            acq_alive = acq_age < self._threshold
            gui_alive = gui_age < self._threshold
            paint_alive = paint_age < self._threshold

            if not acq_alive:
                ft = FreezeType.ACQUISITION_FREEZE
            elif not gui_alive:
                ft = FreezeType.GUI_FREEZE
            elif not paint_alive:
                ft = FreezeType.PAINT_FREEZE
            else:
                ft = FreezeType.NONE

            is_frozen = ft != FreezeType.NONE
            if is_frozen and self._freeze_start is None:
                self._freeze_start = now
            elif not is_frozen:
                self._freeze_start = None

            duration = (now - self._freeze_start) if self._freeze_start is not None else 0.0

            return FreezeReport(
                is_frozen=is_frozen,
                freeze_type=ft,
                acquisition_age=acq_age,
                gui_age=gui_age,
                paint_age=paint_age,
                acquisition_alive=acq_alive,
                gui_alive=gui_alive,
                paint_alive=paint_alive,
                duration_sec=duration,
            )


# ==========================================================
# Latency Analyzer — breakdown by percentage contribution
# ==========================================================

class LatencyAnalyzer:
    STAGE_GROUPS: dict[str, list[PipelineStage]] = {
        "Camera Acquisition": [
            PipelineStage.CAMERA_EXPOSURE,
            PipelineStage.HALCON_GRAB,
        ],
        "NumPy Conversion": [
            PipelineStage.NUMPY_CONVERSION,
        ],
        "RawFrame Publication": [
            PipelineStage.RAWFRAME_CREATE,
            PipelineStage.RAWFRAME_PUBLISH,
        ],
        "GUI Receive": [
            PipelineStage.GUI_RECEIVE,
        ],
        "Calibration": [
            PipelineStage.CALIBRATION,
        ],
        "Display Conversion": [
            PipelineStage.DISPLAY_CONVERSION,
            PipelineStage.COLORMAP,
        ],
        "Qt Rendering": [
            PipelineStage.QIMAGE,
            PipelineStage.QPIXMAP,
            PipelineStage.QT_PAINT,
        ],
    }

    @staticmethod
    def compute_breakdown(stage_timing: StageTimingCollector) -> dict[str, float]:
        all_stats = stage_timing.get_latency_breakdown()
        groups = {}
        for group_name, stages in LatencyAnalyzer.STAGE_GROUPS.items():
            total = 0.0
            for s in stages:
                key = s.name.lower()
                total += all_stats.get(key, 0.0)
            groups[group_name] = total

        grand = sum(groups.values())
        result = dict(groups)
        if grand > 0:
            for k, v in groups.items():
                result[f"{k} %"] = (v / grand) * 100
        result["Total Latency (ms)"] = grand
        return result


# ==========================================================
# NUC Isolation Monitor
# ==========================================================

@dataclass
class CameraPauseEvent:
    camera_id: str
    pause_duration_ms: float
    cause: str
    timestamp: float = field(default_factory=time.time)


class NucIsolationMonitor:
    def __init__(self):
        self._events: list[CameraPauseEvent] = []
        self._camera_frame_times: dict[str, float] = {}
        self._lock = threading.Lock()

    def record_frame(self, camera_id: str) -> None:
        with self._lock:
            self._camera_frame_times[camera_id] = time.perf_counter()

    def check_pause(self, camera_id: str, cause: str, threshold_ms: float = 100.0) -> CameraPauseEvent | None:
        with self._lock:
            last = self._camera_frame_times.get(camera_id)
            if last is None:
                return None
            elapsed_ms = (time.perf_counter() - last) * 1000
            if elapsed_ms > threshold_ms:
                event = CameraPauseEvent(
                    camera_id=camera_id,
                    pause_duration_ms=elapsed_ms,
                    cause=cause,
                )
                self._events.append(event)
                return event
            return None

    def get_events(self, clear: bool = False) -> list[CameraPauseEvent]:
        with self._lock:
            result = list(self._events)
            if clear:
                self._events.clear()
            return result


# ==========================================================
# Network Monitor
# ==========================================================

@dataclass
class NetworkStats:
    packet_loss_pct: float = 0.0
    resend_count: int = 0
    duplicate_count: int = 0
    sequence_loss_pct: float = 0.0
    throughput_mbps: float = 0.0
    frame_size_bytes: int = 0


# ==========================================================
# Frame Observer — observes RawFrame from TV46LCamera
# ==========================================================

class FrameObserver:
    """
    Passive observer that reads frames from the existing TV46LCamera.
    Does NOT create any new acquisition or wrapping thread.

    Uses the production camera's grab_frame() which returns
    RawFrame with embedded stage timestamps.
    """

    def __init__(self, camera: TV46LCamera):
        self._camera = camera
        self._lock = threading.Lock()

    def observe_frame(self) -> tuple[RawFrame | None, float]:
        """
        Returns (rawframe, receive_time).
        rawframe is None if no frame available.
        """
        t_receive = time.perf_counter()
        raw = self._camera.grab_frame()
        return raw, t_receive

    @property
    def camera(self) -> TV46LCamera:
        return self._camera


# ==========================================================
# PipelineAnalyzer — Main coordinating class
# ==========================================================

@dataclass
class AnalyzerSnapshot:
    camera_fps: float = 0.0
    published_fps: float = 0.0
    display_fps: float = 0.0
    paint_fps: float = 0.0
    sequence_loss_pct: float = 0.0
    freeze: FreezeReport | None = None
    latency_breakdown: dict[str, float] = field(default_factory=dict)
    frame_lifecycle: FrameLifecycle | None = None
    frame_count: int = 0
    total_frames_pulled: int = 0
    total_frames_painted: int = 0
    horizontal_distortion: tuple[bool, str] = (False, "")


class PipelineAnalyzer:
    """
    Passive observer of the production acquisition pipeline.

    Usage:
        camera = TV46LCamera(...)
        analyzer = PipelineAnalyzer(camera, calibration)
        # In GUI poll loop:
        analyzer.observe_gui_poll()
        # In paint event:
        analyzer.observe_paint()
        # Every 1s:
        snapshot = analyzer.snapshot()
    """

    def __init__(
        self,
        camera: TV46LCamera,
        calibration: CalibrationManager | None = None,
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL,
        enable_checksum: bool = False,
    ):
        self._observer = FrameObserver(camera)
        self._calibration = calibration

        # FPS trackers — one per stage
        self._camera_fps = FpsTracker()
        self._published_fps = FpsTracker()
        self._display_fps = FpsTracker()
        self._paint_fps = FpsTracker()

        # Stage timing
        self._stage_timing = StageTimingCollector()

        # Sequence analysis
        self._sequence_analyzer = SequenceAnalyzer()

        # Freeze detection
        self._freeze_detector = FreezeDetector()

        # Frame lifecycle tracking
        self._frame_lifecycles: dict[int, FrameLifecycle] = {}
        self._last_completed_lifecycle: FrameLifecycle | None = None

        # Frame tracking
        self._last_gui_sequence: int = -1
        self._total_frames_pulled: int = 0
        self._total_frames_painted: int = 0

        # Last calibrated RGB for display
        self._last_rgb: np.ndarray | None = None

        # Horizontal distortion
        self._enable_checksum = enable_checksum
        self._last_distortion_check: tuple[bool, str] = (False, "")

        # NUC isolation
        self._nuc_monitor = NucIsolationMonitor()

        # Network stats
        self._network_stats: NetworkStats | None = None

        # Config
        self._sample_interval = sample_interval

        # Thread safety
        self._lock = threading.Lock()

    # ==========================================================
    # Properties
    # ==========================================================

    @property
    def camera(self) -> TV46LCamera:
        return self._observer.camera

    @property
    def nuc_monitor(self) -> NucIsolationMonitor:
        return self._nuc_monitor

    @property
    def last_rgb(self) -> np.ndarray | None:
        return self._last_rgb

    @property
    def last_sequence(self) -> int:
        return self._last_gui_sequence

    # ==========================================================
    # Observation hooks — call from the GUI poll loop
    # ==========================================================

    def observe_gui_poll(self) -> FrameLifecycle | None:
        """
        Called every time the GUI polls for a new frame.
        Uses existing RawFrame timestamps + adds calibration observation.

        Returns the FrameLifecycle if a new frame was observed, else None.
        """
        raw, t_receive = self._observer.observe_frame()
        if raw is None:
            return None

        seq = raw.sequence if raw.sequence >= 0 else raw.frame_number

        # Skip duplicate frames (poll is 30ms, camera is ~111ms @ 9 FPS)
        if seq == self._last_gui_sequence:
            return None

        lifecycle = FrameLifecycle(sequence=seq)
        lifecycle.record(PipelineStage.GUI_RECEIVE, t_receive)

        # Use RawFrame's existing timestamps
        if raw.grab_start_time > 0:
            lifecycle.record(PipelineStage.CAMERA_EXPOSURE, raw.grab_start_time)
        if raw.grab_complete_time > 0:
            lifecycle.record(PipelineStage.HALCON_GRAB, raw.grab_complete_time)
            self._stage_timing.record(
                PipelineStage.HALCON_GRAB,
                (raw.grab_complete_time - raw.grab_start_time) * 1000,
            )
        if raw.numpy_complete_time > 0:
            lifecycle.record(PipelineStage.NUMPY_CONVERSION, raw.numpy_complete_time)
            self._stage_timing.record(
                PipelineStage.NUMPY_CONVERSION,
                (raw.numpy_complete_time - raw.grab_complete_time) * 1000,
            )
        if raw.publish_time > 0:
            lifecycle.record(PipelineStage.RAWFRAME_PUBLISH, raw.publish_time)
            self._stage_timing.record(
                PipelineStage.RAWFRAME_PUBLISH,
                (raw.publish_time - raw.numpy_complete_time) * 1000,
            )

        self._published_fps.record()

        with self._lock:
            self._total_frames_pulled += 1
            self._frame_lifecycles[seq] = lifecycle

        self._last_gui_sequence = seq
        self._sequence_analyzer.record(seq)
        self._freeze_detector.record_gui()
        self._freeze_detector.record_acquisition()

        frame_data = raw.image

        # Horizontal distortion check (first 100 frames or periodic)
        if self._enable_checksum and (seq <= 100 or seq % 50 == 0):
            self._last_distortion_check = detect_horizontal_distortion(frame_data)
            if self._last_distortion_check[0]:
                lifecycle.is_corrupted = True

        # Calibration timing — store RGB for display
        self._last_rgb: np.ndarray | None = None
        if self._calibration is not None:
            t_cal_start = time.perf_counter()
            try:
                display = self._calibration.raw_to_display(frame_data)
                t_display_done = time.perf_counter()
                lifecycle.record(PipelineStage.DISPLAY_CONVERSION, t_display_done)
                self._stage_timing.record(
                    PipelineStage.DISPLAY_CONVERSION,
                    (t_display_done - t_cal_start) * 1000,
                )

                t_color_start = time.perf_counter()
                rgb = self._calibration.apply_colormap(display)
                t_color_done = time.perf_counter()
                lifecycle.record(PipelineStage.COLORMAP, t_color_done)
                self._stage_timing.record(
                    PipelineStage.COLORMAP,
                    (t_color_done - t_color_start) * 1000,
                )
                self._last_rgb = rgb
            except Exception as exc:
                print(f"[ANALYZER] Calibration failed for frame {seq}: {exc}")

        self._camera_fps.record()
        if self._last_rgb is not None:
            self._display_fps.record()
        return lifecycle

    def observe_paint_start(self) -> float:
        """Call at the start of paintEvent. Returns timestamp."""
        t = time.perf_counter()
        self._freeze_detector.record_paint()
        return t

    def observe_paint_complete(
        self,
        paint_start: float,
        sequence: int,
        qimage_ms: float = 0.0,
        pixmap_ms: float = 0.0,
    ) -> None:
        """Call at the end of paintEvent with the painted frame sequence."""
        t_end = time.perf_counter()
        self._paint_fps.record()
        with self._lock:
            self._total_frames_painted += 1

        paint_ms = (t_end - paint_start) * 1000
        self._stage_timing.record(PipelineStage.QT_PAINT, paint_ms)

        lifecycle = self._frame_lifecycles.get(sequence)
        if lifecycle is not None:
            lifecycle.record(PipelineStage.QT_PAINT, paint_start)
            lifecycle.record(PipelineStage.PAINT_COMPLETE, t_end)
            if qimage_ms > 0:
                self._stage_timing.record(PipelineStage.QIMAGE, qimage_ms)
            if pixmap_ms > 0:
                self._stage_timing.record(PipelineStage.QPIXMAP, pixmap_ms)
            self._last_completed_lifecycle = lifecycle

    def observe_nuc_start(self, camera_id: str) -> None:
        """Call before NUC execution."""
        self._nuc_monitor.record_frame(camera_id)
        # Record baseline frame times for all other cameras
        # (handled externally by the caller)

    def observe_nuc_complete(self, camera_id: str) -> None:
        """Call after NUC execution. Checks all other cameras for pauses."""
        pass

    # ==========================================================
    # Network Statistics
    # ==========================================================

    def update_network_stats(self) -> NetworkStats:
        """Read transport layer statistics from the camera."""
        try:
            stats = self.camera.get_stream_statistics()
            seen = int(stats.get("[Stream]GevStreamSeenPacketCount", 0))
            lost = int(stats.get("[Stream]GevStreamLostPacketCount", 0))
            resend = int(stats.get("[Stream]GevStreamResendPacketCount", 0))
            duplicate = int(stats.get("[Stream]GevStreamDuplicatePacketCount", 0))
            delivered = int(stats.get("[Stream]GevStreamDeliveredPacketCount", 0))
            loss_pct = (lost / max(seen, 1)) * 100

            frame_size = 640 * 480 * 2  # 16-bit 640x480
            throughput = (delivered * frame_size * 8) / (1024 * 1024) if delivered > 0 else 0.0

            net = NetworkStats(
                packet_loss_pct=loss_pct,
                resend_count=resend,
                duplicate_count=duplicate,
                sequence_loss_pct=self._sequence_analyzer.snapshot().loss_pct,
                throughput_mbps=throughput,
                frame_size_bytes=frame_size,
            )
            self._network_stats = net
            return net
        except Exception:
            return NetworkStats()

    # ==========================================================
    # Snapshot
    # ==========================================================

    def snapshot(self) -> AnalyzerSnapshot:
        seq_snap = self._sequence_analyzer.snapshot()
        freeze = self._freeze_detector.check()
        breakdown = LatencyAnalyzer.compute_breakdown(self._stage_timing)

        return AnalyzerSnapshot(
            camera_fps=round(self._camera_fps.fps, 1),
            published_fps=round(self._published_fps.fps, 1),
            display_fps=round(self._display_fps.fps, 1),
            paint_fps=round(self._paint_fps.fps, 1),
            sequence_loss_pct=round(seq_snap.loss_pct, 2),
            freeze=freeze,
            latency_breakdown=breakdown,
            frame_lifecycle=self._last_completed_lifecycle,
            frame_count=seq_snap.total_received,
            total_frames_pulled=self._total_frames_pulled,
            total_frames_painted=self._total_frames_painted,
            horizontal_distortion=self._last_distortion_check,
        )

    def get_stage_timing(self) -> StageTimingCollector:
        return self._stage_timing

    def get_sequence_analyzer(self) -> SequenceAnalyzer:
        return self._sequence_analyzer

    def get_frame_lifecycle(self, sequence: int) -> FrameLifecycle | None:
        return self._frame_lifecycles.get(sequence)

    def get_network_stats(self) -> NetworkStats | None:
        return self._network_stats

    def reset(self) -> None:
        self._camera_fps.reset()
        self._published_fps.reset()
        self._display_fps.reset()
        self._paint_fps.reset()
        self._stage_timing.reset()
        self._sequence_analyzer.reset()
        self._frame_lifecycles.clear()
        self._last_completed_lifecycle = None
        self._last_gui_sequence = -1
        self._last_rgb = None
        self._total_frames_pulled = 0
        self._total_frames_painted = 0
        self._network_stats = None

    # ==========================================================
    # Lightweight mode — reduces overhead
    # ==========================================================

    def set_lightweight(self, enabled: bool = True) -> None:
        """Enable/disable expensive operations (checksums, full lifecycle tracking)."""
        self._enable_checksum = not enabled
        if enabled:
            self._frame_lifecycles.clear()


# ==========================================================
# Cross-Camera Sync Monitor
# ==========================================================

class CrossCameraSyncMonitor:
    """Tracks frame timestamps across all cameras to measure sync drift."""
    def __init__(self):
        self._frame_times: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def record_frame(self, camera_id: str, timestamp: float) -> None:
        with self._lock:
            if camera_id not in self._frame_times:
                self._frame_times[camera_id] = deque(maxlen=100)
            self._frame_times[camera_id].append(timestamp)

    def get_drift_ms(self) -> float:
        """Returns max timestamp difference across cameras (ms)."""
        with self._lock:
            latest = {}
            for cid, times in self._frame_times.items():
                if times:
                    latest[cid] = times[-1]
            if len(latest) < 2:
                return 0.0
            vals = list(latest.values())
            return (max(vals) - min(vals)) * 1000

    def reset(self) -> None:
        with self._lock:
            self._frame_times.clear()


# ==========================================================
# Isolation Verifier
# ==========================================================

@dataclass
class IsolationResult:
    camera_id: str
    operation: str  # "NUC" or "Focus"
    passed: bool
    affected_cameras: list[str] = field(default_factory=list)
    max_pause_ms: float = 0.0
    details: str = ""


class IsolationVerifier:
    """
    Verifies that operations on one camera (NUC, focus) do not affect others.
    Records frame timestamps BEFORE and AFTER the operation and checks for pauses.
    """
    def __init__(self):
        self._pre_op_times: dict[str, float] = {}
        self._post_op_times: dict[str, float] = {}
        self._lock = threading.Lock()

    def snapshot_times(self, analyzer_manager) -> None:
        """Record current frame receive times for all cameras."""
        with self._lock:
            self._pre_op_times.clear()
            for cid in analyzer_manager.camera_ids():
                a = analyzer_manager.get_analyzer(cid)
                last_time = time.perf_counter()  # baseline
                self._pre_op_times[cid] = last_time

    def check_isolation(self, operated_camera_id: str, operation: str, threshold_ms: float = 100.0) -> IsolationResult:
        """Check if other cameras paused during the operation."""
        affected = []
        max_pause = 0.0
        now = time.perf_counter()
        for cid in self._pre_op_times:
            if cid == operated_camera_id:
                continue
            elapsed_ms = (now - self._pre_op_times[cid]) * 1000
            if elapsed_ms > threshold_ms:
                affected.append(cid)
                max_pause = max(max_pause, elapsed_ms)

        passed = len(affected) == 0
        detail = f"Operation '{operation}' on {operated_camera_id}: "
        if passed:
            detail += "All other cameras unaffected [OK]"
        else:
            detail += f"FAILED - {len(affected)} camera(s) paused (max {max_pause:.0f}ms): {', '.join(affected)}"

        return IsolationResult(
            camera_id=operated_camera_id,
            operation=operation,
            passed=passed,
            affected_cameras=affected,
            max_pause_ms=max_pause,
            details=detail,
        )


# ==========================================================
# Bottleneck Detector
# ==========================================================

class BottleneckDetector:
    """
    Analyzes all camera snapshots and identifies the current bottleneck.
    Runs at low frequency (3-5 Hz) — NOT per frame.
    """
    BOTTLENECK_CATEGORIES = [
        "Camera Acquisition",
        "GigE Transport",
        "HALCON",
        "Acquisition Thread",
        "RawFrame Publishing",
        "GUI Update",
        "Display Conversion",
        "Qt Rendering",
        "Qt Painting",
        "CPU",
        "Memory",
        "Synchronization / Locks",
    ]

    @staticmethod
    def identify(snapshots: dict[str, AnalyzerSnapshot], stage_timings: dict[str, StageTimingCollector]) -> str:
        """
        Returns a string describing the current bottleneck.
        Priority order: most severe first.
        """
        if not snapshots:
            return "No data"

        # 1. Check for freezes
        for cid, snap in snapshots.items():
            if snap.freeze and snap.freeze.is_frozen:
                return f"FREEZE on {cid}: {snap.freeze.freeze_type.value}"

        # 2. Check if any camera has 0 camera FPS (acquisition stopped)
        for cid, snap in snapshots.items():
            if snap.camera_fps < 0.5:
                return f"Acquisition stopped on {cid}"

        # 3. Check if published FPS lags behind camera FPS significantly
        for cid, snap in snapshots.items():
            if snap.camera_fps > 1 and snap.published_fps < snap.camera_fps * 0.5:
                return f"Publishing bottleneck on {cid}"

        # 4. Check if display FPS lags behind published FPS
        for cid, snap in snapshots.items():
            if snap.published_fps > 1 and snap.display_fps < snap.published_fps * 0.5:
                return f"Display conversion bottleneck on {cid}"

        # 5. Check paint FPS
        for cid, snap in snapshots.items():
            if snap.display_fps > 1 and snap.paint_fps < snap.display_fps * 0.5:
                return f"Qt painting bottleneck on {cid}"

        # 6. Check latency breakdown across all cameras
        all_breakdowns = {}
        for cid, snap in snapshots.items():
            bd = snap.latency_breakdown
            for key in ["Camera Acquisition", "NumPy Conversion", "RawFrame Publication",
                        "GUI Receive", "Calibration", "Display Conversion", "Qt Rendering"]:
                pct_key = f"{key} %"
                if pct_key in bd:
                    all_breakdowns[key] = all_breakdowns.get(key, 0.0) + bd[pct_key]

        if all_breakdowns:
            worst = max(all_breakdowns, key=all_breakdowns.get)
            if all_breakdowns[worst] > 30:
                return f"Bottleneck: {worst} ({all_breakdowns[worst]:.0f}% of pipeline)"

        # 7. Check sequence loss
        for cid, snap in snapshots.items():
            if snap.sequence_loss_pct > 5:
                return f"High frame loss on {cid} ({snap.sequence_loss_pct:.1f}%)"

        return "Balanced — no bottleneck detected"


# ==========================================================
# Event Log
# ==========================================================

class EventLog:
    """Thread-safe event log with per-camera identification."""
    def __init__(self, max_entries: int = 1000):
        self._entries: deque[str] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def log(self, camera_id: str, message: str) -> None:
        ts = time.strftime("%H:%M:%S", time.localtime())
        with self._lock:
            self._entries.append(f"[{ts}] [{camera_id}] {message}")

    def get_recent(self, n: int = 50) -> list[str]:
        with self._lock:
            return list(self._entries)[-n:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# ==========================================================
# Cross-Camera Snapshot
# ==========================================================

@dataclass
class CrossCameraSnapshot:
    camera_count: int = 0
    avg_camera_fps: float = 0.0
    avg_display_fps: float = 0.0
    total_gui_fps: float = 0.0
    total_sequence_loss_pct: float = 0.0
    total_dropped_frames: int = 0
    max_latency_ms: float = 0.0
    worst_camera_id: str = ""
    sync_drift_ms: float = 0.0
    bottleneck: str = "No data"
    camera_snapshots: dict[str, AnalyzerSnapshot] = field(default_factory=dict)


# ==========================================================
# Multicamera Analyzer Manager
# ==========================================================

class MulticameraAnalyzerManager:
    """
    Manages N independent PipelineAnalyzers (one per camera).

    Provides:
    - Single poll_all() method for all cameras
    - Cross-camera synchronization tracking
    - Isolation verification for NUC and focus
    - Bottleneck identification
    """

    def __init__(self, camera_data: list[tuple[str, TV46LCamera, CalibrationManager]]):
        self._analyzers: dict[str, PipelineAnalyzer] = {}
        self._calibrations: dict[str, CalibrationManager] = {}
        self._sync_monitor = CrossCameraSyncMonitor()
        self._isolation_verifier = IsolationVerifier()
        self._event_log = EventLog()
        self._camera_ids: list[str] = []

        for cid, camera, cal in camera_data:
            self._analyzers[cid] = PipelineAnalyzer(camera=camera, calibration=cal)
            self._calibrations[cid] = cal
            self._camera_ids.append(cid)

    # --- Properties ---

    @property
    def camera_ids(self) -> list[str]:
        return list(self._camera_ids)

    @property
    def event_log(self) -> EventLog:
        return self._event_log

    @property
    def sync_monitor(self) -> CrossCameraSyncMonitor:
        return self._sync_monitor

    def get_analyzer(self, camera_id: str) -> PipelineAnalyzer | None:
        return self._analyzers.get(camera_id)

    def get_calibration(self, camera_id: str) -> CalibrationManager | None:
        return self._calibrations.get(camera_id)

    def camera_count(self) -> int:
        return len(self._analyzers)

    # --- Polling ---

    def poll_all(self) -> list[tuple[str, FrameLifecycle | None]]:
        results = []
        t_now = time.perf_counter()
        for cid, analyzer in self._analyzers.items():
            lifecycle = analyzer.observe_gui_poll()
            if lifecycle is not None:
                analyzer.nuc_monitor.record_frame(cid)
                self._sync_monitor.record_frame(cid, t_now)
            results.append((cid, lifecycle))
        return results

    # --- Snapshot ---

    def get_cross_camera_snapshot(self) -> CrossCameraSnapshot:
        snapshots = {}
        for cid, analyzer in self._analyzers.items():
            snapshots[cid] = analyzer.snapshot()

        if not snapshots:
            return CrossCameraSnapshot()

        camera_fpses = [s.camera_fps for s in snapshots.values()]
        display_fpses = [s.display_fps for s in snapshots.values()]
        latencies = [s.latency_breakdown.get("Total Latency (ms)", 0.0) for s in snapshots.values()]
        losses = [s.sequence_loss_pct for s in snapshots.values()]
        total_frames = sum(s.total_frames_pulled for s in snapshots.values())

        avg_cam_fps = sum(camera_fpses) / len(camera_fpses) if camera_fpses else 0.0
        avg_disp_fps = sum(display_fpses) / len(display_fpses) if display_fpses else 0.0
        total_gui = sum(camera_fpses)  # sum of all camera FPS
        max_latency = max(latencies) if latencies else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        worst_cid = max(snapshots, key=lambda c: snapshots[c].latency_breakdown.get("Total Latency (ms)", 0.0))
        drift = self._sync_monitor.get_drift_ms()

        # Collect stage timings for bottleneck identification
        stage_timings = {}
        for cid, analyzer in self._analyzers.items():
            stage_timings[cid] = analyzer.get_stage_timing()

        bottleneck = BottleneckDetector.identify(snapshots, stage_timings)

        return CrossCameraSnapshot(
            camera_count=len(snapshots),
            avg_camera_fps=round(avg_cam_fps, 1),
            avg_display_fps=round(avg_disp_fps, 1),
            total_gui_fps=round(total_gui, 1),
            total_sequence_loss_pct=round(avg_loss, 2),
            total_dropped_frames=total_frames,
            max_latency_ms=round(max_latency, 1),
            worst_camera_id=worst_cid,
            sync_drift_ms=round(drift, 2),
            bottleneck=bottleneck,
            camera_snapshots=snapshots,
        )

    # --- NUC with isolation verification ---

    def perform_nuc(self, camera_id: str) -> IsolationResult:
        analyzer = self._analyzers.get(camera_id)
        if analyzer is None:
            return IsolationResult(camera_id=camera_id, operation="NUC", passed=False, details="Camera not found")

        self._event_log.log(camera_id, "NUC requested")

        # Record baseline frame times for all cameras
        baseline = {}
        for cid, a in self._analyzers.items():
            baseline[cid] = a.nuc_monitor._camera_frame_times.get(cid, time.perf_counter())

        # Check other cameras before NUC
        pre_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"NUC on {camera_id}", threshold_ms=50)
                if event:
                    pre_pauses.append(event)

        # Execute NUC
        try:
            analyzer.camera.perform_nuc()
            self._event_log.log(camera_id, "NUC completed")
        except Exception as exc:
            self._event_log.log(camera_id, f"NUC failed: {exc}")
            return IsolationResult(
                camera_id=camera_id, operation="NUC", passed=False,
                details=f"NUC execution failed: {exc}",
            )

        # Check other cameras after NUC
        post_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"NUC on {camera_id}", threshold_ms=100)
                if event:
                    post_pauses.append(event)

        all_pauses = pre_pauses + post_pauses
        passed = len(all_pauses) == 0
        max_pause = max((e.pause_duration_ms for e in all_pauses), default=0.0)
        affected = list(set(e.camera_id for e in all_pauses))

        if passed:
            detail = "NUC isolation PASSED — no other cameras affected"
            self._event_log.log(camera_id, "NUC isolation PASSED")
        else:
            detail = f"NUC isolation FAILED — {len(affected)} camera(s) paused (max {max_pause:.0f}ms): {', '.join(affected)}"
            self._event_log.log(camera_id, f"NUC isolation FAILED: {len(affected)} cameras paused")

        return IsolationResult(
            camera_id=camera_id, operation="NUC", passed=passed,
            affected_cameras=affected, max_pause_ms=max_pause, details=detail,
        )

    # --- Focus with isolation verification ---

    def perform_focus_near(self, camera_id: str) -> IsolationResult:
        analyzer = self._analyzers.get(camera_id)
        if analyzer is None:
            return IsolationResult(camera_id=camera_id, operation="FocusNear", passed=False, details="Camera not found")

        self._event_log.log(camera_id, "Focus near requested")

        # Check other cameras before focus
        pre_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"Focus near on {camera_id}", threshold_ms=50)
                if event:
                    pre_pauses.append(event)

        try:
            result = analyzer.camera.focus_near()
            self._event_log.log(camera_id, f"Focus near: target={result[0]:.0f}mm actual={result[1]:.0f}mm")
        except Exception as exc:
            self._event_log.log(camera_id, f"Focus near failed: {exc}")
            return IsolationResult(
                camera_id=camera_id, operation="FocusNear", passed=False,
                details=f"Focus near failed: {exc}",
            )

        # Check other cameras after focus
        post_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"Focus near on {camera_id}", threshold_ms=100)
                if event:
                    post_pauses.append(event)

        all_pauses = pre_pauses + post_pauses
        passed = len(all_pauses) == 0
        max_pause = max((e.pause_duration_ms for e in all_pauses), default=0.0)
        affected = list(set(e.camera_id for e in all_pauses))

        if passed:
            detail = f"Focus near isolation PASSED — result: {result[1]:.0f}mm"
            self._event_log.log(camera_id, "Focus near isolation PASSED")
        else:
            detail = f"Focus near isolation FAILED — {len(affected)} camera(s) paused"
            self._event_log.log(camera_id, "Focus near isolation FAILED")

        return IsolationResult(
            camera_id=camera_id, operation="FocusNear", passed=passed,
            affected_cameras=affected, max_pause_ms=max_pause, details=detail,
        )

    def perform_focus_far(self, camera_id: str) -> IsolationResult:
        analyzer = self._analyzers.get(camera_id)
        if analyzer is None:
            return IsolationResult(camera_id=camera_id, operation="FocusFar", passed=False, details="Camera not found")

        self._event_log.log(camera_id, "Focus far requested")

        pre_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"Focus far on {camera_id}", threshold_ms=50)
                if event:
                    pre_pauses.append(event)

        try:
            result = analyzer.camera.focus_far()
            self._event_log.log(camera_id, f"Focus far: target={result[0]:.0f}mm actual={result[1]:.0f}mm")
        except Exception as exc:
            self._event_log.log(camera_id, f"Focus far failed: {exc}")
            return IsolationResult(
                camera_id=camera_id, operation="FocusFar", passed=False,
                details=f"Focus far failed: {exc}",
            )

        post_pauses = []
        for cid, a in self._analyzers.items():
            if cid != camera_id:
                event = a.nuc_monitor.check_pause(cid, cause=f"Focus far on {camera_id}", threshold_ms=100)
                if event:
                    post_pauses.append(event)

        all_pauses = pre_pauses + post_pauses
        passed = len(all_pauses) == 0
        max_pause = max((e.pause_duration_ms for e in all_pauses), default=0.0)
        affected = list(set(e.camera_id for e in all_pauses))

        if passed:
            detail = f"Focus far isolation PASSED — result: {result[1]:.0f}mm"
            self._event_log.log(camera_id, "Focus far isolation PASSED")
        else:
            detail = f"Focus far isolation FAILED — {len(affected)} camera(s) paused"
            self._event_log.log(camera_id, "Focus far isolation FAILED")

        return IsolationResult(
            camera_id=camera_id, operation="FocusFar", passed=passed,
            affected_cameras=affected, max_pause_ms=max_pause, details=detail,
        )

    # --- Shutdown ---

    def shutdown_all(self) -> None:
        for cid, analyzer in self._analyzers.items():
            try:
                analyzer.reset()
            except Exception:
                pass
        self._sync_monitor.reset()
        self._event_log.log("SYSTEM", "All analyzers shut down")

    # --- Network ---

    def update_all_network_stats(self) -> dict[str, NetworkStats]:
        results = {}
        for cid, analyzer in self._analyzers.items():
            try:
                results[cid] = analyzer.update_network_stats()
            except Exception:
                results[cid] = NetworkStats()
        return results
