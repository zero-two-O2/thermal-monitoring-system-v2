from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.application_controller import ApplicationController
from gui.theme import (
    COLOR_ACCENT,
    COLOR_PANEL,
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_ORANGE,
    COLOR_ALARM_RED,
    COLOR_ALARM_GRAY,
    STYLE_MAIN_WINDOW,
)

from gui.widgets.camera_tile import CameraTile


TILE_COUNT = 8
TILE_COLS = 4


class _AlarmTableWidget(QTableWidget):
    COL_TIMESTAMP = 0
    COL_CAMERA = 1
    COL_POSITION = 2
    COL_ROI = 3
    COL_LEVEL = 4
    COL_TEMPERATURE = 5

    HEADERS = ["Timestamp", "Camera", "Position", "ROI", "Level", "Temperature"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(True)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ROI, QHeaderView.Stretch)

    def add_alarm(self, timestamp: str, camera: str, position: str, roi: str, level: str, temperature: str) -> None:
        row = self.rowCount()
        self.insertRow(row)

        for col, text in [(self.COL_TIMESTAMP, timestamp), (self.COL_CAMERA, camera),
                          (self.COL_POSITION, position), (self.COL_ROI, roi),
                          (self.COL_LEVEL, level), (self.COL_TEMPERATURE, temperature)]:
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.setItem(row, col, item)

        color_style = {
            "CRITICAL": COLOR_ALARM_RED,
            "HIGH": COLOR_ALARM_ORANGE,
            "WARNING": COLOR_ALARM_GREEN,
            "INFO": COLOR_ALARM_GRAY,
        }
        color = color_style.get(level.upper(), COLOR_ALARM_GRAY)
        for col in range(self.columnCount()):
            self.item(row, col).setBackground(self._get_color(color))

        self.scrollToBottom()

    @staticmethod
    def _get_color(hex_color):
        from PyQt5.QtGui import QColor
        return QColor(hex_color)


class ObserverWindow(QMainWindow):
    camera_detail_requested = pyqtSignal(str)
    POLL_INTERVAL_MS = 33

    def __init__(self, controller: ApplicationController) -> None:
        super().__init__()

        self._controller = controller
        self._tiles: list[CameraTile] = []
        self._slot_map: dict[str, int] = {}
        self._cameras: list = []

        self._build_ui()
        self._apply_theme()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frames)

    def _build_ui(self) -> None:
        self.setWindowTitle("Observation - Operator Mode")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        content = QVBoxLayout()
        content.setContentsMargins(12, 12, 12, 8)
        content.setSpacing(8)

        section = QLabel("Camera Monitoring")
        section.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        content.addWidget(section)

        tile_container = QWidget()
        tile_grid = QGridLayout(tile_container)
        tile_grid.setContentsMargins(0, 0, 0, 0)
        tile_grid.setSpacing(8)

        for i in range(TILE_COUNT):
            tile = CameraTile(camera_id="", camera_name=f"Slot {i + 1}")
            tile.assign_camera("", f"Slot {i + 1}")
            tile.clear_camera()
            tile.double_clicked.connect(self._on_tile_double_clicked)
            self._tiles.append(tile)
            row = i // TILE_COLS
            col = i % TILE_COLS
            tile_grid.addWidget(tile, row, col)

        content.addWidget(tile_container, 3)

        alarm_label = QLabel("Active Alarms")
        alarm_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY}; margin-top: 4px;")
        content.addWidget(alarm_label)

        self._alarm_table = _AlarmTableWidget()
        content.addWidget(self._alarm_table, 2)

        root.addLayout(content)

        self._build_status_bar()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {COLOR_TOOLBAR}; border-bottom: 1px solid {COLOR_BORDER};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        title = QLabel("Operator Monitoring")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        layout.addWidget(title)

        layout.addStretch()

        for text in ["Full Screen", "Reset Layout"]:
            btn = QPushButton(text)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLOR_PANEL}; color: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; border-radius: 3px; padding: 6px 14px; font-size: 11px; }} "
                f"QPushButton:hover {{ background-color: #F0F0F0; border-color: {COLOR_ACCENT}; }}"
            )
            layout.addWidget(btn)

        return bar

    def _build_status_bar(self) -> None:
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Observation mode")
        self._status_bar.addWidget(self._status_label)
        self._camera_count_label = QLabel("Cameras: 0")
        self._status_bar.addPermanentWidget(self._camera_count_label)
        self._alarm_count_label = QLabel("Alarms: 0")
        self._status_bar.addPermanentWidget(self._alarm_count_label)
        self._fps_label = QLabel("FPS: 0")
        self._status_bar.addPermanentWidget(self._fps_label)

    def _apply_theme(self) -> None:
        self.setStyleSheet(STYLE_MAIN_WINDOW)

    # ---------------------------------------------------------
    # Camera Management
    # ---------------------------------------------------------

    def add_camera(self, context) -> None:
        camera_id = context.camera_id
        if camera_id in self._slot_map:
            return

        slot_index = None
        for i, tile in enumerate(self._tiles):
            if not tile.camera_id:
                slot_index = i
                break

        if slot_index is None:
            return

        self._slot_map[camera_id] = slot_index
        self._cameras.append(context)

        tile = self._tiles[slot_index]
        tile.assign_camera(camera_id, context.camera_model.camera_name)
        tile.set_connected(True)
        self._camera_count_label.setText("Cameras: " + str(len(self._cameras)))

    def remove_camera(self, camera_id: str) -> None:
        slot_index = self._slot_map.pop(camera_id, None)
        if slot_index is None:
            return
        self._cameras = [c for c in self._cameras if c.camera_id != camera_id]
        tile = self._tiles[slot_index]
        tile.clear_camera()
        self._camera_count_label.setText("Cameras: " + str(len(self._cameras)))

    # ---------------------------------------------------------
    # Tile Double-Click
    # ---------------------------------------------------------

    def _on_tile_double_clicked(self, camera_id: str) -> None:
        if any(c.camera_id == camera_id for c in self._cameras):
            self.camera_detail_requested.emit(camera_id)

    # ---------------------------------------------------------
    # Frame Polling
    # ---------------------------------------------------------

    def start_polling(self) -> None:
        self._poll_timer.start(self.POLL_INTERVAL_MS)

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    def _poll_frames(self) -> None:
        for context in self._cameras:
            camera_id = context.camera_id
            slot = self._slot_map.get(camera_id)
            if slot is None:
                continue
            tile = self._tiles[slot]
            if tile is None:
                continue
            try:
                raw = context.camera.get_frame()
                if raw is None:
                    continue
                cal = context.camera.get_calibration_manager()
                display = cal.raw_to_display(raw)
                rgb = cal.apply_colormap(display)
                if rgb is not None:
                    tile.update_frame(image=rgb, frame_count=0, sequence=0, latency_ms=0.0, dropped=0, timeouts=0, fps=0.0)
            except Exception:
                pass

    # ---------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_polling()
        event.accept()
