from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class ROISignalBus(QObject):
    roi_selected = pyqtSignal(str)
    roi_deselected = pyqtSignal(str)
    selection_cleared = pyqtSignal()

    roi_created = pyqtSignal(str)
    roi_deleted = pyqtSignal(str)
    roi_duplicated = pyqtSignal(str, str)

    editing_started = pyqtSignal(str)
    editing_finished = pyqtSignal(str)

    roi_geometry_changed = pyqtSignal(str)
    roi_alarm_changed = pyqtSignal(str)
    roi_visibility_changed = pyqtSignal(str)
    roi_appearance_changed = pyqtSignal(str)
    roi_recording_changed = pyqtSignal(str)
    roi_metadata_changed = pyqtSignal(str)
    roi_renamed = pyqtSignal(str)

    camera_changed = pyqtSignal(str)
    position_changed = pyqtSignal(str, str)

    dirty_state_changed = pyqtSignal(bool)

    roi_statistics_updated = pyqtSignal(str)
    roi_alarm_state_changed = pyqtSignal(str, object)

    create_roi_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    edit_finish_requested = pyqtSignal(str)
    save_requested = pyqtSignal()

    geometry_edited = pyqtSignal(str, object)
