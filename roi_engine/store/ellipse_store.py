"""
store/ellipse_store.py

Ellipse type store (parallel geometry arrays).

Geometry arrays follow the canonical field names consumed by the
engine caches (see masks.type_geometry): rows, cols, phis,
radius1s, radius2s.
"""

from __future__ import annotations

import numpy as np

from roi_engine.store.base import TypeStoreBase


class EllipseStore(TypeStoreBase):
    """Type store for ROIShape.ELLIPSE (row, col, phi, radius1, radius2)."""

    def __init__(
        self,
        rows: np.ndarray,
        cols: np.ndarray,
        phis: np.ndarray,
        radius1s: np.ndarray,
        radius2s: np.ndarray,
        **base,
    ) -> None:
        super().__init__(**base)
        self.rows = rows
        self.cols = cols
        self.phis = phis
        self.radius1s = radius1s
        self.radius2s = radius2s
