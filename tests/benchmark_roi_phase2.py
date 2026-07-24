"""
benchmark_roi_phase2.py

Benchmark showing cached region processing vs. rebuilding every frame.

Measures the performance difference between:
    A) Rebuild every frame — recreate HRegion from geometry each time.
    B) Cached — reuse HRegion from RuntimeROICache (only rebuild if dirty).

Expected result:
    Cached processing should be 10-100x faster than rebuild-every-frame
    for typical scenarios with stable geometry.

Usage:
    pytest tests/benchmark_roi_phase2.py -v --benchmark-only
    python -m pytest tests/benchmark_roi_phase2.py -s
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roi.geometry import Rectangle1ROI, CircleROI, ROIGeometry
from roi.configuration import ROIConfiguration
from roi.acquisition_state import AcquisitionState
from roi.runtime_manager import RuntimeROIManagerImpl

halcon = pytest.importorskip("halcon", reason="HALCON not available")
from roi.geometry_to_hregion import geometry_to_hregion  # noqa: E402
from roi.statistics import extract_statistics  # noqa: E402


# ==============================================================
# Benchmark configuration
# ==============================================================

N_ROIS = 100
N_FRAMES = 50
IMAGE_SHAPE = (480, 640)
IMAGE_DTYPE = np.float32


def _make_configs(n: int) -> list[ROIConfiguration]:
    """Generate N unique ROI configurations."""
    state = AcquisitionState(camera_id="cam_1", pan=0, tilt=0, zoom=0, focus=0)
    configs: list[ROIConfiguration] = []
    for i in range(n):
        # Alternate geometry types
        if i % 2 == 0:
            geo: ROIGeometry = Rectangle1ROI(
                row1=float(10 + i % 400),
                col1=float(10 + i % 600),
                row2=float(100 + i % 400),
                col2=float(200 + i % 600),
            )
        else:
            geo = CircleROI(
                row=float(50 + i % 400),
                col=float(50 + i % 600),
                radius=float(20 + (i % 10)),
            )
        cfg = ROIConfiguration(
            roi_id=f"roi_{i:04d}",
            name=f"Benchmark-{i}",
            acquisition_state=state,
            geometry=geo,
        )
        configs.append(cfg)
    return configs


def _make_temperature_image() -> np.ndarray:
    """Create a synthetic temperature frame."""
    img = np.random.random(IMAGE_SHAPE).astype(IMAGE_DTYPE) * 40.0 + 10.0
    return img


# ==============================================================
# Benchmark A: Rebuild every frame
# ==============================================================

def benchmark_rebuild_every_frame(
    configs: list[ROIConfiguration],
    frames: int,
) -> float:
    """Recreate HRegion from geometry for every ROI, every frame."""
    image = _make_temperature_image()
    total_time = 0.0

    for _ in range(frames):
        frame_start = time.perf_counter()
        for cfg in configs:
            # Rebuild region from geometry every frame
            region = geometry_to_hregion(cfg.geometry)
            extract_statistics(region, image, frame_id=0)
        total_time += time.perf_counter() - frame_start

    return total_time


# ==============================================================
# Benchmark B: Cached (rebuild only if dirty)
# ==============================================================

def benchmark_cached(
    configs: list[ROIConfiguration],
    frames: int,
) -> float:
    """Build regions once, cache them, reuse across frames."""
    manager = RuntimeROIManagerImpl()
    manager.load(configs)
    manager.rebuild_dirty_regions(IMAGE_SHAPE)

    image = _make_temperature_image()
    total_time = 0.0

    for _ in range(frames):
        frame_start = time.perf_counter()
        # Use manager.process_frame() which reuses cached regions
        manager.process_frame(image, frame_id=0)
        total_time += time.perf_counter() - frame_start

    manager.unload()
    return total_time


# ==============================================================
# Benchmarks
# ==============================================================

class TestROIBenchmark:

    @pytest.fixture(scope="class")
    def configs(self):
        return _make_configs(N_ROIS)

    def test_rebuild_every_frame(self, configs):
        """Benchmark A: Rebuild HRegion every frame (slow path)."""
        elapsed = benchmark_rebuild_every_frame(configs, N_FRAMES)
        avg = (elapsed / N_FRAMES) * 1000
        per_roi = avg / N_ROIS
        print(
            f"\n  Rebuild every frame:  {elapsed:.3f}s total, "
            f"{avg:.2f}ms/frame, {per_roi:.3f}ms/ROI"
        )

    def test_cached(self, configs):
        """Benchmark B: Cached HRegion (fast path)."""
        elapsed = benchmark_cached(configs, N_FRAMES)
        avg = (elapsed / N_FRAMES) * 1000
        per_roi = avg / N_ROIS
        print(
            f"\n  Cached:               {elapsed:.3f}s total, "
            f"{avg:.2f}ms/frame, {per_roi:.3f}ms/ROI"
        )

    def test_comparison(self, configs):
        """Compare both strategies and report speedup."""
        rebuild_time = benchmark_rebuild_every_frame(configs, N_FRAMES)
        cached_time = benchmark_cached(configs, N_FRAMES)

        speedup = rebuild_time / cached_time if cached_time > 0 else float("inf")
        print(
            f"\n  Speedup (cached vs rebuild-every-frame): {speedup:.1f}x\n"
            f"  Cached:     {cached_time:.3f}s\n"
            f"  Rebuild:    {rebuild_time:.3f}s"
        )

        # Cached should be at least 3x faster in any reasonable scenario
        assert speedup > 3.0, (
            f"Cached ({cached_time:.3f}s) should be significantly faster "
            f"than rebuild-every-frame ({rebuild_time:.3f}s)"
        )


if __name__ == "__main__":
    print("Running ROI Phase 2 benchmark...")
    print(f"  ROIs:   {N_ROIS}")
    print(f"  Frames: {N_FRAMES}")
    print(f"  Image:  {IMAGE_SHAPE}")

    configs = _make_configs(N_ROIS)

    r = benchmark_rebuild_every_frame(configs, 5)
    c = benchmark_cached(configs, 5)
    speedup = r / c if c > 0 else float("inf")

    print(f"\n  Rebuild (5 frames): {r:.3f}s")
    print(f"  Cached  (5 frames): {c:.3f}s")
    print(f"  Speedup: {speedup:.1f}x")