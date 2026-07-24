from __future__ import annotations

import logging
import re

from roi.alarm_settings import ROIAlarmCondition
from roi.persistence.exceptions import (
    SchemaVersionError,
    MissingFieldError,
    ValidationError,
    DuplicateROIError,
)

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

_KNOWN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "camera_id",
    "acquisition_state",
    "rois",
})

_REQUIRED_FILE_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "camera_id",
    "acquisition_state",
    "rois",
})

_REQUIRED_ROI_FIELDS: frozenset[str] = frozenset({
    "roi_id",
    "name",
    "geometry",
})

_REQUIRED_GEOMETRY_FIELDS: dict[str, frozenset[str]] = {
    "rectangle1": frozenset({"type", "row1", "col1", "row2", "col2"}),
    "rectangle2": frozenset({"type", "row", "col", "phi", "length1", "length2"}),
    "circle": frozenset({"type", "row", "col", "radius"}),
    "ellipse": frozenset({"type", "row", "col", "phi", "radius1", "radius2"}),
    "polygon": frozenset({"type", "points"}),
}

_ACQUISITION_STATE_FIELDS: frozenset[str] = frozenset({
    "camera_id",
    "pan",
    "tilt",
    "zoom",
    "focus",
})

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_VALID_ROI_ALARM_CONDITIONS: frozenset[str] = frozenset(
    m.name for m in ROIAlarmCondition
)


def validate_schema_version(data: dict) -> None:
    version = data.get("schema_version")
    if version is None:
        raise MissingFieldError("File is missing 'schema_version'")
    if not isinstance(version, int) or version < 1:
        raise SchemaVersionError(
            f"Invalid schema version: {version}. Expected integer >= 1."
        )
    if version > CURRENT_SCHEMA_VERSION:
        logger.warning(
            "Schema version %s is newer than supported version %s. "
            "Trying forward-compatible read. Unknown fields will be preserved.",
            version,
            CURRENT_SCHEMA_VERSION,
        )


def validate_required_fields(data: dict) -> None:
    missing = _REQUIRED_FILE_FIELDS - data.keys()
    if missing:
        raise MissingFieldError(
            f"File is missing required fields: {', '.join(sorted(missing))}"
        )

    rois = data.get("rois")
    if not isinstance(rois, list):
        raise ValidationError("'rois' must be a list")

    for i, roi in enumerate(rois):
        if not isinstance(roi, dict):
            raise ValidationError(f"ROI at index {i} is not a dict")

        roi_missing = _REQUIRED_ROI_FIELDS - roi.keys()
        if roi_missing:
            raise MissingFieldError(
                f"ROI '{roi.get('roi_id', f'<index {i}>')}' is missing "
                f"required fields: {', '.join(sorted(roi_missing))}"
            )

        geom = roi.get("geometry")
        if not isinstance(geom, dict):
            raise ValidationError(
                f"ROI '{roi.get('roi_id', f'<index {i}>')}' has invalid geometry"
            )

        geom_type = geom.get("type")
        if geom_type not in _REQUIRED_GEOMETRY_FIELDS:
            raise ValidationError(
                f"ROI '{roi.get('roi_id', f'<index {i}>')}' has unknown "
                f"geometry type: '{geom_type}'"
            )

        geom_missing = _REQUIRED_GEOMETRY_FIELDS[geom_type] - geom.keys()
        if geom_missing:
            raise MissingFieldError(
                f"Geometry type '{geom_type}' in ROI "
                f"'{roi.get('roi_id', f'<index {i}>')}' is missing "
                f"fields: {', '.join(sorted(geom_missing))}"
            )

    _validate_acquisition_state(data.get("acquisition_state", {}))


def _validate_acquisition_state(state: dict) -> None:
    if not isinstance(state, dict):
        raise ValidationError("'acquisition_state' must be a dict")
    missing = _ACQUISITION_STATE_FIELDS - state.keys()
    if missing:
        raise MissingFieldError(
            f"'acquisition_state' is missing fields: "
            f"{', '.join(sorted(missing))}"
        )


def validate_roi_ids(data: dict) -> None:
    rois = data.get("rois", [])
    seen: set[str] = set()
    for roi in rois:
        rid = roi.get("roi_id")
        if rid in seen:
            raise DuplicateROIError(f"Duplicate ROI ID: '{rid}'")
        seen.add(rid)


def validate_roi_values(data: dict) -> None:
    rois = data.get("rois", [])
    for i, roi in enumerate(rois):
        _validate_roi_style(roi, i)
        _validate_roi_alarm(roi, i)
        _validate_roi_geometry_values(roi, i)


def extract_extra_fields(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in _KNOWN_TOP_LEVEL_FIELDS}


def _validate_roi_style(roi: dict, index: int) -> None:
    style = roi.get("style")
    if not isinstance(style, dict):
        return
    color = style.get("color", "")
    if color and not _HEX_COLOR_RE.match(color):
        raise ValidationError(
            f"ROI '{roi.get('roi_id', f'<index {index}>')}' has invalid "
            f"style color: '{color}'. Expected hex format (e.g. '#FF0000')."
        )
    selected_color = style.get("selected_color", "")
    if selected_color and not _HEX_COLOR_RE.match(selected_color):
        raise ValidationError(
            f"ROI '{roi.get('roi_id', f'<index {index}>')}' has invalid "
            f"style selected_color: '{selected_color}'. "
            f"Expected hex format (e.g. '#FF0000')."
        )


def _validate_roi_alarm(roi: dict, index: int) -> None:
    alarm = roi.get("alarm")
    if not isinstance(alarm, dict):
        return
    condition = alarm.get("condition")
    if condition is not None and condition not in _VALID_ROI_ALARM_CONDITIONS:
        raise ValidationError(
            f"ROI '{roi.get('roi_id', f'<index {index}>')}' has invalid "
            f"alarm condition: '{condition}'. "
            f"Valid values: {', '.join(sorted(_VALID_ROI_ALARM_CONDITIONS))}."
        )


def _validate_roi_geometry_values(roi: dict, index: int) -> None:
    geom = roi.get("geometry")
    if not isinstance(geom, dict):
        return
    geom_type = geom.get("type")
    if geom_type == "rectangle1":
        _check_positive(geom, "row1", index)
        _check_positive(geom, "col1", index)
        _check_positive(geom, "row2", index)
        _check_positive(geom, "col2", index)
        _check_greater(geom, "row2", "row1", index)
        _check_greater(geom, "col2", "col1", index)
    elif geom_type == "circle":
        _check_positive(geom, "row", index)
        _check_positive(geom, "col", index)
        if "radius" in geom and not _is_positive_number(geom["radius"]):
            raise ValidationError(
                f"ROI '{roi.get('roi_id', f'<index {index}>')}' circle "
                f"radius must be a positive number, got {geom.get('radius')}"
            )
    elif geom_type == "ellipse":
        _check_positive(geom, "row", index)
        _check_positive(geom, "col", index)
        _check_positive_number(geom, "radius1", index, roi)
        _check_positive_number(geom, "radius2", index, roi)


def _check_positive(geom: dict, field: str, index: int) -> None:
    value = geom.get(field)
    if value is not None and (not isinstance(value, (int, float)) or value < 0):
        raise ValidationError(
            f"Geometry field '{field}' must be a positive number, "
            f"got {value} at ROI index {index}"
        )


def _check_greater(geom: dict, larger: str, smaller: str, index: int) -> None:
    v1 = geom.get(larger)
    v2 = geom.get(smaller)
    if v1 is not None and v2 is not None and v1 <= v2:
        raise ValidationError(
            f"Geometry field '{larger}' ({v1}) must be greater than "
            f"'{smaller}' ({v2}) at ROI index {index}"
        )


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _check_positive_number(
    geom: dict, field: str, index: int, roi: dict
) -> None:
    value = geom.get(field)
    if value is not None and not _is_positive_number(value):
        raise ValidationError(
            f"ROI '{roi.get('roi_id', f'<index {index}>')}' geometry "
            f"field '{field}' must be a positive number, got {value}"
        )
