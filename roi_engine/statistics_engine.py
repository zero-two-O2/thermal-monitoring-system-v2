"""
statistics_engine.py

Pure batched HALCON statistics for the roi_engine package.

The engine processes one thermal frame for one position snapshot:

    HImage + ROIStore + RegionCache + MaskCache
        -> per-type batch HALCON operators (intensity, min_max_gray,
           area_center)
        -> numpy hotspot search per enabled ROI (masked argmax)
        -> writes into the store's RuntimeStatsArrays at enabled indices

HALCON values are AUTHORITATIVE for minimum/maximum/mean/standard
deviation/pixel count -- numpy is used ONLY for the hotspot position.

Coordinate convention: hotspot_row is the row index, hotspot_col the
column index (display x = col, y = row; the mapping is applied by
consumers, not here).

Zero GUI, zero Qt, zero window code. Exception safety: an operator error
invalidates the affected ROI type (valid=False) and processing continues
with the remaining types; errors never propagate to the caller.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import halcon as ha
import numpy as np

from roi_engine.masks import MaskCache, TypeStoreProtocol
from roi_engine.region_cache import RegionCache
from roi_engine.runtime import TypeFrameStats
from roi_engine.types import ALL_SHAPES, ROIShape

logger = logging.getLogger(__name__)


def _dilate8(mask: np.ndarray) -> np.ndarray:
    """8-connectivity dilation of a bool mask (no wrap-around)."""
    dilated = mask.copy()
    dilated[1:, :] |= mask[:-1, :]
    dilated[:-1, :] |= mask[1:, :]
    dilated[:, 1:] |= mask[:, :-1]
    dilated[:, :-1] |= mask[:, 1:]
    dilated[1:, 1:] |= mask[:-1, :-1]
    dilated[1:, :-1] |= mask[:-1, 1:]
    dilated[:-1, 1:] |= mask[1:, :-1]
    dilated[:-1, :-1] |= mask[1:, 1:]
    return dilated


class _StoreProtocol(Protocol):
    """Minimal ROIStore surface consumed by the statistics engine."""

    def store_for(self, shape: ROIShape) -> TypeStoreProtocol | None:
        """Return the type store for a shape, or None if empty."""


class StatisticsEngine:
    """Pure batch HALCON statistics, one process() call per frame."""

    def __init__(self) -> None:
        pass

    def process(
        self,
        himage: ha.HObject | None,
        store: _StoreProtocol,
        regions: RegionCache,
        masks: MaskCache,
        frame_id: int,
        timestamp: float,
    ) -> dict[ROIShape, TypeFrameStats]:
        """
        Compute statistics for all enabled ROIs of one frame.

        Returns one TypeFrameStats per non-empty ROI type (ALL_SHAPES
        order). A None or zero-size image yields an empty dict. The
        returned stats arrays are live views into the store's runtime
        arrays; they are overwritten by the next frame.
        """
        result: dict[ROIShape, TypeFrameStats] = {}
        if himage is None:
            return result
        try:
            image = ha.himage_as_numpy_array(himage)
        except Exception:
            logger.exception("Failed to convert HImage to numpy; frame skipped")
            return result
        if image.ndim < 2 or 0 in image.shape:
            return result

        for shape in ALL_SHAPES:
            type_store = store.store_for(shape)
            if type_store is None or type_store.enabled_indices.size == 0:
                continue
            regs = regions.regions(shape)
            if regs is None:
                continue
            enabled = type_store.enabled_indices
            self._process_type(
                shape, type_store, regs, himage, image, masks,
                enabled, frame_id, timestamp,
            )
            result[shape] = TypeFrameStats(shape, int(enabled.size), type_store.runtime)
        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _process_type(
        self,
        shape: ROIShape,
        type_store: TypeStoreProtocol,
        regs: ha.HObject,
        himage: ha.HObject,
        image: np.ndarray,
        masks: MaskCache,
        enabled: np.ndarray,
        frame_id: int,
        timestamp: float,
    ) -> None:
        """Run the batch operators for one type and write runtime arrays."""
        runtime = type_store.runtime
        start = time.perf_counter()
        try:
            mean_t, dev_t = ha.intensity(regs, himage)
            min_t, max_t, _range_t = ha.min_max_gray(regs, himage, 0)
            area_t, _row_t, _col_t = ha.area_center(regs)
            count = int(enabled.size)
            if not (
                len(mean_t) == len(dev_t) == len(min_t) == len(max_t)
                == len(area_t) == count
            ):
                raise RuntimeError(
                    f"HALCON tuple length mismatch for {shape}: expected {count}, "
                    f"got mean={len(mean_t)} dev={len(dev_t)} min={len(min_t)} "
                    f"max={len(max_t)} area={len(area_t)}"
                )

            runtime.minimum[enabled] = np.asarray(min_t, dtype=np.float64)
            runtime.maximum[enabled] = np.asarray(max_t, dtype=np.float64)
            runtime.mean[enabled] = np.asarray(mean_t, dtype=np.float64)
            runtime.standard_deviation[enabled] = np.asarray(dev_t, dtype=np.float64)
            runtime.pixel_count[enabled] = np.asarray(area_t, dtype=np.int64)
            runtime.valid[enabled] = True
            runtime.frame_id[enabled] = frame_id
            runtime.timestamp[enabled] = timestamp
            runtime.processing_time_ms[enabled] = (
                time.perf_counter() - start
            ) * 1000.0

            for idx in enabled:
                h_row, h_col = self._hotspot(
                    shape, type_store, masks, image, int(idx),
                    float(runtime.maximum[idx]),
                )
                runtime.hotspot_row[idx] = h_row
                runtime.hotspot_col[idx] = h_col
        except Exception:
            logger.exception(
                "StatisticsEngine failed for ROI type %s (%d enabled ROIs)",
                shape,
                enabled.size,
            )
            runtime.valid[enabled] = False

    def _hotspot(
        self,
        shape: ROIShape,
        type_store: TypeStoreProtocol,
        masks: MaskCache,
        image: np.ndarray,
        index: int,
        maximum: float,
    ) -> tuple[int, int]:
        """
        Find the hottest pixel of one ROI; (-1, -1) when unavailable.

        The mask approximates the HALCON region: it may include a few
        boundary pixels the region excludes and may drop a few region
        pixels it includes. It is dilated by one pixel (8-connectivity)
        so the true region pixels are always candidates, and any pixel
        hotter than the HALCON maximum is discarded before the argmax;
        the pixel carrying the maximum is among the candidates, so the
        found pixel's value always equals it.
        """
        height = int(image.shape[0])
        width = int(image.shape[1])
        bbox = type_store.bboxes[index]
        r0 = max(int(bbox[0]), 0)
        c0 = max(int(bbox[1]), 0)
        r1 = min(int(bbox[2]), height - 1)
        c1 = min(int(bbox[3]), width - 1)
        if r0 > r1 or c0 > c1:
            return -1, -1

        crop = image[r0 : r1 + 1, c0 : c1 + 1]
        mask, _m_r0, _m_c0 = masks.mask(shape, index)
        if shape is ROIShape.RECTANGLE1:
            values = crop
        else:
            if mask is None or mask.size == 0 or mask.shape != crop.shape:
                return -1, -1
            mask = _dilate8(mask)
            values = np.where(mask, crop, np.nan)
        if np.isfinite(maximum):
            values = np.where(values <= maximum, values, np.nan)

        if np.all(np.isnan(values)):
            return -1, -1
        local_row, local_col = np.unravel_index(
            np.nanargmax(values), values.shape
        )
        return int(local_row) + r0, int(local_col) + c0
