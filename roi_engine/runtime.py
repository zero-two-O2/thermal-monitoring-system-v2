"""
runtime.py

Runtime statistics arrays for the roi_engine package.

The engine writes results into parallel numpy arrays that are reused
every frame (zero per-frame allocation in the hot path). These arrays
are the runtime layer of the type-array architecture:

    Configuration (immutable snapshot)  ->  RuntimeStatsArrays (mutated)

No HALCON handles, no GUI code, no processing logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from roi_engine.types import ROIShape


@dataclass(slots=True)
class RuntimeStatsArrays:
    """
    Parallel runtime arrays for one type store.

    One entry per ROI in the store (index-aligned with the store arrays).
    Entries for disabled ROIs are left at defaults (valid=False).
    Reused across frames: the engine overwrites values, never reallocates.
    """

    minimum: np.ndarray
    maximum: np.ndarray
    mean: np.ndarray
    standard_deviation: np.ndarray
    pixel_count: np.ndarray
    hotspot_row: np.ndarray
    hotspot_col: np.ndarray
    valid: np.ndarray
    frame_id: np.ndarray
    timestamp: np.ndarray
    processing_time_ms: np.ndarray

    @classmethod
    def empty(cls, size: int) -> "RuntimeStatsArrays":
        """Create default-valued arrays of the given length."""
        return cls(
            minimum=np.full(size, np.nan, dtype=np.float64),
            maximum=np.full(size, np.nan, dtype=np.float64),
            mean=np.full(size, np.nan, dtype=np.float64),
            standard_deviation=np.full(size, np.nan, dtype=np.float64),
            pixel_count=np.zeros(size, dtype=np.int64),
            hotspot_row=np.full(size, -1, dtype=np.int64),
            hotspot_col=np.full(size, -1, dtype=np.int64),
            valid=np.zeros(size, dtype=bool),
            frame_id=np.full(size, -1, dtype=np.int64),
            timestamp=np.zeros(size, dtype=np.float64),
            processing_time_ms=np.zeros(size, dtype=np.float64),
        )

    def memory_bytes(self) -> int:
        """Total bytes held by all arrays."""
        return sum(a.nbytes for a in (
            self.minimum, self.maximum, self.mean, self.standard_deviation,
            self.pixel_count, self.hotspot_row, self.hotspot_col, self.valid,
            self.frame_id, self.timestamp, self.processing_time_ms,
        ))


@dataclass(frozen=True, slots=True)
class TypeFrameStats:
    """Statistics view for one ROI type after processing a frame."""

    shape: ROIShape
    count: int
    stats: RuntimeStatsArrays


@dataclass(frozen=True, slots=True)
class FrameStats:
    """
    Result of one process_frame call.

    `per_type` contains one entry per non-empty ROI type of the current
    position. `stats` arrays are live views into the engine's runtime
    arrays: they are overwritten by the next frame. Consumers that need
    to keep values must copy them.
    """

    frame_id: int
    timestamp: float
    per_type: tuple[TypeFrameStats, ...]
    processing_time_ms: float
    total_pixel_count: int
    enabled_roi_count: int
