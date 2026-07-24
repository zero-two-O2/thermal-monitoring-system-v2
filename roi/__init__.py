"""
roi package.

Region of Interest subsystem for the Thermal Monitoring System.

Architecture follows ROI_Design_Decisions.md.

Layers
------
Layer 1 - ROI Definition (persistent data):
    configuration.py, geometry.py, style.py,
    alarm_settings.py, recording_settings.py, types.py,
    acquisition_state.py

Layer 2 - Runtime ROI Cache (runtime data):
    runtime.py, runtime_cache.py, runtime_manager.py, statistics.py

Layer 3 - ROI Editor (HALCON Drawing Objects):
    editor/

Layer 4 - Persistence (JSON save/load):
    persistence/

Conversion:
    geometry_to_hregion.py   (HALCON HRegion generation)

Interfaces:
    interfaces.py

Dependencies
-----------
- Depends on: standard library, numpy, halcon (conversion/statistics).
- Does NOT depend on: GUI, processing pipeline.
"""

from __future__ import annotations

from roi.types import ROIShape
from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
    BoundingBox,
)
from roi.style import ROIStyle
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.recording_settings import ROIRecordingSettings
from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.runtime_cache import RuntimeROICache
from roi.runtime import RuntimeROIState, RuntimeROIStatistics, RuntimeROI
from roi.interfaces import ROIRepository, ROIManager, RuntimeROIManager
from roi.geometry_to_hregion import geometry_to_hregion
from roi.statistics import extract_statistics
from roi.runtime_manager import RuntimeROIManagerImpl
from roi.editor import (
    EditorError,
    GeometryConversionError,
    DrawingObjectError,
    UnsupportedGeometryError,
    EditorNotFoundError,
    geometry_to_drawing_type,
    geometry_to_params,
    is_polygon_shape,
    params_to_geometry,
    ROISelectionManager,
    ROIEditor,
    DrawingObjectFactory,
    ROIEditorManager,
)
from roi.persistence import (
    PersistenceError,
    SchemaVersionError,
    ValidationError,
    FileNotFoundError,
    CorruptedFileError,
    DuplicateROIError,
    CURRENT_SCHEMA_VERSION,
    JSONROIRepository,
    configuration_to_dict,
    dict_to_configuration,
    state_file_to_dict,
    dict_to_state_file,
    geometry_to_dict,
    dict_to_geometry,
    acquisition_state_to_dict,
    dict_to_acquisition_state,
    export_file_content,
    parse_file_content,
    migrate,
)

__all__ = [
    # Types
    "ROIShape",
    # Geometry
    "ROIGeometry",
    "Rectangle1ROI",
    "Rectangle2ROI",
    "CircleROI",
    "EllipseROI",
    "PolygonROI",
    "BoundingBox",
    # Style
    "ROIStyle",
    # Alarm
    "ROIAlarmCondition",
    "ROIAlarmSettings",
    # Recording
    "ROIRecordingSettings",
    # Acquisition State
    "AcquisitionState",
    # Configuration
    "ROIConfiguration",
    # Runtime
    "RuntimeROICache",
    "RuntimeROIState",
    "RuntimeROIStatistics",
    "RuntimeROI",
    # Conversion
    "geometry_to_hregion",
    # Statistics
    "extract_statistics",
    # Implementation
    "RuntimeROIManagerImpl",
    # Editor
    "EditorError",
    "GeometryConversionError",
    "DrawingObjectError",
    "UnsupportedGeometryError",
    "EditorNotFoundError",
    "geometry_to_drawing_type",
    "geometry_to_params",
    "is_polygon_shape",
    "params_to_geometry",
    "ROISelectionManager",
    "ROIEditor",
    "DrawingObjectFactory",
    "ROIEditorManager",
    # Persistence
    "PersistenceError",
    "SchemaVersionError",
    "ValidationError",
    "FileNotFoundError",
    "CorruptedFileError",
    "DuplicateROIError",
    "CURRENT_SCHEMA_VERSION",
    "JSONROIRepository",
    "configuration_to_dict",
    "dict_to_configuration",
    "state_file_to_dict",
    "dict_to_state_file",
    "geometry_to_dict",
    "dict_to_geometry",
    "acquisition_state_to_dict",
    "dict_to_acquisition_state",
    "export_file_content",
    "parse_file_content",
    "migrate",
    # Interfaces
    "ROIRepository",
    "ROIManager",
    "RuntimeROIManager",
]