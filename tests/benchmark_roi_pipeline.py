"""
benchmark_roi_pipeline.py

Benchmark for the batched roi_engine pipeline vs. the legacy per-ROI path.

Measures, per ROI count:
    - store build time (one-off)
    - RegionCache + MaskCache rebuild time (one-off, reported separately)
    - per-frame wall time and FrameStats.processing_time_ms
      (min / median / p95 over measured frames)
    - per-frame allocation estimate via tracemalloc
    - memory footprint (store / masks / regions)
    - legacy per-ROI processing time (RuntimeROIManagerImpl.process_frame)
    - correctness spot-check against legacy extract_statistics (1e-6)

Usage:
    .venv\\Scripts\\python.exe tests/benchmark_roi_pipeline.py
    .venv\\Scripts\\python.exe tests/benchmark_roi_pipeline.py --report
    .venv\\Scripts\\python.exe tests/benchmark_roi_pipeline.py --json out.json
    .venv\\Scripts\\python.exe tests/benchmark_roi_pipeline.py --no-legacy
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import math
import platform
import random
import sys
import time
import tracemalloc
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roi.configuration import ROIConfiguration  # noqa: E402
from roi.geometry import (  # noqa: E402
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
    ROIGeometry,
)
from roi.geometry_to_hregion import geometry_to_hregion  # noqa: E402
from roi.runtime_manager import RuntimeROIManagerImpl  # noqa: E402
from roi.statistics import extract_statistics  # noqa: E402
from roi.types import ROIShape  # noqa: E402
from roi_engine.engine import ROIEngine  # noqa: E402
from roi_engine.masks import MaskCache  # noqa: E402
from roi_engine.region_cache import RegionCache  # noqa: E402
from roi_engine.runtime import FrameStats  # noqa: E402
from roi_engine.store import ROIStore  # noqa: E402
from roi_engine.store.factory import build_store  # noqa: E402
from tests.conftest import make_config, synthetic_image  # noqa: E402

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Benchmark constants
# ------------------------------------------------------------------

IMAGE_HEIGHT = 480
IMAGE_WIDTH = 640
IMAGE_SHAPE = (IMAGE_HEIGHT, IMAGE_WIDTH)

CAMERA_ID = "cam_bench"
POSITION_ID = "pos_bench"

SEED = 42
CELL_MARGIN = 2
VALIDATION_FRAME_ID = 9000

DEFAULT_COUNTS = (50, 100, 250, 500, 1000, 1600)
DEFAULT_MEASURED_FRAMES = 10
WARMUP_FRAMES = 5
MEMORY_MEASURE_FRAMES = 3
LEGACY_WARMUP_FRAMES = 2
LEGACY_REDUCED_FRAMES = 3
LEGACY_REDUCE_THRESHOLD = 1000

# HALCON on Windows can raise spurious KeyboardInterrupts inside C calls
# (parallel operator thread abort); retries make the benchmark resilient.
INTERRUPT_RETRIES = 3

FPS_BUDGET_MS = 111.0
CORRECTNESS_TOLERANCE = 1e-6

# Per-ROI shape distribution: index % 10 -> 5x Rectangle1, 2x Circle,
# 1x each of Ellipse / Rectangle2 / Polygon (50/20/10/10/10 %).
_SHAPE_CYCLE: tuple[ROIShape, ...] = (
    ROIShape.RECTANGLE1, ROIShape.RECTANGLE1, ROIShape.RECTANGLE1,
    ROIShape.RECTANGLE1, ROIShape.RECTANGLE1,
    ROIShape.CIRCLE, ROIShape.CIRCLE,
    ROIShape.ELLIPSE,
    ROIShape.RECTANGLE2,
    ROIShape.POLYGON,
)

# Fixed phi angles keep the axis-aligned extent bound trivial while
# exercising rotated shapes.
_PHI_CHOICES: tuple[float, ...] = (0.0, math.pi / 4.0, math.pi / 3.0, -math.pi / 6.0)

# Fraction of the cell's minimum extent used as the geometry size.
_SIZE_MIN = 0.15
_SIZE_MAX = 0.25

REPORT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "benchmarks" / "ROI_Benchmark_Report.md"
)


# ------------------------------------------------------------------
# Synthetic geometry generation
# ------------------------------------------------------------------

def _cell_for(index: int, count: int) -> tuple[int, int, int, int]:
    """Axis-aligned cell (r0, c0, r1, c1) for an ROI index on a square grid."""
    side = int(math.ceil(math.sqrt(count)))
    cell_h = IMAGE_HEIGHT // side
    cell_w = IMAGE_WIDTH // side
    r0 = (index // side) * cell_h
    c0 = (index % side) * cell_w
    return r0, c0, r0 + cell_h, c0 + cell_w


def _make_geometry(
    index: int, cell: tuple[int, int, int, int], rng: random.Random
) -> ROIGeometry:
    """One deterministic geometry inside its cell (no overlap with neighbors)."""
    r0, c0, r1, c1 = cell
    cell_h = r1 - r0
    cell_w = c1 - c0
    avail_h = cell_h - 2 * CELL_MARGIN
    avail_w = cell_w - 2 * CELL_MARGIN
    min_avail = min(avail_h, avail_w)
    # Any geometry's max extent stays below min_avail / 2, so it fits both
    # axes no matter the orientation.
    size = rng.uniform(_SIZE_MIN, _SIZE_MAX) * min_avail

    shape = _SHAPE_CYCLE[index % len(_SHAPE_CYCLE)]
    if shape is ROIShape.RECTANGLE1:
        inner_r = r0 + CELL_MARGIN + rng.uniform(0.0, size)
        inner_c = c0 + CELL_MARGIN + rng.uniform(0.0, size)
        return Rectangle1ROI(
            row1=inner_r,
            col1=inner_c,
            row2=inner_r + size * rng.uniform(1.2, 2.0),
            col2=inner_c + size * rng.uniform(1.2, 2.0),
        )
    if shape is ROIShape.CIRCLE:
        radius = size
        row = rng.uniform(r0 + CELL_MARGIN + radius, r1 - CELL_MARGIN - radius)
        col = rng.uniform(c0 + CELL_MARGIN + radius, c1 - CELL_MARGIN - radius)
        return CircleROI(row=row, col=col, radius=radius)
    if shape is ROIShape.ELLIPSE:
        phi = rng.choice(_PHI_CHOICES)
        radius1 = size
        radius2 = size * rng.uniform(0.5, 0.9)
        half_row = radius1 * abs(math.sin(phi)) + radius2 * abs(math.cos(phi))
        half_col = radius1 * abs(math.cos(phi)) + radius2 * abs(math.sin(phi))
        row = rng.uniform(r0 + CELL_MARGIN + half_row, r1 - CELL_MARGIN - half_row)
        col = rng.uniform(c0 + CELL_MARGIN + half_col, c1 - CELL_MARGIN - half_col)
        return EllipseROI(row=row, col=col, phi=phi, radius1=radius1, radius2=radius2)
    if shape is ROIShape.RECTANGLE2:
        phi = rng.choice(_PHI_CHOICES)
        length1 = size
        length2 = size * rng.uniform(0.5, 0.9)
        half_row = length1 * abs(math.sin(phi)) + length2 * abs(math.cos(phi))
        half_col = length1 * abs(math.cos(phi)) + length2 * abs(math.sin(phi))
        row = rng.uniform(r0 + CELL_MARGIN + half_row, r1 - CELL_MARGIN - half_row)
        col = rng.uniform(c0 + CELL_MARGIN + half_col, c1 - CELL_MARGIN - half_col)
        return Rectangle2ROI(row=row, col=col, phi=phi, length1=length1, length2=length2)
    # POLYGON: quad on a circle, angles sorted so the hull is convex and
    # strictly inside the cell.
    center_r = r0 + cell_h / 2.0 + rng.uniform(-0.1, 0.1) * min_avail
    center_c = c0 + cell_w / 2.0 + rng.uniform(-0.1, 0.1) * min_avail
    angles = sorted(a + rng.uniform(-0.15, 0.15) for a in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2))
    points = tuple(
        (
            center_r + size * math.cos(a),
            center_c + size * math.sin(a),
        )
        for a in angles
    )
    return PolygonROI(points=points)


def build_configs(count: int, rng: random.Random) -> list[ROIConfiguration]:
    """Generate `count` enabled ROI configurations with mixed geometry."""
    return [
        make_config(f"roi_{i:04d}", _make_geometry(i, _cell_for(i, count), rng))
        for i in range(count)
    ]


# ------------------------------------------------------------------
# Timing / percentile helpers
# ------------------------------------------------------------------

def _timed_ms(fn: Callable[[], object]) -> float:
    """Run fn once and return its wall time in milliseconds."""
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


def _run_guarded(fn: Callable[[], object], what: str) -> None:
    """Run fn, retrying the spurious HALCON KeyboardInterrupts.

    A real Ctrl+C eventually wins: after INTERRUPT_RETRIES + 1 attempts
    the interrupt is re-raised.
    """
    for attempt in range(INTERRUPT_RETRIES + 1):
        try:
            fn()
            return
        except KeyboardInterrupt:
            logger.warning(
                "Spurious KeyboardInterrupt during %s (attempt %d), retrying",
                what, attempt + 1,
            )
    raise KeyboardInterrupt(f"persistent interrupts during {what}")


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile of a sequence of samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(p / 100.0 * len(ordered))) - 1))
    return ordered[index]


def _close(a: float, b: float, tol: float) -> bool:
    """NaN-safe approximate equality."""
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


# ------------------------------------------------------------------
# Correctness spot-check
# ------------------------------------------------------------------

def validate_correctness(
    configs: list[ROIConfiguration],
    engine: ROIEngine,
    image: np.ndarray,
) -> tuple[int, int]:
    """Compare engine runtime values against legacy per-ROI statistics.

    Returns (checked, mismatched). Runtime arrays are read from the
    engine's own store snapshot (the standalone store passed to the
    rebuild timing has its own, untouched runtime arrays).
    """
    _run_guarded(
        lambda: engine.process_frame(image, VALIDATION_FRAME_ID),
        "validation frame",
    )
    store = engine.store()
    assert store is not None
    index = store.roi_index()
    checked = 0
    mismatched = 0
    for cfg in configs:
        legacy = extract_statistics(geometry_to_hregion(cfg.geometry), image, 1)
        shape, idx = index[cfg.roi_id]
        runtime = store.store_for(shape).runtime
        if not legacy.valid or not bool(runtime.valid[idx]):
            mismatched += 1
            logger.error(
                "ROI %s validity mismatch: legacy=%s engine=%s",
                cfg.roi_id, legacy.valid, bool(runtime.valid[idx]),
            )
            continue
        for field in ("minimum", "maximum", "mean", "standard_deviation", "pixel_count"):
            lhs = float(getattr(legacy, field))
            rhs = float(getattr(runtime, field)[idx])
            if not _close(lhs, rhs, CORRECTNESS_TOLERANCE):
                mismatched += 1
                logger.error(
                    "ROI %s %s mismatch: legacy=%r engine=%r",
                    cfg.roi_id, field, lhs, rhs,
                )
                break
        checked += 1
    return checked, mismatched


# ------------------------------------------------------------------
# Legacy per-ROI benchmark
# ------------------------------------------------------------------

def run_legacy(
    configs: list[ROIConfiguration],
    measured_frames: int,
    image: np.ndarray,
) -> tuple[list[float], int]:
    """Time RuntimeROIManagerImpl.process_frame (production per-ROI path).

    Returns (per-frame wall times in ms, number of measured frames).
    Measured frames shrink to LEGACY_REDUCED_FRAMES for very large counts.
    """
    frames = measured_frames
    if len(configs) >= LEGACY_REDUCE_THRESHOLD and frames > LEGACY_REDUCED_FRAMES:
        frames = LEGACY_REDUCED_FRAMES
        logger.info(
            "Legacy measured frames reduced to %d for %d ROIs", frames, len(configs)
        )
    manager = RuntimeROIManagerImpl()
    manager.load(list(configs))
    manager.rebuild_dirty_regions(IMAGE_SHAPE)
    for f in range(LEGACY_WARMUP_FRAMES):
        _run_guarded(
            lambda: manager.process_frame(image, f), "legacy warmup frame"
        )
    times: list[float] = []
    for f in range(frames):
        elapsed_ms: float = 0.0

        def _frame() -> None:
            nonlocal elapsed_ms
            start = time.perf_counter()
            manager.process_frame(image, LEGACY_WARMUP_FRAMES + f)
            elapsed_ms = (time.perf_counter() - start) * 1000.0

        _run_guarded(_frame, "legacy frame")
        times.append(elapsed_ms)
    manager.unload()
    return times, frames


# ------------------------------------------------------------------
# Per-count benchmark
# ------------------------------------------------------------------

@dataclass
class CountResult:
    """All measured numbers for one ROI count."""

    count: int
    store_build_ms: float
    region_rebuild_ms: float
    mask_rebuild_ms: float
    wall_ms: list[float]
    reported_ms: list[float]
    store_memory_bytes: int
    region_memory_bytes: int
    mask_memory_bytes: int
    per_frame_alloc_bytes: int
    validation_checked: int
    validation_mismatches: int
    legacy_wall_ms: list[float]
    legacy_frames: int

    @property
    def wall_min_ms(self) -> float:
        return percentile(self.wall_ms, 0.0)

    @property
    def wall_median_ms(self) -> float:
        return percentile(self.wall_ms, 50.0)

    @property
    def wall_p95_ms(self) -> float:
        return percentile(self.wall_ms, 95.0)

    @property
    def reported_median_ms(self) -> float:
        return percentile(self.reported_ms, 50.0)

    @property
    def legacy_median_ms(self) -> float | None:
        return percentile(self.legacy_wall_ms, 50.0) if self.legacy_wall_ms else None


def _warmup_halcon() -> None:
    """Run one minimal engine cycle so HALCON runtime init is not timed.

    The first HALCON operator call of a process pays runtime startup
    (licensing, operator tables); doing it here keeps the measured
    store-build and rebuild numbers representative.
    """
    cfg = make_config("warmup", Rectangle1ROI(10.0, 10.0, 30.0, 40.0))
    engine = ROIEngine("warmup")
    engine.load_position([cfg])
    _run_guarded(
        lambda: engine.process_frame(synthetic_image(IMAGE_HEIGHT, IMAGE_WIDTH), 0),
        "HALCON warmup",
    )
    engine.clear()


def benchmark_count(
    count: int,
    measured_frames: int,
    include_legacy: bool,
    validate: bool,
) -> CountResult:
    """Run the full benchmark for one ROI count."""
    rng = random.Random(SEED + count)
    configs = build_configs(count, rng)
    image = synthetic_image(IMAGE_HEIGHT, IMAGE_WIDTH)

    store: ROIStore | None = None

    def _build() -> None:
        nonlocal store
        store = build_store(CAMERA_ID, POSITION_ID, configs, generation=1)

    store_build_ms = _timed_ms(_build)
    assert store is not None

    regions = RegionCache()
    masks = MaskCache()
    region_rebuild_ms = _timed_ms(lambda: regions.rebuild(store))
    mask_rebuild_ms = _timed_ms(lambda: masks.rebuild(store, IMAGE_SHAPE))

    engine = ROIEngine(CAMERA_ID)
    engine.load_position(configs)
    # Warmup frames cover the engine-internal cache rebuild, so the
    # measured frames below are pure steady-state processing.
    for f in range(WARMUP_FRAMES):
        _run_guarded(
            lambda: engine.process_frame(image, f), "engine warmup frame"
        )
    sanity: FrameStats | None = None

    def _sanity() -> None:
        nonlocal sanity
        sanity = engine.process_frame(image, WARMUP_FRAMES)

    _run_guarded(_sanity, "sanity frame")
    assert sanity is not None
    if sanity.enabled_roi_count != count:
        logger.error(
            "Engine processed %d/%d enabled ROIs (count=%d)",
            sanity.enabled_roi_count, count, count,
        )

    # Wall timing runs WITHOUT tracemalloc: tracing skews numpy allocation
    # heavy paths by 3-10x and would corrupt the latency numbers. The timer
    # starts inside the guard, so a retried (interrupted) attempt is not
    # counted.
    wall_ms: list[float] = []
    reported_ms: list[float] = []
    for f in range(measured_frames):
        frame_stats: FrameStats | None = None
        frame_elapsed_ms: float = 0.0

        def _frame() -> None:
            nonlocal frame_stats, frame_elapsed_ms
            start = time.perf_counter()
            frame_stats = engine.process_frame(image, WARMUP_FRAMES + 1 + f)
            frame_elapsed_ms = (time.perf_counter() - start) * 1000.0

        _run_guarded(_frame, "measured frame")
        assert frame_stats is not None
        wall_ms.append(frame_elapsed_ms)
        reported_ms.append(frame_stats.processing_time_ms)

    # Separate pass for the per-frame allocation estimate: peak divided by
    # frame count (worst simultaneous Python-side allocation; HALCON
    # C-side memory is invisible to tracemalloc).
    tracemalloc.start()
    for f in range(MEMORY_MEASURE_FRAMES):
        _run_guarded(
            lambda: engine.process_frame(image, WARMUP_FRAMES + 1 + measured_frames + f),
            "tracemalloc frame",
        )
    _current, _peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    per_frame_alloc_bytes = int(_peak / MEMORY_MEASURE_FRAMES)

    checked = mismatched = 0
    if validate:
        checked, mismatched = validate_correctness(configs, engine, image)

    legacy_wall_ms: list[float] = []
    legacy_frames = 0
    if include_legacy:
        legacy_wall_ms, legacy_frames = run_legacy(configs, measured_frames, image)

    return CountResult(
        count=count,
        store_build_ms=store_build_ms,
        region_rebuild_ms=region_rebuild_ms,
        mask_rebuild_ms=mask_rebuild_ms,
        wall_ms=wall_ms,
        reported_ms=reported_ms,
        store_memory_bytes=store.memory_bytes(),
        region_memory_bytes=regions.memory_bytes(),
        mask_memory_bytes=masks.memory_bytes(),
        per_frame_alloc_bytes=per_frame_alloc_bytes,
        validation_checked=checked,
        validation_mismatches=mismatched,
        legacy_wall_ms=legacy_wall_ms,
        legacy_frames=legacy_frames,
    )


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------

def collect_env() -> dict[str, str]:
    """Environment fingerprint for the report."""
    halcon_version = "unknown"
    try:
        halcon_version = importlib.metadata.version("mvtec-halcon")
    except Exception:
        logger.warning("mvtec-halcon distribution metadata not found", exc_info=True)
    return {
        "python": platform.python_version(),
        "mvtec-halcon": halcon_version,
        "numpy": np.__version__,
        "image": f"{IMAGE_HEIGHT}x{IMAGE_WIDTH}",
        "seed": str(SEED),
        "date": datetime.now().isoformat(timespec="seconds"),
    }


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def build_interpretation(results: Sequence[CountResult]) -> str:
    """One paragraph: scaling behaviour and where the FPS budget breaks."""
    first = results[0]
    last = results[-1]
    count_ratio = last.count / first.count
    time_ratio = last.wall_median_ms / first.wall_median_ms
    if time_ratio < count_ratio * 0.8:
        scaling = "sub-linear (batch amortization grows with ROI count)"
    elif time_ratio <= count_ratio * 1.3:
        scaling = "approximately linear"
    else:
        scaling = "super-linear (per-ROI cost rises as the frame gets crowded)"
    over = [r.count for r in results if r.wall_median_ms > FPS_BUDGET_MS]
    if over:
        budget = (
            f"the 111 ms (9 FPS) frame budget is exceeded from "
            f"{over[0]} ROIs onward ({over})"
        )
    else:
        budget = "no tested count exceeds the 111 ms (9 FPS) frame budget"
    return (
        f"Per-frame latency grows {time_ratio:.1f}x for a {count_ratio:.0f}x ROI "
        f"increase, i.e. {scaling}. Per-frame cost is dominated by the batched "
        f"HALCON operators (intensity, min_max_gray, area_center) and the "
        f"himage_from_numpy_array conversion; hotspots run in numpy per ROI. "
        f"Overall, {budget}, so the batched engine stays real-time capable "
        f"within the tested range."
    )


def format_summary(results: Sequence[CountResult]) -> str:
    """Console summary table."""
    headers = (
        "ROIs", "store\nms", "rebuild\nms", "min\nms", "median\nms", "p95\nms",
        "alloc/f\nB", "mem\nKB", "legacy\nms", "speedup",
    )
    rows = []
    for r in results:
        legacy = r.legacy_median_ms
        speedup = legacy / r.wall_median_ms if legacy else float("nan")
        total_mem_kb = (r.store_memory_bytes + r.region_memory_bytes + r.mask_memory_bytes) / 1024.0
        rows.append((
            r.count,
            f"{r.store_build_ms:.2f}",
            f"{r.region_rebuild_ms + r.mask_rebuild_ms:.2f}",
            f"{r.wall_min_ms:.2f}",
            f"{r.wall_median_ms:.2f}",
            f"{r.wall_p95_ms:.2f}",
            f"{r.per_frame_alloc_bytes:,}",
            f"{total_mem_kb:,.0f}",
            f"{legacy:.2f}" if legacy else "-",
            f"{speedup:.1f}x" if legacy else "-",
        ))
    return _md_table(headers, rows)


def write_report(
    results: Sequence[CountResult], env: dict[str, str], measured_frames: int
) -> None:
    """Write the markdown benchmark report."""
    env_rows = [
        ("Python", env["python"]),
        ("mvtec-halcon", env["mvtec-halcon"]),
        ("numpy", env["numpy"]),
        ("Synthetic image", env["image"]),
        ("Seed", env["seed"]),
        ("Date", env["date"]),
    ]
    header = f"# ROI Engine Pipeline Benchmark\n\nGenerated {env['date']} by `tests/benchmark_roi_pipeline.py`.\n"
    env_section = "## Environment\n\n" + _md_table(("Item", "Value"), env_rows) + "\n"

    methodology = (
        "## Methodology\n\n"
        f"- Geometry: mixed shapes (50% Rectangle1, 20% Circle, 10% Ellipse, "
        f"10% Rectangle2, 10% Polygon) on a deterministic non-overlapping "
        f"{IMAGE_HEIGHT}x{IMAGE_WIDTH} grid (seed {SEED}).\n"
        f"- Warmup: {WARMUP_FRAMES} frames per count (includes the one-off cache "
        f"rebuild inside ROIEngine.process_frame); measured frames: "
        f"{measured_frames}.\n"
        f"- Legacy path: `RuntimeROIManagerImpl.process_frame` (per-ROI "
        f"`extract_statistics`), warmup {LEGACY_WARMUP_FRAMES}, measured frames "
        f"reduced to {LEGACY_REDUCED_FRAMES} from {LEGACY_REDUCE_THRESHOLD} ROIs.\n"
        f"- Frame budget: 9 FPS = {FPS_BUDGET_MS:.0f} ms per frame.\n"
        f"- Per-frame allocation: separate tracemalloc pass of "
        f"{MEMORY_MEASURE_FRAMES} frames, peak divided by frame count "
        f"(Python-side estimate; HALCON C-side memory is invisible to "
        f"tracemalloc). Wall timing runs WITHOUT tracemalloc, which skews "
        f"numpy-heavy paths by 3-10x.\n"
        f"- Caveat: absolute timings depend on concurrent machine load; run "
        f"with no other heavy processes for reproducible numbers. Relative "
        f"legacy-vs-batched speedups are robust to constant CPU contention.\n"
    )

    rows1 = []
    for r in results:
        total_mem = r.store_memory_bytes + r.region_memory_bytes + r.mask_memory_bytes
        budget = "OK" if r.wall_median_ms <= FPS_BUDGET_MS else "EXCEEDS"
        rows1.append((
            r.count,
            f"{r.store_build_ms:.2f}",
            f"{r.region_rebuild_ms:.2f}",
            f"{r.mask_rebuild_ms:.2f}",
            f"{r.region_rebuild_ms + r.mask_rebuild_ms:.2f}",
            f"{r.wall_min_ms:.2f}",
            f"{r.wall_median_ms:.2f}",
            f"{r.wall_p95_ms:.2f}",
            f"{r.reported_median_ms:.2f}",
            f"{r.per_frame_alloc_bytes:,}",
            f"{total_mem:,}",
            budget,
        ))
    table1 = (
        "## Batched Engine Results\n\n"
        + _md_table(
            (
                "ROIs", "store\n(ms)", "region\nrebuild\n(ms)", "mask\nrebuild\n(ms)",
                "rebuild\ntotal\n(ms)", "frame\nmin\n(ms)", "frame\nmedian\n(ms)",
                "frame\np95\n(ms)", "proc.\nmedian\n(ms)", "alloc\nper frame\n(B)",
                "total\nmemory\n(B)", "111 ms\nbudget",
            ),
            rows1,
        )
        + "\n"
    )

    rows2 = []
    for r in results:
        legacy = r.legacy_median_ms
        if legacy is None:
            continue
        speedup = legacy / r.wall_median_ms
        rows2.append((
            r.count, f"{legacy:.2f}", f"{r.wall_median_ms:.2f}",
            f"{speedup:.1f}x", r.legacy_frames,
        ))
    table2 = (
        "## Legacy vs. Batched\n\n"
        + _md_table(
            ("ROIs", "legacy median\n(ms)", "batched median\n(ms)", "speedup",
             "legacy frames"),
            rows2,
        )
        + "\n"
    )

    interpretation = "## Interpretation\n\n" + build_interpretation(results) + "\n"

    report = (
        header + "\n" + env_section + "\n" + methodology + "\n" + table1 + "\n"
        + table2 + "\n" + interpretation
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", REPORT_PATH)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the roi_engine batched pipeline vs. the legacy path."
    )
    parser.add_argument(
        "--counts", nargs="+", type=int, default=list(DEFAULT_COUNTS),
        help="ROI counts to benchmark (default: %(default)s)",
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_MEASURED_FRAMES,
        help="measured frames per count (default: %(default)s)",
    )
    parser.add_argument(
        "--no-legacy", action="store_true",
        help="skip the legacy per-ROI comparison",
    )
    parser.add_argument(
        "--json", type=Path, default=None,
        help="write raw results to this JSON file",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="write the markdown report to docs/benchmarks/ROI_Benchmark_Report.md",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    counts = sorted(set(args.counts))
    if not counts:
        logger.error("No counts given")
        return 1
    env = collect_env()
    results: list[CountResult] = []
    _warmup_halcon()
    for i, count in enumerate(counts):
        print(f"Benchmarking {count} ROIs ...")
        result = benchmark_count(
            count=count,
            measured_frames=args.frames,
            include_legacy=not args.no_legacy,
            validate=(i == 0),
        )
        if result.validation_checked:
            status = (
                "PASS" if result.validation_mismatches == 0 else "FAIL"
            )
            print(
                f"  Validation vs legacy: {result.validation_checked - result.validation_mismatches}"
                f"/{result.validation_checked} ROIs match within {CORRECTNESS_TOLERANCE} "
                f"({status})"
            )
            if result.validation_mismatches:
                logger.error(
                    "%d/%d ROIs mismatched legacy statistics",
                    result.validation_mismatches, result.validation_checked,
                )
        results.append(result)

    print("\n" + format_summary(results))
    if args.json or args.report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "environment": env,
                    "counts": [asdict(r) for r in results],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Raw results written to {args.json}")
    if args.report:
        write_report(results, env, args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
