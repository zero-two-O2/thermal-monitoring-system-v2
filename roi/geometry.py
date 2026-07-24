"""
geometry.py

ROI geometry data classes for the Thermal Monitoring System.

Each class stores ONLY numeric geometry values.
No HALCON handles, no GUI code, no processing logic.

Geometry storage follows Decision 6 of ROI_Design_Decisions.md:
    "Geometry is Stored as Plain Data"

Every geometry type knows how to validate itself via validate()
and can report its axis-aligned bounding box via bounding_box().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from roi.types import ROIShape

# Re-expose BoundingBox as a named structure.
BoundingBox = tuple[float, float, float, float]
"""
(row_min, col_min, row_max, col_max)

Axis-aligned bounding box in image coordinates.
"""


class ROIGeometry(ABC):
    """
    Base class for all ROI geometry types.

    All geometry subclasses are frozen dataclasses containing
    only numeric fields. They are immutable and hashable.

    Every subclass must implement:
        shape        — The ROIShape enum value.
        validate()   — Raise ValueError if geometry is invalid.
        bounding_box() — Return the axis-aligned bounding box.

    Responsibilities
    ----------------
    - Provide a common type for geometry dispatch.
    - Provide self-validation so invalid geometry never enters the system.
    - Provide bounding box for display framing and region generation.

    Must never:
    - Contain HALCON handles or references.
    - Contain processing logic beyond self-validation.
    - Contain GUI code.
    - Reference Drawing Objects.
    - Store runtime state or statistics.
    """

    @property
    @abstractmethod
    def shape(self) -> ROIShape:
        """The shape type of this geometry."""
        ...

    @abstractmethod
    def validate(self) -> None:
        """
        Validate geometry parameters.

        Raises
        ------
        ValueError
            If any parameter violates geometric constraints
            (e.g. negative radius, reversed corners).
        """
        ...

    @abstractmethod
    def bounding_box(self) -> BoundingBox:
        """
        Compute the axis-aligned bounding box.

        Returns
        -------
        BoundingBox
            (row_min, col_min, row_max, col_max)
            in image pixel coordinates.
        """
        ...


@dataclass(frozen=True, slots=True)
class Rectangle1ROI(ROIGeometry):
    """
    Axis-aligned rectangle ROI.

    Defined by two corner points.
    Maps to HALCON gen_rectangle1.

    Parameters
    ----------
    row1 : float
        Row of the top-left corner.
    col1 : float
        Column of the top-left corner.
    row2 : float
        Row of the bottom-right corner.
    col2 : float
        Column of the bottom-right corner.

    Validation
    ----------
    - row1 must be <= row2.
    - col1 must be <= col2.
    """

    row1: float
    col1: float
    row2: float
    col2: float

    @property
    def shape(self) -> ROIShape:
        return ROIShape.RECTANGLE1

    def validate(self) -> None:
        if self.row1 > self.row2:
            raise ValueError(f"Rectangle1ROI: row1 ({self.row1}) > row2 ({self.row2})")
        if self.col1 > self.col2:
            raise ValueError(f"Rectangle1ROI: col1 ({self.col1}) > col2 ({self.col2})")

    def bounding_box(self) -> BoundingBox:
        return (self.row1, self.col1, self.row2, self.col2)


@dataclass(frozen=True, slots=True)
class Rectangle2ROI(ROIGeometry):
    """
    Rotated rectangle ROI.

    Defined by center, orientation, and half-dimensions.
    Maps to HALCON gen_rectangle2.

    Parameters
    ----------
    row : float
        Center row coordinate.
    col : float
        Center column coordinate.
    phi : float
        Orientation angle in radians.
    length1 : float
        Half-width (half of the longer side). Must be > 0.
    length2 : float
        Half-height (half of the shorter side). Must be > 0.

    Validation
    ----------
    - length1 must be > 0.
    - length2 must be > 0.

    Notes
    -----
    - phi is not validated for range; any angle is valid.
    - bounding_box is approximate (uses axis-aligned extents of
      the rotated rectangle).
    """

    row: float
    col: float
    phi: float
    length1: float
    length2: float

    @property
    def shape(self) -> ROIShape:
        return ROIShape.RECTANGLE2

    def validate(self) -> None:
        if self.length1 <= 0:
            raise ValueError(f"Rectangle2ROI: length1 ({self.length1}) must be > 0")
        if self.length2 <= 0:
            raise ValueError(f"Rectangle2ROI: length2 ({self.length2}) must be > 0")

    def bounding_box(self) -> BoundingBox:
        cos_p = abs(__import__("math").cos(self.phi))
        sin_p = abs(__import__("math").sin(self.phi))
        half_row = self.length1 * sin_p + self.length2 * cos_p
        half_col = self.length1 * cos_p + self.length2 * sin_p
        return (
            self.row - half_row,
            self.col - half_col,
            self.row + half_row,
            self.col + half_col,
        )


@dataclass(frozen=True, slots=True)
class CircleROI(ROIGeometry):
    """
    Circular ROI.

    Defined by center and radius.
    Maps to HALCON gen_circle.

    Parameters
    ----------
    row : float
        Center row coordinate.
    col : float
        Center column coordinate.
    radius : float
        Radius in pixels. Must be > 0.

    Validation
    ----------
    - radius must be > 0.
    """

    row: float
    col: float
    radius: float

    @property
    def shape(self) -> ROIShape:
        return ROIShape.CIRCLE

    def validate(self) -> None:
        if self.radius <= 0:
            raise ValueError(f"CircleROI: radius ({self.radius}) must be > 0")

    def bounding_box(self) -> BoundingBox:
        return (
            self.row - self.radius,
            self.col - self.radius,
            self.row + self.radius,
            self.col + self.radius,
        )


@dataclass(frozen=True, slots=True)
class EllipseROI(ROIGeometry):
    """
    Elliptical ROI.

    Defined by center, orientation, and two radii.
    Maps to HALCON gen_ellipse.

    Parameters
    ----------
    row : float
        Center row coordinate.
    col : float
        Center column coordinate.
    phi : float
        Orientation angle in radians.
    radius1 : float
        First radius (semi-major axis half-length). Must be > 0.
    radius2 : float
        Second radius (semi-minor axis half-length). Must be > 0.

    Validation
    ----------
    - radius1 must be > 0.
    - radius2 must be > 0.

    Notes
    -----
    - bounding_box is approximate (uses axis-aligned extents of
      the rotated ellipse).
    """

    row: float
    col: float
    phi: float
    radius1: float
    radius2: float

    @property
    def shape(self) -> ROIShape:
        return ROIShape.ELLIPSE

    def validate(self) -> None:
        if self.radius1 <= 0:
            raise ValueError(f"EllipseROI: radius1 ({self.radius1}) must be > 0")
        if self.radius2 <= 0:
            raise ValueError(f"EllipseROI: radius2 ({self.radius2}) must be > 0")

    def bounding_box(self) -> BoundingBox:
        cos_p = abs(__import__("math").cos(self.phi))
        sin_p = abs(__import__("math").sin(self.phi))
        half_row = self.radius1 * sin_p + self.radius2 * cos_p
        half_col = self.radius1 * cos_p + self.radius2 * sin_p
        return (
            self.row - half_row,
            self.col - half_col,
            self.row + half_row,
            self.col + half_col,
        )


@dataclass(frozen=True, slots=True)
class PolygonROI(ROIGeometry):
    """
    Polygon ROI.

    Defined by an ordered tuple of (row, col) vertices.
    Maps to HALCON gen_region_polygon.

    Parameters
    ----------
    points : tuple[tuple[float, float], ...]
        Ordered vertices as (row, col) pairs.
        At least 3 vertices are required.

    Validation
    ----------
    - At least 3 points.
    - All points are finite numbers.

    Notes
    -----
    - Using a tuple of pairs prevents row/col length mismatches.
    - Iteration is simpler: for (r, c) in roi.points.
    - Serialization is cleaner: JSON array of [row, col] arrays.
    """

    points: tuple[tuple[float, float], ...]

    @property
    def shape(self) -> ROIShape:
        return ROIShape.POLYGON

    def validate(self) -> None:
        if len(self.points) < 3:
            raise ValueError(f"PolygonROI: {len(self.points)} points, need at least 3")
        for i, (r, c) in enumerate(self.points):
            import math

            if not math.isfinite(r) or not math.isfinite(c):
                raise ValueError(
                    f"PolygonROI: point {i} has non-finite coordinates ({r}, {c})"
                )

    def bounding_box(self) -> BoundingBox:
        row_min = min(r for r, _ in self.points)
        row_max = max(r for r, _ in self.points)
        col_min = min(c for _, c in self.points)
        col_max = max(c for _, c in self.points)
        return (row_min, col_min, row_max, col_max)

    @property
    def rows(self) -> tuple[float, ...]:
        """Row coordinates of all vertices."""
        return tuple(r for r, _ in self.points)

    @property
    def cols(self) -> tuple[float, ...]:
        """Column coordinates of all vertices."""
        return tuple(c for _, c in self.points)
