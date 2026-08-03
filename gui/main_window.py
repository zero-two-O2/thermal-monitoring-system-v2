from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
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
    COLOR_TEXT_SECONDARY,
    COLOR_ALARM_GREEN,
    COLOR_ALARM_RED,
    COLOR_ALARM_GRAY,
    COLOR_ALARM_ORANGE,
    COLOR_TEXT_DISABLED,
    COLOR_SELECTION,
    COLOR_BACKGROUND,
    STYLE_MAIN_WINDOW,
    STYLE_TOOLBAR_BUTTON,
)

from utilities import logger


COL_CHECK = 0
COL_STATUS = 1
COL_NAME = 2
COL_SERIAL = 3
COL_IP = 4
COL_POSITION = 5
COL_MODEL = 6
COL_CONNECTED = 7

HEADERS = [
    "",
    "",
    "Camera Name",
    "Serial Number",
    "IP Address",
    "Position",
    "Model",
    "Connected",
]

COL_COUNT = len(HEADERS)

class _ConnectionBadge(QLabel):
    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self._state = "unknown"
        self._detail = ""
        self._update_display()

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._detail = detail
        self._update_display()

    def _update_display(self) -> None:
        dots = {"ok": "\u25CF", "warn": "\u26A0", "error": "\u2718", "unknown": "\u25CB"}
        colors = {
            "ok": COLOR_ALARM_GREEN,
            "warn": COLOR_ALARM_ORANGE,
            "error": COLOR_ALARM_RED,
            "unknown": COLOR_ALARM_GRAY,
        }
        dot = dots.get(self._state, "\u25CB")
        color = colors.get(self._state, COLOR_ALARM_GRAY)
        text = f"{dot} {self._label}"
        if self._detail:
            text += f" {self._detail}"
        self.setText(text)
        self.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold; "
            f"padding: 2px 10px; border-left: 1px solid {COLOR_BORDER};"
        )


class MainWindow(QMainWindow):
    calibration_requested = pyqtSignal()
    observation_requested = pyqtSignal()
    discover_requested = pyqtSignal()
    cameras_disconnected = pyqtSignal(list)

    POLL_INTERVAL_MS = 2000
    CLOCK_INTERVAL_MS = 1000

    def __init__(self, controller: ApplicationController) -> None:
        super().__init__()

        self.setAttribute(Qt.WA_DeleteOnClose)

        self._controller = controller
        self._camera_rows: dict[str, int] = {}
        self._badges: dict[str, _ConnectionBadge] = {}
        self._selected_camera_id: str | None = None

        self._build_menu_bar()
        self._build_ui()
        self._apply_theme()
        self._connect_signals()
        self._update_button_states()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(self.POLL_INTERVAL_MS)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(self.CLOCK_INTERVAL_MS)
        self._update_clock()

    # ---------------------------------------------------------
    # Menu Bar
    # ---------------------------------------------------------

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        self._new_project_action = QAction("New Project", self)
        self._open_project_action = QAction("Open Project...", self)
        self._save_project_action = QAction("Save Project", self)
        self._save_project_action.setEnabled(False)
        file_menu.addAction(self._new_project_action)
        file_menu.addAction(self._open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self._save_project_action)
        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        camera_menu = menu_bar.addMenu("Camera")
        self._menu_discover = QAction("Discover", self)
        self._menu_connect = QAction("Connect All", self)
        self._menu_disconnect = QAction("Disconnect All", self)
        self._menu_refresh = QAction("Refresh", self)
        camera_menu.addAction(self._menu_discover)
        camera_menu.addAction(self._menu_connect)
        camera_menu.addAction(self._menu_disconnect)
        camera_menu.addAction(self._menu_refresh)

        view_menu = menu_bar.addMenu("View")
        self._menu_calibration = QAction("Calibration Window", self)
        self._menu_observation = QAction("Observation Window", self)
        view_menu.addAction(self._menu_calibration)
        view_menu.addAction(self._menu_observation)

        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        help_menu.addAction(about_action)

    # ---------------------------------------------------------
    # UI Build
    # ---------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Thermal Monitoring System")
        self.setMinimumSize(1100, 780)
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_header(root)
        self._build_toolbar(root)
        self._build_utilities(root)
        content = self._build_content()
        root.addWidget(content, 1)
        self._build_status_bar()

    def _build_header(self, root: QVBoxLayout) -> None:
        header = QWidget()
        header.setStyleSheet(f"background-color: {COLOR_PANEL}; border-bottom: 1px solid {COLOR_BORDER};")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("Thermal Monitoring System")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        left.addWidget(title)
        project_row = QHBoxLayout()
        project_row.setSpacing(16)
        self._project_label = QLabel("Project: TV46L")
        self._project_label.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_SECONDARY};")
        self._config_label = QLabel("Configuration: Under Production")
        self._config_label.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXT_SECONDARY};")
        project_row.addWidget(self._project_label)
        project_row.addWidget(self._config_label)
        project_row.addStretch()
        left.addLayout(project_row)
        layout.addLayout(left)

        layout.addStretch()

        right = QHBoxLayout()
        right.setSpacing(0)
        for badge_id, label in [
            ("halcon", "HALCON"),
            ("plc", "PLC"),
            ("cameras", "Cameras"),
            ("streaming", "Streaming"),
            ("recording", "Recording"),
        ]:
            badge = _ConnectionBadge(label)
            self._badges[badge_id] = badge
            right.addWidget(badge)
        layout.addLayout(right)

        root.addWidget(header)

    def _build_toolbar(self, root: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {COLOR_TOOLBAR}; border-bottom: 1px solid {COLOR_BORDER};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        for text, icon, slot, obj_name in [
            ("Discover", "\uD83D\uDD0D", self._on_discover, ""),
            ("Connect", "\uD83D\uDD0C", self._on_connect, "primaryButton"),
            ("Disconnect", "\u274C", self._on_disconnect, "dangerButton"),
            ("Refresh", "\uD83D\uDD04", self._on_refresh, ""),
        ]:
            btn = QPushButton(f" {icon} {text}")
            btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
            if obj_name:
                btn.setObjectName(obj_name)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        layout.addStretch()

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLOR_BORDER};")
        layout.addWidget(sep)
        layout.addSpacing(4)

        self._counter_label = QLabel("Discovered: 0  |  Connected: 0 / 8  |  Streaming: 0")
        self._counter_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; padding: 0 8px;")
        layout.addWidget(self._counter_label)

        root.addWidget(bar)

    def _build_utilities(self, root: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {COLOR_BACKGROUND}; border-bottom: 1px solid {COLOR_BORDER};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        label = QLabel("Tools")
        label.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {COLOR_TEXT_SECONDARY}; padding: 0 4px;")
        layout.addWidget(label)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLOR_BORDER};")
        layout.addWidget(sep)
        layout.addSpacing(4)

        for text, slot in [
            ("\u2699\uFE0F Settings", None),
            ("\uD83D\uDD27 Diagnostics", None),
            ("\uD83D\uDCCB Logs", None),
        ]:
            btn = QPushButton(f" {text}")
            btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
            if slot is not None:
                btn.clicked.connect(slot)
            else:
                btn.setEnabled(False)
            layout.addWidget(btn)

        layout.addStretch()
        root.addWidget(bar)

    def _build_content(self) -> QWidget:
        wrapper = QWidget()
        content = QVBoxLayout(wrapper)
        content.setContentsMargins(16, 16, 16, 12)
        content.setSpacing(12)

        section_header = QHBoxLayout()
        section_header.setSpacing(8)
        section_label = QLabel("Camera Management")
        section_label.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {COLOR_BACKGROUND};")
        section_header.addWidget(section_label)
        section_header.addStretch()
        content.addLayout(section_header)

        self._table = QTableWidget(0, COL_COUNT)
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(40)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setColumnWidth(COL_CHECK, 36)
        self._table.setColumnWidth(COL_STATUS, 28)

        hdr = self._table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignCenter)
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_SERIAL, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_IP, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_POSITION, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_MODEL, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_CONNECTED, QHeaderView.ResizeToContents)

        content.addWidget(self._table, 3)

        table_actions = QHBoxLayout()
        table_actions.setSpacing(8)
        self._select_all_cb = QCheckBox("Select All")
        self._select_all_cb.setStyleSheet(f"font-size: 11px; color: {COLOR_SELECTION}; spacing: 6px;")
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        table_actions.addWidget(self._select_all_cb)

        self._clear_sel_btn = QPushButton("Clear")
        self._clear_sel_btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
        self._clear_sel_btn.clicked.connect(self._on_clear_selection)
        table_actions.addWidget(self._clear_sel_btn)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet(f"color: {COLOR_BORDER};")
        table_actions.addWidget(sep1)

        self._connect_sel_btn = QPushButton("Connect Selected")
        self._connect_sel_btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
        self._connect_sel_btn.setObjectName("primaryButton")
        self._connect_sel_btn.clicked.connect(self._on_connect_selected)
        table_actions.addWidget(self._connect_sel_btn)

        self._disconnect_sel_btn = QPushButton("Disconnect Selected")
        self._disconnect_sel_btn.setStyleSheet(STYLE_TOOLBAR_BUTTON)
        self._disconnect_sel_btn.setObjectName("dangerButton")
        self._disconnect_sel_btn.clicked.connect(self._on_disconnect_selected)
        table_actions.addWidget(self._disconnect_sel_btn)

        table_actions.addStretch()
        content.addLayout(table_actions)

        self._details_panel = self._build_details_panel()
        content.addWidget(self._details_panel, 1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color: {COLOR_BORDER};")
        content.addWidget(sep2)

        nav_label = QLabel("Navigation")
        nav_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_BACKGROUND};")
        content.addWidget(nav_label)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(16)
        nav_row.addStretch()

        self._calibration_btn = QPushButton("Calibration")
        self._calibration_btn.setMinimumSize(180, 42)
        self._calibration_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ACCENT}; color: white; border: none; border-radius: 4px; padding: 10px 32px; font-size: 13px; font-weight: bold; }} "
            f"QPushButton:hover {{ background-color: #1565C0; }} "
            f"QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: {COLOR_TEXT_DISABLED}; }}"
        )
        self._calibration_btn.clicked.connect(self._on_calibration)

        self._observation_btn = QPushButton("Observation")
        self._observation_btn.setMinimumSize(180, 42)
        self._observation_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_PANEL}; color: {COLOR_ACCENT}; border: 2px solid {COLOR_ACCENT}; border-radius: 4px; padding: 10px 32px; font-size: 13px; font-weight: bold; }} "
            f"QPushButton:hover {{ background-color: {COLOR_SELECTION}; }} "
            f"QPushButton:disabled {{ background-color: {COLOR_TOOLBAR}; color: {COLOR_TEXT_DISABLED}; border-color: {COLOR_BORDER}; }}"
        )
        self._observation_btn.clicked.connect(self._on_observation)

        nav_row.addWidget(self._calibration_btn)
        nav_row.addWidget(self._observation_btn)
        nav_row.addStretch()
        content.addLayout(nav_row)

        return wrapper

    def _build_details_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedHeight(100)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(24)

        self._details_placeholder = QLabel("Select a camera to view details")
        self._details_placeholder.setStyleSheet(f"color: {COLOR_ALARM_GRAY}; font-size: 11px; font-style: italic;")
        layout.addWidget(self._details_placeholder, 1)

        self._details_grid = QWidget()
        self._details_grid.hide()
        grid = QGridLayout(self._details_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        grid.setHorizontalSpacing(32)

        fields = [
            ("Name:", "_details_name", 0, 0),
            ("Serial:", "_details_serial", 1, 0),
            ("IP Address:", "_details_ip", 2, 0),
            ("Model:", "_details_model", 3, 0),
            ("Position:", "_details_position", 0, 2),
            ("Firmware:", "_details_firmware", 1, 2),
            ("Status:", "_details_status", 2, 2),
            ("FPS:", "_details_fps", 3, 2),
        ]
        self._detail_labels = {}
        for label_text, attr_name, row, col in fields:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("QLabel { color: #555555; font-size: 11px; font-weight: bold; }")
            val = QLabel("--")
            val.setStyleSheet("QLabel { color: #F4F5F7; font-size: 11px; }")
            self._detail_labels[attr_name] = val
            grid.addWidget(lbl, row, col)
            grid.addWidget(val, row, col + 1)

        layout.addWidget(self._details_grid, 1)
        return panel

    def _build_status_bar(self) -> None:
        self._status_message = QLabel("Ready")
        self.statusBar().addWidget(self._status_message)
        self.statusBar().addPermanentWidget(QLabel("Project: Factory_A"))
        self.statusBar().addPermanentWidget(QLabel("v2.0"))
        self._clock_label = QLabel("--:--:--")
        self._clock_label.setStyleSheet("color: #555555; font-size: 10px; font-weight: bold; border: none;")
        self.statusBar().addPermanentWidget(self._clock_label)

    def _apply_theme(self) -> None:
        self.setStyleSheet(STYLE_MAIN_WINDOW)

    # ---------------------------------------------------------
    # Signal Wiring
    # ---------------------------------------------------------

    def _connect_signals(self) -> None:
        self._menu_discover.triggered.connect(self._on_discover)
        self._menu_connect.triggered.connect(self._on_connect)
        self._menu_disconnect.triggered.connect(self._on_disconnect)
        self._menu_refresh.triggered.connect(self._on_refresh)
        self._menu_calibration.triggered.connect(self._on_calibration)
        self._menu_observation.triggered.connect(self._on_observation)

    # ---------------------------------------------------------
    # Actions
    # ---------------------------------------------------------

    def _on_discover(self) -> None:
        self.discover_requested.emit()
        self._refresh_table()
        self._update_status("Discovery completed.")

    def _on_connect(self) -> None:
        try:
            self._controller.connect_all()
            self._refresh_table()
            self._poll_status()
            self._update_status("All cameras connected.")
        except Exception as exc:
            logger.exception("Connect failed")
            self._update_status(f"Connect failed: {exc}")

    def _on_disconnect(self) -> None:
        camera_ids = [c.camera_id for c in self._controller.get_all_cameras()]
        try:
            self._controller.disconnect_all()
            self._refresh_table()
            self._poll_status()
            self._update_status("All cameras disconnected.")
        except Exception as exc:
            logger.exception("Disconnect failed")
            self._update_status(f"Disconnect failed: {exc}")
        if camera_ids:
            self.cameras_disconnected.emit(camera_ids)

    def _on_refresh(self) -> None:
        self._refresh_table()
        self._poll_status()
        self._update_status("Status refreshed.")

    def _on_calibration(self) -> None:
        self.calibration_requested.emit()

    def _on_observation(self) -> None:
        self.observation_requested.emit()

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            status_item = self._table.item(row, COL_STATUS)
            if status_item is not None:
                cid = status_item.data(Qt.UserRole)
                self._selected_camera_id = cid
                self._update_details(cid)
        else:
            self._selected_camera_id = None
            self._clear_details()
        self._update_button_states()

    def _on_select_all(self, state: int) -> None:
        checked = state == Qt.Checked
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_CHECK)
            if item is not None:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _on_clear_selection(self) -> None:
        self._select_all_cb.setCheckState(Qt.Unchecked)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_CHECK)
            if item is not None:
                item.setCheckState(Qt.Unchecked)

    def _on_connect_selected(self) -> None:
        for cid in self._get_checked_camera_ids():
            try:
                self._controller.connect_camera(cid)
            except Exception as exc:
                logger.exception(f"Connect failed for {cid}: {exc}")
        self._refresh_table()
        self._poll_status()
        self._update_status("Selected cameras connected.")

    def _on_disconnect_selected(self) -> None:
        camera_ids = self._get_checked_camera_ids()
        for cid in camera_ids:
            try:
                self._controller.disconnect_camera(cid)
            except Exception as exc:
                logger.exception(f"Disconnect failed for {cid}: {exc}")
        self._refresh_table()
        self._poll_status()
        self._update_status("Selected cameras disconnected.")
        if camera_ids:
            self.cameras_disconnected.emit(camera_ids)

    def _get_checked_camera_ids(self) -> list[str]:
        ids = []
        for row in range(self._table.rowCount()):
            check_item = self._table.item(row, COL_CHECK)
            status_item = self._table.item(row, COL_STATUS)
            if check_item is not None and status_item is not None:
                if check_item.checkState() == Qt.Checked:
                    cid = status_item.data(Qt.UserRole)
                    if cid:
                        ids.append(cid)
        return ids

    def _update_status(self, message: str) -> None:
        self._status_message.setText(message)

    # ---------------------------------------------------------
    # Camera Table
    # ---------------------------------------------------------

    def add_camera(self, camera_id: str, name: str, serial: str = "", ip: str = "", model: str = "") -> None:
        if camera_id in self._camera_rows:
            return
        self._table.setSortingEnabled(False)
        row = self._table.rowCount()
        self._table.insertRow(row)

        def _make_item(text: str, user_role_data=None) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            if user_role_data is not None:
                it.setData(Qt.UserRole, user_role_data)
            return it

        self._table.setItem(row, COL_CHECK, _make_item(""))
        check_item = self._table.item(row, COL_CHECK)
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check_item.setCheckState(Qt.Unchecked)
        check_item.setTextAlignment(Qt.AlignCenter)

        status_item = _make_item("", camera_id)
        status_item.setTextAlignment(Qt.AlignCenter)
        status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._table.setItem(row, COL_STATUS, status_item)

        self._table.setItem(row, COL_NAME, _make_item(name))
        self._table.setItem(row, COL_SERIAL, _make_item(serial))
        self._table.setItem(row, COL_IP, _make_item(ip))
        self._table.setItem(row, COL_POSITION, _make_item("Position 1"))
        self._table.setItem(row, COL_MODEL, _make_item(model))
        self._table.setItem(row, COL_CONNECTED, _make_item("Unknown"))

        self._camera_rows[camera_id] = row
        self._table.setSortingEnabled(True)

    def remove_camera(self, camera_id: str) -> None:
        row = self._camera_rows.pop(camera_id, None)
        if row is not None:
            self._table.removeRow(row)
            self._rebuild_row_map()

    def update_camera_status(self, camera_id: str, connected: bool) -> None:
        row = self._camera_rows.get(camera_id)
        if row is not None:
            connected_item = self._table.item(row, COL_CONNECTED)
            if connected_item is not None:
                connected_item.setText("Connected" if connected else "Disconnected")
                color = COLOR_ALARM_GREEN if connected else COLOR_ALARM_RED
                connected_item.setForeground(self._get_color(color))

            status_item = self._table.item(row, COL_STATUS)
            if status_item is not None:
                icon = "\u25CF" if connected else "\u25CB"
                color = COLOR_ALARM_GREEN if connected else COLOR_ALARM_RED
                status_item.setForeground(self._get_color(color))
                status_item.setText(icon)

    def _refresh_table(self) -> None:
        cameras = self._controller.get_all_cameras()
        seen = set()
        for context in cameras:
            cid = context.camera_id
            seen.add(cid)
            cm = context.camera_model
            if cid in self._camera_rows:
                row = self._camera_rows[cid]
                for col in [COL_NAME, COL_SERIAL, COL_IP, COL_MODEL]:
                    item = self._table.item(row, col)
                    if item is None:
                        continue
                    if col == COL_NAME:
                        item.setText(cm.camera_name)
                    elif col == COL_SERIAL:
                        item.setText(cm.serial_number)
                    elif col == COL_IP:
                        item.setText(cm.ip_address)
                    elif col == COL_MODEL:
                        item.setText(cm.model)
            else:
                self.add_camera(cid, cm.camera_name, cm.serial_number, cm.ip_address, cm.model)
        for cid in list(self._camera_rows.keys()):
            if cid not in seen:
                self.remove_camera(cid)
        if self._selected_camera_id and self._selected_camera_id in self._camera_rows:
            row = self._camera_rows[self._selected_camera_id]
            self._table.selectRow(row)
        self._update_button_states()

    def _rebuild_row_map(self) -> None:
        self._camera_rows.clear()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_STATUS)
            if item is not None:
                cid = item.data(Qt.UserRole)
                if cid:
                    self._camera_rows[cid] = row

    @staticmethod
    def _get_color(hex_color: str):
        from PyQt5.QtGui import QColor
        return QColor(hex_color)

    # ---------------------------------------------------------
    # Details Panel
    # ---------------------------------------------------------

    def _update_details(self, camera_id: str) -> None:
        ctx = self._controller.get_camera(camera_id)
        self._details_placeholder.hide()
        self._details_grid.show()

        if ctx is None:
            vals = {k: "--" for k in self._detail_labels}
        else:
            cm = ctx.camera_model
            connected = ctx.is_connected
            vals = {
                "_details_name": cm.camera_name,
                "_details_serial": cm.serial_number,
                "_details_ip": cm.ip_address,
                "_details_model": cm.model,
                "_details_position": "Position 1",
                "_details_firmware": "--",
                "_details_status": "Connected" if connected else "Disconnected",
                "_details_fps": "--",
            }
        for key, label in self._detail_labels.items():
            label.setText(vals.get(key, "--"))

    def _clear_details(self) -> None:
        self._details_placeholder.show()
        self._details_grid.hide()

    # ---------------------------------------------------------
    # Button States
    # ---------------------------------------------------------

    def _update_button_states(self) -> None:
        # Navigation must never depend on camera availability.
        # All windows open with placeholders when no camera is
        # connected (development mode).
        self._calibration_btn.setEnabled(True)
        self._observation_btn.setEnabled(True)
        self._menu_calibration.setEnabled(True)
        self._menu_observation.setEnabled(True)

    # ---------------------------------------------------------
    # Status Polling
    # ---------------------------------------------------------

    def _poll_status(self) -> None:
        try:
            all_cameras = self._controller.get_all_cameras()
            connected = self._controller.connected_cameras()
            running = self._controller.running_cameras()

            for cid in list(self._camera_rows.keys()):
                ctx = self._controller.get_camera(cid)
                is_connected = ctx is not None and ctx in connected
                self.update_camera_status(cid, is_connected)

            discovered = len(all_cameras)
            connected_count = len(connected)
            streaming_count = len(running)

            self._counter_label.setText(
                f"Discovered: {discovered}  |  Connected: {connected_count} / 8  |  Streaming: {streaming_count}"
            )

            self._badges["halcon"].set_state("ok")
            self._badges["plc"].set_state("ok")
            self._badges["cameras"].set_state(
                "ok" if connected_count > 0 else "warn",
                str(connected_count),
            )
            self._badges["streaming"].set_state(
                "ok" if streaming_count > 0 else "warn",
                str(streaming_count),
            )
            self._badges["recording"].set_state("warn", "Idle")

            if hasattr(self, "_details_grid") and self._details_grid.isVisible() and self._selected_camera_id:
                self._update_details(self._selected_camera_id)

        except Exception:
            logger.exception("Status poll failed")

    # ---------------------------------------------------------
    # Clock
    # ---------------------------------------------------------

    def _update_clock(self) -> None:
        self._clock_label.setText(datetime.now().strftime("%H:%M:%S"))

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll_timer.stop()
        self._clock_timer.stop()
        try:
            self._controller.shutdown()
        except Exception:
            logger.exception("Shutdown error")
        event.accept()
