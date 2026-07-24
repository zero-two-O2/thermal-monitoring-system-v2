"""
runtime_manager.py

Concrete implementation of RuntimeROIManager.

This class manages the lifecycle of RuntimeROI instances for one
camera acquisition state. It bridges between ROIConfiguration
(persistent definitions) and the processing pipeline (which
consumes cached regions and statistics).

Responsibilities (Rule 9)
-------------------------
- Load configurations into runtime cache (1:1, Rule 8).
- Build cached HRegions via geometry_to_hregion (Rule 2).
- Rebuild dirty regions only when geometry changes (Rule 4).
- Release HALCON resources on unload (Rule 10).
- Expose active ROIs for the processing pipeline (Rule 7).
- Store computed statistics on RuntimeROI instances (Rule 6).

Thread safety (Rule 11)
-----------------------
- One RuntimeROIManagerImpl per camera.
- No shared mutable state between cameras.
- External synchronization required if multiple threads
  access the same manager instance.
"""

from __future__ import annotations

from datetime import datetime

import halcon as ha
import numpy as np

from roi.configuration import ROIConfiguration
from roi.geometry_to_hregion import geometry_to_hregion
from roi.interfaces import RuntimeROIManager
from roi.runtime import RuntimeROI, RuntimeROIState, RuntimeROIStatistics
from roi.runtime_cache import RuntimeROICache
from roi.statistics import extract_statistics


class RuntimeROIManagerImpl(RuntimeROIManager):
    """
    Concrete implementation of RuntimeROIManager.

    Manages one set of RuntimeROI instances for one camera
    acquisition state. Created when a camera loads a position,
    destroyed when the position changes.

    Usage
    -----
        manager = RuntimeROIManagerImpl()
        manager.load(configurations)
        manager.rebuild_dirty_regions(image_shape)

        while processing:
            for roi in manager.get_active():
                stats = extract_statistics(roi.cache.region, temp_image, frame_id)
                manager.refresh_statistics(roi.configuration.roi_id, stats)
    """

    def __init__(self) -> None:
        self._rois: dict[str, RuntimeROI] = {}

    # ==========================================================
    # Lifecycle
    # ==========================================================

    def load(
        self,
        configurations: list[ROIConfiguration],
    ) -> None:
        """
        Load configurations into the runtime cache (Rule 8).

        Creates one RuntimeROI per configuration. All start as
        INACTIVE with dirty=True. HRegions are built lazily by
        rebuild_dirty_regions().
        """
        self.unload()
        for cfg in configurations:
            roi = RuntimeROI(
                configuration=cfg,
                state=RuntimeROIState.INACTIVE,
                cache=RuntimeROICache(dirty=True),
                created_at=datetime.now(),
            )
            self._rois[cfg.roi_id] = roi

    def add_configuration(self, config: ROIConfiguration) -> None:
        if config.roi_id in self._rois:
            return
        roi = RuntimeROI(
            configuration=config,
            state=RuntimeROIState.INACTIVE,
            cache=RuntimeROICache(dirty=True),
            created_at=datetime.now(),
        )
        self._rois[config.roi_id] = roi

    def unload(
        self,
    ) -> None:
        """
        Clear all RuntimeROI instances and release HALCON resources (Rule 10).

        Each cache's clear() drops the HRegion reference so HALCON
        can reclaim the memory.
        """
        for roi in self._rois.values():
            roi.cache.clear()
        self._rois.clear()

    # ==========================================================
    # Accessors
    # ==========================================================

    def get_all(
        self,
    ) -> list[RuntimeROI]:
        return list(self._rois.values())

    def get_by_id(
        self,
        roi_id: str,
    ) -> RuntimeROI | None:
        return self._rois.get(roi_id)

    def get_active(
        self,
    ) -> list[RuntimeROI]:
        """
        Enabled, non-error ROIs ready for processing (Rule 7).

        Filters out:
        - Disabled ROIs (configuration.enabled == False).
        - ROIs in ERROR state (failed generation or processing).
        """
        return [
            roi
            for roi in self._rois.values()
            if roi.configuration.enabled and roi.state != RuntimeROIState.ERROR
        ]

    # ==========================================================
    # Cache management
    # ==========================================================

    def mark_dirty(
        self,
        roi_id: str | None = None,
    ) -> None:
        """
        Mark cached HRegions as dirty (Rule 4).

        Dirty regions are rebuilt on the next call to
        rebuild_dirty_regions().
        """
        if roi_id is not None:
            roi = self._rois.get(roi_id)
            if roi is not None:
                roi.cache.dirty = True
        else:
            for roi in self._rois.values():
                roi.cache.dirty = True

    def rebuild_dirty_regions(
        self,
        image_shape: tuple[int, int] = (0, 0),
    ) -> None:
        """
        Rebuild all dirty HRegions from geometry (Rule 4).

        For each dirty, enabled ROI:
            1. Convert geometry to HRegion via geometry_to_hregion().
            2. Compute area and bounding box from the region.
            3. Store in RuntimeROICache.
            4. Set state to ACTIVE.

        Failed conversions set state to ERROR (Rule 7).
        Disabled ROIs keep their current state.
        """
        for roi in self._rois.values():
            if not roi.cache.dirty:
                continue
            if not roi.configuration.enabled:
                continue

            try:
                region = geometry_to_hregion(roi.configuration.geometry)
                _populate_cache(roi.cache, region)
                roi.state = RuntimeROIState.ACTIVE
            except Exception:
                roi.cache.region = None
                roi.cache.dirty = True
                roi.state = RuntimeROIState.ERROR

    # ==========================================================
    # State management
    # ==========================================================

    def update_state(
        self,
        roi_id: str,
        state: RuntimeROIState,
    ) -> None:
        roi = self._rois.get(roi_id)
        if roi is not None:
            roi.state = state

    # ==========================================================
    # Statistics
    # ==========================================================

    def refresh_statistics(
        self,
        roi_id: str,
        statistics: RuntimeROIStatistics,
    ) -> None:
        """
        Store computed statistics on a RuntimeROI (Rule 6).

        Called by the processing pipeline after temperature
        statistics extraction. Does NOT compute statistics.
        """
        roi = self._rois.get(roi_id)
        if roi is not None:
            roi.statistics = statistics
            roi.last_updated = statistics.last_updated

    # ==========================================================
    # Processing convenience
    # ==========================================================

    def process_frame(
        self,
        temperature_image: np.ndarray,
        frame_id: int,
    ) -> list[RuntimeROIStatistics]:
        """
        Process all active ROIs on one temperature frame (Rule 5).

        For each ACTIVE ROI:
            1. Ensure region cache is valid (rebuild if dirty).
            2. Extract temperature statistics via HALCON.
            3. Store statistics on the RuntimeROI.

        This is a convenience method that combines rebuild,
        extraction, and storage into one call for the pipeline.

        Parameters
        ----------
        temperature_image : np.ndarray
            Float temperature array from calibration processor.
        frame_id : int
            Current frame identifier.

        Returns
        -------
        list[RuntimeROIStatistics]
            Statistics for all processed ROIs (may include
            valid=False entries for failed ROIs).
        """
        self.rebuild_dirty_regions(temperature_image.shape)

        results: list[RuntimeROIStatistics] = []
        for roi in self.get_active():
            cache = roi.cache
            if cache.region is None:
                roi.state = RuntimeROIState.ERROR
                continue

            stats = extract_statistics(
                cache.region,
                temperature_image,
                frame_id,
            )
            self.refresh_statistics(roi.configuration.roi_id, stats)
            results.append(stats)

        return results


def _populate_cache(cache: RuntimeROICache, region: ha.HObject) -> None:
    _area = ha.area_center(region)
    _bb = ha.smallest_rectangle1(region)

    cache.region = region
    cache.area = _area[0][0]
    cache.bounding_box = (_bb[0][0], _bb[1][0], _bb[2][0], _bb[3][0])
    cache.dirty = False
    cache.last_generation = datetime.now()