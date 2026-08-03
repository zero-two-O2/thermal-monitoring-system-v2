"""
store/polygon_store.py

Polygon type store (per-ROI vertex containers).

Geometry containers follow the canonical field names consumed by the
engine caches (see masks.type_geometry): rows and cols are per-ROI
vertex containers (list of float arrays), indexed by store index.
"""

from __future__ import annotations

import numpy as np

from roi_engine.store.base import TypeStoreBase


class PolygonStore(TypeStoreBase):
    """Type store for ROIShape.POLYGON (ordered (row, col) vertices)."""

    def __init__(
        self,
        rows: list[np.ndarray],
        cols: list[np.ndarray],
        **base,
    ) -> None:
        super().__init__(**base)
        self.rows = rows
        self.cols = cols
