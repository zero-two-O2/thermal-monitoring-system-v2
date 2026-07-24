"""
types.py

ROI shape types for the Thermal Monitoring System.

Defines:
    ROIShape: Enumeration of supported geometric shapes.

This module contains ONLY type definitions.
No logic, no HALCON, no GUI code.
"""

from __future__ import annotations

from enum import Enum, auto


class ROIShape(Enum):
    """
    Describes the geometric shape of an ROI.

    Each value maps to a specific geometry class in geometry.py
    and a corresponding HALCON region generator.

    Values
    ------
    RECTANGLE1 : Axis-aligned rectangle (row1, col1, row2, col2).
    RECTANGLE2 : Rotated rectangle (row, col, phi, length1, length2).
    CIRCLE     : Circle (row, col, radius).
    ELLIPSE    : Ellipse (row, col, phi, radius1, radius2).
    POLYGON    : Arbitrary polygon (rows[], cols[]).

    Notes
    -----
    - RECTANGLE1 maps to HALCON gen_rectangle1.
    - RECTANGLE2 maps to HALCON gen_rectangle2.
    - CIRCLE maps to HALCON gen_circle.
    - ELLIPSE maps to HALCON gen_ellipse.
    - POLYGON maps to HALCON gen_region_polygon.
    """

    RECTANGLE1 = auto()
    RECTANGLE2 = auto()
    CIRCLE = auto()
    ELLIPSE = auto()
    POLYGON = auto()
