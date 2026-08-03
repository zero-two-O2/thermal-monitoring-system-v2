"""
store/circle_store.py

Circle type store (parallel geometry arrays).

Geometry arrays follow the canonical field names consumed by the
engine caches (see masks.type_geometry): rows, cols, radii.
"""

from __future__ import annotations

import numpy as np

from roi_engine.store.base import TypeStoreBase


class CircleStore(TypeStoreBase):
    """Type store for ROIShape.CIRCLE (row, col, radius)."""

    def __init__(
        self,
        rows: np.ndarray,
        cols: np.ndarray,
        radii: np.ndarray,
        **base,
    ) -> None:
        super().__init__(**base)
        self.rows = rows
        self.cols = cols
        self.radii = radii
