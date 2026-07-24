from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QMessageBox,
)

from gui.theme import (
    COLOR_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_ORANGE,
    COLOR_ALARM_RED,
    COLOR_ALARM_GRAY,
    STYLE_TOOLBAR_BUTTON,
)


COL_TS = 0
COL_SEVERITY = 1
COL_SOURCE = 2
COL_MESSAGE = 3

HEADERS = ["Timestamp", "Severity", "Source", "Message"]

MAX_ENTRIES = 10000


class LogWindow(QMainWindow):
    _instance = None

    @classmethod
    def instance(cls) -> LogWindow | None:
        return cls._instance

    @classmethod
    def log(cls, message: str, severity: str = "INFO", source: str = "GUI") -> None:
        inst = cls._instance
        if inst is not None:
            inst.add_entry(message, severity, source)

    def __init__(self) -> None:
        super().__init__()
        LogWindow._instance = self

        self._entries: list[tuple[str, str, str, str]] = []
        self._filter_text = ""
        self._filter_severity = "All"

        self.setWindowTitle("Event Log")
        self.setMinimumSize(700, 380)
        self.resize(950, 500)

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet(f"background-color: {COLOR_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 3px;")
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)
        t_layout.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search messages...")
        self._search_input.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {COLOR_BORDER}; border-radius: 3px; padding: 4px 8px; font-size: 11px; min-height: 20px; }}"
        )
        self._search_input.setMinimumWidth(200)
        self._search_input.textChanged.connect(self._apply_filters)
        t_layout.addWidget(self._search_input)

        self._severity_filter = QComboBox()
        self._severity_filter.addItems(["All", "INFO", "WARNING", "ERROR"])
        self._severity_filter.setStyleSheet(
            f"QComboBox {{ border: 1px solid {COLOR_BORDER}; border-radius: 3px; padding: 4px 8px; font-size: 11px; min-height: 20px; }}"
        )
        self._severity_filter.currentTextChanged.connect(self._apply_filters)
        t_layout.addWidget(self._severity_filter)

        t_layout.addStretch()

        self._auto_scroll_cb = QCheckBox("Auto Scroll")
        self._auto_scroll_cb.setChecked(True)
        self._auto_scroll_cb.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_PRIMARY}; spacing: 4px;")
        t_layout.addWidget(self._auto_scroll_cb)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
        clear_btn.clicked.connect(self._on_clear)
        t_layout.addWidget(clear_btn)

        export_btn = QPushButton("Export")
        export_btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
        export_btn.clicked.connect(self._on_export)
        t_layout.addWidget(export_btn)

        root.addWidget(toolbar)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(COL_TS, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_SEVERITY, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_MESSAGE, QHeaderView.Stretch)
        hdr.setDefaultAlignment(Qt.AlignLeft)

        root.addWidget(self._table, 1)

        # Status bar
        self._count_label = QLabel("0 entries")
        self._count_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        root.addWidget(self._count_label)

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def add_entry(self, message: str, severity: str = "INFO", source: str = "GUI") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._entries.append((ts, severity, source, message))

        if len(self._entries) > MAX_ENTRIES:
            self._entries.pop(0)

        if self._matches_filter(ts, severity, source, message):
            self._insert_row(len(self._entries) - 1, ts, severity, source, message)

        self._count_label.setText(f"{len(self._entries)} entries")

    # ---------------------------------------------------------
    # Internal
    # ---------------------------------------------------------

    def _insert_row(self, idx: int, ts: str, severity: str, source: str, message: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        def _make(text: str) -> QTableWidgetItem:
            return QTableWidgetItem(text)

        ts_item = _make(ts)
        sev_item = _make(severity)
        src_item = _make(source)
        msg_item = _make(message)

        color_map = {
            "INFO": COLOR_ALARM_GREEN,
            "WARNING": COLOR_ALARM_ORANGE,
            "ERROR": COLOR_ALARM_RED,
        }
        sev_color = color_map.get(severity, COLOR_ALARM_GRAY)
        sev_item.setForeground(self._get_color(sev_color))

        self._table.setItem(row, COL_TS, ts_item)
        self._table.setItem(row, COL_SEVERITY, sev_item)
        self._table.setItem(row, COL_SOURCE, src_item)
        self._table.setItem(row, COL_MESSAGE, msg_item)

        if self._auto_scroll_cb.isChecked():
            self._table.scrollToBottom()

    def _matches_filter(self, ts: str, severity: str, source: str, message: str) -> bool:
        if self._filter_severity != "All" and severity != self._filter_severity:
            return False
        if self._filter_text:
            text = self._filter_text.lower()
            if text not in message.lower() and text not in source.lower():
                return False
        return True

    def _apply_filters(self) -> None:
        self._filter_text = self._search_input.text().strip()
        self._filter_severity = self._severity_filter.currentText()

        self._table.setRowCount(0)
        for i, (ts, sev, src, msg) in enumerate(self._entries):
            if self._matches_filter(ts, sev, src, msg):
                self._insert_row(i, ts, sev, src, msg)

    def _on_clear(self) -> None:
        self._entries.clear()
        self._table.setRowCount(0)
        self._count_label.setText("0 entries")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Event Log", "event_log.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write("Timestamp,Severity,Source,Message\n")
                for ts, sev, src, msg in self._entries:
                    msg_escaped = msg.replace('"', '""')
                    f.write(f'"{ts}","{sev}","{src}","{msg_escaped}"\n')
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))

    @staticmethod
    def _get_color(hex_color: str):
        from PyQt5.QtGui import QColor
        return QColor(hex_color)

    def closeEvent(self, event) -> None:
        LogWindow._instance = None
        super().closeEvent(event)
