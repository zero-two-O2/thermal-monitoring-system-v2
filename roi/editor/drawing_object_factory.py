from __future__ import annotations

from typing import Callable

from roi.editor.exceptions import DrawingObjectError, UnsupportedGeometryError
from roi.editor.geometry_converter import geometry_to_params
from roi.geometry import ROIGeometry, PolygonROI
from roi.style import ROIStyle


class DrawingObjectFactory:
    def create_drawing_object(self, geometry: ROIGeometry) -> object:
        ha = self._get_halcon()
        if ha is None:
            raise DrawingObjectError("HALCON is not available")
        shape_type = geometry_to_params(geometry)[0]
        if shape_type == "polygon":
            return self._create_polygon_drawing_object(geometry)
        params = geometry_to_params(geometry)
        param_values = params[2]
        return self._call_create(ha, shape_type, param_values)

    def _create_polygon_drawing_object(self, geometry: ROIGeometry) -> object:
        ha = self._get_halcon()
        if ha is None:
            raise DrawingObjectError("HALCON is not available")
        if not isinstance(geometry, PolygonROI):
            raise UnsupportedGeometryError(
                f"Expected PolygonROI, got {type(geometry).__name__}"
            )
        polygon = geometry
        rows = list(polygon.rows)
        cols = list(polygon.cols)
        try:
            return ha.create_drawing_object_xld(rows, cols)
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to create polygon drawing object: {e}"
            ) from e

    def _call_create(
        self,
        ha: object,
        shape_type: str,
        param_values: list[float],
    ) -> object:
        func_name = f"create_drawing_object_{shape_type}"
        create_func = getattr(ha, func_name, None)
        if create_func is None:
            raise UnsupportedGeometryError(
                f"HALCON has no function {func_name}"
            )
        try:
            return create_func(*param_values)
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to create {shape_type} drawing object: {e}"
            ) from e

    def set_appearance(
        self, draw_obj: object, style: ROIStyle
    ) -> None:
        if draw_obj is None:
            return
        ha = self._get_halcon()
        if ha is None:
            return
        try:
            ha.set_drawing_object_params(
                draw_obj,
                ["color", "line_width"],
                [style.color, float(style.line_width)],
            )
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to set drawing object appearance: {e}"
            ) from e

    def set_selected_appearance(
        self, draw_obj: object, style: ROIStyle
    ) -> None:
        if draw_obj is None:
            return
        ha = self._get_halcon()
        if ha is None:
            return
        try:
            ha.set_drawing_object_params(
                draw_obj,
                ["color", "line_width"],
                [style.selected_color, float(style.line_width)],
            )
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to set selected appearance: {e}"
            ) from e

    def attach_to_window(
        self, draw_obj: object, window_handle: int
    ) -> None:
        if draw_obj is None:
            return
        ha = self._get_halcon()
        if ha is None:
            return
        try:
            ha.attach_drawing_object_to_window(window_handle, draw_obj)
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to attach drawing object to window: {e}"
            ) from e

    def set_callback(
        self,
        draw_obj: object,
        event: str,
        callback: Callable,
    ) -> None:
        if draw_obj is None:
            return
        ha = self._get_halcon()
        if ha is None:
            return
        try:
            if callable(callback):
                try:
                    ha.set_drawing_object_callback(draw_obj, event, callback)
                except Exception:
                    pass
            else:
                ha.set_drawing_object_callback(draw_obj, event, callback)
        except Exception as e:
            raise DrawingObjectError(
                f"Failed to set callback for event '{event}': {e}"
            ) from e

    @staticmethod
    def _get_halcon():
        try:
            import halcon as ha
            return ha
        except ImportError:
            return None
