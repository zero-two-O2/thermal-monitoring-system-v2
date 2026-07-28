from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy


class ThermalView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_handle: int | None = None
        self._image_shape: tuple[int, int] = (0, 0)
        self._pixmap: QPixmap | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image_label.setStyleSheet("background-color: #1a1a1a;")
        self._layout.addWidget(self._image_label)

        self._placeholder = QLabel("No camera feed")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #666666; font-size: 14px;")
        self._layout.addWidget(self._placeholder)

        self._show_placeholder()

    def create_window(self, width: int, height: int) -> None:
        self._window_handle = None
        try:
            import halcon as ha
            self._window_handle = ha.open_window(
                0, 0, width, height, self.winId(), "buffer", ""
            )
        except Exception:
            pass

    @property
    def window_handle(self) -> int | None:
        return self._window_handle

    @property
    def image_shape(self) -> tuple[int, int]:
        return self._image_shape

    def display_image(self, image: object) -> None:
        if isinstance(image, np.ndarray):
            self._display_numpy(image)
            return
        if self._window_handle is None:
            return
        try:
            import halcon as ha
            ha.disp_obj(image, self._window_handle)
        except Exception:
            pass

    def _display_numpy(self, image: np.ndarray) -> None:
        if image.ndim != 3 or image.shape[2] != 3:
            return
        h, w = image.shape[:2]
        self._image_shape = (h, w)
        import cv2
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * w
        qimage = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimage)
        self._scale_pixmap()
        self._show_feed()

    def _scale_pixmap(self) -> None:
        if self._pixmap is None:
            return
        label_size = self._image_label.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            return
        scaled = self._pixmap.scaled(
            label_size.width(), label_size.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_pixmap()

    def resize_window(self, width: int, height: int) -> None:
        if self._window_handle is None:
            self.create_window(width, height)
            return
        try:
            import halcon as ha
            ha.set_window_extents(self._window_handle, 0, 0, width, height)
        except Exception:
            pass

    def clear_display(self) -> None:
        self._pixmap = None
        self._image_label.clear()
        if self._window_handle is None:
            return
        try:
            import halcon as ha
            ha.clear_window(self._window_handle)
        except Exception:
            pass

    def convert_to_image_coords(
        self, win_row: float, win_col: float
    ) -> tuple[float, float]:
        if self._window_handle is None:
            return (win_row, win_col)
        try:
            import halcon as ha
            return ha.convert_coordinates_window_to_image(
                self._window_handle, win_row, win_col
            )
        except Exception:
            return (win_row, win_col)

    def _show_feed(self) -> None:
        self._image_label.show()
        self._placeholder.hide()

    def _show_placeholder(self) -> None:
        self._image_label.hide()
        self._placeholder.show()

    def show_feed(self) -> None:
        self._show_feed()

    def show_placeholder(self) -> None:
        self._show_placeholder()
        self.clear_display()
