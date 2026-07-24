from __future__ import annotations

from typing import Callable

from roi.configuration import ROIConfiguration
from roi.editor.exceptions import DrawingObjectError
from roi.editor.geometry_converter import (
    geometry_to_params,
    is_polygon_shape,
    params_to_geometry,
)
from roi.editor.selection_manager import ROISelectionManager
from roi.geometry import (
    ROIGeometry,
    PolygonROI,
)


class ROIEditor:
    def __init__(
        self,
        configuration: ROIConfiguration,
        draw_obj: object,
        window_handle: int,
        selection_manager: ROISelectionManager,
        on_changed: Callable[[str], None],
        on_selected: Callable[[str], None],
        on_deselected: Callable[[str], None],
        on_deleted: Callable[[str], None],
    ) -> None:
        self._config = configuration
        self._draw_obj = draw_obj
        self._window_handle = window_handle
        self._selection_manager = selection_manager
        self._on_changed = on_changed
        self._on_selected = on_selected
        self._on_deselected = on_deselected
        self._on_deleted = on_deleted
        self._destroyed: bool = False
        self._callback_refs: list[Callable] = []

    @property
    def roi_id(self) -> str:
        return self._config.roi_id

    @property
    def configuration(self) -> ROIConfiguration:
        return self._config

    @property
    def draw_obj(self) -> object:
        return self._draw_obj

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def register_callback(self, cb: Callable) -> None:
        self._callback_refs.append(cb)

    def _read_polygon_from_xld(self) -> ROIGeometry | None:
        ha = _get_halcon()
        if ha is None or self._draw_obj is None:
            return None
        try:
            xld = ha.get_drawing_object_iconic(self._draw_obj)
            rows, cols = ha.get_contour_xld(xld)
            points = tuple(
                (float(r), float(c)) for r, c in zip(rows, cols)
            )
            if len(points) < 3:
                return None
            return PolygonROI(points=points)
        except Exception as e:
            raise DrawingObjectError(f"Failed to read polygon XLD: {e}") from e

    def read_geometry(self) -> ROIGeometry:
        if self._destroyed:
            raise DrawingObjectError("Cannot read geometry from destroyed editor")
        ha = _get_halcon()
        if ha is None or self._draw_obj is None:
            return self._config.geometry
        shape_type = geometry_to_params(self._config.geometry)[0]
        if is_polygon_shape(shape_type):
            geom = self._read_polygon_from_xld()
            if geom is None:
                return self._config.geometry
            return geom
        try:
            param_names = geometry_to_params(self._config.geometry)[1]
            values = ha.get_drawing_object_params(self._draw_obj, param_names)
            return params_to_geometry(shape_type, values)
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to read drawing object parameters: {e}"
            ) from e

    def get_updated_configuration(self) -> ROIConfiguration:
        geometry = self.read_geometry()
        from dataclasses import replace
        return replace(self._config, geometry=geometry)

    def detach_and_clear(self) -> None:
        if self._destroyed:
            return
        ha = _get_halcon()
        if ha is not None and self._draw_obj is not None:
            try:
                ha.detach_drawing_object_from_window(
                    self._draw_obj, self._window_handle
                )
            except Exception:
                pass
            try:
                ha.clear_drawing_object(self._draw_obj)
            except Exception:
                pass
        self._callback_refs.clear()
        self._draw_obj = None
        self._destroyed = True

    def destroy(self) -> None:
        self.detach_and_clear()
        self._callback_refs.clear()


def _get_halcon():
    try:
        import halcon as ha
        return ha
    except ImportError:
        return None
