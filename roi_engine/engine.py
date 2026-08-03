"""
engine.py

Per-camera public facade of the production ROI engine.

The engine owns one immutable configuration snapshot (ROIStore) plus the
HALCON-derived caches (regions, masks) and the runtime statistics arrays.
One ROIEngine is created per camera and must be used from a single thread
(the camera acquisition thread).

Pipeline (never bypass stages):
    ROIConfiguration (legacy model)
        -> ROIStore (immutable type-array snapshot)
        -> RegionCache / MaskCache (HALCON-derived regions)
        -> StatisticsEngine (batch HALCON statistics)
        -> FrameStats (per-frame results)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import datetime

import halcon as ha
import numpy as np

from roi.configuration import ROIConfiguration
from roi.runtime import RuntimeROIStatistics
from roi_engine.masks import MaskCache
from roi_engine.region_cache import RegionCache
from roi_engine.runtime import FrameStats, TypeFrameStats
from roi_engine.statistics_engine import StatisticsEngine
from roi_engine.store import ROIStore, build_store
from roi_engine.types import ALL_SHAPES, ROIShape

logger = logging.getLogger(__name__)


class ROIEngine:
    """Per-camera production engine facade.

    NOT thread-safe: one engine must be used from one thread at a time
    (one acquisition thread per camera). Use ROIEnginePool to manage one
    engine per camera.
    """

    def __init__(self, camera_id: str) -> None:
        self._camera_id = camera_id
        self._store: ROIStore | None = None
        self._position_id: str | None = None
        self._regions = RegionCache()
        self._masks = MaskCache()
        self._statistics = StatisticsEngine()
        self._force_rebuild = False

    @property
    def camera_id(self) -> str:
        """Identifier of the camera this engine belongs to."""
        return self._camera_id

    def load_position(self, configurations: Sequence[ROIConfiguration]) -> None:
        """Swap in a fresh store snapshot for a position (generation + 1)."""
        generation = self._store.generation + 1 if self._store is not None else 1
        position_id = (
            configurations[0].acquisition_state.position_id
            if configurations
            else ""
        )
        self._store = build_store(
            camera_id=self._camera_id,
            position_id=position_id,
            configurations=configurations,
            generation=generation,
        )
        self._position_id = position_id
        self._regions.clear()
        self._masks.clear()
        self._force_rebuild = False

    def position_id(self) -> str | None:
        """Position id of the loaded store, or None if nothing is loaded."""
        return self._position_id

    def process_frame(
        self,
        temperature_image: np.ndarray | None,
        frame_id: int,
    ) -> FrameStats:
        """Process one thermal frame and produce per-ROI statistics.

        No store loaded, or a None/empty image, yields an empty FrameStats.
        Exceptions inside the HALCON/processing section are logged and
        converted into an empty FrameStats (industrial never-crash rule);
        clear programming errors still raise.
        """
        timestamp = time.time()
        store = self._store
        if (
            store is None
            or temperature_image is None
            or temperature_image.ndim < 2
            or 0 in temperature_image.shape
        ):
            return FrameStats(frame_id, timestamp, (), 0.0, 0, 0)

        image_shape = tuple(int(d) for d in temperature_image.shape[:2])
        try:
            if (
                self._force_rebuild
                or self._regions.needs_rebuild(store)
                or self._masks.needs_rebuild(store, image_shape)
            ):
                self._regions.rebuild(store)
                self._masks.rebuild(store, image_shape)
                self._force_rebuild = False

            start = time.perf_counter()
            himage = ha.himage_from_numpy_array(temperature_image)
            stats_by_type: dict[ROIShape, TypeFrameStats] = self._statistics.process(
                himage, store, self._regions, self._masks, frame_id, timestamp
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
        except Exception:
            logger.exception(
                "ROI engine processing failed: camera=%s position=%s frame_id=%d",
                self._camera_id,
                self._position_id,
                frame_id,
            )
            return FrameStats(
                frame_id, timestamp, (), 0.0, 0, store.enabled_roi_count()
            )

        per_type: list[TypeFrameStats] = []
        total_pixel_count = 0
        for shape in ALL_SHAPES:
            type_stats = stats_by_type.get(shape)
            if type_stats is None or type_stats.count == 0:
                continue
            per_type.append(type_stats)
            total_pixel_count += int(np.sum(type_stats.stats.pixel_count))

        return FrameStats(
            frame_id,
            timestamp,
            tuple(per_type),
            elapsed_ms,
            total_pixel_count,
            store.enabled_roi_count(),
        )

    def invalidate(self) -> None:
        """Force cache rebuild on the next process_frame.

        Used when the image shape changed or geometry was edited without
        loading a new store.
        """
        self._force_rebuild = True

    def get_runtime_statistics(self) -> list[RuntimeROIStatistics]:
        """Backward-compatible statistics view, one per enabled ROI.

        Ordered per type in ALL_SHAPES order, aligned with the enabled
        indices of each type store. hotspot_x/hotspot_y map from the
        engine's col/row hotspot convention.
        """
        store = self._store
        if store is None:
            return []
        result: list[RuntimeROIStatistics] = []
        last_updated = datetime.now()
        for shape in ALL_SHAPES:
            type_store = store.store_for(shape)
            if type_store is None:
                continue
            runtime = type_store.runtime
            for idx in type_store.enabled_indices:
                result.append(
                    RuntimeROIStatistics(
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
                        last_updated=last_updated,
                    )
                )
        return result

    def store(self) -> ROIStore | None:
        """Current immutable configuration snapshot, or None."""
        return self._store

    def memory_bytes(self) -> int:
        """Approximate memory footprint of store + region + mask caches."""
        total = self._masks.memory_bytes() + self._regions.memory_bytes()
        if self._store is not None:
            total += self._store.memory_bytes()
        return total

    def clear(self) -> None:
        """Drop the store and all HALCON caches.

        HALCON objects are released when their references are dropped.
        """
        self._store = None
        self._position_id = None
        self._regions.clear()
        self._masks.clear()
        self._force_rebuild = False


class ROIEnginePool:
    """Multi-camera registry: one independent ROIEngine per camera."""

    def __init__(self) -> None:
        self._engines: dict[str, ROIEngine] = {}

    def engine(self, camera_id: str) -> ROIEngine:
        """Get the engine for a camera, creating it on first use."""
        engine = self._engines.get(camera_id)
        if engine is None:
            engine = ROIEngine(camera_id)
            self._engines[camera_id] = engine
        return engine

    def get(self, camera_id: str) -> ROIEngine | None:
        """Return the engine for a camera, or None if not registered."""
        return self._engines.get(camera_id)

    def remove(self, camera_id: str) -> None:
        """Clear and drop the engine for a camera (no-op if unknown)."""
        engine = self._engines.pop(camera_id, None)
        if engine is not None:
            engine.clear()

    def camera_ids(self) -> list[str]:
        """Registered camera identifiers."""
        return list(self._engines)

    def clear(self) -> None:
        """Clear and drop all engines."""
        for engine in self._engines.values():
            engine.clear()
        self._engines.clear()
