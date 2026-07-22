"""
camera_control_panel.py

Single camera control panel for the qualification tool.

Controls the currently selected camera:
- Manual NUC button
- Focus Near / Focus Far buttons
- Current focus distance display
- Selected camera information

All operations delegate to the existing TV46LCamera APIs.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QVBoxLayout


STYLE_PANEL = """
QFrame#controlPanel {
    background-color: #FAFAFA;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
}
"""

STYLE_PANEL_TITLE = """
QLabel {
    color: #1A1A1A;
    font-size: 13px;
    font-weight: bold;
}
"""

STYLE_SELECTED_INFO = """
QLabel {
    color: #1A73E8;
    font-size: 14px;
    font-weight: bold;
}
"""

STYLE_SECTION_LABEL = """
QLabel {
    color: #555555;
    font-size: 11px;
    font-weight: bold;
}
"""

STYLE_FOCUS_VALUE = """
QLabel {
    color: #1A1A1A;
    font-size: 16px;
    font-weight: bold;
    font-family: "Consolas", "Courier New", monospace;
}
"""

STYLE_BUTTON_NUC = """
QPushButton {
    background-color: #E8F0FE;
    color: #1A73E8;
    border: 1px solid #1A73E8;
    border-radius: 4px;
    padding: 8px 24px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #D2E3FC;
}
QPushButton:pressed {
    background-color: #B3D1F9;
}
QPushButton:disabled {
    background-color: #F0F0F0;
    color: #AAAAAA;
    border: 1px solid #CCCCCC;
}
"""

STYLE_BUTTON_FOCUS = """
QPushButton {
    background-color: #F0F0F0;
    color: #333333;
    border: 1px solid #CCCCCC;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #E0E0E0;
    border: 1px solid #999999;
}
QPushButton:pressed {
    background-color: #D0D0D0;
}
QPushButton:disabled {
    background-color: #F0F0F0;
    color: #AAAAAA;
    border: 1px solid #CCCCCC;
}
"""

STYLE_NO_SELECTION = """
QLabel {
    color: #999999;
    font-size: 12px;
    font-style: italic;
}
"""


class CameraControlPanel(QFrame):
    """
    Control panel for the selected camera.
    """

    nuc_clicked = pyqtSignal()
    focus_near_clicked = pyqtSignal()
    focus_far_clicked = pyqtSignal()

    def __init__(
        self,
        parent=None,
    ) -> None:

        super().__init__(parent)

        self.setObjectName("controlPanel")
        self.setStyleSheet(STYLE_PANEL)

        self._build_ui()
        self.clear_selection()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def _build_ui(self) -> None:

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        #
        # Header
        #

        header = QHBoxLayout()

        title = QLabel("Camera Control")
        title.setStyleSheet(STYLE_PANEL_TITLE)

        header.addWidget(title)
        header.addStretch()

        layout.addLayout(header)

        #
        # Selected camera info
        #

        self._selected_label = QLabel()
        self._selected_label.setStyleSheet(STYLE_SELECTED_INFO)
        layout.addWidget(self._selected_label)

        self._no_selection_label = QLabel(
            "No camera selected. Click a camera tile to select."
        )
        self._no_selection_label.setStyleSheet(STYLE_NO_SELECTION)
        layout.addWidget(self._no_selection_label)

        #
        # Separator
        #

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #D0D0D0;")
        layout.addWidget(sep)

        #
        # Manual NUC
        #

        nuc_layout = QHBoxLayout()
        nuc_layout.setSpacing(8)

        nuc_label = QLabel("Manual NUC")
        nuc_label.setStyleSheet(STYLE_SECTION_LABEL)

        self._nuc_button = QPushButton("Execute NUC")
        self._nuc_button.setStyleSheet(STYLE_BUTTON_NUC)
        self._nuc_button.clicked.connect(
            self._on_nuc_clicked
        )

        nuc_layout.addWidget(nuc_label)
        nuc_layout.addWidget(self._nuc_button)
        nuc_layout.addStretch()

        layout.addLayout(nuc_layout)

        #
        # Focus Control
        #

        focus_label = QLabel("Focus")
        focus_label.setStyleSheet(STYLE_SECTION_LABEL)

        layout.addWidget(focus_label)

        focus_buttons = QHBoxLayout()
        focus_buttons.setSpacing(8)

        self._focus_near_button = QPushButton("<< Near")
        self._focus_near_button.setStyleSheet(STYLE_BUTTON_FOCUS)
        self._focus_near_button.clicked.connect(
            self._on_focus_near
        )

        self._focus_far_button = QPushButton("Far >>")
        self._focus_far_button.setStyleSheet(STYLE_BUTTON_FOCUS)
        self._focus_far_button.clicked.connect(
            self._on_focus_far
        )

        focus_buttons.addWidget(self._focus_near_button)
        focus_buttons.addWidget(self._focus_far_button)
        focus_buttons.addStretch()

        layout.addLayout(focus_buttons)

        #
        # Current Focus
        #

        focus_value = QHBoxLayout()
        focus_value.setSpacing(8)

        focus_current_label = QLabel("Current Focus:")
        focus_current_label.setStyleSheet(STYLE_SECTION_LABEL)

        self._focus_value_label = QLabel("---")
        self._focus_value_label.setStyleSheet(STYLE_FOCUS_VALUE)

        focus_value.addWidget(focus_current_label)
        focus_value.addWidget(self._focus_value_label)
        focus_value.addStretch()

        layout.addLayout(focus_value)

        layout.addStretch()

    # ---------------------------------------------------------
    # Selection
    # ---------------------------------------------------------

    def show_selection(
        self,
        camera_id: str,
        focus_distance: float | None = None,
    ) -> None:

        self._selected_label.setText(
            f"Selected: {camera_id}"
        )
        self._selected_label.show()
        self._no_selection_label.hide()

        self._nuc_button.setEnabled(True)
        self._focus_near_button.setEnabled(True)
        self._focus_far_button.setEnabled(True)

        if focus_distance is not None:

            self._focus_value_label.setText(
                f"{focus_distance:.0f} mm"
            )

        else:

            self._focus_value_label.setText("---")

    def update_focus_distance(
        self,
        distance_mm: float,
    ) -> None:

        self._focus_value_label.setText(
            f"{distance_mm:.0f} mm"
        )

    def clear_selection(self) -> None:

        self._selected_label.hide()
        self._no_selection_label.show()

        self._nuc_button.setEnabled(False)
        self._focus_near_button.setEnabled(False)
        self._focus_far_button.setEnabled(False)

        self._focus_value_label.setText("---")

    # ---------------------------------------------------------
    # Button States
    # ---------------------------------------------------------

    def set_nuc_busy(
        self,
        busy: bool,
    ) -> None:

        self._nuc_button.setEnabled(not busy)

        if busy:

            self._nuc_button.setText("NUC in progress...")

        else:

            self._nuc_button.setText("Execute NUC")

    def set_focus_busy(
        self,
        busy: bool,
    ) -> None:

        self._focus_near_button.setEnabled(not busy)
        self._focus_far_button.setEnabled(not busy)

    # ---------------------------------------------------------
    # Slots
    # ---------------------------------------------------------

    def _on_nuc_clicked(self) -> None:

        self.nuc_clicked.emit()

    def _on_focus_near(self) -> None:

        self.focus_near_clicked.emit()

    def _on_focus_far(self) -> None:

        self.focus_far_clicked.emit()
