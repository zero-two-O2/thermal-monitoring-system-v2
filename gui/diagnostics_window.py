from __future__ import annotations

import platform
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.application_controller import ApplicationController
from utilities import logger

from gui.theme import (
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)


class DiagnosticsWindow(QMainWindow):
    POLL_INTERVAL_MS = 2000

    def __init__(self, controller: ApplicationController) -> None:
        super().__init__()
        self._controller = controller

        self.setWindowTitle("Diagnostics")
        self.setMinimumSize(700, 500)
        self.resize(850, 600)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_INTERVAL_MS)
        self._poll()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(self._build_system_group())
        root.addWidget(self._build_camera_group(), 1)
        root.addWidget(self._build_log_output())

    # ---------------------------------------------------------
    # System Group
    # ---------------------------------------------------------

    def _build_system_group(self) -> QGroupBox:
        group = QGroupBox("System")
        grid = QGridLayout(group)
        grid.setSpacing(6)

        self._sys_labels = {}
        fields = [
            ("Python:", "_sys_python"),
            ("Qt:", "_sys_qt"),
            ("HALCON:", "_sys_halcon"),
            ("Platform:", "_sys_platform"),
            ("Machine:", "_sys_machine"),
        ]
        for col, (label_text, attr) in enumerate(fields):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"font-weight: bold; color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
            val = QLabel("--")
            val.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 10px;")
            self._sys_labels[attr] = val
            grid.addWidget(lbl, 0, col * 2)
            grid.addWidget(val, 0, col * 2 + 1)

        # Set values
        self._sys_labels["_sys_python"].setText(sys.version.split()[0])
        from PyQt5.QtCore import QT_VERSION_STR
        self._sys_labels["_sys_qt"].setText(QT_VERSION_STR)
        try:
            import halcon as ha
            self._sys_labels["_sys_halcon"].setText(ha.__version__ if hasattr(ha, "__version__") else "available")
        except ImportError:
            self._sys_labels["_sys_halcon"].setText("Not loaded")
        self._sys_labels["_sys_platform"].setText(platform.system())
        self._sys_labels["_sys_machine"].setText(platform.machine())

        return group

    # ---------------------------------------------------------
    # Camera Group
    # ---------------------------------------------------------

    def _build_camera_group(self) -> QGroupBox:
        group = QGroupBox("Camera Diagnostics")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(4)

        self._camera_table = QTableWidget(0, 7)
        self._camera_table.setHorizontalHeaderLabels([
            "Camera", "Connection", "FPS", "Latency", "Frame Age", "Dropped", "Status"
        ])
        self._camera_table.setAlternatingRowColors(True)
        self._camera_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._camera_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._camera_table.verticalHeader().setVisible(False)
        self._camera_table.horizontalHeader().setStretchLastSection(True)
        self._camera_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._camera_table.setStyleSheet(
            f"QTableWidget {{ border: 1px solid {COLOR_BORDER}; border-radius: 2px; }} "
            f"QTableWidget::item {{ padding: 4px 6px; font-size: 10px; }} "
            f"QHeaderView::section {{ font-size: 9px; padding: 3px 4px; }}"
        )
        layout.addWidget(self._camera_table)

        return group

    # ---------------------------------------------------------
    # Log Output
    # ---------------------------------------------------------

    def _build_log_output(self) -> QGroupBox:
        group = QGroupBox("Recent Log Output")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 16, 8, 8)

        self._log_display = QLabel("No recent log entries.")
        self._log_display.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic; "
            f"background-color: {COLOR_TOOLBAR}; border: 1px solid {COLOR_BORDER}; border-radius: 2px; "
            f"padding: 8px;"
        )
        self._log_display.setWordWrap(True)
        self._log_display.setMinimumHeight(60)
        self._log_display.setMaximumHeight(100)
        self._log_display.setAlignment(Qt.AlignTop)
        layout.addWidget(self._log_display)

        return group

    # ---------------------------------------------------------
    # Polling
    # ---------------------------------------------------------

    def _poll(self) -> None:
        try:
            cameras = self._controller.get_all_cameras()
            connected = self._controller.connected_cameras()
            running = self._controller.running_cameras()

            self._camera_table.setRowCount(len(cameras))
            for i, ctx in enumerate(cameras):
                cm = ctx.camera_model
                is_connected = ctx in connected
                is_running = ctx in running

                def _item(text: str) -> QTableWidgetItem:
                    return QTableWidgetItem(text)

                self._camera_table.setItem(i, 0, _item(cm.camera_name))
                self._camera_table.setItem(i, 1, _item("Connected" if is_connected else "Disconnected"))
                self._camera_table.setItem(i, 2, _item("N/A"))
                self._camera_table.setItem(i, 3, _item("N/A"))
                self._camera_table.setItem(i, 4, _item("N/A"))
                self._camera_table.setItem(i, 5, _item("N/A"))
                self._camera_table.setItem(i, 6, _item("Running" if is_running else "Idle"))

            count = len(cameras)
            connected_count = len(connected)
            running_count = len(running)
            status_parts = [
                f"Cameras: {count}",
                f"Connected: {connected_count}",
                f"Streaming: {running_count}",
            ]
            self._log_display.setText("  |  ".join(status_parts))

        except Exception:
            logger.exception("Diagnostics poll failed")

    def stop(self) -> None:
        self._timer.stop()
