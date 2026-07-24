from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class ROISelectionManager(QObject):
    selection_changed = pyqtSignal(str)
    selection_cleared = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._selected_id: str | None = None
        self._hovered_id: str | None = None
        self._multi_selection: set[str] = set()

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def hovered_id(self) -> str | None:
        return self._hovered_id

    @property
    def multi_selection(self) -> frozenset[str]:
        return frozenset(self._multi_selection)

    def select(self, roi_id: str) -> None:
        self._multi_selection.clear()
        self._selected_id = roi_id
        self._multi_selection.add(roi_id)
        self.selection_changed.emit(roi_id)

    def add_to_selection(self, roi_id: str) -> None:
        self._multi_selection.add(roi_id)
        self._selected_id = roi_id
        self.selection_changed.emit(roi_id)

    def deselect(self, roi_id: str) -> None:
        self._multi_selection.discard(roi_id)
        if self._selected_id == roi_id:
            self._selected_id = next(iter(self._multi_selection), None)

    def clear_selection(self) -> None:
        self._selected_id = None
        self._multi_selection.clear()
        self.selection_cleared.emit()

    def is_selected(self, roi_id: str) -> bool:
        return roi_id in self._multi_selection

    def set_hovered(self, roi_id: str | None) -> None:
        self._hovered_id = roi_id
