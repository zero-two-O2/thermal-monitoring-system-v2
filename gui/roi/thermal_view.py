from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from gui.theme import (
    COLOR_BORDER,
    COLOR_PANEL,
    COLOR_TEXT_SECONDARY,
)

PLACEHOLDER_TEXT = (
    "No Camera Connected\n\n"
    "Connect a camera from\nthe Main Window"
)


class ThermalView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_handle: int | None = None
        self._image_shape: tuple[int, int] = (0, 0)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel(PLACEHOLDER_TEXT)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 14px; "
            f"background-color: {COLOR_PANEL}; border: 1px solid {COLOR_BORDER};"
        )
        self._layout.addWidget(self._placeholder)

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
        if self._window_handle is None:
            return
        self._placeholder.hide()
        try:
            import halcon as ha
            ha.disp_obj(image, self._window_handle)
        except Exception:
            pass

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

    def show_feed(self) -> None:
        self._placeholder.hide()

    def show_placeholder(self) -> None:
        self._placeholder.show()
        self.clear_display()
