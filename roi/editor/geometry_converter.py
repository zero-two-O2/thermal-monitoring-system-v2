from __future__ import annotations

from roi.editor.exceptions import GeometryConversionError, UnsupportedGeometryError
from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)
from roi.types import ROIShape

DRAWING_OBJECT_SHAPE_MAP: dict[str, ROIShape] = {
    "rectangle1": ROIShape.RECTANGLE1,
    "rectangle2": ROIShape.RECTANGLE2,
    "circle": ROIShape.CIRCLE,
    "ellipse": ROIShape.ELLIPSE,
    "polygon": ROIShape.POLYGON,
}


def geometry_to_drawing_type(geometry: ROIGeometry) -> str:
    mapping: dict[ROIShape, str] = {
        ROIShape.RECTANGLE1: "rectangle1",
        ROIShape.RECTANGLE2: "rectangle2",
        ROIShape.CIRCLE: "circle",
        ROIShape.ELLIPSE: "ellipse",
        ROIShape.POLYGON: "polygon",
    }
    t = mapping.get(geometry.shape)
    if t is None:
        raise UnsupportedGeometryError(
            f"No drawing object type for {type(geometry).__name__}"
        )
    return t


def geometry_to_params(geometry: ROIGeometry) -> tuple[str, list[str], list[float]]:
    if isinstance(geometry, Rectangle1ROI):
        return (
            "rectangle1",
            ["row1", "column1", "row2", "column2"],
            [geometry.row1, geometry.col1, geometry.row2, geometry.col2],
        )
    if isinstance(geometry, Rectangle2ROI):
        return (
            "rectangle2",
            ["row", "column", "phi", "length1", "length2"],
            [geometry.row, geometry.col, geometry.phi, geometry.length1, geometry.length2],
        )
    if isinstance(geometry, CircleROI):
        return (
            "circle",
            ["row", "column", "radius"],
            [geometry.row, geometry.col, geometry.radius],
        )
    if isinstance(geometry, EllipseROI):
        return (
            "ellipse",
            ["row", "column", "phi", "radius1", "radius2"],
            [geometry.row, geometry.col, geometry.phi, geometry.radius1, geometry.radius2],
        )
    if isinstance(geometry, PolygonROI):
        return (
            "polygon",
            [],
            [],
        )
    raise UnsupportedGeometryError(
        f"Cannot convert {type(geometry).__name__} to drawing params"
    )


def is_polygon_shape(type_name: str) -> bool:
    return type_name == "polygon"


def params_to_geometry(
    type_name: str,
    param_values: tuple[float, ...],
) -> ROIGeometry:
    if type_name == "rectangle1":
        row1, col1, row2, col2 = _unpack_params(param_values, 4, type_name)
        return Rectangle1ROI(row1=row1, col1=col1, row2=row2, col2=col2)
    if type_name == "rectangle2":
        row, col, phi, length1, length2 = _unpack_params(param_values, 5, type_name)
        return Rectangle2ROI(
            row=row, col=col, phi=phi, length1=length1, length2=length2
        )
    if type_name == "circle":
        row, col, radius = _unpack_params(param_values, 3, type_name)
        return CircleROI(row=row, col=col, radius=radius)
    if type_name == "ellipse":
        row, col, phi, radius1, radius2 = _unpack_params(param_values, 5, type_name)
        return EllipseROI(
            row=row, col=col, phi=phi, radius1=radius1, radius2=radius2
        )
    raise UnsupportedGeometryError(f"Unknown drawing object type: {type_name}")


def _unpack_params(
    values: tuple[float, ...], expected: int, type_name: str
) -> tuple[float, ...]:
    if not isinstance(values, tuple):
        raise GeometryConversionError(
            f"Expected tuple of {expected} values for {type_name}, "
            f"got {type(values).__name__}"
        )
    if len(values) < expected:
        raise GeometryConversionError(
            f"Expected {expected} parameters for {type_name}, got {len(values)}"
        )
    result = []
    for i in range(expected):
        v = values[i]
        if isinstance(v, (int, float)):
            result.append(float(v))
        else:
            raise GeometryConversionError(
                f"Parameter {i} for {type_name}: "
                f"expected number, got {type(v).__name__} ({v})"
            )
    return tuple(result)
