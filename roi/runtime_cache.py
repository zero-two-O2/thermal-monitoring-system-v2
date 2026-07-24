"""
runtime_cache.py

Cached HALCON-derived data for one RuntimeROI.

This module exists to isolate HALCON-specific cached data
from the generic RuntimeROI model. It prevents HALCON types
from leaking into the ROI configuration layer.

RuntimeROICache holds:
    - region (HRegion)
    - area
    - bounding_box
    - dirty flag
    - last_generation timestamp

Future cache fields (added without modifying RuntimeROI):
    - reduced_domain image
    - contour
    - mask (numpy)
    - transformed region
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

    Must never:
    - Reference ROIConfiguration or geometry.
    - Contain GUI or Drawing Object code.
    - Persist itself.
    - Process images or calculate statistics.

    Notes
    -----
    - The `region` field holds a HALCON HRegion object.
      At the Python level it is typed as `object` to avoid
      a direct HALCON import dependency in this module.
    - The actual HALCON import is confined to the conversion
      layer (geometry_to_hregion.py).
    """

    region: object = None

    area: float = 0.0

    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    dirty: bool = True

    last_generation: datetime | None = None
