from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from roi.acquisition_state import AcquisitionState
from roi.configuration import ROIConfiguration
from roi.editor import (
    GeometryConversionError,
    UnsupportedGeometryError,
    DrawingObjectError,
    geometry_to_drawing_type,
    geometry_to_params,
    is_polygon_shape,
    params_to_geometry,
    ROISelectionManager,
    DrawingObjectFactory,
    ROIEditor,
    ROIEditorManager,
)
from roi.geometry import (
    ROIGeometry,
    Rectangle1ROI,
    Rectangle2ROI,
    CircleROI,
    EllipseROI,
    PolygonROI,
)
from roi.style import ROIStyle

_STATE = AcquisitionState(camera_id="cam_test", pan=0.0)


def _make_config(
    roi_id: str = "test_001",
    geometry: ROIGeometry = Rectangle1ROI(10.0, 10.0, 100.0, 100.0),
) -> ROIConfiguration:
    return ROIConfiguration(
        roi_id=roi_id,
        name=f"Test-{roi_id}",
        acquisition_state=_STATE,
        geometry=geometry,
        style=ROIStyle(color="#FF0000", selected_color="#00FF00", line_width=3),
    )


# ==============================================================
# Tests: geometry_converter
# ==============================================================


class TestGeometryToDrawingType:
    def test_rectangle1(self):
        assert geometry_to_drawing_type(Rectangle1ROI(0, 0, 10, 10)) == "rectangle1"

    def test_rectangle2(self):
        assert geometry_to_drawing_type(Rectangle2ROI(50, 50, 0.0, 30, 20)) == "rectangle2"

    def test_circle(self):
        assert geometry_to_drawing_type(CircleROI(50, 50, 25)) == "circle"

    def test_ellipse(self):
        assert geometry_to_drawing_type(EllipseROI(50, 50, 0.0, 40, 20)) == "ellipse"

    def test_polygon(self):
        g = PolygonROI(((0, 0), (100, 0), (100, 100)))
        assert geometry_to_drawing_type(g) == "polygon"


class TestGeometryToParams:
    def test_rectangle1(self):
        geom = Rectangle1ROI(10.0, 20.0, 100.0, 200.0)
        t, names, values = geometry_to_params(geom)
        assert t == "rectangle1"
        assert names == ["row1", "column1", "row2", "column2"]
        assert values == [10.0, 20.0, 100.0, 200.0]

    def test_rectangle2(self):
        geom = Rectangle2ROI(50.0, 60.0, 0.5, 30.0, 20.0)
        t, names, values = geometry_to_params(geom)
        assert t == "rectangle2"
        assert names == ["row", "column", "phi", "length1", "length2"]
        assert values == [50.0, 60.0, 0.5, 30.0, 20.0]

    def test_circle(self):
        geom = CircleROI(100.0, 100.0, 25.0)
        t, names, values = geometry_to_params(geom)
        assert t == "circle"
        assert names == ["row", "column", "radius"]
        assert values == [100.0, 100.0, 25.0]

    def test_ellipse(self):
        geom = EllipseROI(100.0, 100.0, 0.3, 40.0, 20.0)
        t, names, values = geometry_to_params(geom)
        assert t == "ellipse"
        assert names == ["row", "column", "phi", "radius1", "radius2"]
        assert values == [100.0, 100.0, 0.3, 40.0, 20.0]

    def test_polygon(self):
        geom = PolygonROI(((0.0, 0.0), (100.0, 50.0), (50.0, 100.0)))
        t, names, values = geometry_to_params(geom)
        assert t == "polygon"
        assert names == []
        assert values == []


class TestParamsToGeometry:
    def test_rectangle1(self):
        geom = params_to_geometry("rectangle1", (10.0, 20.0, 100.0, 200.0))
        assert isinstance(geom, Rectangle1ROI)
        assert geom.row1 == 10.0
        assert geom.col1 == 20.0
        assert geom.row2 == 100.0
        assert geom.col2 == 200.0

    def test_rectangle2(self):
        geom = params_to_geometry("rectangle2", (50.0, 60.0, 0.5, 30.0, 20.0))
        assert isinstance(geom, Rectangle2ROI)
        assert geom.row == 50.0
        assert geom.col == 60.0
        assert geom.phi == 0.5
        assert geom.length1 == 30.0
        assert geom.length2 == 20.0

    def test_circle(self):
        geom = params_to_geometry("circle", (100.0, 100.0, 25.0))
        assert isinstance(geom, CircleROI)
        assert geom.row == 100.0
        assert geom.col == 100.0
        assert geom.radius == 25.0

    def test_ellipse(self):
        geom = params_to_geometry("ellipse", (100.0, 100.0, 0.3, 40.0, 20.0))
        assert isinstance(geom, EllipseROI)
        assert geom.row == 100.0
        assert geom.col == 100.0
        assert geom.phi == 0.3
        assert geom.radius1 == 40.0
        assert geom.radius2 == 20.0

    def test_unknown_type_raises(self):
        with pytest.raises(UnsupportedGeometryError, match="Unknown"):
            params_to_geometry("triangle", (1.0, 2.0, 3.0))

    def test_wrong_param_count_raises(self):
        with pytest.raises(GeometryConversionError, match="Expected 4"):
            params_to_geometry("rectangle1", (1.0, 2.0, 3.0))

    def test_non_numeric_param_raises(self):
        with pytest.raises(GeometryConversionError, match="expected number"):
            params_to_geometry("circle", (None, 100.0, 25.0))


class TestIsPolygonShape:
    def test_polygon_true(self):
        assert is_polygon_shape("polygon") is True

    def test_rectangle1_false(self):
        assert is_polygon_shape("rectangle1") is False

    def test_circle_false(self):
        assert is_polygon_shape("circle") is False


class TestRoundTripGeometry:
    def test_rectangle1_round_trip(self):
        original = Rectangle1ROI(10.0, 20.0, 100.0, 200.0)
        t, _, _ = geometry_to_params(original)
        values = (10.0, 20.0, 100.0, 200.0)
        result = params_to_geometry(t, values)
        assert result == original

    def test_circle_round_trip(self):
        original = CircleROI(100.0, 100.0, 25.0)
        t, _, _ = geometry_to_params(original)
        values = (100.0, 100.0, 25.0)
        result = params_to_geometry(t, values)
        assert result == original


# ==============================================================
# Tests: selection_manager
# ==============================================================


class TestROISelectionManager:
    def test_empty_initial(self):
        mgr = ROISelectionManager()
        assert mgr.count == 0
        assert mgr.get_selected() == set()

    def test_select(self):
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        assert mgr.is_selected("roi_1")
        assert mgr.count == 1

    def test_deselect(self):
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.deselect("roi_1")
        assert not mgr.is_selected("roi_1")

    def test_deselect_nonexistent(self):
        mgr = ROISelectionManager()
        mgr.deselect("roi_1")
        assert mgr.count == 0

    def test_toggle_selection(self):
        mgr = ROISelectionManager()
        mgr.toggle_selection("roi_1")
        assert mgr.is_selected("roi_1")
        mgr.toggle_selection("roi_1")
        assert not mgr.is_selected("roi_1")

    def test_multi_selection(self):
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        mgr.select("roi_2")
        mgr.select("roi_3")
        assert mgr.count == 3
        assert mgr.get_selected() == {"roi_1", "roi_2", "roi_3"}

    def test_select_all(self):
        mgr = ROISelectionManager()
        mgr.select_all(["a", "b", "c"])
        assert mgr.count == 3

    def test_clear_selection(self):
        mgr = ROISelectionManager()
        mgr.select_all(["a", "b"])
        mgr.clear_selection()
        assert mgr.count == 0

    def test_contains(self):
        mgr = ROISelectionManager()
        mgr.select("roi_1")
        assert "roi_1" in mgr
        assert "roi_2" not in mgr


# ==============================================================
# Tests: ROIEditor (null draw_obj path)
# ==============================================================


class TestROIEditorWithNullDrawObj:
    def test_read_geometry_fallback(self):
        geom = CircleROI(50.0, 50.0, 30.0)
        config = _make_config(geometry=geom)
        editor = ROIEditor(
            configuration=config,
            draw_obj=None,
            window_handle=0,
            selection_manager=ROISelectionManager(),
            on_changed=lambda rid: None,
            on_selected=lambda rid: None,
            on_deselected=lambda rid: None,
            on_deleted=lambda rid: None,
        )
        assert editor.roi_id == "test_001"
        assert editor.draw_obj is None
        assert not editor.destroyed
        geometry = editor.read_geometry()
        assert geometry == geom

    def test_get_updated_configuration_fallback(self):
        geom = CircleROI(50.0, 50.0, 30.0)
        config = _make_config(geometry=geom)
        editor = ROIEditor(
            configuration=config,
            draw_obj=None,
            window_handle=0,
            selection_manager=ROISelectionManager(),
            on_changed=lambda rid: None,
            on_selected=lambda rid: None,
            on_deselected=lambda rid: None,
            on_deleted=lambda rid: None,
        )
        updated = editor.get_updated_configuration()
        assert updated.roi_id == config.roi_id
        assert updated.geometry == geom
        assert updated is not config

    def test_destroy_null_draw_obj(self):
        config = _make_config()
        editor = ROIEditor(
            configuration=config,
            draw_obj=None,
            window_handle=0,
            selection_manager=ROISelectionManager(),
            on_changed=lambda rid: None,
            on_selected=lambda rid: None,
            on_deselected=lambda rid: None,
            on_deleted=lambda rid: None,
        )
        editor.destroy()
        assert editor.destroyed

    def test_double_destroy_safe(self):
        config = _make_config()
        editor = ROIEditor(
            configuration=config,
            draw_obj=None,
            window_handle=0,
            selection_manager=ROISelectionManager(),
            on_changed=lambda rid: None,
            on_selected=lambda rid: None,
            on_deselected=lambda rid: None,
            on_deleted=lambda rid: None,
        )
        editor.destroy()
        editor.destroy()
        assert editor.destroyed

    def test_read_geometry_after_destroy_raises(self):
        config = _make_config()
        editor = ROIEditor(
            configuration=config,
            draw_obj=None,
            window_handle=0,
            selection_manager=ROISelectionManager(),
            on_changed=lambda rid: None,
            on_selected=lambda rid: None,
            on_deselected=lambda rid: None,
            on_deleted=lambda rid: None,
        )
        editor.destroy()
        with pytest.raises(DrawingObjectError, match="destroyed"):
            editor.read_geometry()


# ==============================================================
# Tests: ROIEditorManager (basic lifecycle, no active editors)
# ==============================================================


class TestROIEditorManagerBasicLifecycle:
    def test_initial_state(self):
        mgr = ROIEditorManager(window_handle=0)
        assert mgr.active_count == 0
        assert mgr.active_editor_ids == []
        assert mgr.selection_manager.count == 0

    def test_close_editor_nonexistent_returns_none(self):
        mgr = ROIEditorManager(window_handle=0)
        result = mgr.close_editor("nonexistent")
        assert result is None

    def test_has_editor_empty_returns_false(self):
        mgr = ROIEditorManager(window_handle=0)
        assert not mgr.has_editor("test_001")

    def test_get_editor_empty_returns_none(self):
        mgr = ROIEditorManager(window_handle=0)
        assert mgr.get_editor("test_001") is None

    def test_delete_editor_nonexistent_safe(self):
        mgr = ROIEditorManager(window_handle=0)
        mgr.delete_editor("nonexistent")
        assert True

    def test_close_all_empty(self):
        mgr = ROIEditorManager(window_handle=0)
        configs = mgr.close_all()
        assert configs == []

    def test_on_config_changed_not_called_for_nonexistent(self):
        changed_configs: list[ROIConfiguration] = []
        mgr = ROIEditorManager(
            window_handle=0,
            on_config_changed=lambda cfg: changed_configs.append(cfg),
        )
        mgr.close_editor("test_001")
        assert len(changed_configs) == 0

    def test_on_config_deleted_not_called_for_nonexistent(self):
        deleted_ids: list[str] = []
        mgr = ROIEditorManager(
            window_handle=0,
            on_config_deleted=lambda rid: deleted_ids.append(rid),
        )
        mgr.delete_editor("test_001")
        assert len(deleted_ids) == 0

    def test_selection_manager_property(self):
        mgr = ROIEditorManager(window_handle=0)
        assert isinstance(mgr.selection_manager, ROISelectionManager)


# ==============================================================
# Tests: DrawingObjectFactory (null draw_obj path)
# ==============================================================


class TestDrawingObjectFactoryNullDrawObj:
    def test_set_appearance_none_draw_obj(self):
        factory = DrawingObjectFactory()
        factory.set_appearance(None, ROIStyle())
        assert True

    def test_set_selected_appearance_none_draw_obj(self):
        factory = DrawingObjectFactory()
        factory.set_selected_appearance(None, ROIStyle())
        assert True

    def test_attach_to_window_none_draw_obj(self):
        factory = DrawingObjectFactory()
        factory.attach_to_window(None, 0)
        assert True

    def test_set_callback_none_draw_obj(self):
        factory = DrawingObjectFactory()
        factory.set_callback(None, "on_drag", lambda *a: 0)
        assert True


# ==============================================================
# Tests: DrawingObjectFactory (real HALCON)
# ==============================================================


class TestDrawingObjectFactoryWithHalcon:
    def test_create_circle_drawing_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(CircleROI(100.0, 100.0, 50.0))
        assert draw_obj is not None

    def test_create_rectangle1_drawing_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(Rectangle1ROI(10.0, 10.0, 100.0, 100.0))
        assert draw_obj is not None

    def test_create_rectangle2_drawing_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(Rectangle2ROI(50.0, 50.0, 0.0, 30.0, 20.0))
        assert draw_obj is not None

    def test_create_ellipse_drawing_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(EllipseROI(100.0, 100.0, 0.0, 40.0, 20.0))
        assert draw_obj is not None

    def test_create_polygon_drawing_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(
            PolygonROI(((50, 50), (150, 50), (150, 150), (50, 150)))
        )
        assert draw_obj is not None

    def test_set_appearance_on_real_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(CircleROI(100, 100, 50))
        factory.set_appearance(draw_obj, ROIStyle(color="#00FF00", line_width=3))
        assert True

    def test_set_selected_appearance_on_real_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(CircleROI(100, 100, 50))
        factory.set_selected_appearance(draw_obj, ROIStyle(selected_color="#FF0000", line_width=3))
        assert True

    def test_attach_to_window_requires_window(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(CircleROI(100, 100, 50))
        with pytest.raises(DrawingObjectError, match="Failed to attach"):
            factory.attach_to_window(draw_obj, 0)

    def test_set_callback_on_real_object(self):
        factory = DrawingObjectFactory()
        draw_obj = factory.create_drawing_object(CircleROI(100, 100, 50))
        factory.set_callback(draw_obj, "on_drag", lambda *a: 0)
        assert True


# ==============================================================
# Tests: ROIEditorManager with HALCON
# ==============================================================


@pytest.fixture(scope="class")
def halcon_window():
    import halcon as ha
    win = ha.open_window(1, 1, 200, 200, 0, "buffer", "")
    yield win
    ha.close_window(win)


class TestROIEditorManagerWithHalcon:
    @pytest.fixture(autouse=True)
    def _halcon_window(self, halcon_window):
        self.window = halcon_window

    def test_create_rectangle1_editor(self):
        mgr = ROIEditorManager(window_handle=self.window)
        config = _make_config(roi_id="rect1", geometry=Rectangle1ROI(10, 20, 100, 200))
        mgr.open_editor(config)
        assert mgr.active_count == 1
        assert mgr.has_editor("rect1")
        editor = mgr.get_editor("rect1")
        assert editor is not None
        assert editor.roi_id == "rect1"

    def test_create_circle_editor(self):
        mgr = ROIEditorManager(window_handle=self.window)
        config = _make_config(roi_id="circle1", geometry=CircleROI(100, 100, 25))
        mgr.open_editor(config)
        assert mgr.active_count == 1

    def test_create_multiple_editors(self):
        mgr = ROIEditorManager(window_handle=self.window)
        mgr.open_editor(_make_config(roi_id="r1", geometry=Rectangle1ROI(0, 0, 10, 10)))
        mgr.open_editor(_make_config(roi_id="r2", geometry=CircleROI(50, 50, 20)))
        assert mgr.active_count == 2
        assert set(mgr.active_editor_ids) == {"r1", "r2"}

    def test_open_duplicate_editor_skips(self):
        mgr = ROIEditorManager(window_handle=self.window)
        config = _make_config(roi_id="dup")
        mgr.open_editor(config)
        mgr.open_editor(config)
        assert mgr.active_count == 1

    def test_close_editor_returns_updated_config(self):
        changed_configs: list[ROIConfiguration] = []
        mgr = ROIEditorManager(
            window_handle=self.window,
            on_config_changed=lambda cfg: changed_configs.append(cfg),
        )
        config = _make_config(roi_id="close1", geometry=Rectangle1ROI(10, 20, 100, 200))
        mgr.open_editor(config)
        result = mgr.close_editor("close1")
        assert result is not None
        assert result.roi_id == "close1"
        assert mgr.active_count == 0
        assert len(changed_configs) == 1

    def test_close_all_returns_all_configs(self):
        changed_configs: list[ROIConfiguration] = []
        mgr = ROIEditorManager(
            window_handle=self.window,
            on_config_changed=lambda cfg: changed_configs.append(cfg),
        )
        mgr.open_editor(_make_config(roi_id="a"))
        mgr.open_editor(_make_config(roi_id="b"))
        results = mgr.close_all()
        assert len(results) == 2
        assert mgr.active_count == 0
        assert len(changed_configs) == 2

    def test_delete_editor(self):
        deleted_ids: list[str] = []
        mgr = ROIEditorManager(
            window_handle=self.window,
            on_config_deleted=lambda rid: deleted_ids.append(rid),
        )
        mgr.open_editor(_make_config(roi_id="del1"))
        mgr.delete_editor("del1")
        assert mgr.active_count == 0
        assert "del1" in deleted_ids

    def test_editor_creates_polygon(self):
        mgr = ROIEditorManager(window_handle=self.window)
        config = _make_config(
            roi_id="poly1",
            geometry=PolygonROI(((50, 50), (150, 50), (150, 150), (50, 150))),
        )
        mgr.open_editor(config)
        assert mgr.active_count == 1

    def test_editor_idempotent_close(self):
        mgr = ROIEditorManager(window_handle=self.window)
        mgr.open_editor(_make_config(roi_id="idem"))
        mgr.close_editor("idem")
        result = mgr.close_editor("idem")
        assert result is None

    def test_selection_notifies(self):
        mgr = ROIEditorManager(window_handle=self.window)
        mgr.open_editor(_make_config(roi_id="sel1"))
        mgr._notify_selected("sel1")
        assert mgr.selection_manager.is_selected("sel1")

    def test_deselection_notifies(self):
        mgr = ROIEditorManager(window_handle=self.window)
        mgr.open_editor(_make_config(roi_id="sel1"))
        mgr._notify_selected("sel1")
        mgr._notify_deselected("sel1")
        assert not mgr.selection_manager.is_selected("sel1")

    def test_detach_removes_editor(self):
        deleted_ids: list[str] = []
        mgr = ROIEditorManager(
            window_handle=self.window,
            on_config_deleted=lambda rid: deleted_ids.append(rid),
        )
        mgr.open_editor(_make_config(roi_id="det1"))
        mgr._notify_detached("det1")
        assert mgr.active_count == 0
        assert "det1" in deleted_ids
