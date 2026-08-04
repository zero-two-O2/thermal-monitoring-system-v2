"""
runtime.py

Read-only ROI processing runtime for the Observation Window.

The runtime is the only observation-side consumer of the production
ROI engine. It owns one ROIEngineManager per camera (backed by a
shared ROIEnginePool, so engines are created once and reused), loads
the ROIStore for the camera's current position from the same JSON
repository the Calibration Window writes to, and evaluates alarms with
the existing AlarmManager.

    ObservationWindow / CameraDetailWindow
        -> ObservationRuntime (this module)
            -> ROIEngineManager (per camera)
                -> ROIEngine (per camera, from ROIEnginePool)
                -> ROIStore / RegionCache / MaskCache / StatisticsEngine
            -> AlarmManager (per camera, unchanged alarm engine)

The runtime is hardware- and GUI-free: it consumes numpy temperature
frames and CameraContext position identifiers only. All processing runs
on the caller's thread (the Observation Window's poll timer), which
serializes access to the engine as its contract requires.

Lifecycle logging only: camera connected/disconnected, engine
created/reused, ROIStore loaded, position changed, errors. There is no
per-frame logging.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from alarm.events import AlarmEvent
from alarm.manager import AlarmManager
from alarm.result import AlarmResult
from configuration.settings import Settings
from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.persistence.exceptions import PersistenceError
from roi.persistence.repository import JSONROIRepository
from roi.runtime import RuntimeROI, RuntimeROIStatistics
from roi_engine.engine import ROIEnginePool
from roi_engine.integration import ROIEngineManager

logger = logging.getLogger(__name__)


class ObservationRuntime:
    """Per-camera ROI engine + alarm evaluation for observation mode.

    One manager and one AlarmManager per camera; engines are reused
    across position switches and window reopenings. Position switches
    load the correct ROIStore and invalidate caches without affecting
    other cameras.
    """

    def __init__(
        self,
        repo_base: str | Path = "data/roi",
        dual_validation: bool | None = None,
        on_alarm_event: Callable[[str, AlarmEvent], None] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        repo_base : str | Path
            Base path of the ROI JSON repository (must match the
            Calibration Window's repository so observation sees the
            saved ROIs; default "data/roi").
        dual_validation : bool | None
            When True, run the legacy manager per frame and compare
            statistics (Settings.ROI_ENGINE_DUAL_VALIDATION). Pass an
            explicit value when toggling for validation runs.
        on_alarm_event : Callable[[str, AlarmEvent], None] | None
            Optional callback invoked with (camera_id, event) whenever
            an alarm machine changes state.
        """
        self._repo = JSONROIRepository(str(repo_base))
        self._pool = ROIEnginePool()
        self._managers: dict[str, ROIEngineManager] = {}
        self._alarms: dict[str, AlarmManager] = {}
        self._configs: dict[str, dict[str, ROIConfiguration]] = {}
        self._registered: dict[str, set[str]] = {}
        self._positions: dict[str, str | None] = {}
        self._frame_counters: dict[str, int] = {}
        self._engine_ms: dict[str, float] = {}
        self._fps_counts: dict[str, int] = {}
        self._fps_windows: dict[str, float] = {}
        self._dual_validation = (
            Settings().ROI_ENGINE_DUAL_VALIDATION
            if dual_validation is None
            else dual_validation
        )
        self._on_alarm_event = on_alarm_event

    # ==========================================================
    # Camera lifecycle
    # ==========================================================

    def add_camera(self, camera_id: str) -> None:
        """Register a camera with its own engine and alarm manager.

        Idempotent: adding an already-registered camera is a no-op.
        """
        if camera_id in self._managers:
            return
        if self._pool.get(camera_id) is None:
            logger.info("Observation: engine created for camera %s", camera_id)
        else:
            logger.info("Observation: engine reused for camera %s", camera_id)
        manager = ROIEngineManager(
            engine=self._pool.engine(camera_id),
            config_provider=lambda rid, _cid=camera_id: self._configs.get(_cid, {}).get(rid),
            dual_validation=self._dual_validation,
        )
        alarm_manager = AlarmManager(
            on_event=(
                (lambda event, _cid=camera_id: self._on_alarm_event(_cid, event))
                if self._on_alarm_event is not None
                else None
            )
        )
        self._managers[camera_id] = manager
        self._alarms[camera_id] = alarm_manager
        self._configs[camera_id] = {}
        self._registered[camera_id] = set()
        self._positions[camera_id] = None
        self._frame_counters[camera_id] = 0
        self._engine_ms[camera_id] = 0.0
        self._fps_counts[camera_id] = 0
        self._fps_windows[camera_id] = time.monotonic()
        logger.info("Observation: camera connected %s", camera_id)

    def remove_camera(self, camera_id: str) -> None:
        """Release the camera's engine, alarms, and cached store."""
        manager = self._managers.pop(camera_id, None)
        if manager is None:
            return
        for roi_id in self._registered.pop(camera_id, set()):
            self._alarms[camera_id].unregister(roi_id)
        self._alarms.pop(camera_id, None)
        self._configs.pop(camera_id, None)
        self._positions.pop(camera_id, None)
        self._frame_counters.pop(camera_id, None)
        self._engine_ms.pop(camera_id, None)
        self._fps_counts.pop(camera_id, None)
        self._fps_windows.pop(camera_id, None)
        manager.unload()
        self._pool.remove(camera_id)
        logger.info("Observation: camera disconnected %s", camera_id)

    def cameras(self) -> list[str]:
        """Camera ids currently registered with the runtime."""
        return list(self._managers.keys())

    def shutdown(self) -> None:
        """Release every camera engine and alarm manager."""
        for camera_id in list(self.cameras()):
            self.remove_camera(camera_id)
        self._pool.clear()
        logger.info("Observation: runtime shutdown")

    # ==========================================================
    # Position handling
    # ==========================================================

    def set_position(self, camera_id: str, position_id: str | None) -> None:
        """Load the ROIStore for the camera's new position.

        Reloads only when the position actually changed. A None
        position loads an empty store (no ROIs configured yet).
        Other cameras are never affected.
        """
        if camera_id not in self._managers:
            return
        if self._positions.get(camera_id) == position_id:
            return
        self._positions[camera_id] = position_id
        self._load_position(camera_id, position_id)

    def position(self, camera_id: str) -> str | None:
        """Currently loaded position id for a camera, or None."""
        return self._positions.get(camera_id)

    def _load_position(self, camera_id: str, position_id: str | None) -> None:
        manager = self._managers[camera_id]
        configs: list[ROIConfiguration] = []
        if position_id is not None:
            state = AcquisitionState(camera_id=camera_id, pan=float(position_id))
            try:
                # The Calibration Window saves through its own repository
                # instance; clear the cache so its latest writes are seen.
                self._repo.clear_cache()
                configs = self._repo.load_all(state)
            except PersistenceError:
                logger.exception(
                    "Observation: failed to load ROIs camera=%s position=%s",
                    camera_id,
                    position_id,
                )
                configs = []
        self._configs[camera_id] = {c.roi_id: c for c in configs}
        manager.load(configs)

        # Alarm machines must follow the store: unregister stale ROIs
        # so old ACTIVE/PENDING machines cannot linger across positions.
        stale = self._registered[camera_id] - set(self._configs[camera_id])
        for roi_id in stale:
            self._alarms[camera_id].unregister(roi_id)
        self._registered[camera_id] = set(self._configs[camera_id])
        for roi_id, config in self._configs[camera_id].items():
            self._alarms[camera_id].register(roi_id, config.alarm)

        logger.info(
            "Observation: ROIStore loaded camera=%s position=%s rois=%d",
            camera_id,
            position_id,
            len(configs),
        )

    # ==========================================================
    # Frame processing
    # ==========================================================

    def process_frame(
        self,
        camera_id: str,
        temperature_image,
        frame_id: int | None = None,
    ) -> tuple[list[RuntimeROIStatistics], list[AlarmResult]]:
        """Process one temperature frame for one camera.

        Runs the engine, evaluates alarms with the existing
        AlarmManager, and returns the fresh statistics and alarm
        results. Unknown cameras are a no-op.
        """
        manager = self._managers.get(camera_id)
        if manager is None:
            return [], []
        if frame_id is None:
            frame_id = self._frame_counters[camera_id]
        self._frame_counters[camera_id] = frame_id + 1

        started = time.monotonic()
        stats = manager.process_frame(temperature_image, frame_id)
        self._engine_ms[camera_id] = (time.monotonic() - started) * 1000.0

        self._fps_counts[camera_id] += 1

        all_stats = {
            roi.configuration.roi_id: roi.statistics
            for roi in manager.get_active()
            if roi.statistics is not None and roi.statistics.valid
        }
        timestamp_ms = int(time.monotonic() * 1000.0)
        results = self._alarms[camera_id].evaluate_all(all_stats, timestamp_ms)
        return stats, results

    # ==========================================================
    # Accessors
    # ==========================================================

    def manager(self, camera_id: str) -> ROIEngineManager | None:
        """The camera's engine manager (None when not registered)."""
        return self._managers.get(camera_id)

    def alarm_manager(self, camera_id: str) -> AlarmManager | None:
        """The camera's alarm manager (None when not registered)."""
        return self._alarms.get(camera_id)

    def active_rois(self, camera_id: str) -> list[RuntimeROI]:
        """Enabled, non-error ROI views for one camera."""
        manager = self._managers.get(camera_id)
        if manager is None:
            return []
        return manager.get_active()

    def stats(self, camera_id: str) -> dict[str, RuntimeROIStatistics]:
        """Valid statistics for one camera, keyed by roi_id."""
        manager = self._managers.get(camera_id)
        if manager is None:
            return {}
        return {
            roi.configuration.roi_id: roi.statistics
            for roi in manager.get_active()
            if roi.statistics is not None and roi.statistics.valid
        }

    def engine_generation(self, camera_id: str) -> int:
        """Store snapshot generation of the camera's engine."""
        engine = self._pool.get(camera_id)
        store = engine.store() if engine is not None else None
        return store.generation if store is not None else 0

    def frame_counter(self, camera_id: str) -> int:
        """Monotonic frame counter used for the last processed frame."""
        return self._frame_counters.get(camera_id, 0)

    def last_engine_ms(self, camera_id: str) -> float:
        """Engine processing time of the last frame, in milliseconds."""
        return self._engine_ms.get(camera_id, 0.0)

    def fps(self, camera_id: str) -> float:
        """Rolling frames-per-second for one camera."""
        count = self._fps_counts.get(camera_id, 0)
        start = self._fps_windows.get(camera_id, 0.0)
        now = time.monotonic()
        elapsed = now - start
        if count == 0:
            return 0.0
        if elapsed >= 1.0:
            self._fps_counts[camera_id] = 0
            self._fps_windows[camera_id] = now
            return count / elapsed
        return count / elapsed

    def memory_bytes(self, camera_id: str) -> int:
        """Approximate engine footprint (store + caches) in bytes."""
        engine = self._pool.get(camera_id)
        return engine.memory_bytes() if engine is not None else 0
