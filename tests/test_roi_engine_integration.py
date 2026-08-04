"""
test_roi_engine_integration.py

Tests for the ROIEngineManager adapter (roi_engine.integration): the
bridge between the Calibration Window and the production ROI engine.

Coverage: statistics parity with the legacy manager, dual validation
mode, store reload semantics on config edits/deletes, lifecycle and
accessors, and workspace-level geometry edit propagation.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np
import pytest

from conftest import make_config, synthetic_image

from roi.acquisition_state import AcquisitionState
from roi.geometry import (
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.runtime import RuntimeROIState
from roi.runtime_manager import RuntimeROIManagerImpl
from roi_engine.engine import ROIEngine, ROIEnginePool
from roi_engine.integration import ROIEngineManager

CAMERA_ID = "cam_1"
STATE = AcquisitionState(camera_id=CAMERA_ID, pan=0)
IMAGE = synthetic_image(256, 256)


def _cfg(roi_id: str, geometry, enabled: bool = True):
    return make_config(roi_id, geometry, enabled=enabled)


def _mixed_configs() -> list:
    """One of every shape, one disabled rect -> 6 enabled ROIs."""
    return [
        _cfg("rect_a", Rectangle1ROI(10, 10, 70, 70)),
        _cfg("rect_b", Rectangle1ROI(150, 150, 210, 210), enabled=False),
        _cfg("rect2_a", Rectangle2ROI(60, 180, 0.3, 20, 10)),
        _cfg("circle_a", CircleROI(120, 120, 20)),
        _cfg("ellipse_a", EllipseROI(200, 50, 0.5, 25, 12)),
        _cfg("poly_a", PolygonROI(((30, 100), (60, 110), (50, 150), (25, 140)))),
        _cfg("rect_c", Rectangle1ROI(30, 200, 60, 230)),
    ]


def _legacy_by_id(configs: list, frame_id: int) -> dict[str, object]:
    """Run the legacy manager and map results back to roi_id."""
    legacy = RuntimeROIManagerImpl()
    legacy.load(configs)
    legacy.rebuild_dirty_regions(IMAGE.shape)
    stats = legacy.process_frame(IMAGE, frame_id)
    return {
        roi.configuration.roi_id: stat
        for roi, stat in zip(legacy.get_active(), stats)
    }


# ---------------------------------------------------------------------------
# Statistics parity with the legacy manager
# ---------------------------------------------------------------------------


def test_statistics_match_legacy() -> None:
    configs = _mixed_configs()
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load(configs)
    legacy_by_id = _legacy_by_id(configs, frame_id=3)

    stats = mgr.process_frame(IMAGE, frame_id=3)
    assert len(stats) == 6

    for view in mgr.get_active():
        s = view.statistics
        assert s is not None
        legacy = legacy_by_id[view.configuration.roi_id]
        assert s.valid == legacy.valid
        assert s.minimum == pytest.approx(legacy.minimum, abs=1e-6)
        assert s.maximum == pytest.approx(legacy.maximum, abs=1e-6)
        assert s.mean == pytest.approx(legacy.mean, abs=1e-6)
        assert s.standard_deviation == pytest.approx(
            legacy.standard_deviation, abs=1e-6
        )
        assert s.pixel_count == legacy.pixel_count
        # The hotspot pixel must carry the maximum temperature. The
        # exact pixel may differ from legacy when several pixels share
        # the max (plateau center vs first max), so only bound it.
        assert IMAGE[s.hotspot_y, s.hotspot_x] == pytest.approx(
            s.maximum, abs=1e-6
        )
        assert abs(s.hotspot_x - legacy.hotspot_x) <= 16
        assert abs(s.hotspot_y - legacy.hotspot_y) <= 16
        assert s.frame_id == 3

    # Second frame reuses cached regions; parity must hold again.
    legacy_by_id2 = _legacy_by_id(configs, frame_id=4)
    mgr.process_frame(IMAGE, frame_id=4)
    for view in mgr.get_active():
        legacy = legacy_by_id2[view.configuration.roi_id]
        assert view.statistics.maximum == pytest.approx(
            legacy.maximum, abs=1e-6
        )


def test_statistics_match_legacy_uniform() -> None:
    configs = _mixed_configs()
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load(configs)
    uniform = np.full((256, 256), 72.5, dtype=np.float32)

    stats = mgr.process_frame(uniform, frame_id=1)
    legacy_by_id = _legacy_by_id_uniform(configs, uniform, frame_id=1)

    assert len(stats) == 6
    for stat in stats:
        assert stat.valid
        assert stat.maximum == pytest.approx(72.5, abs=1e-6)
    for view in mgr.get_active():
        legacy = legacy_by_id[view.configuration.roi_id]
        assert view.statistics.mean == pytest.approx(legacy.mean, abs=1e-6)


def _legacy_by_id_uniform(configs: list, image: np.ndarray, frame_id: int):
    legacy = RuntimeROIManagerImpl()
    legacy.load(configs)
    legacy.rebuild_dirty_regions(image.shape)
    stats = legacy.process_frame(image, frame_id)
    return {
        roi.configuration.roi_id: stat
        for roi, stat in zip(legacy.get_active(), stats)
    }


# ---------------------------------------------------------------------------
# Dual validation mode
# ---------------------------------------------------------------------------


def test_dual_validation_clean_no_warnings(caplog) -> None:
    configs = _mixed_configs()
    mgr = ROIEngineManager(
        ROIEngine(CAMERA_ID), dual_validation=True
    )
    mgr.load(configs)

    with caplog.at_level(logging.WARNING, logger="roi_engine.integration"):
        mgr.process_frame(IMAGE, frame_id=1)
        mgr.process_frame(IMAGE, frame_id=2)

    warnings = [
        r for r in caplog.records if "validation mismatch" in r.getMessage()
    ]
    assert warnings == []
    assert mgr._warned == {}


def test_dual_validation_warns_once_per_mismatch(caplog) -> None:
    config = _cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID), dual_validation=True)
    mgr.load([config])

    # Sabotage the internal legacy manager with a shifted geometry.
    legacy = mgr._legacy
    legacy.load([_cfg("rect_a", Rectangle1ROI(150, 150, 210, 210))])
    legacy.rebuild_dirty_regions(IMAGE.shape)

    with caplog.at_level(logging.WARNING, logger="roi_engine.integration"):
        mgr.process_frame(IMAGE, frame_id=1)
        mgr.process_frame(IMAGE, frame_id=2)

    warnings = [
        r for r in caplog.records if "validation mismatch" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "rect_a" in warnings[0].getMessage()

    # Restore the legacy geometry; the next frame recovers quietly.
    legacy.load([config])
    legacy.rebuild_dirty_regions(IMAGE.shape)
    with caplog.at_level(logging.DEBUG, logger="roi_engine.integration"):
        mgr.process_frame(IMAGE, frame_id=3)
    assert mgr._warned == {}


# ---------------------------------------------------------------------------
# Store reload semantics (edits and deletes)
# ---------------------------------------------------------------------------


def test_mark_dirty_unchanged_config_keeps_store() -> None:
    configs = _mixed_configs()
    provider: dict[str, object] = {c.roi_id: c for c in configs}
    mgr = ROIEngineManager(
        ROIEngine(CAMERA_ID), config_provider=provider.get
    )
    mgr.load(configs)
    store_before = mgr._engine.store()

    mgr.process_frame(IMAGE, frame_id=1)
    mgr.mark_dirty("rect_a")

    assert mgr._engine.store() is store_before
    stats = mgr.process_frame(IMAGE, frame_id=2)
    assert len(stats) == 6


def test_edited_config_rebuilds_store() -> None:
    configs = _mixed_configs()
    provider: dict[str, object] = {c.roi_id: c for c in configs}
    mgr = ROIEngineManager(
        ROIEngine(CAMERA_ID), config_provider=provider.get
    )
    mgr.load(configs)
    store_before = mgr._engine.store()

    mgr.process_frame(IMAGE, frame_id=1)
    first_min = {
        view.configuration.roi_id: view.statistics.minimum
        for view in mgr.get_active()
    }

    # Workspace-style edit: replace the config object, then mark_dirty.
    moved = replace(
        provider["rect_c"], geometry=Rectangle1ROI(200, 200, 250, 250)
    )
    provider["rect_c"] = moved
    mgr.mark_dirty("rect_c")

    assert mgr._engine.store() is not store_before
    second = mgr.process_frame(IMAGE, frame_id=2)
    second_min = {
        view.configuration.roi_id: view.statistics.minimum
        for view in mgr.get_active()
    }
    assert len(second) == 6
    assert second_min["rect_c"] != first_min["rect_c"]
    assert second_min["rect_a"] == pytest.approx(
        first_min["rect_a"], abs=1e-6
    )


def test_deleted_config_removes_roi() -> None:
    configs = _mixed_configs()
    provider: dict[str, object] = {c.roi_id: c for c in configs}
    mgr = ROIEngineManager(
        ROIEngine(CAMERA_ID), config_provider=provider.get
    )
    mgr.load(configs)

    provider.pop("rect_c")
    mgr.mark_dirty("rect_c")

    assert [v.configuration.roi_id for v in mgr.get_active()] == [
        "rect_a",
        "rect2_a",
        "circle_a",
        "ellipse_a",
        "poly_a",
    ]
    stats = mgr.process_frame(IMAGE, frame_id=1)
    assert len(stats) == 5


def test_mark_dirty_all_keeps_store() -> None:
    configs = _mixed_configs()
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load(configs)
    store_before = mgr._engine.store()

    mgr.mark_dirty()
    stats = mgr.process_frame(IMAGE, frame_id=1)
    assert mgr._engine.store() is store_before
    assert len(stats) == 6


# ---------------------------------------------------------------------------
# Lifecycle and accessors
# ---------------------------------------------------------------------------


def test_load_and_accessors() -> None:
    configs = _mixed_configs()
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load(configs)

    assert len(mgr.get_all()) == 7
    assert len(mgr.get_active()) == 6
    assert mgr.get_by_id("rect_a") is not None
    assert mgr.get_by_id("missing") is None

    active_ids = [v.configuration.roi_id for v in mgr.get_active()]
    assert "rect_b" not in active_ids
    assert mgr.get_by_id("rect_b").configuration.enabled is False


def test_add_configuration_appears_in_active() -> None:
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load([_cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))])

    new_cfg = _cfg("circle_b", CircleROI(150, 150, 15))
    mgr.add_configuration(new_cfg)

    assert len(mgr.get_active()) == 2
    stats = mgr.process_frame(IMAGE, frame_id=1)
    assert len(stats) == 2


def test_unload_clears_everything() -> None:
    engine = ROIEngine(CAMERA_ID)
    mgr = ROIEngineManager(engine)
    mgr.load([_cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))])
    mgr.process_frame(IMAGE, frame_id=1)

    mgr.unload()

    assert mgr.get_all() == []
    assert mgr.get_active() == []
    assert mgr.process_frame(IMAGE, frame_id=2) == []
    assert engine.store() is None


def test_pool_backed_engines_are_independent() -> None:
    pool = ROIEnginePool()
    mgr_a = ROIEngineManager(pool.engine("cam_a"))
    mgr_b = ROIEngineManager(pool.engine("cam_b"))
    mgr_a.load([_cfg("a_1", Rectangle1ROI(10, 10, 70, 70))])
    mgr_b.load([_cfg("b_1", Rectangle1ROI(150, 150, 210, 210))])

    stats_a = mgr_a.process_frame(IMAGE, frame_id=1)
    stats_b = mgr_b.process_frame(IMAGE, frame_id=1)

    assert stats_a[0].minimum != stats_b[0].minimum
    assert mgr_a._engine is not mgr_b._engine


# ---------------------------------------------------------------------------
# Edge cases and compatibility surface
# ---------------------------------------------------------------------------


def test_process_frame_without_store_returns_empty() -> None:
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    assert mgr.process_frame(IMAGE, frame_id=1) == []
    assert mgr.process_frame(None, frame_id=2) == []


def test_process_frame_empty_image_yields_invalid_stats() -> None:
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load([_cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))])

    stats = mgr.process_frame(np.zeros((0, 0), dtype=np.float32), frame_id=1)
    assert len(stats) == 1
    assert not stats[0].valid


def test_rebuild_dirty_regions_is_noop() -> None:
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load([_cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))])
    mgr.rebuild_dirty_regions((256, 256))
    stats = mgr.process_frame(IMAGE, frame_id=1)
    assert len(stats) == 1
    assert stats[0].valid


def test_update_state_and_refresh_statistics() -> None:
    mgr = ROIEngineManager(ROIEngine(CAMERA_ID))
    mgr.load([_cfg("rect_a", Rectangle1ROI(10, 10, 70, 70))])
    view = mgr.get_by_id("rect_a")

    mgr.update_state("rect_a", RuntimeROIState.ERROR)
    assert view.state == RuntimeROIState.ERROR
    assert mgr.get_active() == []

    stats = mgr.process_frame(IMAGE, frame_id=1)[0]
    mgr.refresh_statistics("rect_a", stats)
    assert view.statistics is stats


# ---------------------------------------------------------------------------
# Workspace-level: geometry edits must reach the engine
# ---------------------------------------------------------------------------


def test_workspace_geometry_edit_updates_statistics(tmp_path) -> None:
    from gui.roi.roi_dirty_tracker import ROIDirtyTracker
    from gui.roi.roi_selection_manager import ROISelectionManager
    from gui.roi.roi_signal_bus import ROISignalBus
    from gui.roi.roi_workspace import ROIWorkspace
    from roi.editor.editor_manager import ROIEditorManager
    from roi.persistence.repository import JSONROIRepository

    repo = JSONROIRepository(str(tmp_path))
    workspace = ROIWorkspace(
        signal_bus=ROISignalBus(),
        repository=repo,
        selection_manager=ROISelectionManager(),
        dirty_tracker=ROIDirtyTracker(),
        editor_manager=ROIEditorManager(window_handle=0),
    )
    workspace.load_state(STATE)
    workspace._on_create_roi("rectangle1")
    roi_id = list(workspace._configs.keys())[0]

    image = synthetic_image(240, 320)
    workspace.process_frame("cam_1", image, frame_id=1)
    view = workspace.get_runtime_manager("cam_1").get_by_id(roi_id)
    before = view.statistics.minimum

    # Default create geometry is (100,100)-(300,400); move it to the
    # hot bottom-right corner of the gradient image.
    workspace._on_geometry_edited(
        roi_id, Rectangle1ROI(row1=200, col1=280, row2=230, col2=310)
    )
    workspace.process_frame("cam_1", image, frame_id=2)
    view = workspace.get_runtime_manager("cam_1").get_by_id(roi_id)
    after = view.statistics.minimum

    assert after > before
    assert after == pytest.approx(
        20.0 + 200 * 0.05 + 280 * 0.03, abs=0.01
    )
