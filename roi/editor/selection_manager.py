from __future__ import annotations


class ROISelectionManager:
    def __init__(self) -> None:
        self._selected: set[str] = set()

    def select(self, roi_id: str) -> None:
        self._selected.add(roi_id)

    def deselect(self, roi_id: str) -> None:
        self._selected.discard(roi_id)

    def toggle_selection(self, roi_id: str) -> None:
        if roi_id in self._selected:
            self._selected.discard(roi_id)
        else:
            self._selected.add(roi_id)

    def select_all(self, roi_ids: list[str]) -> None:
        self._selected.update(roi_ids)

    def clear_selection(self) -> None:
        self._selected.clear()

    def get_selected(self) -> set[str]:
        return set(self._selected)

    def is_selected(self, roi_id: str) -> bool:
        return roi_id in self._selected

    @property
    def count(self) -> int:
        return len(self._selected)

    def __contains__(self, roi_id: str) -> bool:
        return roi_id in self._selected
