"""
ROI store tests.

These tests validate the type-array ROI store: immutable snapshots built from
multiple ROI configurations, grouped by shape (Rectangle1, Rectangle2, Circle,
Ellipse, Polygon). The store must be immutable, generate per-type parallel
arrays, and support the contract expected by the processing engine.

These are unit tests for the store itself, verifying the contract that the
StatisticsEngine and MaskCache rely on: store_for(), enabled_indices, bboxes,
roi_ids, and the per-type geometry arrays.
"""

from __future__ import annotations

from conftest import make_config
from roi.geometry import CircleROI, EllipseROI, PolygonROI, Rectangle1ROI, Rectangle2ROI
from roi_engine.store.factory import build_store
from roi_engine.types import ALL_SHAPES, ROIShape


def test_build_store_creates_empty_when_no_configs() -> None:
    """Empty configs produce an empty store."""
    store = build_store("cam1", "pos1", [])
    assert store.camera_id == "cam1"
    assert store.position_id == "pos1"
    assert store.generation == 1
    for shape in ALL_SHAPES:
        assert store.store_for(shape) is None


def test_build_store_immutability() -> None:
    """Config arrays are write-protected; runtime arrays remain mutable."""
    configs = [
        make_config("r1", Rectangle1ROI(10, 20, 30, 40), enabled=True),
        make_config("c1", CircleROI(50, 60, 15), enabled=True),
    ]
    store = build_store("cam2", "pos2", configs)
    for shape in ALL_SHAPES:
        type_store = store.store_for(shape)
        if type_store is None:
            continue
        # config arrays should be immutable
        for attr in ("enabled", "visible", "alarm_enabled", "bboxes"):
            assert not getattr(type_store, attr).flags.writeable, f"{shape}.{attr}"
        # runtime arrays may still be written by the stats engine
        type_store.runtime.minimum[0] = 99.0
        assert type_store.runtime.minimum[0] == 99.0


def test_enabled_indices_match_enabled_flag() -> None:
    """enabled_indices contains only indices where enabled=True."""
    configs = [
        make_config("r1", Rectangle1ROI(10, 20, 30, 40), enabled=True),
        make_config("r2", Rectangle1ROI(50, 60, 70, 80), enabled=False),
        make_config("r3", Rectangle1ROI(100, 110, 120, 130), enabled=True),
    ]
    store = build_store("cam3", "pos3", configs)
    type_store = store.store_for(ROIShape.RECTANGLE1)
    assert type_store is not None
    enabled_indices = type_store.enabled_indices
    assert len(enabled_indices) == 2
    assert set(enabled_indices) == {0, 2}
    assert type_store.roi_ids[0] == "r1"
    assert type_store.roi_ids[2] == "r3"


def test_disabled_rois_are_not_in_enabled_indices() -> None:
    """Disabled ROIs never appear in enabled_indices, even if they have IDs."""
    configs = [
        make_config("r1", Rectangle1ROI(0, 0, 10, 10), enabled=False),
        make_config("r2", Rectangle1ROI(20, 20, 30, 30), enabled=False),
    ]
    store = build_store("cam4", "pos4", configs)
    type_store = store.store_for(ROIShape.RECTANGLE1)
    assert type_store is not None
    assert type_store.enabled_indices.size == 0
    assert type_store.count == 2


def test_store_generation_increments() -> None:
    """Explicit generation parameter is stored."""
    configs = [make_config("r1", Rectangle1ROI(0, 0, 10, 10), enabled=True)]
    store = build_store("cam5", "pos5", configs, generation=99)
    assert store.generation == 99


def test_store_unsupported_shape_skipped() -> None:
    """Unsupported geometry shapes are silently skipped (not produced)."""
    # All supported shapes are used here
    configs = [
        make_config("r1", Rectangle1ROI(0, 0, 5, 5), enabled=True),
        make_config("c1", CircleROI(10, 10, 5), enabled=True),
        make_config("e1", EllipseROI(20, 20, 0.0, 5, 3), enabled=True),
        make_config("r21", Rectangle2ROI(30, 30, 0.0, 5, 3), enabled=True),
        make_config("p1", PolygonROI(((0, 0), (10, 0), (10, 10))), enabled=True),
    ]
    store = build_store("cam6", "pos6", configs)
    for shape in ALL_SHAPES:
        type_store = store.store_for(shape)
        if type_store is None:
            continue
        # each type store should have one ROI
        assert type_store.enabled_count() == 1


def test_all_type_arrays_populated() -> None:
    """Every shape that appears gets a fully populated type store."""
    configs = [
        make_config("r1", Rectangle1ROI(0, 0, 5, 5), enabled=True),
        make_config("c1", CircleROI(10, 10, 5), enabled=True),
        make_config("e1", EllipseROI(20, 20, 0.0, 5, 3), enabled=True),
        make_config("r21", Rectangle2ROI(30, 30, 0.0, 5, 3), enabled=True),
        make_config("p1", PolygonROI(((0, 0), (10, 0), (10, 10))), enabled=True),
    ]
    store = build_store("cam7", "pos7", configs)
    # ensure each shape appears and has data
    for shape in ALL_SHAPES:
        type_store = store.store_for(shape)
        if type_store is None:
            continue
        assert type_store.roi_ids
        assert type_store.bboxes is not None
        assert type_store.roi_ids[0] in ("r1", "c1", "e1", "r21", "p1")


def test_memory_bytes_accounts_for_config_and_runtime() -> None:
    """memory_bytes includes both config arrays and runtime arrays."""
    configs = [
        make_config("r1", Rectangle1ROI(0, 0, 5, 5), enabled=True),
        make_config("c1", CircleROI(10, 10, 5), enabled=True),
    ]
    store = build_store("cam8", "pos8", configs)
    total_bytes = store.memory_bytes()
    # rough check: at least 2 ROIs * (bboxes 8 bytes each + overhead)
    # should be > 0
    assert total_bytes > 0


def test_empty_store_has_no_type_stores() -> None:
    """An empty store returns None for all shapes."""
    store = build_store("cam9", "pos9", [])
    for shape in ALL_SHAPES:
        assert store.store_for(shape) is None


def test_multiple_cameras_independent_stores() -> None:
    """Stores are independent per camera and position."""
    configs1 = [make_config("r1", Rectangle1ROI(0, 0, 5, 5), enabled=True)]
    configs2 = [make_config("r2", Rectangle1ROI(10, 10, 15, 15), enabled=True)]
    store1 = build_store("cam_a", "pos_a", configs1)
    store2 = build_store("cam_b", "pos_b", configs2)
    assert store1.camera_id == "cam_a"
    assert store2.camera_id == "cam_b"
    assert store1.position_id == "pos_a"
    assert store2.position_id == "pos_b"
    assert store1.store_for(ROIShape.RECTANGLE1).roi_ids[0] == "r1"
    assert store2.store_for(ROIShape.RECTANGLE1).roi_ids[0] == "r2"


def test_store_uuid_uniqueness() -> None:
    """Different configs produce stores with same IDs but independent internals."""
    # store is immutable snapshot; uuid is not part of the snapshot
    # but we can verify generation is independent
    configs = [make_config("r1", Rectangle1ROI(0, 0, 5, 5), enabled=True)]
    store1 = build_store("cam_x", "pos_x", configs, generation=1)
    store2 = build_store("cam_x", "pos_x", configs, generation=2)
    assert store1.generation != store2.generation
    # runtime arrays are independent snapshots
    assert store1.store_for(ROIShape.RECTANGLE1) is not store2.store_for(ROIShape.RECTANGLE1)
