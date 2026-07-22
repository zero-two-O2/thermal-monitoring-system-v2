"""
camera_tile.py

Compact, selectable camera tile widget for the qualification tool.

Each tile displays:
- Thermal image (~80% of space)
- Compact status bar (Frame, Seq, Lat, Drop, TO)
- SELECTED indicator when active
- Click-to-select behavior
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QVBoxLayout


STYLE_TILE_DEFAULT = """
QFrame#cameraTile {
    background-color: #F5F5F5;
    border: 2px solid #CCCCCC;
    border-radius: 4px;
}
QFrame#cameraTile:hover {
    border: 2px solid #999999;
}
"""

STYLE_TILE_SELECTED = """
QFrame#cameraTile {
    background-color: #E8F0FE;
    border: 3px solid #1A73E8;
    border-radius: 4px;
}
"""

STYLE_LABEL_SELECTED = """
QLabel {
    color: #1A73E8;
    font-weight: bold;
    font-size: 10px;
}
"""

STYLE_STAT_LABEL = """
QLabel {
    color: #333333;
    font-size: 11px;
    font-family: "Consolas", "Courier New", monospace;
}
"""

STYLE_CAMERA_NAME = """
QLabel {
    color: #1A1A1A;
    font-size: 12px;
    font-weight: bold;
}
"""


class CameraTile(QFrame):
    """
    Compact camera tile with thermal image and statistics.
    """

    clicked = pyqtSignal(str)

    SELECTED_STYLESHEET = STYLE_TILE_SELECTED
    DEFAULT_STYLESHEET = STYLE_TILE_DEFAULT

    def __init__(
        self,
        camera_id: str,
        camera_name: str,
        parent=None,
    ) -> None:

        super().__init__(parent)

        self._camera_id = camera_id
        self._camera_name = camera_name
        self._selected = False
        self._frame_count = 0
        self._sequence = 0
        self._latency_ms = 0.0
        self._dropped = 0
        self._timeouts = 0
        self._fps = 0.0
        self._last_frame_time = 0.0
        self._pixmap: QPixmap | None = None

        self.setObjectName("cameraTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(STYLE_TILE_DEFAULT)

        self._build_ui()

    # ---------------------------------------------------------
    # Properties
    # ---------------------------------------------------------

    @property
    def camera_id(self) -> str:

        return self._camera_id

    @property
    def is_selected(self) -> bool:

        return self._selected

    def set_selected(
        self,
        selected: bool,
    ) -> None:

        self._selected = selected

        if selected:

            self.setStyleSheet(STYLE_TILE_SELECTED)
            self._selected_label.show()

        else:

            self.setStyleSheet(STYLE_TILE_DEFAULT)
            self._selected_label.hide()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def _build_ui(self) -> None:

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        #
        # Camera name + SELECTED badge
        #

        header = QHBoxLayout()
        header.setSpacing(4)

        self._name_label = QLabel(self._camera_name)
        self._name_label.setStyleSheet(STYLE_CAMERA_NAME)

        self._selected_label = QLabel("SELECTED")
        self._selected_label.setStyleSheet(STYLE_LABEL_SELECTED)
        self._selected_label.hide()

        header.addWidget(self._name_label)
        header.addStretch()
        header.addWidget(self._selected_label)

        layout.addLayout(header)

        #
        # Thermal image
        #

        self._image_label = QLabel()
        self._image_label.setAlignment(
            Qt.AlignCenter
        )
        self._image_label.setMinimumSize(120, 120)
        self._image_label.setStyleSheet(
            "background-color: #E0E0E0; border: 1px solid #CCCCCC;"
        )

        layout.addWidget(
            self._image_label,
            stretch=1,
        )

        #
        # Compact status bar
        #

        stats = QHBoxLayout()
        stats.setSpacing(8)

        self._frame_label = QLabel("F:0")
        self._seq_label = QLabel("S:0")
        self._lat_label = QLabel("L:0ms")
        self._drop_label = QLabel("D:0")
        self._to_label = QLabel("T:0")
        self._fps_label = QLabel("FPS:0")

        for label in (
            self._frame_label,
            self._seq_label,
            self._lat_label,
            self._drop_label,
            self._to_label,
            self._fps_label,
        ):
            label.setStyleSheet(STYLE_STAT_LABEL)
            stats.addWidget(label)

        layout.addLayout(stats)

    # ---------------------------------------------------------
    # Frame Update
    # ---------------------------------------------------------

    def update_frame(
        self,
        image: np.ndarray | None,
        frame_count: int = 0,
        sequence: int = 0,
        latency_ms: float = 0.0,
        dropped: int = 0,
        timeouts: int = 0,
        fps: float = 0.0,
    ) -> None:

        self._frame_count = frame_count
        self._sequence = sequence
        self._latency_ms = latency_ms
        self._dropped = dropped
        self._timeouts = timeouts
        self._fps = fps

        if image is not None:

            self._update_pixmap(image)

        self._update_stats()

    def _update_pixmap(
        self,
        image: np.ndarray,
    ) -> None:

        h, w = image.shape[:2]
        bytes_per_line = 3 * w

        qimage = QImage(
            image.data,
            w,
            h,
            bytes_per_line,
            QImage.Format_RGB888,
        )

        self._pixmap = QPixmap.fromImage(
            qimage
        )

        self._scale_pixmap()

    def _scale_pixmap(self) -> None:

        if self._pixmap is None:
            return

        label_size = self._image_label.size()

        scaled = self._pixmap.scaled(
            label_size.width(),
            label_size.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self._image_label.setPixmap(scaled)

    def _update_stats(self) -> None:

        self._frame_label.setText(
            f"F:{self._frame_count}"
        )
        self._seq_label.setText(
            f"S:{self._sequence}"
        )
        self._lat_label.setText(
            f"L:{self._latency_ms:.0f}ms"
        )
        self._drop_label.setText(
            f"D:{self._dropped}"
        )
        self._to_label.setText(
            f"T:{self._timeouts}"
        )
        self._fps_label.setText(
            f"FPS:{self._fps:.0f}"
        )

    # ---------------------------------------------------------
    # Resize
    # ---------------------------------------------------------

    def resizeEvent(self, event) -> None:

        super().resizeEvent(event)
        self._scale_pixmap()

    # ---------------------------------------------------------
    # Mouse Events
    # ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:

        self.clicked.emit(self._camera_id)
        super().mousePressEvent(event)
