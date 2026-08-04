"""
Tests for the Phase 4 validation harness (tests/validation).

These tests exercise the harness modules with synthetic frames only:
no camera hardware is required. Scenario functions are run end-to-end
with short parameters to verify report artifacts and verdicts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest

from tests.validation.charts import line_chart
from tests.validation.frame_source import (
    DEFAULT_SCENE,
    SimulatedFrameSource,
)
from tests.validation.harness import (
    ValidationHarness,
    make_roi_config,
)
from tests.validation.metrics import MetricsAnalyzer, MetricsCollector
from tests.validation.scenarios import (
    _make_grid_configs,
    _store_flags,
    run_dual_validation,
    run_error_recovery,
    run_high_count,
    run_position_switch,
    run_roi_editing,
)
from tests.validation.scenarios import run_soak

from roi.geometry import Rectangle1ROI


@pytest.fixture()
def out_dir(tmp_path: Path) -> Path:
    """Per-test report directory."""
    return tmp_path / "reports"


def _args(out_dir: Path, **overrides) -> argparse.Namespace:
    """Namespace with scenario defaults and test overrides."""
    values = {
        "camera": "cam_harness",
        "out": str(out_dir),
        "duration_s": 5.0,
        "warmup_s": 2.0,
        "frames": 1000,
        "rois": 1600,
        "cycles": 100,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _make_harness(out_dir: Path, rois: int = 8) -> ValidationHarness:
    harness = ValidationHarness(
        camera_id="cam_harness", repo_base=str(out_dir / "config")
    )
    harness.load_position(
        _make_grid_configs(harness, "cam_harness", 0, rois, DEFAULT_SCENE),
        pan=0,
    )
    return harness


# ==========================================================
# frame_source
# ==========================================================


def test_simulated_source_is_deterministic_and_hot() -> None:
    source = SimulatedFrameSource(DEFAULT_SCENE)
    frame1, n1 = source.next_frame()
    frame2, n2 = source.next_frame()
    assert frame1.shape == DEFAULT_SCENE
    assert frame1.dtype == np.float32
    assert n1 == 1 and n2 == 2
    assert frame1.max() > 60.0
    assert not np.array_equal(frame1, frame2)


# ==========================================================
# metrics
# ==========================================================


def test_metrics_collector_and_analyzer() -> None:
    collector = MetricsCollector()
    for i in range(120):
        collector.record_frame(
            type("FM", (), {"frame_number": i, "pipeline_ms": 2.0,
                            "engine_ms": 1.8, "gui_ms": 0.2,
                            "dropped": 0, "exception": False,
                            "halcon_error": False, "active_rois": 8})()
        )
    metrics = collector.metrics
    metrics.finalize()
    analyzer = MetricsAnalyzer(metrics)
    counts = analyzer.counts()
    assert counts["processed"] == 120
    assert counts["dropped"] == 0
    assert analyzer.fps_stats()["average"] > 0.0
    assert analyzer.pipeline_stats()["average_ms"] == pytest.approx(2.0)
    assert "mb_per_hour" in analyzer.memory_slope()


# ==========================================================
# charts
# ==========================================================


def test_line_chart_writes_png(out_dir: Path) -> None:
    path = out_dir / "chart.png"
    line_chart(str(path), [1.0, 2.0, 3.0, 2.5], "Test", "value")
    assert path.exists()
    assert path.stat().st_size > 0
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ==========================================================
# harness
# ==========================================================


def test_harness_position_switch_generation(out_dir: Path) -> None:
    harness = _make_harness(out_dir, rois=4)
    harness.load_position(
        _make_grid_configs(harness, "cam_harness", 1, 4, DEFAULT_SCENE),
        pan=1,
    )
    source = SimulatedFrameSource(DEFAULT_SCENE)
    gen0 = harness.engine_generation()
    assert gen0 >= 1

    harness.switch_to_position(0)
    gen1 = harness.engine_generation()
    assert gen1 > gen0

    temperature, _ = source.next_frame()
    harness.process_one(temperature, 1)
    assert len(harness.manager().get_active()) == 4


def test_harness_edit_geometry_via_bus(out_dir: Path) -> None:
    harness = _make_harness(out_dir, rois=1)
    source = SimulatedFrameSource(DEFAULT_SCENE)
    roi_id = harness.workspace.get_all_configurations()[0].roi_id

    temperature, _ = source.next_frame()
    harness.process_one(temperature, 1)
    before = harness.manager().get_by_id(roi_id).statistics.maximum

    harness.signal_bus.geometry_edited.emit(
        roi_id, Rectangle1ROI(row1=42, col1=55, row2=62, col2=75)
    )
    temperature, _ = source.next_frame()
    harness.process_one(temperature, 2)
    after = harness.manager().get_by_id(roi_id).statistics.maximum
    assert after > 60.0
    assert after != before


def test_harness_store_flags(out_dir: Path) -> None:
    harness = _make_harness(out_dir, rois=2)
    roi_id = harness.workspace.get_all_configurations()[0].roi_id
    flags = _store_flags(harness, roi_id)
    assert flags is not None
    assert flags["enabled"] is True
    assert flags["processed"] is True
    assert flags["visible"] is True


def test_config_write_back_rebuilds_store(out_dir: Path) -> None:
    """Regression: appearance/config edits must reach the engine store.

    The property panel pushes edited configs through config_updated
    (workspace.update_configuration). Without the write-back path, the
    immutable engine store kept the old snapshot and enabled/visible
    toggles never took effect (Phase 4 finding).
    """
    from dataclasses import replace

    harness = _make_harness(out_dir, rois=1)
    source = SimulatedFrameSource(DEFAULT_SCENE)
    roi_id = harness.workspace.get_all_configurations()[0].roi_id
    config = harness.workspace.get_configuration(roi_id)

    # disable: engine must drop the ROI from processing on next frame
    disabled = replace(config, enabled=False)
    harness.update_configuration(disabled)
    temperature, _ = source.next_frame()
    harness.process_one(temperature, 1)
    flags = _store_flags(harness, roi_id)
    assert flags["enabled"] is False
    assert flags["processed"] is False

    # hide: GUI-only, engine keeps processing
    hidden = replace(disabled, visible=False)
    harness.update_configuration(hidden)
    temperature, _ = source.next_frame()
    harness.process_one(temperature, 2)
    flags = _store_flags(harness, roi_id)
    assert flags["visible"] is False
    assert flags["processed"] is False  # still disabled from the step above

    # re-enable: back to processing with fresh statistics
    harness.update_configuration(replace(hidden, enabled=True))
    temperature, _ = source.next_frame()
    harness.process_one(temperature, 3)
    flags = _store_flags(harness, roi_id)
    assert flags["enabled"] is True
    assert flags["processed"] is True
    stats = harness.manager().get_by_id(roi_id).statistics
    assert stats is not None and stats.valid


def test_config_write_back_name_reaches_workspace(out_dir: Path) -> None:
    """Regression: the workspace returns the replaced config object."""
    from dataclasses import replace

    harness = _make_harness(out_dir, rois=1)
    roi_id = harness.workspace.get_all_configurations()[0].roi_id
    config = harness.workspace.get_configuration(roi_id)
    harness.update_configuration(replace(config, name="Renamed"))
    assert (
        harness.workspace.get_configuration(roi_id).name == "Renamed"
    )


# ==========================================================
# scenarios (end-to-end, synthetic, short)
# ==========================================================


def test_scenario_roi_editing(out_dir: Path) -> None:
    result = run_roi_editing(_args(out_dir))
    assert result["verdict"] == "PASS", result
    summary = out_dir / "roi_editing_summary.md"
    assert summary.exists()
    assert "PASS" in summary.read_text(encoding="utf-8")


def test_scenario_position_switch(out_dir: Path) -> None:
    result = run_position_switch(_args(out_dir, cycles=2))
    assert result["verdict"] == "PASS", result
    assert result["switches"] == 2 * 5
    metrics_json = json.loads(
        (out_dir / "position_switch_metrics.json").read_text(encoding="utf-8")
    )
    assert metrics_json["scenario"] == "position_switch"


def test_scenario_high_count(out_dir: Path) -> None:
    result = run_high_count(_args(out_dir))
    assert result["verdict"] == "PASS", result
    steps = result["steps"]
    assert steps[0]["rois"] == 100
    assert steps[-1]["rois"] == 1600
    assert all(s["gui_ok"] for s in steps)
    assert all(s["fps"] > 0 for s in steps)


def test_scenario_error_recovery(out_dir: Path) -> None:
    result = run_error_recovery(_args(out_dir, camera="sim"))
    assert result["verdict"] == "PASS", result
    events = {e["event"]: e["ok"] for e in result["events"]}
    assert events["baseline"] is True
    assert events["engine_recreated"] is True
    assert events["position_reload"] is True
    assert events["statistics_recovered"] is True


def test_scenario_dual_validation(out_dir: Path) -> None:
    result = run_dual_validation(_args(out_dir, rois=4))
    assert result["verdict"] == "PASS", result
    assert result["frames"] >= 1000
    assert result["mismatch_warnings"] == 0


def test_scenario_soak(out_dir: Path) -> None:
    result = run_soak(_args(out_dir, camera="sim", duration_s=5.0))
    assert result["verdict"] == "PASS", result
    assert (out_dir / "soak_metrics.json").exists()
    assert (out_dir / "soak_memory.png").exists()
    assert (out_dir / "soak_fps.png").exists()
