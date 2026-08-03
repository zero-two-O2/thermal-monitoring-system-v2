"""
store/rectangle2_store.py

Rotated rectangle type store (parallel geometry arrays).

Geometry arrays follow the canonical field names consumed by the
engine caches (see masks.type_geometry): rows, cols, phis,
length1s, length2s.
"""

from __future__ import annotations

import numpy as np

from roi_engine.store.base import TypeStoreBase


class Rectangle2Store(TypeStoreBase):
    """Type store for ROIShape.RECTANGLE2 (row, col, phi, length1, length2)."""

    def __init__(
        self,
        rows: np.ndarray,
        cols: np.ndarray,
        phis: np.ndarray,
        length1s: np.ndarray,
        length2s: np.ndarray,
        **base,
    ) -> None:
        super().__init__(**base)
        self.rows = rows
        self.cols = cols
        self.phis = phis
        self.length1s = length1s
        self.length2s = length2s
