from __future__ import annotations

COLOR_BACKGROUND = "#F4F5F7"
COLOR_PANEL = "#FFFFFF"
COLOR_TOOLBAR = "#ECECEC"
COLOR_BORDER = "#D6D6D6"
COLOR_ACCENT = "#1976D2"
COLOR_TEXT_PRIMARY = "#1A1A1A"
COLOR_TEXT_SECONDARY = "#555555"
COLOR_TEXT_DISABLED = "#AAAAAA"
COLOR_ALARM_GREEN = "#4CAF50"
COLOR_ALARM_ORANGE = "#FF9800"
COLOR_ALARM_RED = "#F44336"
COLOR_ALARM_GRAY = "#9E9E9E"
COLOR_SELECTION = "#E3F2FD"
COLOR_HOVER = "#F0F0F0"
FONT_FAMILY = '"Segoe UI", "Arial", sans-serif'

STYLE_MAIN_WINDOW = f"""
QMainWindow {{
    background-color: {COLOR_BACKGROUND};
}}
QWidget {{
    background-color: transparent;
    color: {COLOR_TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: 11px;
}}
QLabel {{
    background: transparent;
    color: {COLOR_TEXT_PRIMARY};
}}
QMenuBar {{
    background-color: {COLOR_TOOLBAR};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 2px 0;
    font-size: 11px;
}}
QMenuBar::item {{
    padding: 4px 12px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background-color: {COLOR_SELECTION};
}}
QMenu {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
}}
QMenu::item:selected {{
    background-color: {COLOR_SELECTION};
    color: {COLOR_ACCENT};
}}
QToolBar {{
    background-color: {COLOR_TOOLBAR};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    spacing: 4px;
    padding: 4px;
}}
QPushButton {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_ACCENT};
}}
QPushButton:pressed {{
    background-color: {COLOR_SELECTION};
}}
QPushButton:disabled {{
    background-color: {COLOR_TOOLBAR};
    color: {COLOR_TEXT_DISABLED};
    border-color: {COLOR_BORDER};
}}
QPushButton#primaryButton {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_PANEL};
    border: 1px solid {COLOR_ACCENT};
    font-weight: bold;
}}
QPushButton#primaryButton:hover {{
    background-color: #1565C0;
}}
QPushButton#dangerButton {{
    background-color: {COLOR_ALARM_RED};
    color: {COLOR_PANEL};
    border: 1px solid {COLOR_ALARM_RED};
    font-weight: bold;
}}
QPushButton#dangerButton:hover {{
    background-color: #D32F2F;
}}
QTableWidget {{
    background-color: {COLOR_PANEL};
    alternate-background-color: #FAFAFA;
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    gridline-color: #E8E8E8;
    selection-background-color: {COLOR_SELECTION};
    selection-color: {COLOR_TEXT_PRIMARY};
}}
QTableWidget::item {{
    padding: 6px 8px;
}}
QTableWidget::item:selected {{
    background-color: {COLOR_SELECTION};
    color: {COLOR_ACCENT};
}}
QHeaderView::section {{
    background-color: {COLOR_TOOLBAR};
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-right: 1px solid {COLOR_BORDER};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 6px 8px;
    font-weight: bold;
    font-size: 10px;
    text-transform: uppercase;
}}
QStatusBar {{
    background-color: {COLOR_TOOLBAR};
    border-top: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
    font-size: 10px;
    padding: 2px 8px;
}}
QStatusBar QLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 10px;
    padding: 0 8px;
    border-right: 1px solid {COLOR_BORDER};
}}
QStatusBar QLabel:last-child {{
    border-right: none;
}}
QSplitter::handle {{
    background-color: {COLOR_BORDER};
    width: 1px;
    height: 1px;
}}
QTreeWidget {{
    background-color: {COLOR_PANEL};
    alternate-background-color: #FAFAFA;
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
}}
QTreeWidget::item {{
    padding: 4px 6px;
}}
QTreeWidget::item:selected {{
    background-color: {COLOR_SELECTION};
    color: {COLOR_ACCENT};
}}
QGroupBox {{
    font-weight: bold;
    font-size: 11px;
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    margin-top: 12px;
    padding: 12px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: {COLOR_TEXT_SECONDARY};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QComboBox {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 22px;
}}
QComboBox:hover {{
    border-color: {COLOR_ACCENT};
}}
QLineEdit {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 22px;
}}
QLineEdit:hover {{
    border-color: {COLOR_ACCENT};
}}
QLineEdit:focus {{
    border-color: {COLOR_ACCENT};
}}
QCheckBox {{
    spacing: 6px;
}}
QDoubleSpinBox, QSpinBox {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 22px;
}}
QFrame#toolbarFrame {{
    background-color: {COLOR_TOOLBAR};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
}}
QFrame#panel {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
}}
QFrame#statusPanel {{
    background-color: {COLOR_TOOLBAR};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
}}
"""

STYLE_TOOLBAR_BUTTON = f"""
QPushButton {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 6px 10px;
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_BORDER};
}}
QPushButton:pressed {{
    background-color: {COLOR_SELECTION};
}}
QPushButton:checked {{
    background-color: {COLOR_SELECTION};
    color: {COLOR_ACCENT};
}}
"""

STYLE_SECTION_HEADER = f"""
QToolButton {{
    background-color: {COLOR_TOOLBAR};
    border: 1px solid {COLOR_BORDER};
    border-radius: 2px;
    padding: 6px 8px;
    font-weight: bold;
    font-size: 11px;
    color: {COLOR_TEXT_SECONDARY};
    text-align: left;
}}
QToolButton:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_ACCENT};
}}
QToolButton::menu-indicator {{
    image: none;
}}
"""

STYLE_STATUS_INDICATOR_OK = f"""
QLabel {{
    color: {COLOR_ALARM_GREEN};
    font-weight: bold;
    font-size: 10px;
}}
"""

STYLE_STATUS_INDICATOR_WARN = f"""
QLabel {{
    color: {COLOR_ALARM_ORANGE};
    font-weight: bold;
    font-size: 10px;
}}
"""

STYLE_STATUS_INDICATOR_ERROR = f"""
QLabel {{
    color: {COLOR_ALARM_RED};
    font-weight: bold;
    font-size: 10px;
}}
"""

STYLE_CAMERA_TILE = f"""
QFrame#cameraTile {{
    background-color: {COLOR_PANEL};
    border: 2px solid {COLOR_BORDER};
    border-radius: 4px;
}}
QFrame#cameraTile:hover {{
    border: 2px solid {COLOR_ACCENT};
}}
"""

STYLE_CAMERA_TILE_SELECTED = f"""
QFrame#cameraTile {{
    background-color: {COLOR_SELECTION};
    border: 3px solid {COLOR_ACCENT};
    border-radius: 4px;
}}
"""
