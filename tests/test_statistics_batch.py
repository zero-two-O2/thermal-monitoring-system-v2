"""
Statistics engine batch tests.

The engine's batch HALCON calls must produce exactly the same numbers
as the legacy per-ROI loop in roi/statistics.py (same operators, same
arguments), so the reference here is the legacy path itself.
"""

from __future__ import annotations

import halcon as ha
import numpy as np

from conftest import build_test_store, make_config, synthetic_image
from roi.geometry import (
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.geometry_to_hregion import geometry_to_hregion
from roi.statistics import extract_statistics
from roi_engine.masks import MaskCache
from roi_engine.region_cache import RegionCache
from roi_engine.statistics_engine import StatisticsEngine
from roi_engine.types import ROIShape


def _geometry_batch() -> list:
    geoms: list = []
    for i in range(30):
        r0 = 20 + (i % 5) * 80
        c0 = 20 + (i // 5) * 110
        geoms.append(Rectangle1ROI(r0, c0, r0 + 30, c0 + 40))
    for i in range(20):
        r = 60 + (i % 4) * 100
        c = 80 + (i // 4) * 120
        geoms.append(CircleROI(r, c, 15 + (i % 5) * 3))
    for i in range(10):
        r = 100 + (i % 5) * 70
        c = 120 + (i // 5) * 160
        geoms.append(EllipseROI(r, c, 0.3 + i * 0.1, 25, 10))
    for i in range(10):
        r = 200 + (i % 5) * 60
        c = 180 + (i // 5) * 160
        geoms.append(Rectangle2ROI(r, c, -0.5 + i * 0.2, 30, 12))
    for i in range(5):
        r0 = 60 + i * 80
        c0 = 90 + i * 100
        geoms.append(
            PolygonROI(
                (
                    (r0, c0),
                    (r0 + 30, c0),
                    (r0 + 30, c0 + 30),
                    (r0 + 10, c0 + 40),
                    (r0, c0 + 30),
                )
            )
        )
    return geoms


def _build_env(geoms: list | None = None, enabled_mask: set[int] | None = None):
    geoms = geoms if geoms is not None else _geometry_batch()
    enabled_mask = enabled_mask if enabled_mask is not None else set(range(len(geoms)))
    configs = [
        make_config(f"roi_{i:03d}", geom, enabled=i in enabled_mask)
        for i, geom in enumerate(geoms)
    ]
    store = build_test_store(configs)
    regions = RegionCache()
    regions.rebuild(store)
    masks = MaskCache()
    image = synthetic_image()
    masks.rebuild(store, image.shape)
    himage = ha.himage_from_numpy_array(image)
    return store, regions, masks, himage, image


def _runtime_for(store, roi_id: str):
    """(type_store, index) for an ROI id."""
    for shape in store._stores:
        type_store = store.store_for(shape)
        if roi_id in type_store.roi_ids:
            return type_store, type_store.roi_ids.index(roi_id)
    raise AssertionError(f"ROI {roi_id} not found in store")


def _geometry_from_store(shape, type_store, index):
    """Reconstruct the geometry dataclass from a test type store."""
    if shape is ROIShape.RECTANGLE1:
        return Rectangle1ROI(
            float(type_store.row1s[index]), float(type_store.col1s[index]),
            float(type_store.row2s[index]), float(type_store.col2s[index]),
        )
    if shape is ROIShape.CIRCLE:
        return CircleROI(
            float(type_store.rows[index]), float(type_store.cols[index]),
            float(type_store.radii[index]),
        )
    if shape is ROIShape.ELLIPSE:
        return EllipseROI(
            float(type_store.rows[index]), float(type_store.cols[index]),
            float(type_store.phis[index]), float(type_store.radius1s[index]),
            float(type_store.radius2s[index]),
        )
    if shape is ROIShape.RECTANGLE2:
        return Rectangle2ROI(
            float(type_store.rows[index]), float(type_store.cols[index]),
            float(type_store.phis[index]), float(type_store.length1s[index]),
            float(type_store.length2s[index]),
        )
    if shape is ROIShape.POLYGON:
        rows = type_store.rows[index].tolist()
        cols = type_store.cols[index].tolist()
        return PolygonROI(tuple(zip(map(float, rows), map(float, cols))))
    raise AssertionError(f"Unsupported shape {shape}")


def _legacy_reference(store, image, roi_id):
    """Per-ROI legacy statistics for a single ROI (reference truth)."""
    type_store, idx = _runtime_for(store, roi_id)
    geom = _geometry_from_store(type_store.shape, type_store, idx)
    return extract_statistics(geometry_to_hregion(geom), image, 1)


def test_batch_matches_legacy_exactly() -> None:
    """Batch stats are bit-identical to the legacy per-ROI loop."""
    store, regions, masks, himage, image = _build_env()
    engine = StatisticsEngine()
    results = engine.process(himage, store, regions, masks, frame_id=7, timestamp=1.5)
    assert results
    for shape, type_store in store._stores.items():
        for i, roi_id in enumerate(type_store.roi_ids):
            if not type_store.enabled[i]:
                continue
            ref = _legacy_reference(store, image, roi_id)
            run = type_store.runtime
            assert _same_or_nan(ref.minimum, run.minimum[i])
            assert _same_or_nan(ref.maximum, run.maximum[i])
            assert _same_or_nan(ref.mean, run.mean[i])
            assert _same_or_nan(ref.standard_deviation, run.standard_deviation[i])
            assert ref.pixel_count == run.pixel_count[i]
            assert run.valid[i]
            assert run.frame_id[i] == 7
            assert run.timestamp[i] == 1.5


def test_disabled_rois_are_not_processed() -> None:
    """Disabled ROIs keep the runtime defaults (valid=False, NaN)."""
    geoms = _geometry_batch()
    enabled = {0, 1, 30, 50, 75}
    store, regions, masks, himage, _ = _build_env(
        geoms, enabled_mask=enabled
    )
    engine = StatisticsEngine()
    results = engine.process(himage, store, regions, masks, frame_id=3, timestamp=0.0)
    assert results
    for shape, type_store in store._stores.items():
        for i, roi_id in enumerate(type_store.roi_ids):
            run = type_store.runtime
            if type_store.enabled[i]:
                assert run.valid[i]
            else:
                assert not run.valid[i]
                assert np.isnan(run.minimum[i])
                assert run.hotspot_row[i] == -1
                assert run.hotspot_col[i] == -1
                assert run.pixel_count[i] == 0
                assert run.frame_id[i] == -1


def test_none_image_returns_empty() -> None:
    """A None image yields no results and no errors."""
    store, regions, masks, himage, _ = _build_env()
    engine = StatisticsEngine()
    assert engine.process(None, store, regions, masks, frame_id=1, timestamp=0.0) == {}


def test_nan_frame_matches_legacy() -> None:
    """NaN pixels: min/max/area stay finite, mean/std become NaN."""
    geoms = _geometry_batch() + [
        Rectangle1ROI(200, 200, 260, 260),
        CircleROI(320, 320, 40),
        PolygonROI(((120, 480), (160, 480), (160, 520), (120, 520))),
    ]
    store, regions, masks, himage, image = _build_env(geoms)
    image[200:240, 200:240] = np.nan
    image[300:340, 300:340] = np.nan
    image[120:160, 480:520] = np.nan
    himage = ha.himage_from_numpy_array(image)
    engine = StatisticsEngine()
    results = engine.process(himage, store, regions, masks, frame_id=5, timestamp=0.0)
    assert results
    for shape, type_store in store._stores.items():
        for i, roi_id in enumerate(type_store.roi_ids):
            if not type_store.enabled[i]:
                continue
            ref = _legacy_reference(store, image, roi_id)
            run = type_store.runtime
            assert _same_or_nan(ref.minimum, run.minimum[i])
            assert _same_or_nan(ref.maximum, run.maximum[i])
            assert _same_or_nan(ref.mean, run.mean[i])
            assert _same_or_nan(ref.standard_deviation, run.standard_deviation[i])
            assert ref.pixel_count == run.pixel_count[i]
            assert np.isfinite(image[run.hotspot_row[i], run.hotspot_col[i]])


def test_fully_nan_roi_has_placeholder_hotspot() -> None:
    """An ROI made entirely of NaN pixels reports a (-1, -1) hotspot."""
    geoms = [
        Rectangle1ROI(300, 300, 330, 330),
        CircleROI(200, 200, 20),
    ]
    store, regions, masks, himage, image = _build_env(geoms)
    image[300:331, 300:331] = np.nan
    himage = ha.himage_from_numpy_array(image)
    engine = StatisticsEngine()
    results = engine.process(himage, store, regions, masks, frame_id=2, timestamp=0.0)
    assert results
    type_store, idx = _runtime_for(store, "roi_000")
    assert type_store.runtime.valid[idx]
    assert np.isnan(type_store.runtime.maximum[idx])
    assert type_store.runtime.hotspot_row[idx] == -1
    assert type_store.runtime.hotspot_col[idx] == -1
    type_store1, idx1 = _runtime_for(store, "roi_001")
    assert type_store1.runtime.valid[idx1]
    assert type_store1.runtime.hotspot_row[idx1] != -1


def test_hotspot_inside_bbox_and_equals_maximum() -> None:
    """Hotspot lies inside the ROI bbox and carries the maximum value."""
    geoms = _geometry_batch()
    store, regions, masks, himage, image = _build_env(geoms)
    engine = StatisticsEngine()
    results = engine.process(himage, store, regions, masks, frame_id=4, timestamp=0.0)
    assert results
    for shape, type_store in store._stores.items():
        bboxes = type_store.bboxes
        for i, roi_id in enumerate(type_store.roi_ids):
            if not type_store.enabled[i]:
                continue
            run = type_store.runtime
            hr, hc = run.hotspot_row[i], run.hotspot_col[i]
            r_min, c_min, r_max, c_max = bboxes[i]
            assert r_min <= hr <= r_max
            assert c_min <= hc <= c_max
            assert image[hr, hc] == run.maximum[i]


def test_repeated_frames_are_consistent() -> None:
    """Same inputs produce identical outputs on every call."""
    store, regions, masks, himage, _ = _build_env()
    engine = StatisticsEngine()
    engine.process(himage, store, regions, masks, frame_id=1, timestamp=1.0)
    first = {
        shape: (
            type_store.runtime.minimum.copy(),
            type_store.runtime.maximum.copy(),
            type_store.runtime.hotspot_row.copy(),
            type_store.runtime.hotspot_col.copy(),
        )
        for shape, type_store in store._stores.items()
    }
    engine.process(himage, store, regions, masks, frame_id=2, timestamp=2.0)
    for shape, type_store in store._stores.items():
        min0, max0, hr0, hc0 = first[shape]
        np.testing.assert_array_equal(min0, type_store.runtime.minimum)
        np.testing.assert_array_equal(max0, type_store.runtime.maximum)
        np.testing.assert_array_equal(hr0, type_store.runtime.hotspot_row)
        np.testing.assert_array_equal(hc0, type_store.runtime.hotspot_col)


def _same_or_nan(a: float, b: float) -> bool:
    """Exact equality, treating NaN == NaN as true."""
    return bool((a == b) or (np.isnan(a) and np.isnan(b)))
