from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from roi.configuration import ROIConfiguration


class ROIListWidget(QWidget):
    selection_changed = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    COL_NAME = 0
    COL_SHAPE = 1
    COL_ENABLED = 2
    COL_ALARM = 3
    COL_STATE = 4
    COL_VISIBLE = 5
    COL_COLOR = 6
    COL_TEMPERATURE = 7

    HEADERS = [
        "Name",
        "Shape",
        "Enabled",
        "Alarm",
        "State",
        "Visible",
        "Color",
        "Temperature",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._roi_map: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(self.HEADERS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._tree.setSortingEnabled(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        header = self._tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        layout.addWidget(self._tree)

    def rebuild(self, configurations: list[ROIConfiguration]) -> None:
        self._tree.clear()
        self._roi_map.clear()
        for config in configurations:
            self.add_row(config)

    def add_row(self, config: ROIConfiguration) -> None:
        item = QTreeWidgetItem()
        item.setText(self.COL_NAME, config.name)
        item.setText(self.COL_SHAPE, config.geometry.type.capitalize())
        item.setText(self.COL_ENABLED, "Yes" if config.enabled else "No")
        alarm_enabled = "Yes" if config.alarm.enabled else "No"
        item.setText(self.COL_ALARM, alarm_enabled)
        item.setText(self.COL_STATE, "")
        item.setText(self.COL_VISIBLE, "Yes" if config.visible else "No")
        item.setText(self.COL_COLOR, config.style.color)
        item.setForeground(self.COL_COLOR, QColor(config.style.color))
        item.setText(self.COL_TEMPERATURE, "---")
        item.setData(0, Qt.UserRole, config.roi_id)
        self._tree.addTopLevelItem(item)
        self._roi_map[config.roi_id] = item

    def remove_row(self, roi_id: str) -> None:
        item = self._roi_map.pop(roi_id, None)
        if item is not None:
            root = self._tree.invisibleRootItem()
            root.removeChild(item)

    def update_row(self, config: ROIConfiguration) -> None:
        item = self._roi_map.get(config.roi_id)
        if item is None:
            return
        item.setText(self.COL_NAME, config.name)
        item.setText(self.COL_SHAPE, config.geometry.type.capitalize())
        item.setText(self.COL_ENABLED, "Yes" if config.enabled else "No")
        item.setText(self.COL_ALARM, "Yes" if config.alarm.enabled else "No")
        item.setText(self.COL_VISIBLE, "Yes" if config.visible else "No")
        item.setText(self.COL_COLOR, config.style.color)
        item.setForeground(self.COL_COLOR, QColor(config.style.color))

    def highlight_row(self, roi_id: str) -> None:
        self._tree.clearSelection()
        item = self._roi_map.get(roi_id)
        if item is not None:
            self._tree.setCurrentItem(item)

    def update_alarm_state(self, roi_id: str, alarm_state: str) -> None:
        item = self._roi_map.get(roi_id)
        if item is not None:
            item.setText(self.COL_STATE, alarm_state)

    def update_temperature(self, roi_id: str, temperature: float) -> None:
        item = self._roi_map.get(roi_id)
        if item is not None:
            item.setText(self.COL_TEMPERATURE, f"{temperature:.1f}")

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        roi_id: str = item.data(0, Qt.UserRole)
        self.selection_changed.emit(roi_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        roi_id: str = item.data(0, Qt.UserRole)
        self.edit_requested.emit(roi_id)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete:
            item = self._tree.currentItem()
            if item is not None:
                roi_id: str = item.data(0, Qt.UserRole)
                self.delete_requested.emit(roi_id)
        super().keyPressEvent(event)
