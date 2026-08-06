from __future__ import annotations

from typing import Callable

import numpy as np
from PyQt5.QtCore import QObject

from utilities import logger

from alarm.manager import AlarmManager
from configuration.settings import Settings
from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.editor.editor_manager import ROIEditorManager
from roi.persistence.repository import JSONROIRepository
from roi.runtime import RuntimeROIStatistics
from roi_engine.engine import ROIEnginePool
from roi_engine.integration import ROIEngineManager

from gui.roi.roi_dirty_tracker import ROIDirtyTracker, ROIDirtyType
from gui.roi.roi_selection_manager import ROISelectionManager
from gui.roi.roi_signal_bus import ROISignalBus


class ROIWorkspace(QObject):
    def __init__(
        self,
        signal_bus: ROISignalBus,
        repository: JSONROIRepository,
        selection_manager: ROISelectionManager,
        dirty_tracker: ROIDirtyTracker,
        editor_manager: ROIEditorManager,
        on_alarm_event: Callable | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._signal_bus = signal_bus
        self._repository = repository
        self._selection_manager = selection_manager
        self._dirty_tracker = dirty_tracker
        self._editor_manager = editor_manager

        self._runtime_managers: dict[str, ROIEngineManager] = {}
        self._engine_pool = ROIEnginePool()
        self._dual_validation = Settings().ROI_ENGINE_DUAL_VALIDATION
        self._alarm_manager = AlarmManager(on_event=on_alarm_event)
        self._active_camera_id: str | None = None
        self._current_state: AcquisitionState | None = None
        self._configs: dict[str, ROIConfiguration] = {}

        self._connect_signals()

    @property
    def runtime_manager(self) -> ROIEngineManager:
        return self._get_or_create_manager(self._active_camera_id or "")

    @property
    def alarm_manager(self) -> AlarmManager:
        return self._alarm_manager

    @property
    def current_state(self) -> AcquisitionState | None:
        return self._current_state

    @property
    def active_camera_id(self) -> str | None:
        return self._active_camera_id

    def _get_or_create_manager(self, camera_id: str) -> ROIEngineManager:
        if camera_id not in self._runtime_managers:
            self._runtime_managers[camera_id] = ROIEngineManager(
                engine=self._engine_pool.engine(camera_id),
                config_provider=lambda rid: self._configs.get(rid),
                dual_validation=self._dual_validation,
            )
        return self._runtime_managers[camera_id]

    def get_runtime_manager(self, camera_id: str) -> ROIEngineManager | None:
        return self._runtime_managers.get(camera_id)

    def unload_camera(self, camera_id: str) -> None:
        mgr = self._runtime_managers.pop(camera_id, None)
        if mgr is not None:
            mgr.unload()
        self._engine_pool.remove(camera_id)

    def _connect_signals(self) -> None:
        bus = self._signal_bus
        bus.create_roi_requested.connect(self._on_create_roi)
        bus.delete_requested.connect(self._on_delete_roi)
        bus.duplicate_requested.connect(self._on_duplicate_roi)
        bus.edit_requested.connect(self._on_edit_start)
        bus.edit_finish_requested.connect(self._on_edit_finish)
        bus.save_requested.connect(self._on_save)
        bus.geometry_edited.connect(self._on_geometry_edited)
        bus.roi_alarm_changed.connect(self._on_alarm_changed)
        bus.roi_appearance_changed.connect(self._on_appearance_changed)
        bus.roi_recording_changed.connect(self._on_recording_changed)
        bus.roi_renamed.connect(self._on_renamed)

    def load_state(self, acquisition_state: AcquisitionState) -> None:
        self._editor_manager.close_all()
        self._selection_manager.clear_selection()

        self._current_state = acquisition_state
        self._active_camera_id = acquisition_state.camera_id
        configs = self._repository.load_all(acquisition_state)
        self._configs = {c.roi_id: c for c in configs}
        mgr = self._get_or_create_manager(acquisition_state.camera_id)
        mgr.load(configs)
        mgr.rebuild_dirty_regions()
        self._dirty_tracker.set_baseline(configs)
        self._register_alarms(configs)

    def get_configuration(self, roi_id: str) -> ROIConfiguration | None:
        return self._configs.get(roi_id)

    def update_configuration(self, config: ROIConfiguration) -> None:
        """Replace the stored configuration and reload the engine store.

        Called by the property panel write-back path (enabled, visible,
        style, alarm, recording, name changes). The engine store is
        immutable, so a changed config object must trigger a fresh
        snapshot through mark_dirty().
        """
        if config.roi_id not in self._configs:
            return
        self._configs[config.roi_id] = config
        mgr = self._get_or_create_manager(self._active_camera_id or "")
        mgr.mark_dirty(config.roi_id)

    def get_all_configurations(self) -> list[ROIConfiguration]:
        return list(self._configs.values())

    def get_configurations_for_camera(self, camera_id: str) -> list[ROIConfiguration]:
        return [c for c in self._configs.values() if c.camera_id == camera_id]

    def _register_alarms(self, configs: list[ROIConfiguration]) -> None:
        for cfg in configs:
            self._alarm_manager.register(cfg.roi_id, cfg.alarm)

    def _on_create_roi(self, shape_type: str) -> None:
        if self._current_state is None:
            return
        from roi.configuration import ROIConfiguration
        from roi.geometry import (
            CircleROI, EllipseROI, Rectangle1ROI,
            Rectangle2ROI, PolygonROI, ROIGeometry,
        )
        from roi.alarm_settings import ROIAlarmSettings, ROIAlarmCondition
        from roi.recording_settings import ROIRecordingSettings
        from roi.style import ROIStyle

        import uuid
        roi_id = f"roi_{uuid.uuid4().hex[:8]}"

        geometry: ROIGeometry
        if shape_type == "rectangle1":
            geometry = Rectangle1ROI(row1=100, col1=100, row2=300, col2=400)
        elif shape_type == "rectangle2":
            geometry = Rectangle2ROI(row=200, col=250, phi=0.0, length1=100, length2=60)
        elif shape_type == "circle":
            geometry = CircleROI(row=200, col=250, radius=50)
        elif shape_type == "ellipse":
            geometry = EllipseROI(row=200, col=250, phi=0.0, radius1=80, radius2=40)
        elif shape_type == "polygon":
            geometry = PolygonROI(points=((150, 150), (250, 150), (250, 250), (150, 250)))
        else:
            return

        config = ROIConfiguration(
            roi_id=roi_id,
            name=shape_type.capitalize(),
            acquisition_state=self._current_state,
            geometry=geometry,
            style=ROIStyle(color="#FFFF00", selected_color="#00FF00"),
            alarm=ROIAlarmSettings(
                enabled=False,
                condition=ROIAlarmCondition.HIGH,
                value=85.0,
            ),
            recording=ROIRecordingSettings(enabled=False),
            enabled=True,
            visible=True,
        )

        self._configs[roi_id] = config
        mgr = self._get_or_create_manager(self._active_camera_id or "")
        mgr.add_configuration(config)
        mgr.mark_dirty(config.roi_id)
        mgr.rebuild_dirty_regions()
        self._alarm_manager.register(config.roi_id, config.alarm)
        self._dirty_tracker.mark_created(roi_id)
        self._signal_bus.roi_created.emit(roi_id)
        self._on_edit_start(roi_id)

    def _on_delete_roi(self, roi_id: str) -> None:
        if roi_id not in self._configs:
            return
        self._editor_manager.delete_editor(roi_id)
        self._alarm_manager.unregister(roi_id)
        self._configs.pop(roi_id, None)
        mgr = self._get_or_create_manager(self._active_camera_id or "")
        mgr.mark_dirty(roi_id)
        self._selection_manager.deselect(roi_id)
        self._dirty_tracker.mark_deleted(roi_id)
        self._signal_bus.roi_deleted.emit(roi_id)

    def _on_duplicate_roi(self, roi_id: str) -> None:
        original = self._configs.get(roi_id)
        if original is None:
            return
        from dataclasses import replace
        import uuid
        new_id = f"roi_{uuid.uuid4().hex[:8]}"
        duplicate = replace(original, roi_id=new_id, name=f"{original.name} (copy)")
        self._configs[new_id] = duplicate
        mgr = self._get_or_create_manager(self._active_camera_id or "")
        mgr.add_configuration(duplicate)
        mgr.mark_dirty(duplicate.roi_id)
        mgr.rebuild_dirty_regions()
        self._alarm_manager.register(duplicate.roi_id, duplicate.alarm)
        self._dirty_tracker.mark_created(new_id)
        self._signal_bus.roi_duplicated.emit(new_id, roi_id)

    def _on_edit_start(self, roi_id: str) -> None:
        config = self._configs.get(roi_id)
        if config is None:
            return
        try:
            self._editor_manager.open_editor(config)
        except Exception:
            logger.warning(f"Failed to open editor for ROI {roi_id}")
            return
        self._signal_bus.editing_started.emit(roi_id)

    def _on_edit_finish(self, roi_id: str) -> None:
        config = self._editor_manager.close_editor(roi_id)
        if config is not None:
            self._configs[roi_id] = config
            mgr = self._get_or_create_manager(self._active_camera_id or "")
            mgr.mark_dirty(roi_id)
            mgr.rebuild_dirty_regions()
            self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.GEOMETRY)
        self._signal_bus.editing_finished.emit(roi_id)

    def _on_geometry_edited(self, roi_id: str, geometry: object) -> None:
        config = self._configs.get(roi_id)
        if config is None:
            return
        from dataclasses import replace
        self._configs[roi_id] = replace(config, geometry=geometry)
        mgr = self._get_or_create_manager(self._active_camera_id or "")
        mgr.mark_dirty(roi_id)
        self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.GEOMETRY)
        self._signal_bus.roi_geometry_changed.emit(roi_id)

    def _on_alarm_changed(self, roi_id: str) -> None:
        config = self._configs.get(roi_id)
        if config is not None:
            self._alarm_manager.register(roi_id, config.alarm)
        self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.ALARM)

    def _on_appearance_changed(self, roi_id: str) -> None:
        self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.APPEARANCE)

    def _on_recording_changed(self, roi_id: str) -> None:
        self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.RECORDING)

    def _on_renamed(self, roi_id: str) -> None:
        self._dirty_tracker.mark_modified(roi_id, ROIDirtyType.CONFIGURATION)

    def process_frame(
        self,
        camera_id: str,
        temperature_image: np.ndarray,
        frame_id: int,
    ) -> list[RuntimeROIStatistics]:
        mgr = self._get_or_create_manager(camera_id)
        stats = mgr.process_frame(temperature_image, frame_id)
        if stats and camera_id == self._active_camera_id:
            self._signal_bus.roi_statistics_updated.emit(camera_id)
        active_rois = mgr.get_active()
        all_stats: dict[str, RuntimeROIStatistics] = {}
        for roi in active_rois:
            if roi.statistics is not None and roi.statistics.valid:
                all_stats[roi.configuration.roi_id] = roi.statistics
        alarms = self._alarm_manager.evaluate_all(all_stats, frame_id)
        if alarms:
            for alarm in alarms:
                self._signal_bus.roi_alarm_state_changed.emit(
                    alarm.roi_id, alarm
                )
        return stats

    def _on_save(self) -> None:
        if self._current_state is None:
            return
        self._editor_manager.close_all()
        configs = self.get_all_configurations()
        self._repository.save_all(configs)
        self._dirty_tracker.set_baseline(configs)
