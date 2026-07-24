"""
geometry_to_hregion.py

Dedicated conversion layer between ROI geometry and HALCON HRegion.

This module has exactly one responsibility:
    Convert ROIGeometry → HALCON HRegion

It keeps HALCON code isolated from the rest of the ROI subsystem,
following the project convention that HALCON calls belong in
dedicated modules.

The actual HALCON import is confined to the implementation functions.
No other module needs to import `halcon` directly for region generation.

Workflow
--------
    Rectangle2ROI(row, col, phi, l1, l2)
        ↓
    geometry_to_hregion(geometry)
        ↓
    halcon.gen_rectangle2(row, col, phi, l1, l2)
        ↓
    HRegion

Mapping
-------
    Rectangle1ROI  →  gen_rectangle1
    Rectangle2ROI  →  gen_rectangle2
    CircleROI      →  gen_circle
    EllipseROI     →  gen_ellipse
    PolygonROI     →  gen_region_polygon
"""

from __future__ import annotations

from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)


def geometry_to_hregion(geometry: ROIGeometry) -> object:
    """
    Convert an ROIGeometry to a HALCON HRegion.

    Parameters
    ----------
    geometry : ROIGeometry
        The geometry to convert. Must be one of the five
        concrete geometry types.

    Returns
    -------
    object
        A HALCON HRegion object. Typed as object to avoid
        a mandatory HALCON import at the call site.

    Raises
    ------
    ValueError
        If geometry validation fails before generation.
    TypeError
        If the geometry type is not supported.

    Notes
    -----
    - Implementation will use halcon.HRegion() or the
      corresponding gen_* operator.
    - Geometry is validated before generation.
    """
    geometry.validate()

    if isinstance(geometry, Rectangle1ROI):
        return _gen_rectangle1(geometry)
    if isinstance(geometry, Rectangle2ROI):
        return _gen_rectangle2(geometry)
    if isinstance(geometry, CircleROI):
        return _gen_circle(geometry)
    if isinstance(geometry, EllipseROI):
        return _gen_ellipse(geometry)
    if isinstance(geometry, PolygonROI):
        return _gen_polygon(geometry)

    raise TypeError(f"Unsupported geometry type: {type(geometry).__name__}")


def _gen_rectangle1(geometry: Rectangle1ROI) -> object:
    """Generate HRegion from axis-aligned rectangle."""
    # import halcon as ha
    # return ha.HRegion.gen_rectangle1(
    #     geometry.row1, geometry.col1,
    #     geometry.row2, geometry.col2
    # )
    raise NotImplementedError("HALCON not yet available")


def _gen_rectangle2(geometry: Rectangle2ROI) -> object:
    """Generate HRegion from rotated rectangle."""
    raise NotImplementedError("HALCON not yet available")


def _gen_circle(geometry: CircleROI) -> object:
    """Generate HRegion from circle."""
    raise NotImplementedError("HALCON not yet available")


def _gen_ellipse(geometry: EllipseROI) -> object:
    """Generate HRegion from ellipse."""
    raise NotImplementedError("HALCON not yet available")


def _gen_polygon(geometry: PolygonROI) -> object:
    """Generate HRegion from polygon."""
    raise NotImplementedError("HALCON not yet available")
