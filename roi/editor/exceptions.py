class EditorError(Exception):
    """Base exception for ROI editor errors."""


class GeometryConversionError(EditorError):
    """Raised when geometry cannot be converted to/from drawing object parameters."""


class DrawingObjectError(EditorError):
    """Raised when a HALCON drawing object operation fails."""


class UnsupportedGeometryError(EditorError):
    """Raised when a geometry type has no corresponding drawing object."""


class EditorNotFoundError(EditorError):
    """Raised when attempting to access a non-existent editor."""
