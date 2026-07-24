from __future__ import annotations

from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QSpinBox,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
)

from gui.theme import (
    COLOR_PANEL,
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_ACCENT,
)


CATEGORIES = [
    ("General", "General Settings"),
    ("Appearance", "Appearance Settings"),
    ("Project", "Project Settings"),
    ("Cameras", "Camera Settings"),
    ("ROI Defaults", "ROI Default Settings"),
    ("Alarm Defaults", "Alarm Default Settings"),
    ("Recording", "Recording Settings"),
    ("Logging", "Logging Settings"),
    ("Network", "Network Settings"),
    ("Advanced", "Advanced Settings"),
]


class SettingsWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 520)
        self.resize(900, 580)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._nav = QListWidget()
        self._nav.setFixedWidth(180)
        self._nav.setStyleSheet(
            f"QListWidget {{ background-color: {COLOR_TOOLBAR}; border: none; border-right: 1px solid {COLOR_BORDER}; outline: none; }} "
            f"QListWidget::item {{ padding: 8px 12px; font-size: 11px; color: {COLOR_TEXT_PRIMARY}; }} "
            f"QListWidget::item:selected {{ background-color: {COLOR_ACCENT}; color: white; }} "
            f"QListWidget::item:hover {{ background-color: #E0E0E0; }} "
        )
        root.addWidget(self._nav)

        self._pages = QStackedWidget()
        self._pages.setStyleSheet(f"background-color: {COLOR_PANEL};")
        root.addWidget(self._pages, 1)

        for title, _ in CATEGORIES:
            item = QListWidgetItem(title)
            self._nav.addItem(item)
            self._pages.addWidget(self._build_page(title))

        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _build_page(self, title: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        heading = QLabel(title)
        heading.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        layout.addWidget(heading)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {COLOR_BORDER};")
        layout.addWidget(sep)

        body = self._build_body(title)
        body.setStyleSheet("background: transparent;")
        layout.addWidget(body, 1)

        layout.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ACCENT}; color: white; border: none; border-radius: 3px; padding: 6px 20px; font-size: 11px; }} "
            f"QPushButton:hover {{ background-color: #1565C0; }} "
        )
        actions.addWidget(apply_btn)
        layout.addLayout(actions)

        return page

    def _build_body(self, title: str) -> QWidget:
        body_map: dict[str, QWidget] = {
            "General": self._build_general,
            "Appearance": self._build_appearance,
            "Project": self._build_project,
            "Cameras": self._build_cameras,
            "ROI Defaults": self._build_roi_defaults,
            "Alarm Defaults": self._build_alarm_defaults,
            "Recording": self._build_recording,
            "Logging": self._build_logging,
            "Network": self._build_network,
            "Advanced": self._build_advanced,
        }
        builder = body_map.get(title, self._build_placeholder)
        return builder()

    def _build_placeholder(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Settings not yet implemented.")
        lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic;")
        layout.addWidget(lbl)
        layout.addStretch()
        return w

    def _build_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        # TODO: Wire to QSettings

        lang = QComboBox()
        lang.addItems(["English", "German", "Chinese", "Japanese"])
        form.addRow("Language:", lang)

        theme = QComboBox()
        theme.addItems(["Light", "Dark"])
        form.addRow("Theme:", theme)

        auto_start = QCheckBox("Automatically discover cameras on startup")
        form.addRow("", auto_start)

        minimize_tray = QCheckBox("Minimize to system tray")
        form.addRow("", minimize_tray)

        form.addRow("", QLabel(""))
        note = QLabel("General settings are loaded from QSettings on startup.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_appearance(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        theme = QComboBox()
        theme.addItems(["Light Industrial", "Dark"])
        form.addRow("Color Scheme:", theme)

        font_size = QSpinBox()
        font_size.setRange(9, 16)
        font_size.setValue(11)
        form.addRow("Font Size:", font_size)

        grid = QCheckBox("Show grid lines in camera table")
        grid.setChecked(True)
        form.addRow("", grid)

        anim = QCheckBox("Enable animated transitions")
        form.addRow("", anim)

        form.addRow("", QLabel(""))
        note = QLabel("Restart required for some appearance changes.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_project(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        name = QLineEdit("Factory Line A")
        form.addRow("Project Name:", name)

        desc = QLineEdit("Thermal monitoring production line")
        form.addRow("Description:", desc)

        location = QLineEdit("Building 3, Floor 2")
        form.addRow("Location:", location)

        form.addRow("", QLabel(""))
        note = QLabel("Project settings are saved per-project configuration.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_cameras(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        timeout = QSpinBox()
        timeout.setRange(1, 60)
        timeout.setValue(5)
        timeout.setSuffix(" s")
        form.addRow("Connection Timeout:", timeout)

        reconnect = QCheckBox("Auto-reconnect on disconnect")
        reconnect.setChecked(True)
        form.addRow("", reconnect)

        max_cams = QSpinBox()
        max_cams.setRange(1, 32)
        max_cams.setValue(8)
        form.addRow("Max Cameras:", max_cams)

        buffer = QSpinBox()
        buffer.setRange(1, 100)
        buffer.setValue(10)
        form.addRow("Frame Buffer:", buffer)

        form.addRow("", QLabel(""))
        note = QLabel("Camera settings affect all connected cameras.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_roi_defaults(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        shape = QComboBox()
        shape.addItems(["Rectangle", "Circle", "Ellipse", "Polygon"])
        form.addRow("Default Shape:", shape)

        width = QSpinBox()
        width.setRange(10, 1000)
        width.setValue(100)
        form.addRow("Default Width:", width)

        height = QSpinBox()
        height.setRange(10, 1000)
        height.setValue(100)
        form.addRow("Default Height:", height)

        form.addRow("", QLabel(""))
        note = QLabel("ROI defaults are used when creating new regions.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_alarm_defaults(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        high = QSpinBox()
        high.setRange(0, 500)
        high.setValue(80)
        high.setSuffix(" \u00B0C")
        form.addRow("High Threshold:", high)

        low = QSpinBox()
        low.setRange(0, 500)
        low.setValue(10)
        low.setSuffix(" \u00B0C")
        form.addRow("Low Threshold:", low)

        hysteresis = QSpinBox()
        hysteresis.setRange(0, 50)
        hysteresis.setValue(2)
        hysteresis.setSuffix(" \u00B0C")
        form.addRow("Hysteresis:", hysteresis)

        form.addRow("", QLabel(""))
        note = QLabel("Alarm defaults apply to new ROI regions.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_recording(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        path = QLineEdit("C:\\Recordings\\")
        form.addRow("Storage Path:", path)

        fmt = QComboBox()
        fmt.addItems(["AVI", "MP4", "Raw"])
        form.addRow("Format:", fmt)

        max_size = QSpinBox()
        max_size.setRange(100, 100000)
        max_size.setValue(10000)
        max_size.setSuffix(" MB")
        form.addRow("Max File Size:", max_size)

        retention = QSpinBox()
        retention.setRange(1, 365)
        retention.setValue(30)
        retention.setSuffix(" days")
        form.addRow("Retention:", retention)

        form.addRow("", QLabel(""))
        note = QLabel("Recording settings apply per-camera stream.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_logging(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        level = QComboBox()
        level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        level.setCurrentText("INFO")
        form.addRow("Log Level:", level)

        max_entries = QSpinBox()
        max_entries.setRange(100, 100000)
        max_entries.setValue(10000)
        form.addRow("Max Entries:", max_entries)

        auto_scroll = QCheckBox("Auto-scroll to new entries")
        auto_scroll.setChecked(True)
        form.addRow("", auto_scroll)

        form.addRow("", QLabel(""))
        note = QLabel("Logging settings affect the Event Log window.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_network(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        iface = QComboBox()
        iface.addItems(["Auto", "Ethernet 1", "Ethernet 2", "Wi-Fi"])
        form.addRow("Network Interface:", iface)

        port = QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(50010)
        form.addRow("GigE Port:", port)

        packet_size = QSpinBox()
        packet_size.setRange(1500, 9000)
        packet_size.setValue(1500)
        packet_size.setSuffix(" bytes")
        form.addRow("Packet Size:", packet_size)

        form.addRow("", QLabel(""))
        note = QLabel("Network settings require reconnect to take effect.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w

    def _build_advanced(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        debug = QCheckBox("Enable debug mode")
        form.addRow("", debug)

        dev = QCheckBox("Developer tools")
        form.addRow("", dev)

        perf = QCheckBox("Performance logging")
        form.addRow("", perf)

        sim = QCheckBox("Simulation mode (no cameras)")
        form.addRow("", sim)

        form.addRow("", QLabel(""))
        note = QLabel("Advanced settings are for diagnostic purposes only.")
        note.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-style: italic;")
        form.addRow("", note)

        return w
