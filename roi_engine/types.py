"""
types.py

Shared types for the roi_engine package (production batched ROI engine).

Re-exports ROIShape from the legacy roi package (no GUI/HALCON runtime
dependency) and defines the bounding-box convention used by the engine.
"""

from __future__ import annotations

from roi.types import ROIShape  # noqa: F401  (re-export)

# Axis-aligned bounding box: (row_min, col_min, row_max, col_max), inclusive.
# Rows/cols are image pixel coordinates. This matches the HALCON row/col
# convention; pixel (row, col) maps to display (x=col, y=row).
BBox = tuple[int, int, int, int]

# Canonical processing order for per-type batch stages.
ALL_SHAPES: tuple[ROIShape, ...] = (
    ROIShape.RECTANGLE1,
    ROIShape.RECTANGLE2,
    ROIShape.CIRCLE,
    ROIShape.ELLIPSE,
    ROIShape.POLYGON,
)
