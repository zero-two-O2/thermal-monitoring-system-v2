"""
test_roi_engine.py

Tests for the production ROI engine facade (roi_engine.engine).

Coverage: basic batch processing, statistic values, multi-camera
independence via the pool, pool lifecycle, guards, store generation
rebuilds, invalidate, backward-compatible runtime statistics, legacy
JSON repository compatibility, and resource release on clear().
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pytest

from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.geometry import (
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.persistence.repository import JSONROIRepository
from roi.runtime import RuntimeROIStatistics
from roi_engine.engine import ROIEngine, ROIEnginePool
from roi_engine.types import ROIShape

CAMERA_ID = "cam_1"
POSITION_STATE = AcquisitionState(camera_id=CAMERA_ID, pan=0, tilt=0, zoom=0, focus=0)
IMAGE_SIZE = 256


def _cfg(roi_id: str, geometry, enabled: bool = True) -> ROIConfiguration:
    """Build a minimal ROIConfiguration for tests."""
    return ROIConfiguration(
        roi_id=roi_id,
        name=roi_id,
        acquisition_state=POSITION_STATE,
        geometry=geometry,
        enabled=enabled,
    )


def _rect(roi_id: str, row: float, col: float, size: float, enabled: bool = True):
    return _cfg(roi_id, Rectangle1ROI(row, col, row + size, col + size), enabled)


def _gradient() -> np.ndarray:
    """256x256 uint16 image: column gradient 0..255."""
    return np.tile(np.arange(IMAGE_SIZE, dtype=np.uint16), (IMAGE_SIZE, 1))


def _mixed_configs(engine: ROIEngine) -> list[ROIConfiguration]:
    """50 rects + 20 circles + 10 polygons, 5 rects disabled -> 75 enabled."""
    configs: list[ROIConfiguration] = []
    for i in range(50):
        configs.append(_rect(f"rect_{i}", 10, 10, 60, enabled=i >= 5))
    for i in range(20):
        configs.append(_cfg(f"circle_{i}", CircleROI(120, 120, 20)))
    for i in range(10):
        configs.append(
            _cfg(
                f"poly_{i}",
                PolygonROI(((30, 100), (60, 110), (50, 150), (25, 140))),
            )
        )
    engine.load_position(configs)
    return configs


def _assert_valid(valid: np.ndarray, index: int) -> None:
    assert bool(valid[index]), f"ROI index {index} expected valid"


# ---------------------------------------------------------------------------
# Basic batch processing
# ---------------------------------------------------------------------------


def test_process_frame_basic() -> None:
    engine = ROIEngine(CAMERA_ID)
    configs = _mixed_configs(engine)

    result = engine.process_frame(_gradient(), frame_id=7)

    assert result.enabled_roi_count == 75
    assert result.frame_id == 7
    assert result.total_pixel_count > 0
    assert result.processing_time_ms >= 0.0

    by_shape = {ts.shape: ts for ts in result.per_type}
    assert set(by_shape) == {
        ROIShape.RECTANGLE1,
        ROIShape.CIRCLE,
        ROIShape.POLYGON,
    }
    assert by_shape[ROIShape.RECTANGLE1].count == 45
    assert by_shape[ROIShape.CIRCLE].count == 20
    assert by_shape[ROIShape.POLYGON].count == 10

    rect_stats = by_shape[ROIShape.RECTANGLE1].stats
    assert int(np.sum(rect_stats.valid)) == 45
    rect_store = engine.store().store_for(ROIShape.RECTANGLE1)
    first_enabled = int(rect_store.enabled_indices[0])
    assert rect_stats.frame_id[first_enabled] == 7
    assert rect_stats.timestamp[first_enabled] > 0.0

    for i in range(rect_store.count):
        assert bool(rect_stats.valid[i]) == bool(rect_store.enabled[i])

    disabled_rects = [i for i, c in enumerate(configs[:50]) if not c.enabled]
    assert disabled_rects
    for i in disabled_rects:
        assert not bool(rect_stats.valid[i])
        assert math.isnan(rect_stats.minimum[i])


def test_frame_stats_values() -> None:
    engine = ROIEngine(CAMERA_ID)
    engine.load_position([_rect("full", 0, 0, IMAGE_SIZE - 1)])

    result = engine.process_frame(_gradient(), frame_id=1)
    rect_stats = result.per_type[0].stats

    minimum = float(rect_stats.minimum[0])
    maximum = float(rect_stats.maximum[0])
    mean = float(rect_stats.mean[0])
    std = float(rect_stats.standard_deviation[0])

    assert minimum == pytest.approx(0.0, abs=1.0)
    assert maximum == pytest.approx(255.0, abs=1.0)
    assert mean == pytest.approx(127.5, abs=2.0)
    assert std == pytest.approx(73.9, abs=5.0)

    row_min, col_min, row_max, col_max = engine.store().store_for(
        ROIShape.RECTANGLE1
    ).bboxes[0]
    hotspot_y = int(rect_stats.hotspot_row[0])
    hotspot_x = int(rect_stats.hotspot_col[0])
    assert row_min <= hotspot_y <= row_max
    assert col_min <= hotspot_x <= col_max


# ---------------------------------------------------------------------------
# Pool: multi-camera independence + lifecycle
# ---------------------------------------------------------------------------


def test_multi_camera_independence() -> None:
    pool = ROIEnginePool()
    engine_a = pool.engine("cam_a")
    engine_b = pool.engine("cam_b")

    engine_a.load_position([_rect("a_1", 10, 10, 60)])
    engine_b.load_position([_rect("b_1", 100, 100, 60)])

    result_a = engine_a.process_frame(_gradient(), frame_id=1)
    result_b = engine_b.process_frame(_gradient(), frame_id=2)

    mean_a = float(result_a.per_type[0].stats.mean[0])
    mean_b = float(result_b.per_type[0].stats.mean[0])
    assert mean_a == pytest.approx(40.0, abs=2.0)
    assert mean_b == pytest.approx(130.0, abs=2.0)
    assert mean_a != mean_b
    assert result_b.frame_id == 2

    pool.remove("cam_a")
    assert pool.get("cam_a") is None
    assert pool.engine("cam_b") is engine_b
    assert engine_b.process_frame(_gradient(), frame_id=3).enabled_roi_count == 1


def test_pool_lifecycle() -> None:
    pool = ROIEnginePool()
    assert pool.camera_ids() == []

    engine = pool.engine("cam_a")
    assert pool.engine("cam_a") is engine
    assert pool.get("cam_a") is engine
    assert pool.camera_ids() == ["cam_a"]

    pool.remove("cam_a")
    assert pool.get("cam_a") is None
    assert pool.camera_ids() == []

    pool.engine("cam_b")
    pool.clear()
    assert pool.camera_ids() == []
    assert pool.get("cam_b") is None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_no_position_guard() -> None:
    engine = ROIEngine(CAMERA_ID)
    result = engine.process_frame(_gradient(), frame_id=1)
    assert result.enabled_roi_count == 0
    assert result.per_type == ()


def test_empty_image_guard() -> None:
    engine = ROIEngine(CAMERA_ID)
    _mixed_configs(engine)

    empty_result = engine.process_frame(np.zeros((0, 0), dtype=np.uint16), frame_id=1)
    assert empty_result.enabled_roi_count == 0
    assert empty_result.per_type == ()
    assert empty_result.total_pixel_count == 0

    none_result = engine.process_frame(None, frame_id=2)
    assert none_result.enabled_roi_count == 0
    assert none_result.per_type == ()


# ---------------------------------------------------------------------------
# Rebuild behaviour
# ---------------------------------------------------------------------------


def test_generation_rebuild() -> None:
    engine = ROIEngine(CAMERA_ID)
    engine.load_position([_rect("first", 0, 0, 40)])
    first = engine.process_frame(_gradient(), frame_id=1)
    assert first.enabled_roi_count == 1
    first_min = float(first.per_type[0].stats.minimum[0])
    assert first_min == pytest.approx(0.0, abs=1.0)

    engine.load_position([_rect("second", 150, 150, 40)])
    second = engine.process_frame(_gradient(), frame_id=2)
    assert second.enabled_roi_count == 1
    second_min = float(second.per_type[0].stats.minimum[0])
    assert second_min == pytest.approx(150.0, abs=1.0)
    assert second_min != first_min

    row_min, col_min, _, _ = engine.store().store_for(
        ROIShape.RECTANGLE1
    ).bboxes[0]
    assert int(row_min) == 150
    assert int(col_min) == 150


def test_invalidate() -> None:
    engine = ROIEngine(CAMERA_ID)
    engine.load_position([_rect("r", 0, 0, 40)])
    first = engine.process_frame(_gradient(), frame_id=1)
    assert bool(first.per_type[0].stats.valid[0])

    engine.invalidate()
    second = engine.process_frame(_gradient(), frame_id=2)
    assert bool(second.per_type[0].stats.valid[0])
    assert second.enabled_roi_count == 1


# ---------------------------------------------------------------------------
# Backward-compatible runtime statistics
# ---------------------------------------------------------------------------


def test_get_runtime_statistics_compat() -> None:
    engine = ROIEngine(CAMERA_ID)
    _mixed_configs(engine)
    engine.process_frame(_gradient(), frame_id=9)

    stats = engine.get_runtime_statistics()
    assert len(stats) == 75
    assert all(isinstance(s, RuntimeROIStatistics) for s in stats)

    store = engine.store()
    offset = 0
    for shape in (
        ROIShape.RECTANGLE1,
        ROIShape.CIRCLE,
        ROIShape.POLYGON,
    ):
        type_store = store.store_for(shape)
        runtime = type_store.runtime
        entries = stats[offset : offset + type_store.enabled_count()]
        offset += type_store.enabled_count()
        assert len(entries) == type_store.enabled_count()
        for idx, s in zip(type_store.enabled_indices, entries):
            assert s.valid == bool(runtime.valid[idx])
            assert s.hotspot_x == int(runtime.hotspot_col[idx])
            assert s.hotspot_y == int(runtime.hotspot_row[idx])
            assert s.pixel_count == int(runtime.pixel_count[idx])
            assert s.processing_time_ms == pytest.approx(
                float(runtime.processing_time_ms[idx])
            )
            assert s.frame_id == int(runtime.frame_id[idx])
            assert not s.alarm_active
            assert s.alarm_since is None
            assert isinstance(s.last_updated, datetime)
            _approx_or_nan(s.minimum, float(runtime.minimum[idx]))
            _approx_or_nan(s.maximum, float(runtime.maximum[idx]))
            _approx_or_nan(s.mean, float(runtime.mean[idx]))
            _approx_or_nan(s.standard_deviation, float(runtime.standard_deviation[idx]))


def _approx_or_nan(actual: float, expected: float) -> None:
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Legacy JSON repository compatibility
# ---------------------------------------------------------------------------


def test_backward_compat_json_load(tmp_path) -> None:
    repository = JSONROIRepository(str(tmp_path))
    configs = [
        _rect("rect_a", 10, 10, 40),
        _rect("rect_b", 60, 60, 30, enabled=False),
        _cfg("circle_a", CircleROI(120, 120, 15)),
        _cfg("poly_a", PolygonROI(((30, 100), (60, 110), (50, 150)))),
        _cfg(
            "rect2_a",
            Rectangle2ROI(80, 180, 0.3, 20, 10),
        ),
        _cfg("ellipse_a", EllipseROI(200, 50, 0.5, 25, 12)),
        _rect("rect_c", 30, 200, 30),
        _cfg("circle_b", CircleROI(200, 200, 12)),
        _cfg("poly_b", PolygonROI(((150, 40), (190, 40), (170, 90)))),
        _cfg(
            "rect2_b",
            Rectangle2ROI(50, 220, -0.5, 15, 8),
        ),
    ]
    repository.save_all(configs)

    loaded = repository.load_all(POSITION_STATE)
    assert len(loaded) == 10

    engine = ROIEngine(CAMERA_ID)
    engine.load_position(loaded)
    result = engine.process_frame(_gradient(), frame_id=5)

    assert result.enabled_roi_count == 9
    assert result.total_pixel_count > 0
    assert len(engine.get_runtime_statistics()) == 9


# ---------------------------------------------------------------------------
# Resource release
# ---------------------------------------------------------------------------


def test_clear_releases() -> None:
    engine = ROIEngine(CAMERA_ID)
    _mixed_configs(engine)
    assert engine.process_frame(_gradient(), frame_id=1).enabled_roi_count == 75

    engine.clear()
    assert engine.store() is None
    assert engine.position_id() is None
    assert engine.get_runtime_statistics() == []

    result = engine.process_frame(_gradient(), frame_id=2)
    assert result.enabled_roi_count == 0
    assert result.per_type == ()
