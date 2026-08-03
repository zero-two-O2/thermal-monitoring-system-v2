"""
store/rectangle1_store.py

Axis-aligned rectangle type store (parallel geometry arrays).

Geometry arrays follow the canonical field names consumed by the
engine caches (see masks.type_geometry): row1s, col1s, row2s, col2s.
"""

from __future__ import annotations

import numpy as np

from roi_engine.store.base import TypeStoreBase


class Rectangle1Store(TypeStoreBase):
    """Type store for ROIShape.RECTANGLE1 (row1, col1, row2, col2)."""

    def __init__(
        self,
        row1s: np.ndarray,
        col1s: np.ndarray,
        row2s: np.ndarray,
        col2s: np.ndarray,
        **base,
    ) -> None:
        super().__init__(**base)
        self.row1s = row1s
        self.col1s = col1s
        self.row2s = row2s
        self.col2s = col2s
