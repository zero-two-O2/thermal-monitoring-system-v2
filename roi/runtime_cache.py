"""
runtime_cache.py

Cached HALCON-derived data for one RuntimeROI.

This module exists to isolate HALCON-specific cached data
from the generic RuntimeROI model. It prevents HALCON types
from leaking into the ROI configuration layer.

Rule 3 of Phase 2:
    "RuntimeROICache owns every HALCON object"
    Store: HRegion, area, bounding_box, dirty flag, generation timestamp
    Never store HALCON objects anywhere else.

Memory ownership (Rule 10):
    clear() releases the HRegion reference so the HALCON
    garbage collector can reclaim it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RuntimeROICache:
    """
    Cached HALCON-derived data for one RuntimeROI.

    Created lazily by RuntimeROIManager when image dimensions
    are first known. Invalidated when geometry changes.

    Responsibilities
    ----------------
    - Hold the generated HALCON HRegion.
    - Hold derived properties (area, bounding_box).
    - Track whether the cache is still valid (dirty flag).
    - Track when the region was last generated.
    - Provide clear() for memory cleanup.

    Must never:
    - Reference ROIConfiguration or geometry.
    - Contain GUI or Drawing Object code.
    - Persist itself.
    - Process images or calculate statistics.

    Notes
    -----
    - The `region` field holds a HALCON HRegion object.
      Typed as `object` to avoid HALCON import in this module.
    - Call clear() before discarding to release HALCON resources.
    """

    region: object = None

    area: float = 0.0

    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    dirty: bool = True

    last_generation: datetime | None = None

    def clear(self) -> None:
        """
        Release the HALCON HRegion and reset all fields.

        Call this before discarding the cache to ensure
        no stale HALCON handles remain (Rule 10).

        After clear(), the cache returns to its initial state:
            region=None, area=0, dirty=True, generation=None.
        """
        self.region = None
        self.area = 0.0
        self.bounding_box = (0.0, 0.0, 0.0, 0.0)
        self.dirty = True
        self.last_generation = None