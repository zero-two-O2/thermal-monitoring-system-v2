"""
metrics.py

Sampling and statistics collection for the validation harness.

The collector is deliberately dumb: it records raw per-frame values and
per-second samples; analysis (min/max/avg, memory slope, verdicts) is
computed later by report.py / the scenarios.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import psutil

from utilities import logger


@dataclass(slots=True)
class FrameMetric:
    """Metrics captured for one processed frame."""

    frame_number: int
    pipeline_ms: float
    engine_ms: float
    gui_ms: float
    dropped: int
    exception: bool
    halcon_error: bool
    active_rois: int


@dataclass(slots=True)
class IntervalSample:
    """Per-second sample of system and pipeline state."""

    t: float
    fps: float
    rss_mb: float
    cpu_percent: float
    active_rois: int
    engine_memory_mb: float
    store_memory_mb: float


@dataclass(slots=True)
class Metrics:
    """All raw metrics collected during a run."""

    frames: list[FrameMetric] = field(default_factory=list)
    intervals: list[IntervalSample] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    reconnect_events: int = 0

    def __post_init__(self) -> None:
        self.start_time = time.time()

    def finalize(self) -> None:
        """Stamp the end time after the run completes."""
        self.end_time = time.time()

    def duration_s(self) -> float:
        """Wall-clock duration of the run in seconds."""
        end = self.end_time or time.time()
        return max(0.0, end - self.start_time)


class MetricsCollector:
    """Records per-frame metrics and per-second interval samples."""

    INTERVAL_S = 1.0

    def __init__(
        self,
        process_handle: psutil.Process | None = None,
        memory_provider: Callable[[], tuple[float, float]] | None = None,
    ) -> None:
        """Collect process metrics.

        Parameters
        ----------
        process_handle : psutil.Process | None
            Process to sample; defaults to the current process.
        memory_provider : Callable[[], tuple[float, float]] | None
            Optional per-interval source of (engine_memory_mb,
            store_memory_mb) for the ROI engine components.
        """
        self._process = process_handle or psutil.Process()
        self._memory_provider = memory_provider
        self._metrics = Metrics()
        self._last_sample_t = 0.0
        self._fps_window_frames = 0
        self._last_rss_mb = 0.0
        self._last_cpu = 0.0

    @property
    def metrics(self) -> Metrics:
        """Raw metrics accumulated so far."""
        return self._metrics

    def record_frame(self, metric: FrameMetric) -> None:
        """Record one processed frame and tick the interval sampler."""
        self._metrics.frames.append(metric)
        self._fps_window_frames += 1
        now = time.time()
        if now - self._last_sample_t >= self.INTERVAL_S:
            self._sample_interval(now)

    def count_reconnect(self) -> None:
        """Count one camera reconnect event."""
        self._metrics.reconnect_events += 1

    def _sample_interval(self, now: float) -> None:
        elapsed = now - self._last_sample_t if self._last_sample_t else self.INTERVAL_S
        fps = self._fps_window_frames / elapsed
        rss = self._process.memory_info().rss / (1024 * 1024)
        cpu = self._process.cpu_percent(interval=None)
        engine_mb = 0.0
        store_mb = 0.0
        if self._memory_provider is not None:
            try:
                engine_mb, store_mb = self._memory_provider()
            except Exception:
                logger.exception("memory provider failed during interval sample")

        self._metrics.intervals.append(
            IntervalSample(
                t=now - self._metrics.start_time,
                fps=fps,
                rss_mb=rss,
                cpu_percent=cpu,
                active_rois=(
                    self._metrics.frames[-1].active_rois
                    if self._metrics.frames
                    else 0
                ),
                engine_memory_mb=engine_mb,
                store_memory_mb=store_mb,
            )
        )
        self._last_sample_t = now
        self._fps_window_frames = 0


class MetricsAnalyzer:
    """Derived statistics over a Metrics object."""

    def __init__(self, metrics: Metrics) -> None:
        self._metrics = metrics

    def fps_stats(self, warmup_s: float = 0.0) -> dict[str, float]:
        """Current/avg/min/max FPS from interval samples (post-warmup)."""
        samples = [
            s for s in self._metrics.intervals
            if s.t >= warmup_s and s.fps > 0.0
        ]
        if not samples:
            return {"current": 0.0, "average": 0.0, "minimum": 0.0, "maximum": 0.0}
        return {
            "current": samples[-1].fps,
            "average": sum(s.fps for s in samples) / len(samples),
            "minimum": min(s.fps for s in samples),
            "maximum": max(s.fps for s in samples),
        }

    def memory_slope(
        self, tail_fraction: float = 0.5
    ) -> dict[str, float]:
        """Linear slope of RSS over time for the last portion of the run.

        Slope is expressed in MB per hour. Near-zero (or negative) slope
        means memory has stabilized; sustained positive slope is a leak
        indicator.
        """
        samples = self._metrics.intervals
        if len(samples) < 10:
            return {"mb_per_hour": 0.0, "mb_total": 0.0}
        tail = samples[int(len(samples) * (1.0 - tail_fraction)):]
        if len(tail) < 5:
            return {"mb_per_hour": 0.0, "mb_total": 0.0}
        n = len(tail)
        t0 = tail[0].t
        xs = [s.t - t0 for s in tail]
        ys = [s.rss_mb for s in tail]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        denom = sum((x - mean_x) ** 2 for x in xs)
        if denom == 0.0:
            return {"mb_per_hour": 0.0, "mb_total": 0.0}
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
        mb_per_hour = slope * 3600.0
        first = tail[0].rss_mb
        last = tail[-1].rss_mb
        return {
            "mb_per_hour": round(mb_per_hour, 3),
            "mb_total": round(last - first, 3),
        }

    def memory_range(self) -> dict[str, float]:
        """Minimum and maximum RSS observed (MB)."""
        if not self._metrics.intervals:
            return {"min": 0.0, "max": 0.0}
        rss = [s.rss_mb for s in self._metrics.intervals]
        return {"min": min(rss), "max": max(rss)}

    def pipeline_stats(self, warmup_frames: int = 0) -> dict[str, float]:
        """Average/p99/max pipeline time per frame (ms)."""
        frames = self._metrics.frames[warmup_frames:]
        if not frames:
            return {"average_ms": 0.0, "p99_ms": 0.0, "maximum_ms": 0.0}
        times = sorted(f.pipeline_ms for f in frames)
        return {
            "average_ms": sum(times) / len(times),
            "p99_ms": times[int(len(times) * 0.99) - 1],
            "maximum_ms": times[-1],
        }

    def counts(self) -> dict[str, int]:
        """Processed/dropped/exception counters."""
        frames = self._metrics.frames
        return {
            "processed": len(frames),
            "dropped": sum(f.dropped for f in frames),
            "exceptions": sum(1 for f in frames if f.exception),
            "halcon_errors": sum(1 for f in frames if f.halcon_error),
            "reconnect_events": self._metrics.reconnect_events,
        }
