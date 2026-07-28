from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.application_controller import ApplicationController

from gui.theme import (
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_GRAY,
    STYLE_MAIN_WINDOW,
)

from gui.roi import ThermalView


class _StatisticsTable(QTableWidget):
    COL_ROI = 0
    COL_MIN = 1
    COL_AVG = 2
    COL_MAX = 3
    COL_ALARM = 4

    HEADERS = ["ROI", "Min", "Avg", "Max", "Alarm"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ROI, QHeaderView.Stretch)
        hdr.setStretchLastSection(True)


class _AlarmHistoryTable(QTableWidget):
    COL_TIMESTAMP = 0
    COL_ROI = 1
    COL_LEVEL = 2
    COL_TEMPERATURE = 3
    COL_EVENT = 4

    HEADERS = ["Timestamp", "ROI", "Level", "Temperature", "Event"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_EVENT, QHeaderView.Stretch)


class CameraDetailWindow(QWidget):
    POLL_INTERVAL_MS = 100

    def __init__(self, camera_id: str, camera_name: str, controller: ApplicationController, parent=None) -> None:
        super().__init__(parent)

        self._camera_id = camera_id
        self._camera_name = camera_name
        self._controller = controller

        self.setWindowTitle("Camera Detail - " + camera_name)
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self._build_ui()
        self._apply_theme()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = self._build_header()
        root.addWidget(header)

        content = QVBoxLayout()
        content.setContentsMargins(16, 16, 16, 16)
        content.setSpacing(12)

        viewer_splitter = QSplitter(Qt.Horizontal)
        viewer_splitter.setHandleWidth(1)

        thermal_container = QFrame()
        thermal_container.setObjectName("panel")
        thermal_layout = QVBoxLayout(thermal_container)
        thermal_layout.setContentsMargins(4, 4, 4, 4)
        self._thermal_view = ThermalView()
        thermal_layout.addWidget(self._thermal_view)
        viewer_splitter.addWidget(thermal_container)

        visible_container = QFrame()
        visible_container.setObjectName("panel")
        visible_layout = QVBoxLayout(visible_container)
        visible_layout.setContentsMargins(4, 4, 4, 4)
        self._visible_view = ThermalView()
        visible_layout.addWidget(self._visible_view)
        viewer_splitter.addWidget(visible_container)

        viewer_splitter.setStretchFactor(0, 1)
        viewer_splitter.setStretchFactor(1, 1)

        content.addWidget(viewer_splitter, 3)

        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.setHandleWidth(1)

        stats_section = QFrame()
        stats_section.setObjectName("panel")
        stats_layout = QVBoxLayout(stats_section)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setSpacing(4)
        stats_label = QLabel("ROI Statistics")
        stats_label.setStyleSheet(f"font-weight: bold; color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        stats_layout.addWidget(stats_label)
        self._stats_table = _StatisticsTable()
        stats_layout.addWidget(self._stats_table)
        bottom_splitter.addWidget(stats_section)

        trend_section = QFrame()
        trend_section.setObjectName("panel")
        trend_layout = QVBoxLayout(trend_section)
        trend_layout.setContentsMargins(8, 8, 8, 8)
        trend_layout.setSpacing(4)
        trend_label = QLabel("Temperature Trend")
        trend_label.setStyleSheet(f"font-weight: bold; color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        trend_layout.addWidget(trend_label)
        trend_placeholder = QLabel("Trend chart placeholder")
        trend_placeholder.setAlignment(Qt.AlignCenter)
        trend_placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; background-color: {COLOR_TOOLBAR}; border: 1px solid {COLOR_BORDER}; border-radius: 3px;")
        trend_layout.addWidget(trend_placeholder, 1)
        bottom_splitter.addWidget(trend_section)

        bottom_splitter.setStretchFactor(0, 1)
        bottom_splitter.setStretchFactor(1, 1)

        content.addWidget(bottom_splitter, 2)

        alarm_label = QLabel("Alarm History")
        alarm_label.setStyleSheet(f"font-weight: bold; color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        content.addWidget(alarm_label)

        self._alarm_history = _AlarmHistoryTable()
        content.addWidget(self._alarm_history, 2)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        for text, obj_name in [
            ("Snapshot", ""),
            ("Record", "primaryButton"),
            ("Export", ""),
            ("Reset Alarm", "dangerButton"),
            ("Silence", ""),
        ]:
            btn = QPushButton(text)
            if obj_name:
                btn.setObjectName(obj_name)
            actions.addWidget(btn)

        actions.addStretch()
        content.addLayout(actions)

        root.addLayout(content)

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {COLOR_TOOLBAR}; border-bottom: 1px solid {COLOR_BORDER};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)

        self._header_name = QLabel(self._camera_name)
        self._header_name.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        layout.addWidget(self._header_name)

        self._header_status_labels = []
        for label, color in [
            ("Position", COLOR_TEXT_SECONDARY),
            ("Alarm", COLOR_ALARM_GREEN),
            ("Recording", COLOR_ALARM_GRAY),
            ("Status", COLOR_ALARM_GRAY),
        ]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {color}; font-size: 11px; padding: 2px 8px; border-left: 1px solid {COLOR_BORDER};")
            layout.addWidget(lbl)
            self._header_status_labels.append(lbl)

        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return bar

    def _apply_theme(self) -> None:
        self.setStyleSheet(STYLE_MAIN_WINDOW)

    def start_polling(self) -> None:
        self._poll_timer.start(self.POLL_INTERVAL_MS)

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    def _update_connection_state(self) -> None:
        context = self._controller.get_camera(self._camera_id)
        if context is None or not context.is_connected:
            self._header_name.setText(self._camera_name or "No Camera Connected")
            if len(self._header_status_labels) >= 4:
                self._header_status_labels[3].setText("Disconnected")
                self._header_status_labels[3].setStyleSheet(
                    f"color: {COLOR_ALARM_GRAY}; font-size: 11px; padding: 2px 8px; border-left: 1px solid {COLOR_BORDER};"
                )
            self._thermal_view.show_placeholder()
            self._visible_view.show_placeholder()
        else:
            self._header_name.setText(self._camera_name)
            if len(self._header_status_labels) >= 4:
                self._header_status_labels[3].setText("Connected")
                self._header_status_labels[3].setStyleSheet(
                    f"color: {COLOR_ALARM_GREEN}; font-size: 11px; padding: 2px 8px; border-left: 1px solid {COLOR_BORDER};"
                )

    def _poll(self) -> None:
        try:
            context = self._controller.get_camera(self._camera_id)
            if context is None:
                self._update_connection_state()
                return
            self._update_connection_state()
            raw = context.camera.get_frame()
            if raw is None:
                return
            cal = context.camera.get_calibration_manager()
            display = cal.raw_to_display(raw)
            rgb = cal.apply_colormap(display)
            self._thermal_view.display_image(rgb)
        except Exception:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_polling()
        event.accept()
