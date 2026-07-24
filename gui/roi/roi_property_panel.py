from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from roi.alarm_settings import ROIAlarmCondition
from roi.configuration import ROIConfiguration


class ROIPropertyPanel(QWidget):
    alarm_changed = pyqtSignal(str)
    appearance_changed = pyqtSignal(str)
    recording_changed = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_roi_id: str | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setSpacing(8)

        self._build_general()
        self._build_geometry()
        self._build_appearance()
        self._build_alarm()
        self._build_recording()
        self._build_metadata()

        self._layout.addStretch()

        scroll.setWidget(self._content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.clear()

    def _build_general(self) -> None:
        group = QGroupBox("General")
        form = QFormLayout(group)

        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)
        form.addRow("Name:", self._name_edit)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.stateChanged.connect(self._on_enabled_changed)
        form.addRow("", self._enabled_check)

        self._visible_check = QCheckBox("Visible")
        self._visible_check.stateChanged.connect(self._on_visible_changed)
        form.addRow("", self._visible_check)

        self._layout.addWidget(group)

    def _build_geometry(self) -> None:
        group = QGroupBox("Geometry")
        self._geometry_form = QFormLayout(group)
        self._geometry_fields: dict[str, QDoubleSpinBox] = {}
        self._geom_placeholder = QLabel("Select an ROI to view geometry")
        self._geom_placeholder.setStyleSheet("color: #888888;")
        self._geometry_form.addRow(self._geom_placeholder)
        self._layout.addWidget(group)

    def _build_appearance(self) -> None:
        group = QGroupBox("Appearance")
        form = QFormLayout(group)

        self._color_edit = QLineEdit()
        self._color_edit.setMaxLength(7)
        self._color_edit.setPlaceholderText("#RRGGBB")
        self._color_edit.editingFinished.connect(self._on_color_changed)
        form.addRow("Color:", self._color_edit)

        self._line_width_spin = QSpinBox()
        self._line_width_spin.setRange(1, 10)
        self._line_width_spin.valueChanged.connect(self._on_line_width_changed)
        form.addRow("Line Width:", self._line_width_spin)

        self._layout.addWidget(group)

    def _build_alarm(self) -> None:
        group = QGroupBox("Alarm")
        form = QFormLayout(group)

        self._alarm_enabled_check = QCheckBox("Alarm Enabled")
        self._alarm_enabled_check.stateChanged.connect(self._on_alarm_changed)
        form.addRow("", self._alarm_enabled_check)

        self._condition_combo = QComboBox()
        for c in ROIAlarmCondition:
            self._condition_combo.addItem(c.name, c)
        self._condition_combo.currentIndexChanged.connect(self._on_alarm_changed)
        form.addRow("Condition:", self._condition_combo)

        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(-100, 500)
        self._threshold_spin.setDecimals(1)
        self._threshold_spin.setSuffix(" °C")
        self._threshold_spin.editingFinished.connect(self._on_alarm_changed)
        form.addRow("Threshold:", self._threshold_spin)

        self._hysteresis_spin = QDoubleSpinBox()
        self._hysteresis_spin.setRange(0, 100)
        self._hysteresis_spin.setDecimals(1)
        self._hysteresis_spin.setSuffix(" °C")
        self._hysteresis_spin.editingFinished.connect(self._on_alarm_changed)
        form.addRow("Hysteresis:", self._hysteresis_spin)

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 60000)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.editingFinished.connect(self._on_alarm_changed)
        form.addRow("Delay:", self._delay_spin)

        self._layout.addWidget(group)

    def _build_recording(self) -> None:
        group = QGroupBox("Recording")
        form = QFormLayout(group)

        self._rec_enabled_check = QCheckBox("Recording Enabled")
        self._rec_enabled_check.stateChanged.connect(self._on_recording_changed)
        form.addRow("", self._rec_enabled_check)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 3600)
        self._duration_spin.setSuffix(" s")
        self._duration_spin.editingFinished.connect(self._on_recording_changed)
        form.addRow("Duration:", self._duration_spin)

        self._layout.addWidget(group)

    def _build_metadata(self) -> None:
        group = QGroupBox("Metadata")
        form = QFormLayout(group)

        self._roi_id_label = QLabel("")
        self._roi_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("ID:", self._roi_id_label)

        self._created_label = QLabel("")
        form.addRow("Created:", self._created_label)

        self._modified_label = QLabel("")
        form.addRow("Modified:", self._modified_label)

        self._description_edit = QLineEdit()
        self._description_edit.editingFinished.connect(self._on_description_changed)
        form.addRow("Description:", self._description_edit)

        self._layout.addWidget(group)

    def load_roi(self, config: ROIConfiguration) -> None:
        self._current_roi_id = config.roi_id

        block = self.blockSignals(True)

        self._name_edit.setText(config.name)
        self._enabled_check.setChecked(config.enabled)
        self._visible_check.setChecked(config.visible)

        self._populate_geometry(config)

        self._color_edit.setText(config.style.color)
        self._line_width_spin.setValue(config.style.line_width)

        self._alarm_enabled_check.setChecked(config.alarm.enabled)
        idx = self._condition_combo.findData(config.alarm.condition)
        if idx >= 0:
            self._condition_combo.setCurrentIndex(idx)
        self._threshold_spin.setValue(config.alarm.value)
        self._hysteresis_spin.setValue(config.alarm.hysteresis)
        self._delay_spin.setValue(config.alarm.delay_ms)

        self._rec_enabled_check.setChecked(config.recording.enabled)
        self._duration_spin.setValue(config.recording.duration_seconds)

        self._roi_id_label.setText(config.roi_id)
        self._description_edit.setText(config.description)

        self.blockSignals(block)

    def is_current_roi(self, roi_id: str) -> bool:
        return self._current_roi_id == roi_id

    def clear(self) -> None:
        self._current_roi_id = None
        block = self.blockSignals(True)
        self._name_edit.clear()
        self._enabled_check.setChecked(True)
        self._visible_check.setChecked(True)
        self._clear_geometry()
        self._color_edit.setText("#FFFF00")
        self._line_width_spin.setValue(2)
        self._alarm_enabled_check.setChecked(False)
        self._threshold_spin.setValue(85.0)
        self._hysteresis_spin.setValue(1.0)
        self._delay_spin.setValue(0)
        self._rec_enabled_check.setChecked(False)
        self._duration_spin.setValue(30)
        self._roi_id_label.clear()
        self._description_edit.clear()
        self.blockSignals(block)

    def _populate_geometry(self, config: ROIConfiguration) -> None:
        self._clear_geometry()

        shape_type = config.geometry.type
        fields = self._get_geometry_fields(config)
        if not fields:
            self._geometry_form.addRow(QLabel(shape_type.capitalize()))
            return

        for name, value in fields.items():
            spin = QDoubleSpinBox()
            spin.setRange(-99999, 99999)
            spin.setDecimals(1)
            spin.setValue(float(value))
            spin.setReadOnly(True)
            spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
            self._geometry_fields[name] = spin
            self._geometry_form.addRow(f"{name}:", spin)

    def _clear_geometry(self) -> None:
        for field in list(self._geometry_fields.keys()):
            widget = self._geometry_fields.pop(field)
            self._geometry_form.removeRow(widget)
            widget.deleteLater()
        row = self._geometry_form.rowCount()
        while row > 0:
            row -= 1
            item = self._geometry_form.itemAt(row)
            if item is not None:
                w = item.widget()
                if w is not None:
                    self._geometry_form.removeRow(w)

    def _get_geometry_fields(self, config: ROIConfiguration) -> dict[str, float]:
        g = config.geometry
        shape_type = g.type
        if shape_type == "rectangle1":
            return {"row1": g.row1, "col1": g.col1, "row2": g.row2, "col2": g.col2}
        elif shape_type == "rectangle2":
            return {"row": g.row, "col": g.col, "phi": g.phi, "length1": g.length1, "length2": g.length2}
        elif shape_type == "circle":
            return {"row": g.row, "col": g.col, "radius": g.radius}
        elif shape_type == "ellipse":
            return {"row": g.row, "col": g.col, "phi": g.phi, "radius1": g.radius1, "radius2": g.radius2}
        return {}

    def _on_name_changed(self) -> None:
        if self._current_roi_id:
            self.rename_requested.emit(self._current_roi_id, self._name_edit.text())

    def _on_enabled_changed(self) -> None:
        self._emit_appearance()

    def _on_visible_changed(self) -> None:
        self._emit_appearance()

    def _on_color_changed(self) -> None:
        self._emit_appearance()

    def _on_line_width_changed(self) -> None:
        self._emit_appearance()

    def _on_alarm_changed(self) -> None:
        if self._current_roi_id:
            self.alarm_changed.emit(self._current_roi_id)

    def _on_recording_changed(self) -> None:
        if self._current_roi_id:
            self.recording_changed.emit(self._current_roi_id)

    def _on_description_changed(self) -> None:
        self._emit_appearance()

    def _emit_appearance(self) -> None:
        if self._current_roi_id:
            self.appearance_changed.emit(self._current_roi_id)

    def get_current_roi_id(self) -> str | None:
        return self._current_roi_id
