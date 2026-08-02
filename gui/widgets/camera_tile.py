from __future__ import annotations

import numpy as np
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from gui.theme import (
    COLOR_ACCENT,
    COLOR_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_RED,
    COLOR_ALARM_GRAY,
    COLOR_ALARM_ORANGE,
    COLOR_TOOLBAR,
)


STYLE_TILE = f"""
QFrame#cameraTile {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}
QFrame#cameraTile:hover {{
    border: 1px solid {COLOR_ACCENT};
}}
"""


class CameraTile(QFrame):
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)

    def __init__(self, camera_id: str, camera_name: str, parent=None) -> None:
        super().__init__(parent)

        self._camera_id = camera_id
        self._camera_name = camera_name
        self._connected = False
        self._pixmap: QPixmap | None = None

        self.setObjectName("cameraTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(STYLE_TILE)

        self._build_ui()
        self._update_status_ui()

    @property
    def camera_id(self) -> str:
        return self._camera_id

    def set_camera_id(self, camera_id: str) -> None:
        self._camera_id = camera_id

    def set_camera_name(self, name: str) -> None:
        self._camera_name = name
        self._name_label.setText(name)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_status_ui()

    def set_position(self, position: str) -> None:
        self._position_label.setText(position if position else "---")

    def set_fps(self, fps: float) -> None:
        self._fps_label.setText(f"{fps:.1f} FPS")

    def set_alarm(self, alarm: bool, level: str = "") -> None:
        if alarm:
            color = COLOR_ALARM_RED if level == "CRITICAL" else COLOR_ALARM_ORANGE
            self._alarm_label.setText("ALARM")
            self._alarm_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 10px; padding: 1px 4px; background-color: {color}20; border-radius: 2px;")
            self._alarm_label.show()
        else:
            self._alarm_label.hide()

    def assign_camera(self, camera_id: str, name: str) -> None:
        self._camera_id = camera_id
        self._camera_name = name
        self._name_label.setText(name if name else "No Camera Connected")
        self._name_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        self._pixmap = None
        self._image_label.setText("No Camera Connected\n\nConnect a camera from\nthe Main Window")
        self._image_label.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 11px; background-color: {COLOR_TOOLBAR}; border: 1px solid {COLOR_BORDER};")

    def clear_camera(self) -> None:
        self._camera_id = ""
        self._camera_name = ""
        self._name_label.setText("No Camera Connected")
        self._name_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_ALARM_GRAY};")
        self._connected = False
        self._pixmap = None
        self._image_label.clear()
        self._image_label.setText("No Camera Connected\n\nConnect a camera from\nthe Main Window")
        self._image_label.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 11px; background-color: {COLOR_TOOLBAR}; border: 1px solid {COLOR_BORDER};")
        self._status_label.setText("Disconnected")
        self._status_label.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 10px;")
        self._position_label.setText("---")
        self._fps_label.setText("")
        self._alarm_label.hide()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._name_label = QLabel(self._camera_name)
        self._name_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        header.addWidget(self._name_label)

        self._alarm_label = QLabel()
        self._alarm_label.hide()
        header.addWidget(self._alarm_label)

        header.addStretch()

        self._status_label = QLabel()
        self._status_label.setStyleSheet(f"color: {COLOR_ALARM_GREEN}; font-size: 10px;")
        header.addWidget(self._status_label)
        layout.addLayout(header)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(80, 60)
        self._image_label.setStyleSheet(f"background-color: {COLOR_TOOLBAR}; border: 1px solid {COLOR_BORDER}; border-radius: 2px;")
        layout.addWidget(self._image_label, 1)

        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        self._position_label = QLabel("---")
        self._position_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        self._fps_label = QLabel("")
        self._fps_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        info_row.addWidget(self._position_label)
        info_row.addStretch()
        info_row.addWidget(self._fps_label)
        layout.addLayout(info_row)

    def _update_status_ui(self) -> None:
        if self._connected:
            self._status_label.setText("Connected")
            self._status_label.setStyleSheet(f"color: {COLOR_ALARM_GREEN}; font-size: 10px;")
        else:
            self._status_label.setText("Disconnected")
            self._status_label.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 10px;")

    # ---------------------------------------------------------
    # Frame Update
    # ---------------------------------------------------------

    def update_frame(self, image: np.ndarray | None = None, frame_count: int = 0, sequence: int = 0, latency_ms: float = 0.0, dropped: int = 0, timeouts: int = 0, fps: float = 0.0) -> None:
        if image is not None:
            self._update_pixmap(image)
        if fps > 0:
            self._fps_label.setText(f"{fps:.1f} FPS")

    def _update_pixmap(self, image: np.ndarray) -> None:
        self._image_label.setText("")
        h, w = image.shape[:2]
        bytes_per_line = 3 * w
        qimage = QImage(image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimage)
        self._scale_pixmap()

    def _scale_pixmap(self) -> None:
        if self._pixmap is None:
            return
        label_size = self._image_label.size()
        scaled = self._pixmap.scaled(label_size.width(), label_size.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_pixmap()

    # ---------------------------------------------------------
    # Mouse Events
    # ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._camera_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._camera_id:
            self.double_clicked.emit(self._camera_id)
        super().mouseDoubleClickEvent(event)
