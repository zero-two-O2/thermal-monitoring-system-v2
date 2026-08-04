"""
integration.py

Backward-compatible runtime manager facade backed by the ROI engine.

ROIEngineManager mirrors the public surface of the legacy
RuntimeROIManagerImpl (roi/runtime_manager.py) so the Calibration
Window can run on the production ROI engine without GUI changes.
It is the only bridge the GUI is allowed to use:

    GUI (ROIWorkspace / CalibrationWindow)
        -> ROIEngineManager (adapter, this file)
            -> ROIEngine / ROIEnginePool (per-camera engine)
            -> RegionCache / MaskCache / StatisticsEngine / ROIStore

The GUI never touches the engine internals directly.

Semantics
---------
- Configurations are kept in an internal dict (source of truth) and
  pushed into an immutable ROIStore snapshot. Any configuration change
  (create, delete, edit, duplicate) requires a new snapshot; cache-only
  changes reuse the store and only invalidate the region/mask caches.
- Geometry edits are picked up on the next mark_dirty() call: the
  config provider (the workspace's config dict) is consulted, and a new
  config object triggers a store reload. This fixes a legacy gap where
  edited geometry was not reflected in statistics until reload.
- Statistics are exposed as fresh RuntimeROIStatistics objects per
  frame, one per enabled ROI, attached to lightweight RuntimeROI views
  so existing consumers (get_active() / roi.statistics) keep working.

Dual validation mode
--------------------
When enabled (see Settings.ROI_ENGINE_DUAL_VALIDATION), each frame is
also processed by the legacy RuntimeROIManagerImpl and the results are
compared (minimum, maximum, mean, standard deviation, pixel count,
hotspot). One warning is logged per mismatching ROI; warnings do not
repeat while the ROI keeps mismatching, and clean ROIs log at debug
level. The mode exists only for integration verification and is off in
production.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

import numpy as np

from roi.configuration import ROIConfiguration
from roi.runtime import RuntimeROI, RuntimeROIState, RuntimeROIStatistics
from roi.runtime_manager import RuntimeROIManagerImpl
from roi_engine.engine import ROIEngine
from roi_engine.types import ALL_SHAPES

logger = logging.getLogger(__name__)

_VALIDATION_FIELDS: tuple[str, ...] = (
    "minimum",
    "maximum",
    "mean",
    "standard_deviation",
    "pixel_count",
)

# The engine reports the first pixel carrying the maximum temperature
# (numpy argmax over the masked crop); the legacy path reports the
# center of the whole max-temperature plateau. When several pixels
# share the maximum (common with float32 rounding on gradients) the
# two coordinates differ by a few pixels while the temperature value
# is identical. Tolerate that plateau artifact; larger deltas indicate
# a genuine region disagreement.
_HOTSPOT_TOLERANCE_PX = 16.0


class ROIEngineManager:
    """RuntimeROIManager-compatible facade over one ROIEngine.

    One instance wraps one engine (one per camera). Not thread-safe;
    callers must serialize access, as with the legacy manager.
    """

    def __init__(
        self,
        engine: ROIEngine,
        config_provider: Callable[[str], ROIConfiguration | None] | None = None,
        dual_validation: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        engine : ROIEngine
            Per-camera engine this manager drives.
        config_provider : Callable[[str], ROIConfiguration | None] | None
            Optional getter for the current configuration of a roi_id
            (e.g. the owning workspace's config dict). Used by
            mark_dirty() to detect configuration changes.
        dual_validation : bool
            When True, also run the legacy manager per frame and
            compare statistics (Settings.ROI_ENGINE_DUAL_VALIDATION).
        """
        self._engine = engine
        self._config_provider = config_provider
        self._dual_validation = dual_validation
        self._configs: dict[str, ROIConfiguration] = {}
        self._views: dict[str, RuntimeROI] = {}
        self._legacy: RuntimeROIManagerImpl | None = (
            RuntimeROIManagerImpl() if dual_validation else None
        )
        self._warned: dict[str, str] = {}

    # ==========================================================
    # Lifecycle
    # ==========================================================

    def load(self, configurations: Sequence[ROIConfiguration]) -> None:
        """Load configurations and build a fresh store snapshot."""
        self._configs = {c.roi_id: c for c in configurations}
        self._reload_store()

    def add_configuration(self, config: ROIConfiguration) -> None:
        """Add one ROI and reload the store snapshot."""
        if config.roi_id in self._configs:
            return
        self._configs[config.roi_id] = config
        self._reload_store()

    def unload(self) -> None:
        """Drop all configurations, views, and engine caches."""
        self._configs.clear()
        self._views.clear()
        self._warned.clear()
        if self._legacy is not None:
            self._legacy.unload()
        self._engine.clear()

    # ==========================================================
    # Accessors
    # ==========================================================

    def get_all(self) -> list[RuntimeROI]:
        """All ROI views (any state), in load order."""
        return list(self._views.values())

    def get_by_id(self, roi_id: str) -> RuntimeROI | None:
        """View for one roi_id, or None."""
        return self._views.get(roi_id)

    def get_active(self) -> list[RuntimeROI]:
        """Enabled, non-error views, ready for processing."""
        return [
            view
            for view in self._views.values()
            if view.configuration.enabled
            and view.state != RuntimeROIState.ERROR
        ]

    # ==========================================================
    # Cache management
    # ==========================================================

    def mark_dirty(self, roi_id: str | None = None) -> None:
        """Mark caches stale; reload the store when configs changed.

        With a config provider, a missing roi_id means the ROI was
        deleted and a replaced config object means it was edited: both
        require a new store snapshot (the store is immutable). An
        unchanged config only needs region/mask cache invalidation.
        """
        if roi_id is None:
            self._engine.invalidate()
            if self._legacy is not None:
                self._legacy.mark_dirty()
            return

        if self._config_provider is not None:
            current = self._config_provider(roi_id)
            if current is None and roi_id in self._configs:
                self._configs.pop(roi_id)
                self._reload_store()
                return
            if current is not None and self._configs.get(roi_id) is not current:
                self._configs[roi_id] = current
                self._reload_store()
                return

        self._engine.invalidate()
        if self._legacy is not None:
            self._legacy.mark_dirty(roi_id)

    def rebuild_dirty_regions(self, image_shape: tuple[int, int] = (0, 0)) -> None:
        """No-op: the engine rebuilds regions lazily on process_frame.

        Kept for API compatibility with the legacy manager.
        """

    # ==========================================================
    # State management
    # ==========================================================

    def update_state(self, roi_id: str, state: RuntimeROIState) -> None:
        """Update the runtime state of one ROI view."""
        view = self._views.get(roi_id)
        if view is not None:
            view.state = state

    # ==========================================================
    # Statistics
    # ==========================================================

    def refresh_statistics(
        self,
        roi_id: str,
        statistics: RuntimeROIStatistics,
    ) -> None:
        """Attach externally computed statistics to one ROI view."""
        view = self._views.get(roi_id)
        if view is not None:
            view.statistics = statistics

    # ==========================================================
    # Processing
    # ==========================================================

    def process_frame(
        self,
        temperature_image: np.ndarray,
        frame_id: int,
    ) -> list[RuntimeROIStatistics]:
        """Process all enabled ROIs on one temperature frame.

        Runs the engine, builds fresh RuntimeROIStatistics objects (one
        per enabled ROI, in ALL_SHAPES order), attaches them to the ROI
        views, and runs the optional legacy comparison.

        Returns
        -------
        list[RuntimeROIStatistics]
            Statistics for all enabled ROIs (valid=False entries for
            ROIs the engine could not measure).
        """
        self._engine.process_frame(temperature_image, frame_id)
        stats = self._build_statistics()
        self._attach_statistics(stats)

        if self._legacy is not None:
            legacy_stats = self._legacy.process_frame(temperature_image, frame_id)
            legacy_by_id: dict[str, RuntimeROIStatistics] = {}
            active = self._legacy.get_active()
            for roi, stat in zip(active, legacy_stats):
                legacy_by_id[roi.configuration.roi_id] = stat
            self._validate(legacy_by_id, stats)

        return list(stats.values())

    # ==========================================================
    # Internals
    # ==========================================================

    def _reload_store(self) -> None:
        """Push the config dict into a fresh store snapshot."""
        configs = list(self._configs.values())
        if configs:
            self._engine.load_position(configs)
        else:
            self._engine.clear()
        if self._legacy is not None:
            self._legacy.load(configs)
            self._legacy.rebuild_dirty_regions()
        self._rebuild_views()

    def _rebuild_views(self) -> None:
        """Sync view objects with the config dict."""
        for roi_id in [rid for rid in self._views if rid not in self._configs]:
            del self._views[roi_id]
        for roi_id, config in self._configs.items():
            view = self._views.get(roi_id)
            if view is None:
                self._views[roi_id] = RuntimeROI(
                    configuration=config,
                    state=(
                        RuntimeROIState.ACTIVE
                        if config.enabled
                        else RuntimeROIState.INACTIVE
                    ),
                    statistics=None,
                    created_at=datetime.now(),
                )
            else:
                view.configuration = config

    def _build_statistics(self) -> dict[str, RuntimeROIStatistics]:
        """Fresh statistics per enabled ROI, copied from engine arrays."""
        store = self._engine.store()
        if store is None:
            return {}
        result: dict[str, RuntimeROIStatistics] = {}
        for shape in ALL_SHAPES:
            type_store = store.store_for(shape)
            if type_store is None:
                continue
            runtime = type_store.runtime
            for idx in type_store.enabled_indices:
                result[type_store.roi_ids[idx]] = RuntimeROIStatistics(
                    valid=bool(runtime.valid[idx]),
                    minimum=float(runtime.minimum[idx]),
                    maximum=float(runtime.maximum[idx]),
                    mean=float(runtime.mean[idx]),
                    standard_deviation=float(runtime.standard_deviation[idx]),
                    hotspot_x=int(runtime.hotspot_col[idx]),
                    hotspot_y=int(runtime.hotspot_row[idx]),
                    pixel_count=int(runtime.pixel_count[idx]),
                    processing_time_ms=float(runtime.processing_time_ms[idx]),
                    frame_id=int(runtime.frame_id[idx]),
                    alarm_active=False,
                    alarm_since=None,
                    last_updated=datetime.now(),
                )
        return result

    def _attach_statistics(self, stats: dict[str, RuntimeROIStatistics]) -> None:
        """Attach the fresh per-frame statistics to the ROI views."""
        for roi_id, stat in stats.items():
            view = self._views.get(roi_id)
            if view is not None:
                view.statistics = stat

    def _validate(
        self,
        legacy_by_id: dict[str, RuntimeROIStatistics],
        engine_by_id: dict[str, RuntimeROIStatistics],
    ) -> None:
        """Compare engine and legacy results; warn once per mismatch.

        Each mismatching ROI logs at most one warning until it matches
        again; recovered ROIs log one debug line.
        """
        for roi_id in sorted(set(legacy_by_id) | set(engine_by_id)):
            legacy = legacy_by_id.get(roi_id)
            current = engine_by_id.get(roi_id)
            mismatch = _mismatch_kind(legacy, current)
            if mismatch is not None:
                if self._warned.get(roi_id) != mismatch:
                    logger.warning(
                        "ROI engine validation mismatch: roi=%s field=%s "
                        "legacy=%s engine=%s",
                        roi_id,
                        mismatch,
                        _fmt_stat(legacy),
                        _fmt_stat(current),
                    )
                    self._warned[roi_id] = mismatch
            elif roi_id in self._warned:
                logger.debug(
                    "ROI engine validation recovered: roi=%s", roi_id
                )
                del self._warned[roi_id]


def _mismatch_kind(
    legacy: RuntimeROIStatistics | None,
    current: RuntimeROIStatistics | None,
) -> str | None:
    """First mismatching aspect of two statistics, or None when equal."""
    if legacy is None or current is None:
        return "missing"
    if legacy.valid != current.valid:
        return "valid"
    for field in _VALIDATION_FIELDS:
        if abs(getattr(legacy, field) - getattr(current, field)) > 1e-6:
            return field
    if (
        abs(legacy.hotspot_x - current.hotspot_x) > _HOTSPOT_TOLERANCE_PX
        or abs(legacy.hotspot_y - current.hotspot_y) > _HOTSPOT_TOLERANCE_PX
    ):
        return "hotspot"
    return None


def _fmt_stat(stat: RuntimeROIStatistics | None) -> str:
    """Compact statistics summary for log messages."""
    if stat is None:
        return "None"
    return (
        f"valid={stat.valid} min={stat.minimum:.6g} max={stat.maximum:.6g} "
        f"mean={stat.mean:.6g} std={stat.standard_deviation:.6g} "
        f"px={stat.pixel_count} hotspot=({stat.hotspot_x},{stat.hotspot_y})"
    )
