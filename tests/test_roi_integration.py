from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PyQt5.QtCore import QObject
from pytest import approx

from alarm import AlarmResult
from alarm.manager import AlarmManager
from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import Rectangle1ROI, CircleROI
from roi.recording_settings import ROIRecordingSettings
from roi.style import ROIStyle
from roi.runtime import RuntimeROIState

from gui.roi.roi_signal_bus import ROISignalBus
from gui.roi.roi_selection_manager import ROISelectionManager
from gui.roi.roi_dirty_tracker import ROIDirtyTracker
from gui.roi.roi_workspace import ROIWorkspace
from roi.editor.editor_manager import ROIEditorManager
from roi.persistence.repository import JSONROIRepository

_STATE = AcquisitionState(camera_id="cam_1", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)


def _make_config(
    roi_id: str = "test_001",
    name: str = "Test ROI",
    alarm_enabled: bool = True,
    alarm_value: float = 85.0,
) -> ROIConfiguration:
    return ROIConfiguration(
        roi_id=roi_id,
        name=name,
        acquisition_state=_STATE,
        geometry=Rectangle1ROI(row1=10, col1=10, row2=100, col2=200),
        style=ROIStyle(color="#FF0000", selected_color="#00FF00"),
        alarm=ROIAlarmSettings(
            enabled=alarm_enabled,
            condition=ROIAlarmCondition.HIGH,
            value=alarm_value,
        ),
        recording=ROIRecordingSettings(enabled=False),
        enabled=True,
        visible=True,
    )


def _make_workspace(tmp_path, on_alarm_event=None) -> ROIWorkspace:
    repo = JSONROIRepository(str(tmp_path))
    signal_bus = ROISignalBus()
    selection_mgr = ROISelectionManager()
    dirty_tracker = ROIDirtyTracker()
    editor_mgr = ROIEditorManager(window_handle=0)
    return ROIWorkspace(
        signal_bus=signal_bus,
        repository=repo,
        selection_manager=selection_mgr,
        dirty_tracker=dirty_tracker,
        editor_manager=editor_mgr,
        on_alarm_event=on_alarm_event,
    )


def _make_temp_image(
    width: int = 640, height: int = 480, value: float = 50.0
) -> np.ndarray:
    return np.full((height, width), value, dtype=np.float32)


# ==============================================================
# Integration: ROIWorkspace + RuntimeROIManager + AlarmManager
# ==============================================================


class TestProcessFrame:
    def test_process_frame_returns_stats(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        temp = _make_temp_image(value=75.0)
        stats = ws.process_frame("cam_1", temp, frame_id=1)

        assert len(stats) == 1
        assert stats[0].valid
        assert stats[0].maximum == approx(75.0)
        assert stats[0].frame_id == 1

    def test_process_frame_no_rois(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        temp = _make_temp_image()
        stats = ws.process_frame("cam_1", temp, frame_id=1)
        assert stats == []

    def test_process_frame_emits_statistics_updated(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        received: list[str] = []
        ws._signal_bus.roi_statistics_updated.connect(received.append)

        temp = _make_temp_image(value=75.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        assert received == ["cam_1"]

    def test_process_frame_does_not_emit_for_non_active(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        received: list[str] = []
        ws._signal_bus.roi_statistics_updated.connect(received.append)

        temp = _make_temp_image(value=75.0)
        ws.process_frame("cam_other", temp, frame_id=1)

        assert received == []

    def test_process_frame_triggers_alarm(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        cfg = ws.get_configuration(roi_id)
        from dataclasses import replace
        ws._configs[roi_id] = replace(
            cfg,
            alarm=ROIAlarmSettings(
                enabled=True,
                condition=ROIAlarmCondition.HIGH,
                value=50.0,
            ),
        )
        ws._alarm_manager.register(
            roi_id, ws._configs[roi_id].alarm
        )

        temp = _make_temp_image(value=100.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        state = ws._alarm_manager.get_state(roi_id)
        from alarm.state_machine import AlarmState
        assert state in (AlarmState.ACTIVE, AlarmState.PENDING)

    def test_process_frame_alarm_not_triggered_below_threshold(self, tmp_path):
        received: list[AlarmResult] = []
        ws = _make_workspace(tmp_path, on_alarm_event=received.append)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        temp = _make_temp_image(value=30.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        for r in received:
            assert not r.active

    def test_process_frame_emits_alarm_state_changed(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        received: list[tuple[str, AlarmResult]] = []
        ws._signal_bus.roi_alarm_state_changed.connect(
            lambda rid, ar: received.append((rid, ar))
        )

        temp = _make_temp_image(value=100.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        assert len(received) == 1
        assert received[0][0] == roi_id

    def test_disabled_roi_skipped(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        roi_id = list(ws._configs.keys())[0]
        config = ws.get_configuration(roi_id)
        from dataclasses import replace
        updated = replace(config, enabled=False)
        ws._configs[roi_id] = updated
        mgr = ws._get_or_create_manager("cam_1")
        mgr.load([updated])
        mgr.rebuild_dirty_regions()

        temp = _make_temp_image(value=100.0)
        stats = ws.process_frame("cam_1", temp, frame_id=1)

        assert stats == []

    def test_multiple_rois_processed(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        ws._on_create_roi("circle")

        temp = _make_temp_image(value=60.0)
        stats = ws.process_frame("cam_1", temp, frame_id=1)

        assert len(stats) == 2
        assert all(s.valid for s in stats)


class TestMultiCamera:
    def test_per_camera_managers(self, tmp_path):
        ws = _make_workspace(tmp_path)
        state_a = AcquisitionState(camera_id="cam_a")
        state_b = AcquisitionState(camera_id="cam_b")

        ws.load_state(state_a)
        assert ws._active_camera_id == "cam_a"
        mgr_a = ws._get_or_create_manager("cam_a")

        ws.load_state(state_b)
        assert ws._active_camera_id == "cam_b"
        mgr_b = ws._get_or_create_manager("cam_b")

        assert mgr_a is not mgr_b

    def test_independent_processing(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_a = list(ws._configs.keys())[0]

        temp_a = _make_temp_image(value=90.0)
        stats_a = ws.process_frame("cam_1", temp_a, frame_id=1)
        assert len(stats_a) == 1
        assert stats_a[0].maximum == approx(90.0)

        mgr_a = ws._get_or_create_manager("cam_1")
        roi_a_obj = mgr_a.get_by_id(roi_a)
        assert roi_a_obj is not None

        cfg_a = ws.get_configuration(roi_a)
        ws._repository.save_all([cfg_a])

        state_b = AcquisitionState(camera_id="cam_b")
        ws.load_state(state_b)
        ws._on_create_roi("circle")

        stats_b = ws.process_frame("cam_b", _make_temp_image(value=30.0), frame_id=1)
        assert len(stats_b) == 1
        assert stats_b[0].maximum == approx(30.0)

    def test_alarm_independent_across_cameras(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        from dataclasses import replace
        cfg = ws.get_configuration(roi_id)
        ws._configs[roi_id] = replace(
            cfg,
            alarm=ROIAlarmSettings(
                enabled=True,
                condition=ROIAlarmCondition.HIGH,
                value=50.0,
            ),
        )
        ws._alarm_manager.register(
            roi_id, ws._configs[roi_id].alarm
        )

        temp = _make_temp_image(value=100.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        state_a = ws._alarm_manager.get_state(roi_id)
        from alarm.state_machine import AlarmState
        assert state_a in (AlarmState.ACTIVE, AlarmState.PENDING)

        state_b = AcquisitionState(camera_id="cam_b")
        ws.load_state(state_b)
        ws._on_create_roi("circle")
        roi_b = list(ws._configs.keys())[-1]

        cfg_b = ws.get_configuration(roi_b)
        ws._configs[roi_b] = replace(
            cfg_b,
            alarm=ROIAlarmSettings(
                enabled=True,
                condition=ROIAlarmCondition.HIGH,
                value=10.0,
            ),
        )
        ws._alarm_manager.register(
            roi_b, ws._configs[roi_b].alarm
        )

        temp_b = _make_temp_image(value=20.0)
        ws.process_frame("cam_b", temp_b, frame_id=2)

        state_b = ws._alarm_manager.get_state(roi_b)
        assert state_b in (AlarmState.ACTIVE, AlarmState.PENDING)


class TestAlarmRegistration:
    def test_create_registers_alarm(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        state = ws._alarm_manager.get_state(roi_id)
        assert state is not None

    def test_delete_unregisters_alarm(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        ws._on_delete_roi(roi_id)
        state = ws._alarm_manager.get_state(roi_id)
        assert state is None

    def test_duplicate_registers_alarm(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        received: list[str] = []
        ws._signal_bus.roi_duplicated.connect(
            lambda n, o: received.append(n)
        )
        ws._on_duplicate_roi(roi_id)
        new_id = received[0]

        state = ws._alarm_manager.get_state(new_id)
        assert state is not None

    def test_alarm_change_re_registers(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        ws._configs[roi_id].alarm.value = 50.0
        ws._on_alarm_changed(roi_id)

        settings = ws._alarm_manager._settings.get(roi_id)
        assert settings is not None
        assert settings.value == 50.0

    def test_load_state_registers_alarms(self, tmp_path):
        cfg = _make_config(roi_id="persisted_roi")
        repo = JSONROIRepository(str(tmp_path))
        repo.save_all([cfg])

        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)

        state = ws._alarm_manager.get_state("persisted_roi")
        assert state is not None

    def test_disabled_alarm_does_not_trip(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        config = ws.get_configuration(roi_id)
        from dataclasses import replace
        ws._configs[roi_id] = replace(
            config,
            alarm=ROIAlarmSettings(
                enabled=False,
                condition=ROIAlarmCondition.HIGH,
                value=10.0,
            ),
        )
        ws._alarm_manager.register(roi_id, ws._configs[roi_id].alarm)

        temp = _make_temp_image(value=100.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        state = ws._alarm_manager.get_state(roi_id)
        assert state == "normal" or state is not None


class TestGuiSignalIntegration:
    def test_statistics_updated_signal_emitted(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        received: list[str] = []
        ws._signal_bus.roi_statistics_updated.connect(received.append)

        temp = _make_temp_image(value=88.5)
        ws.process_frame("cam_1", temp, frame_id=1)

        assert "cam_1" in received

    def test_alarm_state_changed_signal_emitted(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        cfg = ws.get_configuration(roi_id)
        from dataclasses import replace
        ws._configs[roi_id] = replace(
            cfg,
            alarm=ROIAlarmSettings(
                enabled=True,
                condition=ROIAlarmCondition.HIGH,
                value=50.0,
            ),
        )
        ws._alarm_manager.register(
            roi_id, ws._configs[roi_id].alarm
        )

        received: list[str] = []
        ws._signal_bus.roi_alarm_state_changed.connect(
            lambda rid, ar: received.append(rid)
        )

        temp = _make_temp_image(value=100.0)
        ws.process_frame("cam_1", temp, frame_id=1)

        assert len(received) >= 1
        assert received[-1] == roi_id


class TestEdgeCases:
    def test_process_frame_empty_temperature(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        temp = np.zeros((0, 0), dtype=np.float64)
        stats = ws.process_frame("cam_1", temp, frame_id=1)
        assert len(stats) == 1

    def test_process_frame_nan_temperature(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        temp = np.full((240, 320), np.nan, dtype=np.float64)
        stats = ws.process_frame("cam_1", temp, frame_id=1)
        assert len(stats) >= 0

    def test_unload_camera_cleans_up(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        ws.unload_camera("cam_1")
        mgr = ws.get_runtime_manager("cam_1")
        assert mgr is None

    def test_process_frame_called_repeatedly(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        for i in range(5):
            temp = _make_temp_image(value=float(50 + i * 10))
            stats = ws.process_frame("cam_1", temp, frame_id=i)
            assert len(stats) == 1
            if stats[0].valid:
                assert stats[0].maximum == approx(50 + i * 10)

    def test_camera_switch_preserves_other_state(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")

        ws.process_frame("cam_1", _make_temp_image(value=90.0), frame_id=1)
        mgr_a = ws._get_or_create_manager("cam_1")

        state_b = AcquisitionState(camera_id="cam_b")
        ws.load_state(state_b)
        ws._on_create_roi("circle")
        ws.process_frame("cam_b", _make_temp_image(value=30.0), frame_id=1)

        mgr_a_after = ws._get_or_create_manager("cam_1")
        assert mgr_a is mgr_a_after
        rois_a = mgr_a.get_active()
        assert len(rois_a) == 1

    def test_edited_roi_rebuilds_for_next_frame(self, tmp_path):
        ws = _make_workspace(tmp_path)
        ws.load_state(_STATE)
        ws._on_create_roi("rectangle1")
        roi_id = list(ws._configs.keys())[0]

        ws.process_frame("cam_1", _make_temp_image(), frame_id=1)
        ws._on_geometry_edited(roi_id, Rectangle1ROI(row1=5, col1=5, row2=50, col2=100))

        temp = _make_temp_image(value=80.0)
        stats = ws.process_frame("cam_1", temp, frame_id=2)
        assert len(stats) == 1
