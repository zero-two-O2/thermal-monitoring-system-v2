from __future__ import annotations

from typing import Callable, Any

from roi.configuration import ROIConfiguration
from roi.editor.drawing_object_factory import DrawingObjectFactory
from roi.editor.editor import ROIEditor
from roi.editor.selection_manager import ROISelectionManager


class ROIEditorManager:
    def __init__(
        self,
        window_handle: int,
        on_config_changed: Callable[[ROIConfiguration], None] | None = None,
        on_config_deleted: Callable[[str], None] | None = None,
    ) -> None:
        self._window_handle = window_handle
        self._on_config_changed = on_config_changed
        self._on_config_deleted = on_config_deleted
        self._factory = DrawingObjectFactory()
        self._selection_manager = ROISelectionManager()
        self._active_editors: dict[str, ROIEditor] = {}

    @property
    def selection_manager(self) -> ROISelectionManager:
        return self._selection_manager

    @property
    def active_count(self) -> int:
        return len(self._active_editors)

    @property
    def active_editor_ids(self) -> list[str]:
        return list(self._active_editors.keys())

    def has_editor(self, roi_id: str) -> bool:
        return roi_id in self._active_editors

    def get_editor(self, roi_id: str) -> ROIEditor | None:
        return self._active_editors.get(roi_id)

    def open_editor(self, configuration: ROIConfiguration) -> None:
        if configuration.roi_id in self._active_editors:
            return
        draw_obj = self._factory.create_drawing_object(configuration.geometry)
        self._factory.set_appearance(draw_obj, configuration.style)
        roi_id = configuration.roi_id
        editor = ROIEditor(
            configuration=configuration,
            draw_obj=draw_obj,
            window_handle=self._window_handle,
            selection_manager=self._selection_manager,
            on_changed=lambda rid: self._notify_changed(rid),
            on_selected=lambda rid: self._notify_selected(rid),
            on_deselected=lambda rid: self._notify_deselected(rid),
            on_deleted=lambda rid: self._notify_detached(rid),
        )
        editor.register_callback(_make_callback(self, roi_id, "on_drag"))
        editor.register_callback(_make_callback(self, roi_id, "on_resize"))
        editor.register_callback(_make_callback(self, roi_id, "on_select"))
        editor.register_callback(_make_callback(self, roi_id, "on_detach"))
        self._factory.set_callback(
            draw_obj, "on_drag", _make_callback(self, roi_id, "on_drag")
        )
        self._factory.set_callback(
            draw_obj, "on_resize", _make_callback(self, roi_id, "on_resize")
        )
        self._factory.set_callback(
            draw_obj, "on_select", _make_callback(self, roi_id, "on_select")
        )
        self._factory.set_callback(
            draw_obj, "on_detach", _make_callback(self, roi_id, "on_detach")
        )
        self._factory.attach_to_window(draw_obj, self._window_handle)
        self._active_editors[roi_id] = editor

    def close_editor(self, roi_id: str) -> ROIConfiguration | None:
        editor = self._active_editors.pop(roi_id, None)
        if editor is None:
            return None
        try:
            new_config = editor.get_updated_configuration()
        except Exception:
            new_config = editor.configuration
        editor.destroy()
        if self._on_config_changed is not None and new_config is not None:
            self._on_config_changed(new_config)
        return new_config

    def close_all(self) -> list[ROIConfiguration]:
        configs: list[ROIConfiguration] = []
        roi_ids = list(self._active_editors.keys())
        for roi_id in roi_ids:
            config = self.close_editor(roi_id)
            if config is not None:
                configs.append(config)
        self._selection_manager.clear_selection()
        return configs

    def delete_editor(self, roi_id: str) -> None:
        editor = self._active_editors.pop(roi_id, None)
        if editor is None:
            return
        editor.destroy()
        self._selection_manager.deselect(roi_id)
        if self._on_config_deleted is not None:
            self._on_config_deleted(roi_id)

    def _notify_changed(self, roi_id: str) -> None:
        pass

    def _notify_selected(self, roi_id: str) -> None:
        editor = self._active_editors.get(roi_id)
        if editor is None:
            return
        self._selection_manager.select(roi_id)
        self._factory.set_selected_appearance(
            editor.draw_obj, editor.configuration.style
        )

    def _notify_deselected(self, roi_id: str) -> None:
        editor = self._active_editors.get(roi_id)
        if editor is None:
            return
        self._selection_manager.deselect(roi_id)
        self._factory.set_appearance(
            editor.draw_obj, editor.configuration.style
        )

    def _notify_detached(self, roi_id: str) -> None:
        editor = self._active_editors.get(roi_id)
        if editor is None:
            return
        if editor.destroyed:
            return
        self._active_editors.pop(roi_id, None)
        editor.destroy()
        self._selection_manager.deselect(roi_id)
        if self._on_config_deleted is not None:
            self._on_config_deleted(roi_id)


_HALCON_CALLBACKS: list[Any] = []


def _make_callback(
    manager: ROIEditorManager, roi_id: str, event: str
) -> Any:
    def callback(draw_id: Any, window_handle: Any, halcon_event: str) -> int:
        if event == "on_drag" or event == "on_resize":
            manager._notify_changed(roi_id)
        elif event == "on_select":
            manager._notify_selected(roi_id)
        elif event == "on_detach":
            manager._notify_detached(roi_id)
        return 0

    _HALCON_CALLBACKS.append(callback)
    return callback
