"""
harness.py

Headless driver for the ROI Workspace (Calibration Window integration),
mirroring the wiring done by CalibrationWindow:

    ROIWorkspace(signal_bus, repository, selection_manager,
                 dirty_tracker, editor_manager)

The harness:

• builds a workspace with a temporary JSON repository
• loads positions via workspace.load_state()
• drives per-frame processing via workspace.process_frame()
• measures pipeline time, GUI-handler time, and process memory
• simulates the calibration window's statistics handler so GUI
  performance is measurable without a real window

The editor manager is a stub (windowless), because drawing-object
editors require a HALCON window; the workspace wraps editor calls in
try/except, so behavior remains representative. Editing scenarios
drive the signal bus (bus.geometry_edited etc.) which is exactly what
the calibration window does.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np

from gui.roi.roi_dirty_tracker import ROIDirtyTracker
from gui.roi.roi_selection_manager import ROISelectionManager
from gui.roi.roi_signal_bus import ROISignalBus
from gui.roi.roi_workspace import ROIWorkspace
from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import Rectangle1ROI
from roi.persistence.repository import JSONROIRepository
from roi.recording_settings import ROIRecordingSettings
from roi.style import ROIStyle
from tests.validation.frame_source import CameraFrameSource, SimulatedFrameSource
from tests.validation.metrics import (
    FrameMetric,
    Metrics,
    MetricsCollector,
)
from utilities import logger

MB = 1024 * 1024

DEFAULT_CAMERA_ID = "cam_harness"
FRAME_SKIP_SLEEP = 0.005


class FakeEditorManager:
    """Windowless editor manager stub for the validation harness.

    The workspace tolerates editor failures (it catches exceptions from
    open_editor), so a stub keeps the harness headless while exercising
    the exact workspace code path.
    """

    def close_all(self) -> None:
        """Close all editors (no-op)."""

    def delete_editor(self, roi_id: str) -> None:
        """Delete an editor (no-op)."""

    def close_editor(self, roi_id: str):
        """Close an editor; returns None like an already-closed editor."""
        return None

    def open_editor(self, configuration: ROIConfiguration) -> None:
        """Open an editor (no-op)."""


def make_roi_config(
    roi_id: str,
    name: str,
    state: AcquisitionState,
    row1: int = 60,
    col1: int = 60,
    row2: int = 160,
    col2: int = 200,
    enabled: bool = True,
    visible: bool = True,
) -> ROIConfiguration:
    """Build a rectangle ROIConfiguration for a given acquisition state."""
    return ROIConfiguration(
        roi_id=roi_id,
        name=name,
        acquisition_state=state,
        geometry=Rectangle1ROI(row1=row1, col1=col1, row2=row2, col2=col2),
        style=ROIStyle(color="#FFFF00", selected_color="#00FF00"),
        alarm=ROIAlarmSettings(
            enabled=False,
            condition=ROIAlarmCondition.HIGH,
            value=85.0,
        ),
        recording=ROIRecordingSettings(enabled=False),
        enabled=enabled,
        visible=visible,
    )


class WarningCapture(logging.Handler):
    """Collects WARNING+ log records for assertion on dual validation."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages_containing(self, text: str) -> list[str]:
        return [r.getMessage() for r in self.records if text in r.getMessage()]


class ValidationHarness:
    """Headless ROIWorkspace driver producing validation metrics."""

    def __init__(
        self,
        camera_id: str = DEFAULT_CAMERA_ID,
        repo_base: str | Path | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._signal_bus = ROISignalBus()
        self._selection_manager = ROISelectionManager()
        self._dirty_tracker = ROIDirtyTracker()
        self._editor_manager = FakeEditorManager()
        self._repo_base = Path(repo_base) if repo_base else Path("config/roi_validation")
        self._repository = JSONROIRepository(str(self._repo_base))
        self._workspace = ROIWorkspace(
            signal_bus=self._signal_bus,
            repository=self._repository,
            selection_manager=self._selection_manager,
            dirty_tracker=self._dirty_tracker,
            editor_manager=self._editor_manager,
        )
        self._collector = MetricsCollector(memory_provider=self._engine_memory_mb)
        self._current_state: AcquisitionState | None = None

    # ----------------------------------------------------------
    # Accessors
    # ----------------------------------------------------------

    @property
    def workspace(self) -> ROIWorkspace:
        """The ROIWorkspace under validation."""
        return self._workspace

    @property
    def signal_bus(self) -> ROISignalBus:
        """Signal bus driving the workspace (same as the window's)."""
        return self._signal_bus

    @property
    def repository(self) -> JSONROIRepository:
        """Repository used by the workspace (points at the repo base)."""
        return self._repository

    @property
    def collector(self) -> MetricsCollector:
        """Metrics collector for the current run."""
        return self._collector

    @property
    def metrics(self) -> Metrics:
        """Raw metrics of the current run."""
        return self._collector.metrics

    @property
    def current_state(self) -> AcquisitionState | None:
        """Acquisition state of the position currently loaded."""
        return self._current_state

    def manager(self) -> object:
        """The ROIEngineManager of the currently active camera."""
        camera_id = self._workspace.active_camera_id or self._camera_id
        return self._workspace.get_runtime_manager(camera_id)

    def engine(self) -> object:
        """The ROIEngine behind the active camera (validation access)."""
        return getattr(self.manager(), "_engine", None)

    def engine_generation(self) -> int:
        """Store generation counter of the engine (monotonic on reload)."""
        engine = getattr(self.manager(), "_engine", None)
        store = engine.store() if engine is not None else None
        return store.generation if store is not None else 0

    # ----------------------------------------------------------
    # Position management (mirrors calibration window switching)
    # ----------------------------------------------------------

    def save_position(
        self,
        configs: list[ROIConfiguration],
        pan: int = 0,
        camera_id: str | None = None,
    ) -> AcquisitionState:
        """Persist a position's ROIs and return its AcquisitionState.

        The camera_id defaults to the harness camera; pass an explicit
        value when storing positions for other cameras (camera-switch
        scenario).
        """
        camera_id = camera_id or self._camera_id
        state = AcquisitionState(camera_id=camera_id, pan=float(pan))
        self._repository.save_all(configs)
        return state

    def load_position(
        self,
        configs: list[ROIConfiguration],
        pan: int = 0,
        camera_id: str | None = None,
    ) -> AcquisitionState:
        """Persist and load a position exactly like position switching."""
        state = self.save_position(configs, pan, camera_id)
        self._workspace.load_state(state)
        self._current_state = state
        return state

    def switch_to_position(self, pan: int) -> None:
        """Re-load the repository state for an already-saved position."""
        state = AcquisitionState(camera_id=self._camera_id, pan=float(pan))
        self._workspace.load_state(state)
        self._current_state = state

    # ----------------------------------------------------------
    # ROI editing (signal-bus driven, as the window does)
    # ----------------------------------------------------------

    def edit_geometry(self, roi_id: str, geometry: object) -> None:
        """Emit geometry_edited; triggers mark_dirty + dirty tracker."""
        self._signal_bus.geometry_edited.emit(roi_id, geometry)

    def update_configuration(
        self,
        config: ROIConfiguration,
        emit_appearance: bool = True,
    ) -> None:
        """Write a config change back like the property panel does.

        The panel pushes a new config object via config_updated
        (workspace.update_configuration -> engine store reload) and
        emits the appearance signal for list/dirty tracking.
        """
        self._workspace.update_configuration(config)
        if emit_appearance:
            self._signal_bus.roi_appearance_changed.emit(config.roi_id)

    def delete_roi(self, roi_id: str) -> None:
        """Emit delete_requested."""
        self._signal_bus.delete_requested.emit(roi_id)

    def rename_roi(self, roi_id: str, new_name: str) -> None:
        """Rename a ROI the same way the panel does.

        The panel pushes a new config via config_updated and emits
        roi_renamed for list/dirty tracking.
        """
        config = self._workspace.get_configuration(roi_id)
        if config is None:
            return
        renamed = replace(config, name=new_name)
        self._workspace.update_configuration(renamed)
        self._signal_bus.roi_renamed.emit(roi_id)

    # ----------------------------------------------------------
    # Processing
    # ----------------------------------------------------------

    def process_one(
        self,
        temperature_image: np.ndarray,
        frame_id: int,
    ) -> FrameMetric:
        """Process one frame through the workspace and measure time.

        pipeline_ms is the workspace.process_frame() duration (engine
        dominated). gui_ms simulates the calibration window's statistics
        handler: iterating active ROIs and reading their statistics.
        engine_ms is approximated as pipeline_ms minus gui_ms.
        """
        dropped = 0
        exception = False
        halcon_error = False
        camera_id = self._workspace.active_camera_id or self._camera_id

        t0 = time.perf_counter()
        try:
            stats = self._workspace.process_frame(
                camera_id, temperature_image, frame_id
            )
        except Exception:
            exception = True
            stats = []
            logger.exception("harness process_frame failed")
        t1 = time.perf_counter()

        gui_ms = self._simulate_gui_handler()
        t2 = time.perf_counter()

        pipeline_ms = (t1 - t0) * 1000.0
        engine_ms = max(0.0, pipeline_ms - gui_ms)
        active_rois = len(self.manager().get_active())

        metric = FrameMetric(
            frame_number=frame_id,
            pipeline_ms=pipeline_ms,
            engine_ms=engine_ms,
            gui_ms=gui_ms,
            dropped=dropped,
            exception=exception,
            halcon_error=halcon_error,
            active_rois=active_rois,
        )
        self._collector.record_frame(metric)
        return metric

    def _simulate_gui_handler(self) -> float:
        """Time the calibration window's on_statistics_updated body."""
        t0 = time.perf_counter()
        mgr = self.manager()
        if mgr is None:
            return 0.0
        for roi in mgr.get_active():
            stat = roi.statistics
            if stat is not None and stat.valid:
                _ = stat.maximum
                _ = stat.mean
        return (time.perf_counter() - t0) * 1000.0

    def _engine_memory_mb(self) -> tuple[float, float]:
        """Return (engine_bytes, store_bytes) in MB for interval samples."""
        engine = self.engine()
        if engine is None:
            return 0.0, 0.0
        engine_mb = engine.memory_bytes() / MB
        store = engine.store()
        store_mb = store.memory_bytes() / MB if store is not None else 0.0
        return round(engine_mb, 3), round(store_mb, 3)

    # ----------------------------------------------------------
    # Frame loops
    # ----------------------------------------------------------

    def run_frames(
        self,
        source: CameraFrameSource | SimulatedFrameSource,
        count: int,
        per_frame: Callable[[int, np.ndarray, int], None] | None = None,
    ) -> Metrics:
        """Process up to `count` frames from `source`.

        Returns the collected metrics. When the source is a real camera
        (may return None between frames), the loop waits for the next
        frame; `count` is then the number of processed frames.
        """
        frame_id = 0
        processed = 0
        while processed < count:
            result = source.next_frame()
            if result is None:
                time.sleep(FRAME_SKIP_SLEEP)
                continue
            temperature, src_frame_no = result
            frame_id += 1
            if per_frame is not None:
                per_frame(frame_id, temperature, src_frame_no)
            self.process_one(temperature, frame_id)
            processed += 1
        self._collector.metrics.finalize()
        return self._collector.metrics

    def run_duration(
        self,
        source: CameraFrameSource | SimulatedFrameSource,
        seconds: float,
        per_frame: Callable[[int, np.ndarray, int], None] | None = None,
    ) -> Metrics:
        """Process frames from `source` for `seconds` wall-clock time."""
        deadline = time.monotonic() + seconds
        frame_id = 0
        while time.monotonic() < deadline:
            result = source.next_frame()
            if result is None:
                time.sleep(FRAME_SKIP_SLEEP)
                continue
            temperature, src_frame_no = result
            frame_id += 1
            if per_frame is not None:
                per_frame(frame_id, temperature, src_frame_no)
            self.process_one(temperature, frame_id)
        self._collector.metrics.finalize()
        return self._collector.metrics

    def finalize(self) -> None:
        """Finalize metrics (idempotent)."""
        self._collector.metrics.finalize()
