from __future__ import annotations

from copy import deepcopy
from enum import Enum, auto

from PyQt5.QtCore import QObject, pyqtSignal

from roi.configuration import ROIConfiguration


class ROIDirtyType(Enum):
    GEOMETRY = auto()
    ALARM = auto()
    APPEARANCE = auto()
    RECORDING = auto()
    METADATA = auto()
    CONFIGURATION = auto()


class ROIDirtyTracker(QObject):
    dirty_state_changed = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dirty_types: dict[str, set[ROIDirtyType]] = {}
        self._baseline: dict[str, ROIConfiguration] = {}
        self._dirty = False

    def set_baseline(self, rois: list[ROIConfiguration]) -> None:
        self._baseline = {r.roi_id: deepcopy(r) for r in rois}
        self._dirty_types.clear()
        self._set_dirty(False)

    def mark_modified(self, roi_id: str, dirty_type: ROIDirtyType) -> None:
        if roi_id not in self._dirty_types:
            self._dirty_types[roi_id] = set()
        self._dirty_types[roi_id].add(dirty_type)
        self._set_dirty(True)

    def mark_created(self, roi_id: str) -> None:
        self._dirty_types[roi_id] = {ROIDirtyType.CONFIGURATION}
        self._set_dirty(True)

    def mark_deleted(self, roi_id: str) -> None:
        self._dirty_types[roi_id] = {ROIDirtyType.CONFIGURATION}
        self._set_dirty(True)

    def reset(self) -> None:
        self._dirty_types.clear()
        self._baseline.clear()
        self._set_dirty(False)

    def is_dirty(self) -> bool:
        return self._dirty

    def get_dirty_types(self, roi_id: str) -> frozenset[ROIDirtyType]:
        return frozenset(self._dirty_types.get(roi_id, set()))

    def get_all_dirty_roi_ids(self) -> frozenset[str]:
        return frozenset(self._dirty_types.keys())

    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirty_state_changed.emit(value)
