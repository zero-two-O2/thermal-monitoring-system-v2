from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.application_controller import ApplicationController
from roi.acquisition_state import AcquisitionState
from roi.editor.editor_manager import ROIEditorManager
from roi.persistence.repository import JSONROIRepository

from gui.theme import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_TOOLBAR,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    STYLE_MAIN_WINDOW,
)

from gui.widgets.camera_control_panel import CameraControlPanel
from gui.roi import (
    ROISignalBus,
    ROISelectionManager,
    ROIDirtyTracker,
    ROIWorkspace,
    ROIListWidget,
    ROIPropertyPanel,
    ROIToolbar,
    ThermalView,
)

from utilities import logger


class CalibrationWindow(QMainWindow):
    POLL_INTERVAL_MS = 33

    def __init__(self, controller: ApplicationController) -> None:
        super().__init__()

        self._controller = controller
        self._selected_camera_id: str | None = None

        self._build_ui()
        self._apply_theme()
        self._init_roi()
        self._connect_signals()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_frame)

    # ---------------------------------------------------------
    # ROI Initialization
    # ---------------------------------------------------------

    def _init_roi(self) -> None:
        self._roi_signal_bus = ROISignalBus()
        self._roi_selection = ROISelectionManager()
        self._roi_dirty = ROIDirtyTracker()
        self._roi_editor_mgr = ROIEditorManager(window_handle=0)
        self._roi_repo = JSONROIRepository("./data/roi")
        self._roi_workspace = ROIWorkspace(
            signal_bus=self._roi_signal_bus,
            repository=self._roi_repo,
            selection_manager=self._roi_selection,
            dirty_tracker=self._roi_dirty,
            editor_manager=self._roi_editor_mgr,
        )

    # ---------------------------------------------------------
    # UI Build
    # ---------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Calibration - ROI Engineering")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(1)

        left_panel = self._build_left_panel()
        left_panel.setMinimumWidth(220)
        left_panel.setMaximumWidth(300)
        main_splitter.addWidget(left_panel)

        center = self._build_center()
        main_splitter.addWidget(center)

        right_panel = self._build_right_panel()
        right_panel.setMinimumWidth(280)
        main_splitter.addWidget(right_panel)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 7)
        main_splitter.setStretchFactor(2, 3)

        main_splitter.setSizes([260, 700, 400])

        root.addWidget(main_splitter, 1)

        self._build_status_bar()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {COLOR_TOOLBAR}; border-bottom: 1px solid {COLOR_BORDER};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        title = QLabel("Calibration Engineering")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        layout.addWidget(title)

        layout.addSpacing(24)

        self._camera_combo_label = QLabel("Camera:")
        self._camera_combo_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._camera_combo_label)

        from PyQt5.QtWidgets import QComboBox
        self._camera_combo = QComboBox()
        self._camera_combo.setMinimumWidth(180)
        self._camera_combo.currentIndexChanged.connect(self._on_camera_selected)
        layout.addWidget(self._camera_combo)

        layout.addStretch()

        for text, slot, style in [
            ("Save", self._on_save, f"QPushButton {{ background-color: {COLOR_ACCENT}; color: white; border: none; border-radius: 3px; padding: 6px 14px; font-size: 11px; font-weight: bold; }} QPushButton:hover {{ background-color: #1565C0; }}"),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._control_panel = CameraControlPanel()
        self._control_panel.nuc_clicked.connect(self._on_nuc_clicked)
        self._control_panel.focus_near_clicked.connect(self._on_focus_near)
        self._control_panel.focus_far_clicked.connect(self._on_focus_far)
        layout.addWidget(self._control_panel)

        return panel

    def _build_center(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(8)

        viewer_header = QHBoxLayout()
        thermal_label = QLabel("Thermal")
        thermal_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        visible_label = QLabel("Visible")
        visible_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        viewer_header.addWidget(thermal_label)
        viewer_header.addStretch()
        viewer_header.addWidget(visible_label)
        layout.addLayout(viewer_header)

        viewer_row = QHBoxLayout()
        viewer_row.setSpacing(8)

        thermal_container = QWidget()
        thermal_container.setObjectName("panel")
        thermal_container.setFixedSize(644, 488)
        thermal_layout = QVBoxLayout(thermal_container)
        thermal_layout.setContentsMargins(2, 2, 2, 2)
        self._thermal_view = ThermalView()
        thermal_layout.addWidget(self._thermal_view)
        viewer_row.addWidget(thermal_container)

        visible_container = QWidget()
        visible_container.setObjectName("panel")
        visible_container.setFixedSize(644, 488)
        visible_layout = QVBoxLayout(visible_container)
        visible_layout.setContentsMargins(2, 2, 2, 2)
        self._visible_view = ThermalView()
        visible_layout.addWidget(self._visible_view)
        viewer_row.addWidget(visible_container)

        viewer_row.addStretch()
        layout.addLayout(viewer_row)

        layout.addStretch()

        return widget

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        section = QLabel("ROI Workspace")
        section.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR_TEXT_PRIMARY};")
        layout.addWidget(section)

        self._roi_toolbar = ROIToolbar()
        layout.addWidget(self._roi_toolbar)

        self._roi_list = ROIListWidget()
        layout.addWidget(self._roi_list, 1)

        self._roi_property = ROIPropertyPanel()
        layout.addWidget(self._roi_property, 2)

        return panel

    def _build_status_bar(self) -> None:
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Calibration ready.")
        self._status_bar.addWidget(self._status_label)
        self._fps_label = QLabel("FPS: 0")
        self._status_bar.addPermanentWidget(self._fps_label)
        self._camera_label = QLabel("No camera selected")
        self._status_bar.addPermanentWidget(self._camera_label)

    def _apply_theme(self) -> None:
        self.setStyleSheet(STYLE_MAIN_WINDOW)

    # ---------------------------------------------------------
    # Signal Wiring
    # ---------------------------------------------------------

    def _connect_signals(self) -> None:
        signal_bus = self._roi_signal_bus
        selection = self._roi_selection
        roi_list = self._roi_list
        roi_property = self._roi_property
        toolbar = self._roi_toolbar

        toolbar.create_roi_requested.connect(signal_bus.create_roi_requested.emit)
        toolbar.delete_requested.connect(lambda _: signal_bus.delete_requested.emit(selection.selected_id or ""))
        toolbar.duplicate_requested.connect(lambda _: signal_bus.duplicate_requested.emit(selection.selected_id or ""))
        toolbar.save_requested.connect(signal_bus.save_requested.emit)

        roi_list.selection_changed.connect(signal_bus.roi_selected.emit)
        roi_list.edit_requested.connect(signal_bus.edit_requested.emit)
        roi_list.delete_requested.connect(signal_bus.delete_requested.emit)

        roi_property.alarm_changed.connect(signal_bus.roi_alarm_changed.emit)
        roi_property.appearance_changed.connect(signal_bus.roi_appearance_changed.emit)
        roi_property.recording_changed.connect(signal_bus.roi_recording_changed.emit)
        roi_property.rename_requested.connect(lambda rid, name: signal_bus.roi_renamed.emit(rid))

        signal_bus.roi_created.connect(self._on_roi_created)
        signal_bus.roi_deleted.connect(lambda rid: roi_list.remove_row(rid))
        signal_bus.roi_selected.connect(self._on_roi_selected)
        signal_bus.roi_geometry_changed.connect(self._refresh_roi_list_row)
        signal_bus.roi_alarm_changed.connect(self._refresh_roi_list_row)
        signal_bus.roi_appearance_changed.connect(self._refresh_roi_list_row)
        signal_bus.roi_renamed.connect(self._refresh_roi_list_row)
        signal_bus.dirty_state_changed.connect(toolbar.set_dirty)
        signal_bus.roi_statistics_updated.connect(self._on_roi_statistics_updated)
        signal_bus.roi_alarm_state_changed.connect(self._on_roi_alarm_state_changed)

    def _on_roi_created(self, roi_id: str) -> None:
        config = self._roi_workspace.get_configuration(roi_id)
        if config is not None:
            self._roi_list.add_row(config)

    def _on_roi_selected(self, roi_id: str) -> None:
        self._roi_list.highlight_row(roi_id)
        config = self._roi_workspace.get_configuration(roi_id)
        if config is not None:
            self._roi_property.load_roi(config)

    def _refresh_roi_list_row(self, roi_id: str) -> None:
        config = self._roi_workspace.get_configuration(roi_id)
        if config is not None:
            self._roi_list.update_row(config)

    def _on_roi_statistics_updated(self, camera_id: str) -> None:
        if camera_id != self._roi_workspace.active_camera_id:
            return
        mgr = self._roi_workspace.get_runtime_manager(camera_id)
        if mgr is None:
            return
        for roi in mgr.get_active():
            if roi.statistics is None:
                continue
            s = roi.statistics
            if s.valid:
                self._roi_list.update_temperature(roi.configuration.roi_id, s.maximum)

    def _on_roi_alarm_state_changed(self, roi_id: str, alarm_result: object) -> None:
        from alarm import AlarmResult
        if not isinstance(alarm_result, AlarmResult):
            return
        state_name = alarm_result.state.name if alarm_result.state else ""
        self._roi_list.update_alarm_state(roi_id, state_name)
        if self._roi_property.is_current_roi(roi_id):
            config = self._roi_workspace.get_configuration(roi_id)
            if config is not None:
                self._roi_property.load_roi(config)

    # ---------------------------------------------------------
    # Camera Selection
    # ---------------------------------------------------------

    def refresh_camera_list(self) -> None:
        block = self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        for ctx in self._controller.get_all_cameras():
            self._camera_combo.addItem(ctx.camera_model.camera_name, ctx.camera_id)
        self._camera_combo.blockSignals(block)

    def _on_camera_selected(self, index: int) -> None:
        if index < 0:
            return
        camera_id = self._camera_combo.itemData(index)
        if not camera_id:
            return
        self._select_camera(camera_id)

    def _select_camera(self, camera_id: str) -> None:
        self._selected_camera_id = camera_id

        try:
            self._controller.select_camera(camera_id)
            focus_dist = self._controller.get_focus_distance_selected()
            self._control_panel.show_selection(camera_id, focus_dist)
            self._status_label.setText("Selected: " + camera_id)
            self._camera_label.setText("Camera: " + camera_id)
        except Exception:
            self._control_panel.show_selection(camera_id, None)
            self._status_label.setText("Selected: " + camera_id)

        try:
            self._roi_signal_bus.camera_changed.emit(camera_id)
            acq_state = AcquisitionState(camera_id=camera_id)
            self._roi_workspace.load_state(acq_state)
            self._roi_list.rebuild(self._roi_workspace.get_all_configurations())
            self._roi_property.clear()
        except Exception:
            logger.exception("Failed to load ROI state for " + camera_id)

    # ---------------------------------------------------------
    # Frame Polling
    # ---------------------------------------------------------

    def start_polling(self) -> None:
        self._poll_timer.start(self.POLL_INTERVAL_MS)

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    def _poll_frame(self) -> None:
        if not self._selected_camera_id:
            return

        context = self._controller.get_camera(self._selected_camera_id)
        if context is None:
            return

        try:
            raw = context.camera.get_frame()
            if raw is None:
                return

            cal = context.camera.get_calibration_manager()
            display = cal.raw_to_display(raw)
            rgb = cal.apply_colormap(display)
            temperature = cal.raw_to_temperature(raw)

            self._roi_workspace.process_frame(
                camera_id=context.camera_id,
                temperature_image=temperature,
                frame_id=0,
            )

            self._thermal_view.display_image(rgb)
            self._control_panel.update_info(fps=0.0, status="streaming")

        except Exception:
            pass

    # ---------------------------------------------------------
    # NUC & Focus
    # ---------------------------------------------------------

    def _on_nuc_clicked(self) -> None:
        if not self._selected_camera_id:
            return
        self._control_panel.set_nuc_busy(True)
        self._status_label.setText("NUC in progress...")
        QApplication.processEvents()
        try:
            self._controller.perform_nuc(self._selected_camera_id)
            self._status_label.setText("NUC completed.")
        except Exception:
            self._status_label.setText("NUC failed.")
            logger.exception("NUC failed")
        finally:
            self._control_panel.set_nuc_busy(False)

    def _on_focus_near(self) -> None:
        self._execute_focus("near")

    def _on_focus_far(self) -> None:
        self._execute_focus("far")

    def _execute_focus(self, direction: str) -> None:
        if not self._selected_camera_id:
            return
        self._control_panel.set_focus_busy(True)
        self._status_label.setText("Focus " + direction + "...")
        QApplication.processEvents()
        try:
            if direction == "near":
                requested, actual = self._controller.focus_near(self._selected_camera_id)
            else:
                requested, actual = self._controller.focus_far(self._selected_camera_id)
            self._control_panel.update_focus_distance(actual)
            self._status_label.setText("Focus " + direction + ": " + f"{actual:.0f}mm")
        except Exception:
            self._status_label.setText("Focus failed.")
            logger.exception("Focus failed")
        finally:
            self._control_panel.set_focus_busy(False)

    def _on_save(self) -> None:
        self._roi_workspace._on_save()
        self._status_label.setText("ROI configurations saved.")

    # ---------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_polling()
        try:
            self._controller.select_camera(None)
            self._control_panel.clear_selection()
        except Exception:
            pass
        event.accept()
