"""
geometry_to_hregion.py

Dedicated conversion layer between ROI geometry and HALCON HRegion.

This module has exactly one responsibility:
    Convert ROIGeometry → HALCON HRegion

It keeps HALCON code isolated from the rest of the ROI subsystem.
No other module should call HALCON region constructors directly.

Rule 2 of Phase 2:
    "geometry_to_hregion is the only conversion layer"

Mapping
-------
    Rectangle1ROI  →  gen_rectangle1
    Rectangle2ROI  →  gen_rectangle2
    CircleROI      →  gen_circle
    EllipseROI     →  gen_ellipse
    PolygonROI     →  gen_region_polygon

Error handling
--------------
    - Geometry is validated before generation.
    - If HALCON is unavailable, NotImplementedError is raised.
    - If generation fails, the exception propagates to the caller
      (RuntimeROIManager catches it and sets ERROR state).
"""

from __future__ import annotations

import logging

import halcon as ha

from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)

_logger = logging.getLogger(__name__)

_clip_region_configured = False


def _configure_clip_region() -> None:
    """Disable region clipping so standalone region generation works.

    HALCON clips regions to the last-read image dimensions by default,
    which silently produces empty regions when no image has been read.

    The HALCON call is deferred and never allowed to break module import:
    if it fails (transient license/environment issue), the failure is logged
    and retried on the next conversion.
    """
    global _clip_region_configured
    if _clip_region_configured:
        return
    try:
        ha.set_system("clip_region", "false")
        _clip_region_configured = True
    except Exception:
        _logger.warning(
            "Failed to set HALCON clip_region=false; will retry on next conversion.",
            exc_info=True,
        )


def geometry_to_hregion(geometry: ROIGeometry) -> ha.HObject:
    """
    Convert an ROIGeometry to a HALCON HRegion.

    Parameters
    ----------
    geometry : ROIGeometry
        The geometry to convert. Must be one of the five
        concrete geometry types.

    Returns
    -------
    ha.HRegion
        A HALCON HRegion object matching the geometry.

    Raises
    ------
    ValueError
        If geometry validation fails before generation.
    TypeError
        If the geometry type is not supported.
    """
    _configure_clip_region()
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


def _gen_rectangle1(geometry: Rectangle1ROI) -> ha.HObject:
    """Generate HRegion from axis-aligned rectangle."""
    return ha.gen_rectangle1(
        _round(geometry.row1),
        _round(geometry.col1),
        _round(geometry.row2),
        _round(geometry.col2),
    )


def _gen_rectangle2(geometry: Rectangle2ROI) -> ha.HObject:
    """Generate HRegion from rotated rectangle."""
    return ha.gen_rectangle2(
        geometry.row,
        geometry.col,
        geometry.phi,
        geometry.length1,
        geometry.length2,
    )


def _gen_circle(geometry: CircleROI) -> ha.HObject:
    """Generate HRegion from circle."""
    return ha.gen_circle(
        geometry.row,
        geometry.col,
        geometry.radius,
    )


def _gen_ellipse(geometry: EllipseROI) -> ha.HObject:
    """Generate HRegion from ellipse."""
    return ha.gen_ellipse(
        geometry.row,
        geometry.col,
        geometry.phi,
        geometry.radius1,
        geometry.radius2,
    )


def _gen_polygon(geometry: PolygonROI) -> ha.HObject:
    """Generate HRegion from polygon."""
    rows = [r for r, _ in geometry.points]
    cols = [c for _, c in geometry.points]
    return ha.gen_region_polygon_filled(
        rows,
        cols,
    )


def _round(value: float) -> int:
    """Round a float to the nearest integer (HALCON pixel coordinate)."""
    return int(round(value))