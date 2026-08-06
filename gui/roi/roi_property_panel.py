from __future__ import annotations

from dataclasses import replace

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import (
    COLOR_PANEL,
    COLOR_TOOLBAR,
    COLOR_TEXT_SECONDARY,
    STYLE_SECTION_HEADER,
)

from roi.alarm_settings import ROIAlarmCondition
from roi.configuration import ROIConfiguration


class _CollapsibleSection(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.DownArrow)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setStyleSheet(STYLE_SECTION_HEADER)
        self._toggle.toggled.connect(self._on_toggle)
        self._layout.addWidget(self._toggle)

        self._content = QWidget()
        self._content_layout = QFormLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 4)
        self._content_layout.setSpacing(6)
        self._content_layout.setLabelAlignment(Qt.AlignRight)
        self._layout.addWidget(self._content)

    def _on_toggle(self, checked: bool) -> None:
        self._content.setVisible(checked)
        self._toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def add_row(self, label: str, widget: QWidget) -> None:
        self._content_layout.addRow(label, widget)

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addRow(widget)

    def content_layout(self) -> QFormLayout:
        return self._content_layout

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)
        self._content.setVisible(expanded)
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def clear(self) -> None:
        for i in reversed(range(self._content_layout.rowCount())):
            self._content_layout.removeRow(i)


class ROIPropertyPanel(QWidget):
    alarm_changed = pyqtSignal(str)
    appearance_changed = pyqtSignal(str)
    recording_changed = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    config_updated = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_roi_id: str | None = None
        self._current_config: ROIConfiguration | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLOR_PANEL};")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        self._no_selection_label = QLabel("Select an ROI to inspect properties.")
        self._no_selection_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-style: italic; padding: 16px;")
        self._no_selection_label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._no_selection_label)

        self._props_widget = QWidget()
        self._props_layout = QVBoxLayout(self._props_widget)
        self._props_layout.setContentsMargins(0, 0, 0, 0)
        self._props_layout.setSpacing(4)

        self._build_general_section()
        self._build_geometry_section()
        self._build_appearance_section()
        self._build_alarm_section()
        self._build_recording_section()
        self._build_metadata_section()

        self._props_widget.hide()
        self._layout.addWidget(self._props_widget)
        self._layout.addStretch()

        scroll.setWidget(self._content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self.clear()

    def _build_general_section(self) -> None:
        self._general_section = _CollapsibleSection("General")
        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)
        self._general_section.add_row("Name:", self._name_edit)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.stateChanged.connect(self._on_enabled_changed)
        self._general_section.add_widget(self._enabled_check)

        self._visible_check = QCheckBox("Visible")
        self._visible_check.stateChanged.connect(self._on_visible_changed)
        self._general_section.add_widget(self._visible_check)

        self._props_layout.addWidget(self._general_section)

    def _build_geometry_section(self) -> None:
        self._geometry_section = _CollapsibleSection("Geometry")
        self._geometry_fields: dict[str, QDoubleSpinBox] = {}
        self._geom_placeholder = QLabel("Select an ROI to view geometry")
        self._geom_placeholder.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        self._geometry_section.add_widget(self._geom_placeholder)
        self._props_layout.addWidget(self._geometry_section)

    def _build_appearance_section(self) -> None:
        self._appearance_section = _CollapsibleSection("Appearance")
        self._color_edit = QLineEdit()
        self._color_edit.setMaxLength(7)
        self._color_edit.setPlaceholderText("#RRGGBB")
        self._color_edit.editingFinished.connect(self._on_color_changed)
        self._appearance_section.add_row("Color:", self._color_edit)

        self._line_width_spin = QSpinBox()
        self._line_width_spin.setRange(1, 10)
        self._line_width_spin.valueChanged.connect(self._on_line_width_changed)
        self._appearance_section.add_row("Line Width:", self._line_width_spin)

        self._props_layout.addWidget(self._appearance_section)

    def _build_alarm_section(self) -> None:
        self._alarm_section = _CollapsibleSection("Alarm")
        self._alarm_enabled_check = QCheckBox("Alarm Enabled")
        self._alarm_enabled_check.stateChanged.connect(self._on_alarm_changed)
        self._alarm_section.add_widget(self._alarm_enabled_check)

        self._condition_combo = QComboBox()
        for c in ROIAlarmCondition:
            self._condition_combo.addItem(c.name, c)
        self._condition_combo.currentIndexChanged.connect(self._on_alarm_changed)
        self._alarm_section.add_row("Condition:", self._condition_combo)

        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(-100, 500)
        self._threshold_spin.setDecimals(1)
        self._threshold_spin.setSuffix(" \u00b0C")
        self._threshold_spin.editingFinished.connect(self._on_alarm_changed)
        self._alarm_section.add_row("Threshold:", self._threshold_spin)

        self._hysteresis_spin = QDoubleSpinBox()
        self._hysteresis_spin.setRange(0, 100)
        self._hysteresis_spin.setDecimals(1)
        self._hysteresis_spin.setSuffix(" \u00b0C")
        self._hysteresis_spin.editingFinished.connect(self._on_alarm_changed)
        self._alarm_section.add_row("Hysteresis:", self._hysteresis_spin)

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 60000)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.editingFinished.connect(self._on_alarm_changed)
        self._alarm_section.add_row("Delay:", self._delay_spin)

        self._props_layout.addWidget(self._alarm_section)

    def _build_recording_section(self) -> None:
        self._recording_section = _CollapsibleSection("Recording")
        self._rec_enabled_check = QCheckBox("Recording Enabled")
        self._rec_enabled_check.stateChanged.connect(self._on_recording_changed)
        self._recording_section.add_widget(self._rec_enabled_check)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 3600)
        self._duration_spin.setSuffix(" s")
        self._duration_spin.editingFinished.connect(self._on_recording_changed)
        self._recording_section.add_row("Duration:", self._duration_spin)

        self._props_layout.addWidget(self._recording_section)

    def _build_metadata_section(self) -> None:
        self._metadata_section = _CollapsibleSection("Metadata")
        self._roi_id_label = QLabel("")
        self._roi_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._metadata_section.add_row("ID:", self._roi_id_label)

        self._created_label = QLabel("")
        self._metadata_section.add_row("Created:", self._created_label)

        self._modified_label = QLabel("")
        self._metadata_section.add_row("Modified:", self._modified_label)

        self._description_edit = QLineEdit()
        self._description_edit.editingFinished.connect(self._on_description_changed)
        self._metadata_section.add_row("Description:", self._description_edit)

        self._props_layout.addWidget(self._metadata_section)

    def load_roi(self, config: ROIConfiguration) -> None:
        self._current_roi_id = config.roi_id
        self._current_config = config
        self._no_selection_label.hide()
        self._props_widget.show()

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

    def get_current_roi_id(self) -> str | None:
        return self._current_roi_id

    def clear(self) -> None:
        self._current_roi_id = None
        self._current_config = None
        self._no_selection_label.show()
        self._props_widget.hide()

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
            self._geometry_section.add_row(shape_type.capitalize(), QLabel(""))
            return

        for name, value in fields.items():
            spin = QDoubleSpinBox()
            spin.setRange(-99999, 99999)
            spin.setDecimals(1)
            spin.setValue(float(value))
            spin.setReadOnly(True)
            spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
            spin.setStyleSheet(f"background-color: {COLOR_TOOLBAR};")
            self._geometry_fields[name] = spin
            self._geometry_section.add_row(name + ":", spin)

    def _clear_geometry(self) -> None:
        for field in list(self._geometry_fields.keys()):
            widget = self._geometry_fields.pop(field)
            widget.deleteLater()
        self._geometry_section.clear()

    def _get_geometry_fields(self, config: ROIConfiguration) -> dict[str, float]:
        g = config.geometry
        shape_type = g.type
        if shape_type == "rectangle1":
            return {"Row1": g.row1, "Col1": g.col1, "Row2": g.row2, "Col2": g.col2}
        elif shape_type == "rectangle2":
            return {"Row": g.row, "Col": g.col, "Phi": g.phi, "Length1": g.length1, "Length2": g.length2}
        elif shape_type == "circle":
            return {"Row": g.row, "Col": g.col, "Radius": g.radius}
        elif shape_type == "ellipse":
            return {"Row": g.row, "Col": g.col, "Phi": g.phi, "Radius1": g.radius1, "Radius2": g.radius2}
        return {}

    def _on_name_changed(self) -> None:
        if self._current_roi_id:
            self._rename_config(name=self._name_edit.text())
            self.rename_requested.emit(self._current_roi_id, self._name_edit.text())

    def _on_enabled_changed(self) -> None:
        self._appearance_config(enabled=self._enabled_check.isChecked())

    def _on_visible_changed(self) -> None:
        self._appearance_config(visible=self._visible_check.isChecked())

    def _on_color_changed(self) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        self._appearance_config(
            style=replace(
                self._current_config.style,
                color=self._color_edit.text(),
            )
        )

    def _on_line_width_changed(self) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        self._appearance_config(
            style=replace(
                self._current_config.style,
                line_width=int(self._line_width_spin.value()),
            )
        )

    def _on_alarm_changed(self) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        updated = replace(
            self._current_config,
            alarm=replace(
                self._current_config.alarm,
                enabled=self._alarm_enabled_check.isChecked(),
                condition=self._condition_combo.currentData(),
                value=float(self._threshold_spin.value()),
                hysteresis=float(self._hysteresis_spin.value()),
                delay_ms=int(self._delay_spin.value()),
            ),
        )
        self._push_config(updated)
        self.alarm_changed.emit(self._current_roi_id)

    def _on_recording_changed(self) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        updated = replace(
            self._current_config,
            recording=replace(
                self._current_config.recording,
                enabled=self._rec_enabled_check.isChecked(),
                duration_seconds=int(self._duration_spin.value()),
            ),
        )
        self._push_config(updated)
        self.recording_changed.emit(self._current_roi_id)

    def _on_description_changed(self) -> None:
        self._appearance_config(description=self._description_edit.text())

    def _emit_appearance(self) -> None:
        if self._current_roi_id:
            self.appearance_changed.emit(self._current_roi_id)

    def _appearance_config(self, **changes) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        self._push_config(replace(self._current_config, **changes))
        self.appearance_changed.emit(self._current_roi_id)

    def _rename_config(self, name: str) -> None:
        if self._current_roi_id is None or self._current_config is None:
            return
        self._push_config(replace(self._current_config, name=name))

    def _push_config(self, config: ROIConfiguration) -> None:
        """Store the new config and notify the workspace."""
        self._current_config = config
        self.config_updated.emit(config)
