"""
diagnose_pipeline.py

Standalone pipeline diagnostic for the Fluke TV46L GigE Vision camera.

Purpose
-------
Determine which stage of the acquisition pipeline accumulates latency:

    CAMERA
      |
    HALCON grab_image_async()
      |
    RAW FRAME
      |
    PROCESSING
      |
    FRAME PUBLICATION
      |
    GUI DISPLAY

This tool ONLY observes. It never modifies the camera configuration,
NUC, focus, buffers, frame rate, or the production application.

Run
---
    python tests/diagnose_pipeline.py [--duration SECONDS] [--serial SN]

    --duration 0 (default): run until Ctrl+C.
    --serial SN          : use camera with serial SN (first if omitted).
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import signal
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import psutil

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from camera.camera_discovery import CameraDiscovery
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings

# ==========================================================
# Constants
# ==========================================================

_IMAGE_POLL_MS = 33          # GUI polls the latest published frame ~30x/s
_INFO_POLL_MS = 1000         # GUI diagnostics update once per second
_SIG_POLL_MS = 100           # lets Python deliver SIGINT while Qt runs

_FRAME_ID_CANDIDATES = (
    "[Stream]GevFrameID",
    "[Device]GevFrameID",
    "GevFrameID",
    "ChunkFrameID",
    "FrameID",
    "[ChunkData]FrameID",
)

_MEMORY_GROWTH_MB = 50.0     # "significant" memory growth threshold
_LATENCY_TREND_MS = 100.0    # sustained latency increase threshold


# ==========================================================
# Memory / helpers
# ==========================================================

def _rss_mb() -> float:
    """Current process RSS memory in megabytes."""
    try:
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def _frame_checksum(image: np.ndarray) -> bytes:
    """Lightweight per-frame checksum for duplicate detection."""
    return hashlib.md5(image.tobytes()).digest()


def _lightweight_processing(image: np.ndarray) -> tuple[float, float, float]:
    """
    Minimal diagnostic processing stage.

    Only raw-count statistics. No calibration, ROI, or alarm work.
    """
    lo = float(image.min())
    hi = float(image.max())
    mean = float(image.mean())
    return lo, hi, mean


# ==========================================================
# Rolling statistics
# ==========================================================

class SampleStats:
    """Small rolling statistic collector (avg/min/max/std/p95)."""

    def __init__(self, window: int = 6000) -> None:
        self.window = window
        self._samples: deque[float] = deque(maxlen=window)
        self.latest = 0.0
        self._min = 0.0
        self._max = 0.0
        self._sum = 0.0
        self._sum_sq = 0.0
        self.count = 0

    def update(self, value: float) -> None:
        if value is None:
            return
        self.latest = value
        if self.count == 0:
            self._min = value
            self._max = value
        else:
            if value < self._min:
                self._min = value
            if value > self._max:
                self._max = value
        self._samples.append(value)
        self._sum += value
        self._sum_sq += value * value
        self.count += 1

    @property
    def minimum(self) -> float:
        return self._min

    @property
    def maximum(self) -> float:
        return self._max

    @property
    def average(self) -> float:
        return self._sum / self.count if self.count else 0.0

    @property
    def stddev(self) -> float:
        if self.count < 2:
            return 0.0
        mean = self.average
        var = max(self._sum_sq / self.count - mean * mean, 0.0)
        return var ** 0.5

    @property
    def p95(self) -> float:
        if not self._samples:
            return 0.0
        ordered = sorted(self._samples)
        idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return ordered[idx]

    def first_average(self, n: int = 60) -> float:
        samples = list(self._samples)
        if not samples:
            return 0.0
        return sum(samples[:n]) / len(samples[:n]) if samples[:n] else 0.0

    def last_average(self, n: int = 60) -> float:
        samples = list(self._samples)
        if not samples:
            return 0.0
        tail = samples[-n:]
        return sum(tail) / len(tail) if tail else 0.0


# ==========================================================
# Shared diagnostic state
# ==========================================================

class Diagnostics:
    """Thread-safe collection point for all measurements."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.start_time = time.monotonic()

        self.observed = 0
        self.processed = 0
        self.published = 0
        self.displayed = 0
        self.missed = 0

        self.last_observed_t = 0.0

        self.intervals = SampleStats()          # ms
        self.processing = SampleStats()         # ms
        self.acquire_to_publish = SampleStats() # ms
        self.display_time = SampleStats()       # ms (GUI conversion+draw)
        self.display_latency = SampleStats()    # ms (acquire -> display)

        self.dup_frames = 0
        self.dup_runs = 0
        self.dup_run_max = 0
        self.dup_run_current = 0
        self._prev_checksum: Optional[bytes] = None

        self.max_acq_backlog = 0
        self.max_proc_backlog = 0
        self.max_disp_backlog = 0

        self.proc_lo = 0.0
        self.proc_hi = 0.0
        self.proc_mean = 0.0

        self.frame_id_note = "unavailable"
        self.frame_age_note = "unavailable"

        self.initial_rss = _rss_mb()
        self.max_rss = self.initial_rss
        self.final_rss = self.initial_rss
        self.mem_samples: list[tuple[float, float]] = []

        self.gc_counts = (0, 0, 0)

        self.initial_packets: dict = {}
        self.final_packets: dict = {}

    # ------------------------------------------------------
    # Frame bookkeeping (pipeline thread)
    # ------------------------------------------------------

    def begin_frame(self, now: float) -> int:
        with self.lock:
            self.observed += 1
            if self.last_observed_t:
                self.intervals.update(
                    (now - self.last_observed_t) * 1000.0
                )
            self.last_observed_t = now
            return self.observed

    def record_frame_checksum(self, checksum: bytes) -> bool:
        """
        Track consecutive-identical detection for one frame.

        Returns True when the frame is identical to the previous one.
        """
        with self.lock:
            is_dup = (
                self._prev_checksum is not None
                and checksum == self._prev_checksum
            )
            self._prev_checksum = checksum
            if is_dup:
                self.dup_frames += 1
                self.dup_run_current += 1
                if self.dup_run_current == 2:
                    self.dup_runs += 1
                if self.dup_run_current > self.dup_run_max:
                    self.dup_run_max = self.dup_run_current
            else:
                self.dup_run_current = 0
            return is_dup

    def record_processing(
        self,
        proc_ms: float,
        lo: float,
        hi: float,
        mean: float,
    ) -> None:
        with self.lock:
            self.processed += 1
            self.proc_lo = lo
            self.proc_hi = hi
            self.proc_mean = mean
            self.processing.update(proc_ms)

    def record_published(self, now: float, processed_t: float) -> None:
        with self.lock:
            self.published += 1
            self.acquire_to_publish.update(
                (processed_t - now) * 1000.0
            )

    # ------------------------------------------------------
    # Display bookkeeping (GUI thread)
    # ------------------------------------------------------

    def record_displayed(self, now: float, latency_ms: float) -> None:
        with self.lock:
            self.displayed += 1
            self.display_latency.update(latency_ms)

    def record_display_time(self, ms: float) -> None:
        with self.lock:
            self.display_time.update(ms)

    # ------------------------------------------------------
    # Backlogs (report thread, once per second)
    # ------------------------------------------------------

    def record_backlogs(
        self,
        camera: TV46LCamera,
    ) -> None:
        with self.lock:
            produced = camera.frame_count
            acq_backlog = produced - self.observed
            proc_backlog = self.observed - self.processed
            disp_backlog = self.published - self.displayed
            if acq_backlog > self.max_acq_backlog:
                self.max_acq_backlog = acq_backlog
            if proc_backlog > self.max_proc_backlog:
                self.max_proc_backlog = proc_backlog
            if disp_backlog > self.max_disp_backlog:
                self.max_disp_backlog = disp_backlog

    def record_mem(self, now: float) -> None:
        rss = _rss_mb()
        with self.lock:
            self.mem_samples.append((now, rss))
            if rss > self.max_rss:
                self.max_rss = rss
            self.final_rss = rss

    def record_gc(self, counts: tuple[int, int, int]) -> None:
        with self.lock:
            self.gc_counts = counts

    # ------------------------------------------------------
    # Snapshot for periodic + final reporting
    # ------------------------------------------------------

    def snapshot(self) -> dict:
        now = time.monotonic()
        elapsed = now - self.start_time
        with self.lock:
            return {
                "elapsed": elapsed,
                "observed": self.observed,
                "processed": self.processed,
                "published": self.published,
                "displayed": self.displayed,
                "missed": self.missed,
                "intervals": self.intervals,
                "processing": self.processing,
                "acquire_to_publish": self.acquire_to_publish,
                "display_time": self.display_time,
                "display_latency": self.display_latency,
                "dup_frames": self.dup_frames,
                "dup_runs": self.dup_runs,
                "dup_run_max": self.dup_run_max,
                "proc_lo": self.proc_lo,
                "proc_hi": self.proc_hi,
                "proc_mean": self.proc_mean,
                "max_acq_backlog": self.max_acq_backlog,
                "max_proc_backlog": self.max_proc_backlog,
                "max_disp_backlog": self.max_disp_backlog,
                "frame_id_note": self.frame_id_note,
                "frame_age_note": self.frame_age_note,
                "initial_rss": self.initial_rss,
                "max_rss": self.max_rss,
                "final_rss": self.final_rss,
                "gc_counts": self.gc_counts,
            }

    def add_missed(self, count: int) -> None:
        with self.lock:
            self.missed += count


# ==========================================================
# Latest-frame publication (no queue)
# ==========================================================

@dataclass(slots=True)
class PublishedFrame:
    image: np.ndarray
    diag_seq: int
    cam_seq: int
    acquired_t: float
    processed_t: float
    processing_ms: float


class FramePublisher:
    """
    Latest-frame-wins publisher.

    The lock is only used to exchange the frame reference.
    No image copying happens while the lock is held.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[PublishedFrame] = None

    def publish(self, frame: PublishedFrame) -> None:
        with self._lock:
            self._frame = frame

    def get_latest(self) -> Optional[PublishedFrame]:
        with self._lock:
            return self._frame


# ==========================================================
# Pipeline thread
# ==========================================================

def _pipeline_loop(
    camera: TV46LCamera,
    publisher: FramePublisher,
    diag: Diagnostics,
    stop_event: threading.Event,
) -> None:
    """
    Observe each newly published camera frame, run the minimal
    processing stage, and publish the newest frame (latest wins).
    """
    last_cam_seq: Optional[int] = None

    while not stop_event.is_set():
        frame = camera.get_latest_frame_reference()
        if frame is None:
            time.sleep(0.002)
            continue

        if last_cam_seq is not None and frame.frame_number == last_cam_seq:
            time.sleep(0.002)
            continue

        now = time.monotonic()

        if last_cam_seq is not None and frame.frame_number > last_cam_seq + 1:
            diag.add_missed(frame.frame_number - last_cam_seq - 1)

        last_cam_seq = frame.frame_number
        diag_seq = diag.begin_frame(now)

        checksum = _frame_checksum(frame.image)
        diag.record_frame_checksum(checksum)

        p_start = time.monotonic()
        lo, hi, mean = _lightweight_processing(frame.image)
        p_end = time.monotonic()
        proc_ms = (p_end - p_start) * 1000.0

        diag.record_processing(proc_ms, lo, hi, mean)

        published = PublishedFrame(
            image=frame.image,
            diag_seq=diag_seq,
            cam_seq=frame.frame_number,
            acquired_t=now,
            processed_t=p_end,
            processing_ms=proc_ms,
        )
        publisher.publish(published)
        diag.record_published(now, p_end)


# ==========================================================
# HALCON frame ID / age probe
# ==========================================================

def _read_frame_id(camera: TV46LCamera) -> str:
    """
    Attempt to read a HALCON-side frame ID/timestamp source.

    Returns the first supported parameter value, else 'unavailable'.
    """
    for parameter in _FRAME_ID_CANDIDATES:
        try:
            value = camera.get_parameter(parameter)
            if value is not None:
                return f"{parameter} = {value}"
        except Exception:
            continue
    return "unavailable"


# ==========================================================
# Periodic console report
# ==========================================================

_PACKET_NAMES = (
    "[Stream]GevStreamSeenPacketCount",
    "[Stream]GevStreamLostPacketCount",
    "[Stream]GevStreamDeliveredPacketCount",
    "[Stream]GevStreamUnavailablePacketCount",
    "[Stream]GevStreamDuplicatePacketCount",
    "[Stream]GevStreamResendPacketCount",
)


def _fmt_packet(value) -> str:
    if value is None or value == -1:
        return "N/A"
    return str(value)


def _packet_snapshot(camera: TV46LCamera) -> dict:
    try:
        return camera.get_stream_statistics()
    except Exception:
        return {}


def _report_loop(
    camera: TV46LCamera,
    diag: Diagnostics,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        if stop_event.wait(1.0):
            break
        now = time.monotonic()
        diag.record_mem(now)
        diag.record_backlogs(camera)
        diag.record_gc(tuple(gc.get_count()))
        _print_block(camera, diag)


def _print_block(camera: TV46LCamera, diag: Diagnostics) -> None:
    snap = diag.snapshot()
    elapsed = snap["elapsed"]
    observed = snap["observed"]
    processed = snap["processed"]
    published = snap["published"]
    displayed = snap["displayed"]

    intervals = snap["intervals"]
    processing = snap["processing"]
    display_time = snap["display_time"]
    latency = snap["display_latency"]

    acq_fps = observed / elapsed if elapsed > 0 else 0.0
    proc_fps = processed / elapsed if elapsed > 0 else 0.0
    disp_fps = displayed / elapsed if elapsed > 0 else 0.0

    produced = camera.frame_count
    acq_backlog = produced - observed
    proc_backlog = observed - processed
    disp_backlog = published - displayed

    stats = camera.get_stream_statistics()
    seen = stats.get(_PACKET_NAMES[0], -1)
    lost = stats.get(_PACKET_NAMES[1], -1)
    resent = stats.get(_PACKET_NAMES[5], -1)
    duplicated = stats.get(_PACKET_NAMES[4], -1)

    rss = _rss_mb()

    print("-" * 60)
    print("TV46L PIPELINE DIAGNOSTIC")
    print(f"Elapsed: {elapsed:.1f} s")
    print("")
    print(f"Diagnostic frame      : {observed}")
    print(f"Camera frame          : {produced}")
    print(f"Frame ID source       : {snap['frame_id_note']}")
    print("")
    print(f"Acquisition FPS       : {acq_fps:.2f}")
    print(f"Acquisition interval  : {intervals.latest:.1f} ms")
    print(f"Acquisition jitter    : {intervals.stddev:.1f} ms")
    print("")
    print(f"Processing FPS        : {proc_fps:.2f}")
    print(f"Processing time       : {processing.average:.1f} ms")
    print("")
    print(f"Display FPS           : {disp_fps:.2f}")
    print(f"Display time          : {display_time.average:.1f} ms")
    print("")
    print(f"Current display lag   : {latency.latest:.0f} ms")
    print(f"Average display lag   : {latency.average:.0f} ms")
    print(f"Maximum display lag   : {latency.maximum:.0f} ms")
    print("")
    print(f"Acquisition backlog   : {max(acq_backlog, 0)} frames")
    print(f"Processing backlog    : {max(proc_backlog, 0)} frames")
    print(f"Display backlog       : {max(disp_backlog, 0)} frames")
    print("")
    print(f"Duplicate frames      : {snap['dup_frames']}")
    print(f"Longest duplicate run : {snap['dup_run_max']}")
    print("")
    print(f"Packets seen          : {_fmt_packet(seen)}")
    print(f"Packets lost          : {_fmt_packet(lost)}")
    print(f"Packets resent        : {_fmt_packet(resent)}")
    print(f"Packets duplicated    : {_fmt_packet(duplicated)}")
    print("")
    print(f"Frame age (HALCON)    : {snap['frame_age_note']}")
    print(f"Memory RSS            : {rss:.1f} MB")
    print("-" * 60)


# ==========================================================
# GUI
# ==========================================================

def _to_display_pixmap(image: np.ndarray) -> QPixmap:
    """16-bit raw counts -> colored 8-bit QPixmap (display only)."""
    gray = cv2.normalize(
        image,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
        dtype=cv2.CV_8UC1,
    )
    color = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
    rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    bytes_per_line = channels * width
    qimage = QImage(
        rgb.tobytes(),
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(qimage)


class DiagnosticWindow(QMainWindow):
    """Minimal viewer: thermal image + diagnostics. No ROI/alarm/DB."""

    def __init__(
        self,
        publisher: FramePublisher,
        diag: Diagnostics,
    ) -> None:
        super().__init__()
        self._publisher = publisher
        self._diag = diag
        self._last_displayed_seq = -1

        self._gui_frame_count = 0
        self._gui_fps = 0.0
        self._gui_fps_timer = time.monotonic()

        self.setWindowTitle("TV46L Pipeline Diagnostic")
        self.setMinimumSize(640, 520)
        self.resize(800, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._image_label = QLabel("Waiting for first frame...")
        self._image_label.setMinimumSize(320, 240)
        self._image_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._image_label.setStyleSheet("background-color: black;")
        layout.addWidget(self._image_label, stretch=1)

        self._info_label = QLabel("collecting diagnostics...")
        self._info_label.setStyleSheet(
            "font-family: Consolas; font-size: 10px;"
        )
        self._info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self._info_label)

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._poll_frame)
        self._frame_timer.start(_IMAGE_POLL_MS)

        self._info_timer = QTimer(self)
        self._info_timer.timeout.connect(self._update_info)
        self._info_timer.start(_INFO_POLL_MS)

        self._sig_timer = QTimer(self)
        self._sig_timer.timeout.connect(lambda: None)
        self._sig_timer.start(_SIG_POLL_MS)

    # ------------------------------------------------------
    # Latest-frame-wins polling
    # ------------------------------------------------------

    def _poll_frame(self) -> None:
        published = self._publisher.get_latest()
        if published is None or published.diag_seq == self._last_displayed_seq:
            return

        self._last_displayed_seq = published.diag_seq
        self._gui_frame_count += 1

        now = time.monotonic()
        latency_ms = (now - published.acquired_t) * 1000.0
        self._diag.record_displayed(now, latency_ms)

        start = time.monotonic()
        pixmap = _to_display_pixmap(published.image)
        duration_ms = (time.monotonic() - start) * 1000.0
        self._diag.record_display_time(duration_ms)

        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._image_label.setPixmap(scaled)

        now_mono = time.monotonic()
        if now_mono - self._gui_fps_timer >= 1.0:
            self._gui_fps = self._gui_frame_count
            self._gui_frame_count = 0
            self._gui_fps_timer = now_mono

    # ------------------------------------------------------
    # Diagnostic text panel
    # ------------------------------------------------------

    def _update_info(self) -> None:
        snap = self._diag.snapshot()
        elapsed = snap["elapsed"]
        latency = snap["display_latency"]
        text = (
            f"Elapsed: {elapsed:.1f} s\n"
            f"Observed: {snap['observed']}  Processed: {snap['processed']}  "
            f"Displayed: {snap['displayed']}\n"
            f"Acq FPS: {snap['observed']/elapsed:.2f}  "
            f"Proc FPS: {snap['processed']/elapsed:.2f}  "
            f"Display FPS: {self._gui_fps:.2f}\n"
            f"Display lag cur/avg/max: "
            f"{latency.latest:.0f}/{latency.average:.0f}/{latency.maximum:.0f} ms\n"
            f"Backlog acq/proc/disp: "
            f"{snap['max_acq_backlog']}/{snap['max_proc_backlog']}/"
            f"{snap['max_disp_backlog']}\n"
            f"Duplicates: {snap['dup_frames']} "
            f"(longest run {snap['dup_run_max']})\n"
            f"Raw lo/hi/mean: {snap['proc_lo']:.0f}/"
            f"{snap['proc_hi']:.0f}/{snap['proc_mean']:.0f}\n"
            f"Memory RSS: {snap['final_rss']:.1f} MB (max {snap['max_rss']:.1f})"
        )
        self._info_label.setText(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._frame_timer.stop()
        self._info_timer.stop()
        self._sig_timer.stop()
        super().closeEvent(event)


# ==========================================================
# Final summary + interpretation
# ==========================================================

def _final_summary(camera: TV46LCamera, diag: Diagnostics) -> str:
    snap = diag.snapshot()
    elapsed = snap["elapsed"]
    observed = snap["observed"]
    processed = snap["processed"]
    displayed = snap["displayed"]

    intervals = snap["intervals"]
    processing = snap["processing"]
    latency = snap["display_latency"]

    acq_fps = observed / elapsed if elapsed > 0 else 0.0
    proc_fps = processed / elapsed if elapsed > 0 else 0.0
    disp_fps = displayed / elapsed if elapsed > 0 else 0.0

    stats = camera.get_stream_statistics()
    seen = stats.get(_PACKET_NAMES[0], -1)
    lost = stats.get(_PACKET_NAMES[1], -1)
    resent = stats.get(_PACKET_NAMES[5], -1)
    duplicated = stats.get(_PACKET_NAMES[4], -1)

    lines = []
    lines.append("=" * 60)
    lines.append("FINAL PIPELINE DIAGNOSTIC")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Runtime:")
    lines.append(f"    {elapsed:.1f} seconds")
    lines.append("")
    lines.append("Acquisition:")
    lines.append(f"    Frames:        {observed}")
    lines.append(f"    FPS:           {acq_fps:.2f}")
    lines.append(f"    Avg interval:  {intervals.average:.1f} ms")
    lines.append(f"    Min interval:  {intervals.minimum:.1f} ms")
    lines.append(f"    Max interval:  {intervals.maximum:.1f} ms")
    lines.append(f"    Jitter:        {intervals.stddev:.1f} ms")
    lines.append("")
    lines.append("Processing:")
    lines.append(f"    Frames:        {processed}")
    lines.append(f"    FPS:           {proc_fps:.2f}")
    lines.append(f"    Avg processing:{processing.average:.1f} ms")
    lines.append(f"    Max processing:{processing.maximum:.1f} ms")
    lines.append("")
    lines.append("Display:")
    lines.append(f"    Frames:        {displayed}")
    lines.append(f"    FPS:           {disp_fps:.2f}")
    lines.append(f"    Avg latency:   {latency.average:.1f} ms")
    lines.append(f"    Max latency:   {latency.maximum:.1f} ms")
    lines.append("")
    lines.append("Backlog:")
    lines.append(f"    Max acquisition backlog: {snap['max_acq_backlog']}")
    lines.append(f"    Max processing backlog:  {snap['max_proc_backlog']}")
    lines.append(f"    Max display backlog:     {snap['max_disp_backlog']}")
    lines.append("")
    lines.append("Frames:")
    lines.append(f"    Duplicate frames:     {snap['dup_frames']}")
    lines.append(f"    Longest duplicate run:{snap['dup_run_max']}")
    lines.append("")
    lines.append("Packets:")
    lines.append(f"    Seen:     {_fmt_packet(seen)}")
    lines.append(f"    Lost:     {_fmt_packet(lost)}")
    lines.append(f"    Resent:   {_fmt_packet(resent)}")
    lines.append(f"    Duplicate:{_fmt_packet(duplicated)}")
    lines.append("")
    lines.append("Memory:")
    lines.append(f"    Initial RSS:  {snap['initial_rss']:.1f} MB")
    lines.append(f"    Final RSS:    {snap['final_rss']:.1f} MB")
    lines.append(f"    Maximum RSS:  {snap['max_rss']:.1f} MB")
    lines.append("")
    lines.append("Frame ID source: " + snap["frame_id_note"])
    lines.append("Frame age:       " + snap["frame_age_note"])
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def _interpret(camera: TV46LCamera, diag: Diagnostics) -> str:
    """Evidence-based interpretation. Never guesses root cause."""
    snap = diag.snapshot()
    elapsed = snap["elapsed"]
    observed = snap["observed"]
    processed = snap["processed"]
    published = snap["published"]
    displayed = snap["displayed"]

    intervals = snap["intervals"]
    processing = snap["processing"]
    latency = snap["display_latency"]

    produced = camera.frame_count

    findings: list[str] = []
    lines = ["", "=" * 60, "AUTOMATIC INTERPRETATION", "=" * 60, ""]

    # ---- CASE A: acquisition / camera / transport timing ----
    interval_std = intervals.stddev
    interval_avg = intervals.average
    interval_max = intervals.maximum
    late_interval = intervals.last_average(60)
    early_interval = intervals.first_average(60)

    acquisition_unstable = (
        (interval_avg > 0 and interval_std > 0.3 * interval_avg)
        or (interval_avg > 0 and interval_max > 3.0 * interval_avg)
    )
    acquisition_slowed = (
        early_interval > 0 and late_interval > 1.5 * early_interval
    )

    if acquisition_unstable or acquisition_slowed:
        detail = []
        if acquisition_unstable:
            detail.append(
                f"interval jitter {interval_std:.1f} ms on "
                f"{interval_avg:.1f} ms average"
            )
        if acquisition_slowed:
            detail.append(
                f"late interval avg {late_interval:.1f} ms vs "
                f"early {early_interval:.1f} ms"
            )
        findings.append(
            "Possible acquisition/camera/transport problem."
            + (" Evidence: " + "; ".join(detail) + "." if detail else "")
        )

    # ---- CASE B: processing cannot keep up ----
    proc_backlog = max(snap["max_proc_backlog"], 0)
    missed = max(snap["missed"], 0)
    proc_slow = processing.average > 50.0
    if proc_backlog > 3 or missed > 5 or proc_slow:
        detail = []
        if proc_backlog > 3:
            detail.append(f"processing backlog {proc_backlog}")
        if missed > 5:
            detail.append(f"{missed} camera frames never observed")
        if proc_slow:
            detail.append(f"avg processing {processing.average:.1f} ms")
        findings.append(
            "Processing cannot keep up with acquisition."
            + (" Evidence: " + "; ".join(detail) + "." if detail else "")
        )

    # ---- CASE C: GUI/display path falling behind ----
    disp_backlog = max(snap["max_disp_backlog"], 0)
    late_latency = latency.last_average(60)
    early_latency = latency.first_average(60)
    latency_growing = (
        early_latency > 0
        and late_latency > 2.0 * early_latency
        and (late_latency - early_latency) > _LATENCY_TREND_MS
    )
    if disp_backlog > 3 or latency_growing:
        detail = []
        if disp_backlog > 3:
            detail.append(f"display backlog {disp_backlog}")
        if latency_growing:
            detail.append(
                f"display latency avg grew {early_latency:.0f} ms "
                f"to {late_latency:.0f} ms"
            )
        findings.append(
            "GUI/display path is falling behind."
            + (" Evidence: " + "; ".join(detail) + "." if detail else "")
        )

    # ---- CASE D: duplicate frames ----
    if snap["dup_frames"] > 0:
        findings.append(
            "Possible reused/duplicate frame behavior."
            f" Evidence: {snap['dup_frames']} consecutive duplicates, "
            f"longest run {snap['dup_run_max']}."
        )

    # ---- CASE E: GigE transport packet activity ----
    stats = camera.get_stream_statistics()
    lost = stats.get(_PACKET_NAMES[1], 0) or 0
    resent = stats.get(_PACKET_NAMES[5], 0) or 0
    duplicated = stats.get(_PACKET_NAMES[4], 0) or 0
    initial_lost = (diag.initial_packets.get(_PACKET_NAMES[1], 0) or 0)
    initial_resent = (diag.initial_packets.get(_PACKET_NAMES[5], 0) or 0)
    initial_duplicated = (diag.initial_packets.get(_PACKET_NAMES[4], 0) or 0)
    if (
        lost > initial_lost
        or resent > initial_resent
        or duplicated > initial_duplicated
    ):
        findings.append(
            "GigE transport packet activity detected."
            f" Evidence: lost {initial_lost}->{lost}, "
            f"resend {initial_resent}->{resent}, "
            f"duplicate {initial_duplicated}->{duplicated}."
        )

    # ---- CASE F: memory growth ----
    mem_growth = snap["final_rss"] - snap["initial_rss"]
    if mem_growth > _MEMORY_GROWTH_MB:
        findings.append(
            "Possible memory/resource retention."
            f" Evidence: RSS grew {mem_growth:.1f} MB "
            f"({snap['initial_rss']:.1f} -> {snap['final_rss']:.1f} MB)."
        )

    # ---- CASE G: everything stable but tearing remains ----
    if not findings:
        findings.append(
            "Pipeline timing does not explain the visual artifact. "
            "Investigate image rendering/QImage/QPixmap conversion or "
            "image integrity separately."
        )

    if observed == 0:
        lines.append("No frames observed during the run.")
    else:
        lines.append(f"Run length: {elapsed:.1f} s, {observed} frames observed.")
        lines.append(
            f"Observed {observed} / processed {processed} / "
            f"published {published} / displayed {displayed}; "
            f"camera produced {produced}."
        )
        lines.append("")
        for item in findings:
            lines.append("  * " + item)

    lines.append("")
    lines.append("NOTE: This interpretation is evidence-based, not a root-cause")
    lines.append("claim. Inspect the numbers above before changing anything.")
    lines.append("=" * 60)
    return "\n".join(lines)


# ==========================================================
# Entry point
# ==========================================================

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="TV46L pipeline diagnostic (observation only)."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run for N seconds, then stop. 0 = until Ctrl+C (default).",
    )
    parser.add_argument(
        "--serial",
        type=str,
        default="",
        help="Serial number of the camera to use (first camera if omitted).",
    )
    args = parser.parse_args(argv)

    print("[DIAG] Discovering cameras...")
    discovery = CameraDiscovery()
    cameras = discovery.discover()

    if not cameras:
        print("[DIAG] No TV46L cameras discovered.")
        return 1

    cam_info = next(
        (c for c in cameras if c.serial == args.serial),
        None,
    ) if args.serial else cameras[0]

    if cam_info is None:
        print(f"[DIAG] Camera with serial {args.serial} not found.")
        print("[DIAG] Available cameras:")
        for c in cameras:
            print(f"    {c.serial}  {c.model}  {c.ip}")
        return 1

    print(
        f"[DIAG] Using {cam_info.model} "
        f"(SN={cam_info.serial}, IP={cam_info.ip})"
    )

    settings = Settings()
    camera = TV46LCamera(camera_info=cam_info, settings=settings)

    try:
        camera.connect()
        camera.start()

        if not camera.wait_for_first_frame(timeout=20.0):
            print("[DIAG] No first frame received within 20 s.")
            print(
                "[DIAG] The camera may be stuck in a degraded state "
                "(same behaviour the pipeline investigation targets)."
            )
            return 1

        print("[DIAG] Camera streaming.")

        diag = Diagnostics()
        diag.frame_id_note = _read_frame_id(camera)
        diag.initial_packets = _packet_snapshot(camera)

        publisher = FramePublisher()
        stop_event = threading.Event()

        pipeline_thread = threading.Thread(
            target=_pipeline_loop,
            args=(camera, publisher, diag, stop_event),
            name="DiagPipeline",
            daemon=True,
        )
        report_thread = threading.Thread(
            target=_report_loop,
            args=(camera, diag, stop_event),
            name="DiagReport",
            daemon=True,
        )

        app = QApplication([])
        window = DiagnosticWindow(publisher, diag)
        window.show()

        def _on_sigint(*_args) -> None:
            print("\n[DIAG] Ctrl+C received. Stopping...")
            stop_event.set()
            app.quit()

        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, _on_sigint)

        pipeline_thread.start()
        report_thread.start()

        if args.duration and args.duration > 0:
            def _auto_stop() -> None:
                print(f"\n[DIAG] Duration reached ({args.duration:.0f} s). Stopping...")
                stop_event.set()
                app.quit()

            auto_timer = QTimer()
            auto_timer.setSingleShot(True)
            auto_timer.timeout.connect(_auto_stop)
            auto_timer.start(int(args.duration * 1000))
            auto_timer.setParent(window)

        app.exec()

        stop_event.set()
        pipeline_thread.join(timeout=2.0)
        report_thread.join(timeout=2.0)

        print("\n" + _final_summary(camera, diag))
        print(_interpret(camera, diag))

    except KeyboardInterrupt:
        print("\n[DIAG] Interrupted.")
    finally:
        try:
            camera.stop()
            camera.disconnect()
        except Exception:
            pass
        print("[DIAG] Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
