"""
region_cache.py

Per-type cached HALCON region tuples for the roi_engine package.

Region tuples are aligned with each type store's enabled_indices order:
    regions(shape)[k]  <->  enabled ROIs of that type, in enabled order.

Batch generation (empirically verified on HALCON 24.11):
    - RECTANGLE1 / RECTANGLE2 / CIRCLE / ELLIPSE are generated with one
      batched operator call per type using enabled-only slices
      (~4 ms per 500 regions).
    - POLYGON regions are generated per polygon with
      gen_region_polygon_filled (the same operator the legacy
      geometry_to_hregion uses, so batch and legacy regions are
      pixel-identical) and combined with functools.reduce(concat_obj, ...).
      Verified: a Python list of HObjects is NOT accepted by batch
      operators, and concat_obj takes exactly two objects; the reduce
      chain preserves input order (area_center of the concatenated tuple
      equals the per-region areas in order).

The clip_region=false guard MUST run before any region generation: regions
are built before any image exists (during load_state) and with the default
clip_region=true most regions come out silently empty.
"""

from __future__ import annotations

import functools
import logging

import halcon as ha
import numpy as np

from roi_engine.masks import ROIStoreProtocol, type_geometry
from roi_engine.types import ALL_SHAPES, ROIShape

logger = logging.getLogger(__name__)

_clip_region_configured = False


def _configure_clip_region() -> None:
    """Disable HALCON region clipping (guard pattern, see geometry_to_hregion).

    HALCON clips regions to the last-read image dimensions by default,
    which silently produces empty regions when no image has been read.
    The call is deferred and never breaks module import; on failure the
    warning is logged and the next rebuild retries.
    """
    global _clip_region_configured
    if _clip_region_configured:
        return
    try:
        ha.set_system("clip_region", "false")
        _clip_region_configured = True
    except Exception:
        logger.warning(
            "Failed to set HALCON clip_region=false; will retry on next rebuild.",
            exc_info=True,
        )


def _float_list(values: object) -> list[float]:
    """Convert a numpy array / sequence to a Python list of floats."""
    return [float(v) for v in values]


class RegionCache:
    """Cached per-type HALCON region tuples, aligned with enabled indices."""

    def __init__(self) -> None:
        self._regions: dict[ROIShape, ha.HObject] = {}
        self._counts: dict[ROIShape, int] = {}
        self._pixel_counts: dict[ROIShape, int] = {}
        self._generation: int | None = None

    def rebuild(self, store: ROIStoreProtocol) -> None:
        """(Re)generate HALCON regions for every non-empty enabled type."""
        _configure_clip_region()
        self._regions.clear()
        self._counts.clear()
        self._pixel_counts.clear()
        for shape in ALL_SHAPES:
            type_store = store.store_for(shape)
            if type_store is None:
                continue
            enabled = np.asarray(type_store.enabled_indices, dtype=np.int64)
            if enabled.size == 0:
                continue
            geometry = type_geometry(type_store)
            regions = self._generate(shape, geometry, enabled)
            area = ha.area_center(regions)[0]
            self._regions[shape] = regions
            self._counts[shape] = int(enabled.size)
            self._pixel_counts[shape] = int(sum(area))
        self._generation = store.generation

    def needs_rebuild(self, store: ROIStoreProtocol) -> bool:
        """True when the store generation changed or the cache is empty."""
        return (
            not self._regions or self._generation != store.generation
        )

    def regions(self, shape: ROIShape) -> ha.HObject | None:
        """Region tuple for a shape, or None when nothing is enabled."""
        return self._regions.get(shape)

    def region_count(self, shape: ROIShape) -> int:
        """Number of enabled regions cached for a shape."""
        return self._counts.get(shape, 0)

    def memory_bytes(self) -> int:
        """Approximate memory footprint: sum of cached region pixel counts."""
        return sum(self._pixel_counts.values())

    def clear(self) -> None:
        """Drop all cached regions and forget the rebuild baseline."""
        self._regions.clear()
        self._counts.clear()
        self._pixel_counts.clear()
        self._generation = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _generate(
        self,
        shape: ROIShape,
        geometry: dict[str, object],
        enabled: np.ndarray,
    ) -> ha.HObject:
        """Batch-generate one aligned region tuple for an enabled subset."""
        if shape is ROIShape.POLYGON:
            per_polygon = [
                ha.gen_region_polygon_filled(
                    _float_list(geometry["rows"][i]),
                    _float_list(geometry["cols"][i]),
                )
                for i in enabled
            ]
            return functools.reduce(ha.concat_obj, per_polygon)
        if shape is ROIShape.RECTANGLE1:
            return ha.gen_rectangle1(
                _float_list(geometry["row1s"][enabled]),
                _float_list(geometry["col1s"][enabled]),
                _float_list(geometry["row2s"][enabled]),
                _float_list(geometry["col2s"][enabled]),
            )
        rows = _float_list(geometry["rows"][enabled])
        cols = _float_list(geometry["cols"][enabled])
        if shape is ROIShape.CIRCLE:
            return ha.gen_circle(
                rows, cols, _float_list(geometry["radii"][enabled])
            )
        if shape is ROIShape.RECTANGLE2:
            return ha.gen_rectangle2(
                rows,
                cols,
                _float_list(geometry["phis"][enabled]),
                _float_list(geometry["length1s"][enabled]),
                _float_list(geometry["length2s"][enabled]),
            )
        if shape is ROIShape.ELLIPSE:
            return ha.gen_ellipse(
                rows,
                cols,
                _float_list(geometry["phis"][enabled]),
                _float_list(geometry["radius1s"][enabled]),
                _float_list(geometry["radius2s"][enabled]),
            )
        raise ValueError(f"Unsupported ROI shape: {shape}")
