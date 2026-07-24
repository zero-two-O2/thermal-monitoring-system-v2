from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui.theme import (
    COLOR_ACCENT,
    COLOR_PANEL,
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_GRAY,
)


STYLE_BUTTON_NUC = f"""
QPushButton {{
    background-color: #E8F0FE;
    color: {COLOR_ACCENT};
    border: 1px solid {COLOR_ACCENT};
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 11px;
    font-weight: bold;
}}
QPushButton:hover {{ background-color: #D2E3FC; }}
QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: #AAAAAA; border: 1px solid {COLOR_BORDER}; }}
"""

STYLE_BUTTON = f"""
QPushButton {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 6px 14px;
    font-size: 11px;
}}
QPushButton:hover {{ background-color: #F0F0F0; border-color: {COLOR_ACCENT}; }}
QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: #AAAAAA; border: 1px solid {COLOR_BORDER}; }}
"""

STYLE_BUTTON_SMALL = f"""
QPushButton {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 10px;
    font-size: 10px;
    min-width: 28px;
}}
QPushButton:hover {{ background-color: #F0F0F0; border-color: {COLOR_ACCENT}; }}
QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: #AAAAAA; border: 1px solid {COLOR_BORDER}; }}
"""

STYLE_VALUE = """
QLabel#valueLabel {
    color: #1A1A1A;
    font-size: 14px;
    font-weight: bold;
    font-family: "Consolas", "Courier New", monospace;
}
"""


class CameraControlPanel(QWidget):
    nuc_clicked = pyqtSignal()
    focus_near_clicked = pyqtSignal()
    focus_far_clicked = pyqtSignal()
    focus_fine_minus_clicked = pyqtSignal()
    focus_fine_plus_clicked = pyqtSignal()
    position_changed = pyqtSignal(str)
    ptz_up_clicked = pyqtSignal()
    ptz_down_clicked = pyqtSignal()
    ptz_left_clicked = pyqtSignal()
    ptz_right_clicked = pyqtSignal()
    ptz_home_clicked = pyqtSignal()
    go_to_position_clicked = pyqtSignal(str)
    home_position_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.clear_selection()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._build_camera_info(layout)
        self._build_position_group(layout)
        self._build_ptz_group(layout)
        self._build_focus_group(layout)
        self._build_nuc_group(layout)

        layout.addStretch()

    def _build_camera_info(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Camera")
        form = QVBoxLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(2)

        self._no_selection_label = QLabel("No camera selected.\nSelect a camera from the list above.")
        self._no_selection_label.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 11px; font-style: italic;")
        form.addWidget(self._no_selection_label)

        self._camera_name_label = QLabel()
        self._camera_name_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_ACCENT};")
        self._camera_name_label.hide()
        form.addWidget(self._camera_name_label)

        self._camera_info_label = QLabel()
        self._camera_info_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; line-height: 1.5;")
        self._camera_info_label.hide()
        form.addWidget(self._camera_info_label)

        self._camera_status_label = QLabel()
        self._camera_status_label.setStyleSheet(f"color: {COLOR_ALARM_GREEN}; font-size: 10px;")
        self._camera_status_label.hide()
        form.addWidget(self._camera_status_label)

        layout.addWidget(group)

    def _build_position_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Position")
        form = QVBoxLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)

        pos_row = QHBoxLayout()
        pos_row.setSpacing(4)
        pos_label = QLabel("Current:")
        pos_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        pos_row.addWidget(pos_label)

        self._position_combo = QComboBox()
        self._position_combo.setMinimumWidth(80)
        pos_row.addWidget(self._position_combo, 1)
        form.addLayout(pos_row)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(4)
        self._prev_pos_btn = QPushButton("Prev")
        self._prev_pos_btn.setStyleSheet(STYLE_BUTTON_SMALL)
        self._next_pos_btn = QPushButton("Next")
        self._next_pos_btn.setStyleSheet(STYLE_BUTTON_SMALL)
        self._goto_pos_btn = QPushButton("Go To")
        self._goto_pos_btn.setStyleSheet(STYLE_BUTTON_SMALL)
        self._home_pos_btn = QPushButton("Home")
        self._home_pos_btn.setStyleSheet(STYLE_BUTTON_SMALL)

        nav_row.addWidget(self._prev_pos_btn)
        nav_row.addWidget(self._next_pos_btn)
        nav_row.addWidget(self._goto_pos_btn)
        nav_row.addWidget(self._home_pos_btn)
        form.addLayout(nav_row)

        for btn in [self._prev_pos_btn, self._next_pos_btn, self._goto_pos_btn, self._home_pos_btn]:
            btn.setEnabled(False)

        layout.addWidget(group)

    def _build_ptz_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("PTZ")
        form = QVBoxLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)
        form.setAlignment(Qt.AlignCenter)

        d = QHBoxLayout()
        d.setSpacing(4)
        d.addStretch()
        self._ptz_up = QPushButton("\u2191")
        self._ptz_up.setStyleSheet(STYLE_BUTTON_SMALL)
        self._ptz_up.setFixedWidth(36)
        d.addWidget(self._ptz_up)
        d.addStretch()
        form.addLayout(d)

        m = QHBoxLayout()
        m.setSpacing(4)
        m.addStretch()
        self._ptz_left = QPushButton("\u2190")
        self._ptz_left.setStyleSheet(STYLE_BUTTON_SMALL)
        self._ptz_left.setFixedWidth(36)
        m.addWidget(self._ptz_left)

        self._ptz_home = QPushButton("HOME")
        self._ptz_home.setStyleSheet(STYLE_BUTTON_SMALL)
        self._ptz_home.setFixedWidth(60)
        self._ptz_home.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ACCENT}; color: white; border: none; border-radius: 3px; padding: 4px 10px; font-size: 10px; font-weight: bold; }} "
            f"QPushButton:hover {{ background-color: #1565C0; }} "
            f"QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: #AAAAAA; }}"
        )
        m.addWidget(self._ptz_home)

        self._ptz_right = QPushButton("\u2192")
        self._ptz_right.setStyleSheet(STYLE_BUTTON_SMALL)
        self._ptz_right.setFixedWidth(36)
        m.addWidget(self._ptz_right)
        m.addStretch()
        form.addLayout(m)

        d2 = QHBoxLayout()
        d2.setSpacing(4)
        d2.addStretch()
        self._ptz_down = QPushButton("\u2193")
        self._ptz_down.setStyleSheet(STYLE_BUTTON_SMALL)
        self._ptz_down.setFixedWidth(36)
        d2.addWidget(self._ptz_down)
        d2.addStretch()
        form.addLayout(d2)

        for btn in [self._ptz_up, self._ptz_down, self._ptz_left, self._ptz_right, self._ptz_home]:
            btn.setEnabled(False)

        layout.addWidget(group)

    def _build_focus_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Focus")
        form = QVBoxLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)

        main_row = QHBoxLayout()
        main_row.setSpacing(4)
        self._focus_near_btn = QPushButton("Near")
        self._focus_near_btn.setStyleSheet(STYLE_BUTTON)
        self._focus_far_btn = QPushButton("Far")
        self._focus_far_btn.setStyleSheet(STYLE_BUTTON)
        main_row.addWidget(self._focus_near_btn)
        main_row.addWidget(self._focus_far_btn)
        form.addLayout(main_row)

        fine_row = QHBoxLayout()
        fine_row.setSpacing(4)
        fine_label = QLabel("Fine:")
        fine_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        fine_row.addWidget(fine_label)
        self._focus_fine_minus = QPushButton("-")
        self._focus_fine_minus.setStyleSheet(STYLE_BUTTON_SMALL)
        self._focus_fine_minus.setFixedWidth(32)
        self._focus_fine_plus = QPushButton("+")
        self._focus_fine_plus.setStyleSheet(STYLE_BUTTON_SMALL)
        self._focus_fine_plus.setFixedWidth(32)
        fine_row.addWidget(self._focus_fine_minus)
        fine_row.addWidget(self._focus_fine_plus)
        fine_row.addStretch()
        form.addLayout(fine_row)

        dist_label = QLabel("Distance:")
        dist_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        form.addWidget(dist_label)

        self._focus_distance_label = QLabel("---")
        self._focus_distance_label.setObjectName("valueLabel")
        self._focus_distance_label.setStyleSheet(STYLE_VALUE)
        form.addWidget(self._focus_distance_label)

        for btn in [self._focus_near_btn, self._focus_far_btn, self._focus_fine_minus, self._focus_fine_plus]:
            btn.setEnabled(False)

        layout.addWidget(group)

    def _build_nuc_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("NUC")
        form = QVBoxLayout(group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)

        self._nuc_button = QPushButton("Execute NUC")
        self._nuc_button.setStyleSheet(STYLE_BUTTON_NUC)
        self._nuc_button.setEnabled(False)
        form.addWidget(self._nuc_button)

        layout.addWidget(group)

        self._nuc_button.clicked.connect(self._on_nuc_clicked)
        self._focus_near_btn.clicked.connect(self._on_focus_near)
        self._focus_far_btn.clicked.connect(self._on_focus_far)
        self._focus_fine_minus.clicked.connect(self.focus_fine_minus_clicked.emit)
        self._focus_fine_plus.clicked.connect(self.focus_fine_plus_clicked.emit)
        self._ptz_up.clicked.connect(self.ptz_up_clicked.emit)
        self._ptz_down.clicked.connect(self.ptz_down_clicked.emit)
        self._ptz_left.clicked.connect(self.ptz_left_clicked.emit)
        self._ptz_right.clicked.connect(self.ptz_right_clicked.emit)
        self._ptz_home.clicked.connect(self.ptz_home_clicked.emit)
        self._prev_pos_btn.clicked.connect(lambda: self.position_changed.emit("prev"))
        self._next_pos_btn.clicked.connect(lambda: self.position_changed.emit("next"))
        self._goto_pos_btn.clicked.connect(lambda: self.position_changed.emit(self._position_combo.currentText()))
        self._home_pos_btn.clicked.connect(self.home_position_clicked.emit)

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def show_selection(self, camera_id: str, focus_distance: float | None = None) -> None:
        self._no_selection_label.hide()
        self._camera_name_label.show()
        self._camera_info_label.show()
        self._camera_status_label.show()

        self._camera_name_label.setText(camera_id)
        self._camera_status_label.setText("Connected")
        self._camera_status_label.setStyleSheet(f"color: {COLOR_ALARM_GREEN}; font-size: 10px;")

        self._enable_all(True)

        if focus_distance is not None:
            self._focus_distance_label.setText(f"{focus_distance:.0f} mm")
        else:
            self._focus_distance_label.setText("---")

    def update_focus_distance(self, distance_mm: float) -> None:
        self._focus_distance_label.setText(f"{distance_mm:.0f} mm")

    def update_camera_info(self, serial: str = "", model: str = "", ip: str = "", fps: float = 0.0) -> None:
        parts = []
        if serial:
            parts.append("S/N: " + serial)
        if model:
            parts.append(model)
        if ip:
            parts.append(ip)
        if fps > 0:
            parts.append(f"{fps:.1f} FPS")
        self._camera_info_label.setText(" | ".join(parts))

    def set_positions(self, positions: list[str], current: str = "") -> None:
        self._position_combo.clear()
        for p in positions:
            self._position_combo.addItem(p)
        if current:
            idx = self._position_combo.findText(current)
            if idx >= 0:
                self._position_combo.setCurrentIndex(idx)

    def clear_selection(self) -> None:
        self._no_selection_label.show()
        self._camera_name_label.hide()
        self._camera_info_label.hide()
        self._camera_status_label.hide()
        self._enable_all(False)
        self._focus_distance_label.setText("---")

    def _enable_all(self, enabled: bool) -> None:
        for btn in [self._nuc_button, self._focus_near_btn, self._focus_far_btn,
                     self._focus_fine_minus, self._focus_fine_plus,
                     self._ptz_up, self._ptz_down, self._ptz_left, self._ptz_right, self._ptz_home,
                     self._prev_pos_btn, self._next_pos_btn, self._goto_pos_btn, self._home_pos_btn]:
            btn.setEnabled(enabled)
        self._position_combo.setEnabled(enabled)

    def set_nuc_busy(self, busy: bool) -> None:
        self._nuc_button.setEnabled(not busy)
        self._nuc_button.setText("NUC in progress..." if busy else "Execute NUC")

    def set_focus_busy(self, busy: bool) -> None:
        self._focus_near_btn.setEnabled(not busy)
        self._focus_far_btn.setEnabled(not busy)

    def _on_nuc_clicked(self) -> None:
        self.nuc_clicked.emit()

    def _on_focus_near(self) -> None:
        self.focus_near_clicked.emit()

    def _on_focus_far(self) -> None:
        self.focus_far_clicked.emit()
