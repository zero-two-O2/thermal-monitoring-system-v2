from datetime import datetime

from roi.acquisition_state import AcquisitionState
from roi.alarm_settings import ROIAlarmCondition, ROIAlarmSettings
from roi.configuration import ROIConfiguration
from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)
from roi.persistence.project import CameraReference, Project
from roi.recording_settings import ROIRecordingSettings
from roi.style import ROIStyle


def configuration_to_dict(config: ROIConfiguration) -> dict:
    return {
        "roi_id": config.roi_id,
        "name": config.name,
        "enabled": config.enabled,
        "visible": config.visible,
        "description": config.description,
        "metadata": dict(config.metadata),
        "geometry": _geometry_to_dict(config.geometry),
        "style": _style_to_dict(config.style),
        "alarm": _alarm_to_dict(config.alarm),
        "recording": _recording_to_dict(config.recording),
    }


def project_to_dict(project: Project) -> dict:
    return {
        "name": project.name,
        "description": project.description,
        "author": project.author,
        "application_version": project.application_version,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
        "cameras": [_camera_ref_to_dict(c) for c in project.cameras],
        "metadata": dict(project.metadata),
    }


def dict_to_project(data: dict) -> Project:
    created_at = _parse_datetime(data.get("created_at", ""))
    updated_at = _parse_datetime(data.get("updated_at", ""))
    cameras = [_dict_to_camera_ref(c) for c in data.get("cameras", [])]
    return Project(
        name=data.get("name", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        application_version=data.get("application_version", "1.0.0"),
        created_at=created_at,
        updated_at=updated_at,
        cameras=cameras,
        metadata=dict(data.get("metadata", {})),
    )


def dict_to_configuration(
    data: dict,
    acquisition_state: AcquisitionState,
) -> ROIConfiguration:
    geom = _dict_to_geometry(data["geometry"])
    style = _dict_to_style(data.get("style", {}))
    alarm = _dict_to_alarm(data.get("alarm", {}))
    recording = _dict_to_recording(data.get("recording", {}))

    return ROIConfiguration(
        roi_id=data["roi_id"],
        name=data["name"],
        acquisition_state=acquisition_state,
        geometry=geom,
        style=style,
        alarm=alarm,
        recording=recording,
        enabled=data.get("enabled", True),
        visible=data.get("visible", True),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {})),
    )


def state_file_to_dict(
    acquisition_state: AcquisitionState,
    rois: list[ROIConfiguration],
) -> dict:
    return {
        "schema_version": 1,
        "camera_id": acquisition_state.camera_id,
        "acquisition_state": _acquisition_state_to_dict(acquisition_state),
        "rois": [configuration_to_dict(r) for r in rois],
    }


def dict_to_state_file(data: dict) -> tuple[AcquisitionState, list[ROIConfiguration]]:
    state = _dict_to_acquisition_state(data["acquisition_state"])
    rois = [dict_to_configuration(r, state) for r in data["rois"]]
    return state, rois


def geometry_to_dict(geometry: ROIGeometry) -> dict:
    return _geometry_to_dict(geometry)


def dict_to_geometry(data: dict) -> ROIGeometry:
    return _dict_to_geometry(data)


def acquisition_state_to_dict(state: AcquisitionState) -> dict:
    return _acquisition_state_to_dict(state)


def dict_to_acquisition_state(data: dict) -> AcquisitionState:
    return _dict_to_acquisition_state(data)


def export_file_content(
    acquisition_state: AcquisitionState,
    rois: list[ROIConfiguration],
) -> str:
    import json
    data = state_file_to_dict(acquisition_state, rois)
    return json.dumps(data, indent=2, ensure_ascii=False)


def parse_file_content(content: str) -> tuple[AcquisitionState, list[ROIConfiguration]]:
    import json
    data = json.loads(content)
    return dict_to_state_file(data)


# ------------------------------------------------------------------
# Internal converters
# ------------------------------------------------------------------

_GEOMETRY_TYPE_MAP: dict[type, str] = {
    Rectangle1ROI: "rectangle1",
    Rectangle2ROI: "rectangle2",
    CircleROI: "circle",
    EllipseROI: "ellipse",
    PolygonROI: "polygon",
}

_REVERSE_GEOMETRY_TYPE: dict[str, type] = {v: k for k, v in _GEOMETRY_TYPE_MAP.items()}

_ALARM_CONDITION_NAMES: dict[ROIAlarmCondition, str] = {
    ROIAlarmCondition.HIGH: "HIGH",
    ROIAlarmCondition.LOW: "LOW",
    ROIAlarmCondition.RANGE: "RANGE",
}

_REVERSE_ALARM_CONDITION: dict[str, ROIAlarmCondition] = {
    v: k for k, v in _ALARM_CONDITION_NAMES.items()
}


def _geometry_to_dict(geometry: ROIGeometry) -> dict:
    t = _GEOMETRY_TYPE_MAP[type(geometry)]
    if isinstance(geometry, Rectangle1ROI):
        return {"type": t, "row1": geometry.row1, "col1": geometry.col1,
                "row2": geometry.row2, "col2": geometry.col2}
    if isinstance(geometry, Rectangle2ROI):
        return {"type": t, "row": geometry.row, "col": geometry.col,
                "phi": geometry.phi, "length1": geometry.length1,
                "length2": geometry.length2}
    if isinstance(geometry, CircleROI):
        return {"type": t, "row": geometry.row, "col": geometry.col,
                "radius": geometry.radius}
    if isinstance(geometry, EllipseROI):
        return {"type": t, "row": geometry.row, "col": geometry.col,
                "phi": geometry.phi, "radius1": geometry.radius1,
                "radius2": geometry.radius2}
    if isinstance(geometry, PolygonROI):
        return {"type": t, "points": [[r, c] for r, c in geometry.points]}
    raise TypeError(f"Unsupported geometry type: {type(geometry).__name__}")


def _dict_to_geometry(data: dict) -> ROIGeometry:
    t = data.get("type", "")
    cls = _REVERSE_GEOMETRY_TYPE.get(t)
    if cls is None:
        raise ValueError(f"Unknown geometry type: '{t}'")

    if cls is Rectangle1ROI:
        return Rectangle1ROI(row1=data["row1"], col1=data["col1"],
                             row2=data["row2"], col2=data["col2"])
    if cls is Rectangle2ROI:
        return Rectangle2ROI(row=data["row"], col=data["col"],
                             phi=data["phi"], length1=data["length1"],
                             length2=data["length2"])
    if cls is CircleROI:
        return CircleROI(row=data["row"], col=data["col"],
                         radius=data["radius"])
    if cls is EllipseROI:
        return EllipseROI(row=data["row"], col=data["col"],
                          phi=data["phi"], radius1=data["radius1"],
                          radius2=data["radius2"])
    if cls is PolygonROI:
        points = tuple((float(p[0]), float(p[1])) for p in data["points"])
        return PolygonROI(points=points)

    raise ValueError(f"Unhandled geometry class: {cls.__name__}")


def _style_to_dict(style: ROIStyle) -> dict:
    return {
        "color": style.color,
        "selected_color": style.selected_color,
        "alarm_color": style.alarm_color,
        "line_width": style.line_width,
        "label_visible": style.label_visible,
        "label_size": style.label_size,
    }


def _dict_to_style(data: dict) -> ROIStyle:
    return ROIStyle(
        color=data.get("color", "#FFFF00"),
        selected_color=data.get("selected_color", "#00FF00"),
        alarm_color=data.get("alarm_color", "#FF0000"),
        line_width=data.get("line_width", 2),
        label_visible=data.get("label_visible", True),
        label_size=data.get("label_size", 10),
    )


def _alarm_to_dict(alarm: ROIAlarmSettings) -> dict:
    return {
        "enabled": alarm.enabled,
        "condition": _ALARM_CONDITION_NAMES[alarm.condition],
        "value": alarm.value,
        "hysteresis": alarm.hysteresis,
        "delay_ms": alarm.delay_ms,
    }


def _dict_to_alarm(data: dict) -> ROIAlarmSettings:
    condition_name = data.get("condition", "HIGH")
    condition = _REVERSE_ALARM_CONDITION.get(condition_name, ROIAlarmCondition.HIGH)
    return ROIAlarmSettings(
        enabled=data.get("enabled", False),
        condition=condition,
        value=data.get("value", 0.0),
        hysteresis=data.get("hysteresis", 1.0),
        delay_ms=data.get("delay_ms", 0),
    )


def _recording_to_dict(rec: ROIRecordingSettings) -> dict:
    return {
        "enabled": rec.enabled,
        "duration_seconds": rec.duration_seconds,
        "pre_trigger_seconds": rec.pre_trigger_seconds,
        "post_trigger_seconds": rec.post_trigger_seconds,
        "save_images": rec.save_images,
        "save_video": rec.save_video,
    }


def _dict_to_recording(data: dict) -> ROIRecordingSettings:
    return ROIRecordingSettings(
        enabled=data.get("enabled", False),
        duration_seconds=data.get("duration_seconds", 20),
        pre_trigger_seconds=data.get("pre_trigger_seconds", 0),
        post_trigger_seconds=data.get("post_trigger_seconds", 20),
        save_images=data.get("save_images", False),
        save_video=data.get("save_video", True),
    )


def _acquisition_state_to_dict(state: AcquisitionState) -> dict:
    return {
        "camera_id": state.camera_id,
        "pan": state.pan,
        "tilt": state.tilt,
        "zoom": state.zoom,
        "focus": state.focus,
    }


def _camera_ref_to_dict(cam: CameraReference) -> dict:
    return {
        "camera_id": cam.camera_id,
        "name": cam.name,
        "model": cam.model,
        "metadata": dict(cam.metadata),
    }


def _dict_to_camera_ref(data: dict) -> CameraReference:
    return CameraReference(
        camera_id=data.get("camera_id", ""),
        name=data.get("name", ""),
        model=data.get("model", ""),
        metadata=dict(data.get("metadata", {})),
    )


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _dict_to_acquisition_state(data: dict) -> AcquisitionState:
    return AcquisitionState(
        camera_id=data["camera_id"],
        pan=float(data.get("pan", 0.0)),
        tilt=float(data.get("tilt", 0.0)),
        zoom=float(data.get("zoom", 0.0)),
        focus=float(data.get("focus", 0.0)),
    )
