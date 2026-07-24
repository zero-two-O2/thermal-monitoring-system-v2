from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import Rectangle1ROI
from roi.recording_settings import ROIRecordingSettings
from roi.style import ROIStyle


# ==============================================================
# Test helpers
# ==============================================================

_STATE = AcquisitionState(camera_id="cam_1", pan=0.0, tilt=0.0, zoom=0.0, focus=0.0)


def _make_config(roi_id: str = "test_001", name: str = "Test ROI") -> ROIConfiguration:
    return ROIConfiguration(
        roi_id=roi_id,
        name=name,
        acquisition_state=_STATE,
        geometry=Rectangle1ROI(row1=10, col1=10, row2=100, col2=200),
        style=ROIStyle(color="#FF0000", selected_color="#00FF00"),
        alarm=ROIAlarmSettings(enabled=True, condition=ROIAlarmCondition.HIGH, value=85.0),
        recording=ROIRecordingSettings(enabled=False),
        enabled=True,
        visible=True,
    )


# ==============================================================
# Test ROISignalBus
# ==============================================================

class TestROISignalBus:
    def test_signal_bus_emits_roi_selected(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[str] = []
        bus.roi_selected.connect(received.append)
        bus.roi_selected.emit("roi_1")
        assert received == ["roi_1"]

    def test_signal_bus_emits_roi_created(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[str] = []
        bus.roi_created.connect(received.append)
        bus.roi_created.emit("roi_1")
        assert received == ["roi_1"]

    def test_signal_bus_emits_roi_deleted(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[str] = []
        bus.roi_deleted.connect(received.append)
        bus.roi_deleted.emit("roi_1")
        assert received == ["roi_1"]

    def test_signal_bus_emits_roi_duplicated(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[tuple[str, str]] = []
        bus.roi_duplicated.connect(lambda a, b: received.append((a, b)))
        bus.roi_duplicated.emit("new_id", "old_id")
        assert received == [("new_id", "old_id")]

    def test_signal_bus_emits_dirty_state_changed(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[bool] = []
        bus.dirty_state_changed.connect(received.append)
        bus.dirty_state_changed.emit(True)
        bus.dirty_state_changed.emit(False)
        assert received == [True, False]

    def test_signal_bus_emits_camera_changed(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[str] = []
        bus.camera_changed.connect(received.append)
        bus.camera_changed.emit("cam_1")
        assert received == ["cam_1"]

    def test_signal_bus_emits_create_roi_requested(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[str] = []
        bus.create_roi_requested.connect(received.append)
        bus.create_roi_requested.emit("rectangle1")
        assert received == ["rectangle1"]

    def test_signal_bus_emits_geometry_edited(self):
        from gui.roi.roi_signal_bus import ROISignalBus
        bus = ROISignalBus()
        received: list[tuple[str, object]] = []
        bus.geometry_edited.connect(lambda a, b: received.append((a, b)))
        bus.geometry_edited.emit("roi_1", object())
        assert len(received) == 1
        assert received[0][0] == "roi_1"


# ==============================================================
# Test ROISelectionManager
# ==============================================================

class TestROISelectionManager:
    def test_initial_state(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        assert mgr.selected_id is None
        assert mgr.hovered_id is None
        assert mgr.multi_selection == frozenset()

    def test_select(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        assert mgr.selected_id == "roi_1"
        assert "roi_1" in mgr.multi_selection

    def test_select_emits_signal(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        received: list[str] = []
        mgr.selection_changed.connect(received.append)
        mgr.select("roi_1")
        assert received == ["roi_1"]

    def test_select_replaces(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.select("roi_2")
        assert mgr.selected_id == "roi_2"
        assert mgr.multi_selection == frozenset({"roi_2"})

    def test_add_to_selection(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.add_to_selection("roi_2")
        assert mgr.multi_selection == frozenset({"roi_1", "roi_2"})

    def test_deselect(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.deselect("roi_1")
        assert mgr.selected_id is None
        assert mgr.multi_selection == frozenset()

    def test_deselect_nonexistent(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.deselect("nonexistent")

    def test_clear_selection(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.clear_selection()
        assert mgr.selected_id is None
        assert mgr.multi_selection == frozenset()

    def test_clear_emits_signal(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        received: list[int] = []
        mgr.selection_cleared.connect(lambda: received.append(1))
        mgr.clear_selection()
        assert received == [1]

    def test_is_selected(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        assert mgr.is_selected("roi_1")
        assert not mgr.is_selected("roi_2")

    def test_set_hovered(self):
        from gui.roi.roi_selection_manager import ROISelectionManager
        mgr = ROISelectionManager()
        mgr.set_hovered("roi_1")
        assert mgr.hovered_id == "roi_1"
        mgr.set_hovered(None)
        assert mgr.hovered_id is None


# ==============================================================
# Test ROIDirtyTracker
# ==============================================================

class TestROIDirtyTracker:
    def test_initial_not_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        assert not tracker.is_dirty()

    def test_set_baseline_clears_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        tracker.mark_created("roi_1")
        assert tracker.is_dirty()
        tracker.set_baseline([_make_config()])
        assert not tracker.is_dirty()

    def test_mark_created_sets_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        tracker.mark_created("roi_1")
        assert tracker.is_dirty()

    def test_mark_deleted_sets_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        tracker.mark_deleted("roi_1")
        assert tracker.is_dirty()

    def test_mark_modified_sets_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker, ROIDirtyType
        tracker = ROIDirtyTracker()
        tracker.mark_modified("roi_1", ROIDirtyType.GEOMETRY)
        assert tracker.is_dirty()

    def test_mark_modified_with_type(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker, ROIDirtyType
        tracker = ROIDirtyTracker()
        tracker.mark_modified("roi_1", ROIDirtyType.ALARM)
        tracker.mark_modified("roi_1", ROIDirtyType.GEOMETRY)
        types = tracker.get_dirty_types("roi_1")
        assert ROIDirtyType.ALARM in types
        assert ROIDirtyType.GEOMETRY in types

    def test_get_dirty_types_none(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        assert tracker.get_dirty_types("nonexistent") == frozenset()

    def test_get_all_dirty_roi_ids(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker, ROIDirtyType
        tracker = ROIDirtyTracker()
        tracker.mark_modified("roi_1", ROIDirtyType.GEOMETRY)
        tracker.mark_created("roi_2")
        assert tracker.get_all_dirty_roi_ids() == frozenset({"roi_1", "roi_2"})

    def test_reset_clears_dirty(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        tracker.mark_created("roi_1")
        tracker.reset()
        assert not tracker.is_dirty()
        assert tracker.get_all_dirty_roi_ids() == frozenset()

    def test_emits_dirty_state_changed(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        received: list[bool] = []
        tracker.dirty_state_changed.connect(received.append)
        tracker.mark_created("roi_1")
        assert received == [True]
        tracker.set_baseline([_make_config()])
        assert received == [True, False]

    def test_duplicate_dirty_does_not_reemit(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        tracker = ROIDirtyTracker()
        received: list[bool] = []
        tracker.dirty_state_changed.connect(received.append)
        tracker.mark_created("roi_1")
        tracker.mark_created("roi_1")
        assert received == [True]

    def test_roi_dirty_type_enum_values(self):
        from gui.roi.roi_dirty_tracker import ROIDirtyType
        assert ROIDirtyType.GEOMETRY.value == 1
        assert ROIDirtyType.ALARM.value == 2
        assert ROIDirtyType.APPEARANCE.value == 3
        assert ROIDirtyType.RECORDING.value == 4
        assert ROIDirtyType.METADATA.value == 5
        assert ROIDirtyType.CONFIGURATION.value == 6


# ==============================================================
# Test ROICommand
# ==============================================================

class TestROICommand:
    def test_execute_callable(self):
        from gui.roi.roi_command import ROICommand
        state: dict[str, bool] = {"executed": False}

        def action() -> None:
            state["executed"] = True

        cmd = ROICommand(execute=action, description="Test")
        cmd.run()
        assert state["executed"]

    def test_execute_returns_result(self):
        from gui.roi.roi_command import ROICommand
        cmd = ROICommand(execute=lambda: 42)
        assert cmd.run() == 42

    def test_execute_tracks_execution(self):
        from gui.roi.roi_command import ROICommand
        cmd = ROICommand(execute=lambda: None)
        assert not cmd._executed
        cmd.run()
        assert cmd._executed

    def test_description(self):
        from gui.roi.roi_command import ROICommand
        cmd = ROICommand(execute=lambda: None, description="Create ROI")
        assert cmd.description == "Create ROI"

    def test_undo_optional(self):
        from gui.roi.roi_command import ROICommand
        cmd = ROICommand(execute=lambda: None)
        assert cmd.undo is None
        cmd2 = ROICommand(execute=lambda: None, undo=lambda: None)
        assert cmd2.undo is not None


# ==============================================================
# Test ROIWorkspace
# ==============================================================

class TestROIWorkspace:
    def test_load_state_creates_runtime_rois(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )

        workspace.load_state(_STATE)

        assert workspace.current_state == _STATE
        assert workspace.get_all_configurations() == []
        assert not dirty_tracker.is_dirty()

    def test_roi_creation_emits_roi_created(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )
        workspace.load_state(_STATE)

        received: list[str] = []
        signal_bus.roi_created.connect(received.append)

        workspace._on_create_roi("rectangle1")
        assert len(received) == 1
        roi_id = received[0]
        assert workspace.get_configuration(roi_id) is not None
        assert dirty_tracker.is_dirty()

    def test_roi_deletion(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )
        workspace.load_state(_STATE)
        workspace._on_create_roi("rectangle1")
        roi_id = list(workspace._configs.keys())[0]

        received: list[str] = []
        signal_bus.roi_deleted.connect(received.append)
        workspace._on_delete_roi(roi_id)
        assert received == [roi_id]
        assert workspace.get_configuration(roi_id) is None

    def test_roi_duplication(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )
        workspace.load_state(_STATE)
        workspace._on_create_roi("circle")
        roi_id = list(workspace._configs.keys())[0]

        received: list[tuple[str, str]] = []
        signal_bus.roi_duplicated.connect(lambda a, b: received.append((a, b)))
        workspace._on_duplicate_roi(roi_id)
        assert len(received) == 1
        new_id, original_id = received[0]
        assert original_id == roi_id
        assert new_id != roi_id
        assert workspace.get_configuration(new_id) is not None
        assert workspace.get_configuration(new_id).name.endswith("(copy)")

    def test_geometry_changed_marks_dirty(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker, ROIDirtyType
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository
        from roi.geometry import Rectangle1ROI

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )
        workspace.load_state(_STATE)
        workspace._on_create_roi("rectangle1")
        roi_id = list(workspace._configs.keys())[0]

        dirty_tracker.set_baseline(workspace.get_all_configurations())

        new_geom = Rectangle1ROI(row1=0, col1=0, row2=50, col2=100)
        workspace._on_geometry_edited(roi_id, new_geom)
        assert dirty_tracker.is_dirty()
        assert ROIDirtyType.GEOMETRY in dirty_tracker.get_dirty_types(roi_id)

    def test_save_clears_dirty(self, tmp_path):
        from gui.roi.roi_signal_bus import ROISignalBus
        from gui.roi.roi_selection_manager import ROISelectionManager
        from gui.roi.roi_dirty_tracker import ROIDirtyTracker
        from gui.roi.roi_workspace import ROIWorkspace
        from roi.editor.editor_manager import ROIEditorManager
        from roi.persistence.repository import JSONROIRepository

        repo = JSONROIRepository(str(tmp_path))
        signal_bus = ROISignalBus()
        selection_mgr = ROISelectionManager()
        dirty_tracker = ROIDirtyTracker()
        editor_mgr = ROIEditorManager(window_handle=0)

        workspace = ROIWorkspace(
            signal_bus=signal_bus,
            repository=repo,
            selection_manager=selection_mgr,
            dirty_tracker=dirty_tracker,
            editor_manager=editor_mgr,
        )
        workspace.load_state(_STATE)
        workspace._on_create_roi("rectangle1")

        assert dirty_tracker.is_dirty()
        workspace._on_save()
        assert not dirty_tracker.is_dirty()
