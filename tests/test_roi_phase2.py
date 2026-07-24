"""
test_roi_phase2.py

Unit tests for Phase 2 of the ROI subsystem:
- geometry_to_hregion conversion (HALCON-based)
- RuntimeROICache lifecycle (clear, dirty flag)
- RuntimeROIManagerImpl (load, rebuild, error handling)
- Statistics extraction (HALCON-based)

Tests requiring HALCON are skipped when the library is unavailable.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from roi.configuration import ROIConfiguration
from roi.acquisition_state import AcquisitionState
from roi.geometry import (
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
    ROIGeometry,
)
from roi.runtime_cache import RuntimeROICache
from roi.runtime import RuntimeROIState, RuntimeROIStatistics
from roi.runtime_manager import RuntimeROIManagerImpl


# ==============================================================
# Helpers
# ==============================================================

_TEMP_IMAGE = np.zeros((480, 640), dtype=np.float32)
_TEMP_IMAGE[200:300, 200:400] = 36.5  # warm rectangle
_TEMP_IMAGE[240:260, 280:320] = 42.0  # hotspot


def _make_config(
    roi_id: str,
    geometry: ROIGeometry,
) -> ROIConfiguration:
    return ROIConfiguration(
        roi_id=roi_id,
        name=f"Test-{roi_id}",
        acquisition_state=AcquisitionState(
            camera_id="cam_1", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0
        ),
        geometry=geometry,
    )


# ==============================================================
# Tests: geometry_to_hregion (require HALCON)
# ==============================================================

halcon = pytest.importorskip("halcon", reason="HALCON library not available")
from roi.geometry_to_hregion import geometry_to_hregion  # noqa: E402


class TestGeometryToHRegion:
    """Verify all five geometry types convert correctly."""

    def test_rectangle1(self):
        g = Rectangle1ROI(row1=100.0, col1=50.0, row2=200.0, col2=300.0)
        region = geometry_to_hregion(g)
        assert region is not None
        _ac = halcon.area_center(region)
        expected = (200 - 100) * (300 - 50)
        assert int(_ac[0][0]) == expected

    def test_rectangle2(self):
        g = Rectangle2ROI(row=150, col=200, phi=0.0, length1=50, length2=30)
        region = geometry_to_hregion(g)
        _ac = halcon.area_center(region)
        expected = 100 * 60  # 2*length1 * 2*length2
        assert int(_ac[0][0]) == expected

    def test_circle(self):
        g = CircleROI(row=100, col=100, radius=25)
        region = geometry_to_hregion(g)
        _ac = halcon.area_center(region)
        assert int(_ac[0][0]) > 1900  # pi * 25^2 ≈ 1963
        assert int(_ac[1][0]) == 100
        assert int(_ac[2][0]) == 100

    def test_ellipse(self):
        g = EllipseROI(row=100, col=100, phi=0.0, radius1=40, radius2=20)
        region = geometry_to_hregion(g)
        _ac = halcon.area_center(region)
        assert int(_ac[0][0]) > 2400  # pi * 40 * 20 ≈ 2513

    def test_polygon(self):
        g = PolygonROI(points=((50, 50), (150, 50), (150, 150), (50, 150)))
        region = geometry_to_hregion(g)
        _ac = halcon.area_center(region)
        assert int(_ac[0][0]) == 100 * 100

    def test_invalid_geometry_raises(self):
        g = CircleROI(row=0, col=0, radius=-5)
        with pytest.raises(ValueError):
            geometry_to_hregion(g)

    def test_unknown_type_raises(self):
        class FakeGeometry(ROIGeometry):
            @property
            def shape(self):
                from roi.types import ROIShape
                return ROIShape.POLYGON
            def validate(self):
                pass
            def bounding_box(self):
                return (0, 0, 0, 0)
        with pytest.raises(TypeError):
            geometry_to_hregion(FakeGeometry())


# ==============================================================
# Tests: RuntimeROICache lifecycle
# ==============================================================

class TestRuntimeROICache:

    def test_initial_state(self):
        cache = RuntimeROICache()
        assert cache.region is None
        assert cache.area == 0.0
        assert cache.bounding_box == (0.0, 0.0, 0.0, 0.0)
        assert cache.dirty is True
        assert cache.last_generation is None

    def test_populated_cache(self):
        cache = RuntimeROICache()
        cache.region = halcon.gen_circle(50, 50, 25)
        cache.area = 1963.0
        cache.bounding_box = (25.0, 25.0, 75.0, 75.0)
        cache.dirty = False
        cache.last_generation = datetime.now()

        assert cache.region is not None
        assert cache.area == pytest.approx(1963.0, rel=0.1)
        assert cache.dirty is False

    def test_clear_releases_region(self):
        cache = RuntimeROICache()
        cache.region = halcon.gen_circle(50, 50, 25)
        cache.area = 1963.0
        cache.dirty = False
        cache.last_generation = datetime.now()

        cache.clear()

        assert cache.region is None
        assert cache.area == 0.0
        assert cache.dirty is True
        assert cache.last_generation is None


# ==============================================================
# Tests: RuntimeROIManagerImpl
# ==============================================================

class TestRuntimeROIManagerImpl:

    def test_load_creates_one_roi_per_config(self):
        mgr = RuntimeROIManagerImpl()
        configs = [
            _make_config("r1", Rectangle1ROI(10, 10, 100, 100)),
            _make_config("r2", CircleROI(50, 50, 25)),
        ]
        mgr.load(configs)
        assert len(mgr.get_all()) == 2
        assert mgr.get_by_id("r1") is not None
        assert mgr.get_by_id("r2") is not None
        assert mgr.get_by_id("missing") is None

    def test_load_replaces_previous(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", Rectangle1ROI(10, 10, 100, 100))])
        assert len(mgr.get_all()) == 1

        mgr.load([_make_config("r2", CircleROI(50, 50, 25))])
        assert len(mgr.get_all()) == 1
        assert mgr.get_by_id("r2") is not None

    def test_unload_clears_everything(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", Rectangle1ROI(10, 10, 100, 100))])
        mgr.rebuild_dirty_regions()

        mgr.unload()
        assert len(mgr.get_all()) == 0

    def test_get_active_filters_disabled_and_error(self):
        mgr = RuntimeROIManagerImpl()
        cfg1 = _make_config("good", CircleROI(50, 50, 25))
        cfg2 = _make_config("disabled", Rectangle1ROI(10, 10, 100, 100))
        cfg2.enabled = False
        cfg3 = _make_config("error", CircleROI(50, 50, 25))

        mgr.load([cfg1, cfg2, cfg3])
        mgr.rebuild_dirty_regions()
        mgr.update_state("error", RuntimeROIState.ERROR)

        active = mgr.get_active()
        assert len(active) == 1
        assert active[0].configuration.roi_id == "good"

    def test_rebuild_dirty_regions_success(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("r1", Rectangle1ROI(10, 10, 100, 200)),
            _make_config("r2", CircleROI(50, 50, 25)),
        ])

        assert all(r.cache.dirty for r in mgr.get_all())

        mgr.rebuild_dirty_regions((480, 640))

        for roi in mgr.get_all():
            assert roi.cache.dirty is False
            assert roi.cache.region is not None
            assert roi.cache.area > 0
            assert roi.state == RuntimeROIState.ACTIVE

    def test_rebuild_dirty_sets_error_on_failure(self):
        mgr = RuntimeROIManagerImpl()
        # Valid geometry
        good = _make_config("good", Rectangle1ROI(10, 10, 100, 100))
        mgr.load([good])

        mgr.rebuild_dirty_regions((480, 640))
        assert mgr.get_by_id("good").state == RuntimeROIState.ACTIVE

    def test_mark_dirty_specific(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("r1", CircleROI(50, 50, 25)),
            _make_config("r2", CircleROI(50, 50, 30)),
        ])
        mgr.rebuild_dirty_regions()
        assert all(not r.cache.dirty for r in mgr.get_all())

        mgr.mark_dirty("r1")
        assert mgr.get_by_id("r1").cache.dirty is True
        assert mgr.get_by_id("r2").cache.dirty is False

    def test_mark_dirty_all(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("r1", CircleROI(50, 50, 25)),
            _make_config("r2", CircleROI(50, 50, 30)),
        ])
        mgr.rebuild_dirty_regions()

        mgr.mark_dirty()
        assert all(r.cache.dirty for r in mgr.get_all())

    def test_refresh_statistics_updates_roi(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", CircleROI(50, 50, 25))])

        stats = RuntimeROIStatistics(
            valid=True,
            mean=36.5,
            maximum=42.0,
            frame_id=100,
            processing_time_ms=1.5,
        )
        mgr.refresh_statistics("r1", stats)

        roi = mgr.get_by_id("r1")
        assert roi.statistics is not None
        assert roi.statistics.mean == 36.5
        assert roi.statistics.frame_id == 100

    def test_update_state(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", CircleROI(50, 50, 25))])

        mgr.update_state("r1", RuntimeROIState.ERROR)
        assert mgr.get_by_id("r1").state == RuntimeROIState.ERROR


# ==============================================================
# Tests: Statistics extraction (require HALCON)
# ==============================================================

@pytest.mark.skipif(not halcon, reason="HALCON not available")
class TestStatisticsExtraction:

    def test_extract_statistics_valid(self):
        from roi.statistics import extract_statistics

        # Create a simple region and temperature image
        region = halcon.HRegion.gen_rectangle1(100, 100, 200, 300)
        image = np.zeros((480, 640), dtype=np.float32)
        image[100:201, 100:301] = 36.5

        stats = extract_statistics(region, image, frame_id=1)

        assert stats.valid is True
        assert stats.mean > 0
        assert stats.pixel_count == 101 * 201
        assert stats.frame_id == 1
        assert stats.processing_time_ms > 0

    def test_extract_statistics_empty_region(self):
        from roi.statistics import extract_statistics

        region = halcon.gen_empty_region()
        image = np.zeros((480, 640), dtype=np.float32)

        stats = extract_statistics(region, image, frame_id=2)

        assert stats.valid is False
        assert stats.pixel_count == 0

    def test_extract_statistics_hotspot(self):
        from roi.statistics import extract_statistics

        region = halcon.HRegion.gen_rectangle1(50, 50, 150, 150)
        image = np.full((480, 640), 36.0, dtype=np.float32)
        image[100, 100] = 50.0  # hotspot

        stats = extract_statistics(region, image, frame_id=3)

        assert stats.valid is True
        assert stats.maximum >= 50.0
        assert stats.hotspot_x == 100
        assert stats.hotspot_y == 100


# ==============================================================
# Tests: Process_frame integration
# ==============================================================

@pytest.mark.skipif(not halcon, reason="HALCON not available")
class TestProcessFrame:

    def test_process_frame_with_hotspot(self):
        mgr = RuntimeROIManagerImpl()
        rect = Rectangle1ROI(50, 50, 150, 150)
        cfg = _make_config("r1", rect)
        mgr.load([cfg])

        image = np.full((480, 640), 30.0, dtype=np.float32)
        image[100, 100] = 50.0

        results = mgr.process_frame(image, frame_id=10)

        assert len(results) == 1
        stats = results[0]
        assert stats.valid is True
        assert stats.maximum >= 50.0
        assert stats.frame_id == 10

    def test_process_frame_multiple_rois(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("r1", Rectangle1ROI(10, 10, 100, 200)),
            _make_config("r2", CircleROI(50, 50, 25)),
            _make_config("r3", Rectangle1ROI(200, 200, 300, 400)),
        ])

        image = np.zeros((480, 640), dtype=np.float32)
        results = mgr.process_frame(image, frame_id=5)

        assert len(results) == 3
        assert all(r.valid for r in results)

    def test_process_frame_handles_disabled(self):
        mgr = RuntimeROIManagerImpl()
        cfg = _make_config("r1", Rectangle1ROI(10, 10, 100, 100))
        cfg.enabled = False
        mgr.load([cfg, _make_config("r2", CircleROI(50, 50, 25))])

        image = np.zeros((480, 640), dtype=np.float32)
        results = mgr.process_frame(image, frame_id=5)

        assert len(results) == 1  # only enabled ROI

    def test_persistent_config_unchanged_after_processing(self):
        """Rule 1: ROIConfiguration must never be modified during runtime."""
        mgr = RuntimeROIManagerImpl()
        geometry = Rectangle1ROI(10, 10, 100, 100)
        cfg = _make_config("r1", geometry)
        original_id = cfg.roi_id
        original_name = cfg.name

        mgr.load([cfg])
        image = np.zeros((480, 640), dtype=np.float32)
        mgr.process_frame(image, frame_id=1)

        assert cfg.roi_id == original_id
        assert cfg.name == original_name
        assert cfg.geometry == geometry


# ==============================================================
# Tests: Dirty rebuild lifecycle (Rule 4)
# ==============================================================

@pytest.mark.skipif(not halcon, reason="HALCON not available")
class TestDirtyRebuildLifecycle:

    def test_regions_not_rebuilt_if_not_dirty(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", Rectangle1ROI(10, 10, 100, 100))])
        mgr.rebuild_dirty_regions((480, 640))
        region_before = mgr.get_by_id("r1").cache.region

        # Rebuild again — should be no-op since not dirty
        mgr.rebuild_dirty_regions((480, 640))
        region_after = mgr.get_by_id("r1").cache.region
        assert region_before is region_after  # same object

    def test_mark_dirty_triggers_rebuild(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([_make_config("r1", Rectangle1ROI(10, 10, 100, 100))])
        mgr.rebuild_dirty_regions((480, 640))
        region_before = mgr.get_by_id("r1").cache.region

        mgr.mark_dirty("r1")
        mgr.rebuild_dirty_regions((480, 640))
        region_after = mgr.get_by_id("r1").cache.region

        # Should be a different HRegion instance (newly generated)
        assert region_before is not region_after


# ==============================================================
# Tests: Error handling (Rule 7)
# ==============================================================

class TestErrorHandling:

    def test_invalid_geometry_sets_error_state(self):
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("bad", CircleROI(0, 0, -1)),  # invalid
            _make_config("good", Rectangle1ROI(10, 10, 100, 100)),
        ])
        mgr.rebuild_dirty_regions((480, 640))

        assert mgr.get_by_id("bad").state == RuntimeROIState.ERROR
        assert mgr.get_by_id("good").state == RuntimeROIState.ACTIVE

    def test_one_invalid_does_not_block_others(self):
        """Rule 7: Never stop the entire camera because one ROI fails."""
        mgr = RuntimeROIManagerImpl()
        mgr.load([
            _make_config("bad", CircleROI(0, 0, -1)),
            _make_config("good", Rectangle1ROI(10, 10, 100, 100)),
        ])
        mgr.rebuild_dirty_regions((480, 640))

        active = mgr.get_active()
        assert len(active) == 1
        assert active[0].configuration.roi_id == "good"