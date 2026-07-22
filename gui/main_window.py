"""
main_window.py

Qualification tool main window.

Layout:
    Top:    Responsive grid of camera tiles (images + compact status)
    Bottom: Camera Control Panel (NUC, Focus, info) for selected camera

Uses existing production APIs:
    TV46LCamera.perform_nuc()
    TV46LCamera.focus_near()
    TV46LCamera.focus_far()
    TV46LCamera.get_focus_distance()
"""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QGridLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QSplitter
from PyQt5.QtWidgets import QStatusBar
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget

from app.application_controller import ApplicationController
from camera.models.camera_context import CameraContext

from gui.widgets.camera_control_panel import CameraControlPanel
from gui.widgets.camera_tile import CameraTile

from utilities import logger


LIGHT_THEME = """
QMainWindow {
    background-color: #FFFFFF;
}
QWidget {
    background-color: #FFFFFF;
    color: #1A1A1A;
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 11px;
}
QPushButton {
    background-color: #F0F0F0;
    color: #333333;
    border: 1px solid #CCCCCC;
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 11px;
}
QPushButton:hover {
    background-color: #E0E0E0;
    border: 1px solid #999999;
}
QPushButton:pressed {
    background-color: #D0D0D0;
}
QPushButton:disabled {
    background-color: #F5F5F5;
    color: #AAAAAA;
    border: 1px solid #DDDDDD;
}
QStatusBar {
    background-color: #F5F5F5;
    border-top: 1px solid #D0D0D0;
    color: #555555;
    font-size: 10px;
}
QStatusBar QLabel {
    color: #555555;
    font-size: 10px;
}
QSplitter::handle {
    background-color: #D0D0D0;
    height: 1px;
}
"""


class MainWindow(QMainWindow):
    """
    Qualification tool main window.
    """

    POLL_INTERVAL_MS = 33

    def __init__(
        self,
        controller: ApplicationController,
    ) -> None:

        super().__init__()

        self._controller = controller

        self._tiles: dict[str, CameraTile] = {}
        self._cameras: list[CameraContext] = []

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(
            self._poll_frames
        )

        self._focus_busy = False
        self._nuc_busy = False

        self._build_ui()
        self._apply_theme()

    # ---------------------------------------------------------
    # UI Build
    # ---------------------------------------------------------

    def _build_ui(self) -> None:

        self.setWindowTitle(
            "Thermal Monitoring System - Camera Qualification Tool"
        )
        self.setMinimumSize(1024, 700)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        #
        # Toolbar
        #

        toolbar = self._build_toolbar()
        root.addWidget(toolbar)

        #
        # Splitter: Tiles (top) / Control Panel (bottom)
        #

        splitter = QSplitter(Qt.Vertical)

        #
        # Camera Tile Grid
        #

        self._tile_container = QWidget()
        self._tile_grid = QGridLayout(
            self._tile_container
        )
        self._tile_grid.setContentsMargins(0, 0, 0, 0)
        self._tile_grid.setSpacing(6)

        self._empty_label = QLabel(
            "No cameras connected.\n\n"
            "Use Start All to begin acquisition."
        )
        self._empty_label.setAlignment(
            Qt.AlignCenter
        )
        self._empty_label.setStyleSheet(
            "color: #999999; font-size: 16px;"
        )
        self._tile_grid.addWidget(
            self._empty_label,
            0,
            0,
        )

        splitter.addWidget(self._tile_container)

        #
        # Camera Control Panel
        #

        self._control_panel = CameraControlPanel()
        self._control_panel.nuc_clicked.connect(
            self._on_nuc_clicked
        )
        self._control_panel.focus_near_clicked.connect(
            self._on_focus_near
        )
        self._control_panel.focus_far_clicked.connect(
            self._on_focus_far
        )

        splitter.addWidget(self._control_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

        #
        # Status Bar
        #

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._status_label = QLabel("Ready")
        self._status_bar.addWidget(
            self._status_label
        )

        self._fps_status_label = QLabel("")
        self._status_bar.addPermanentWidget(
            self._fps_status_label
        )

        self._camera_count_label = QLabel("Cameras: 0")
        self._status_bar.addPermanentWidget(
            self._camera_count_label
        )

    def _build_toolbar(self) -> QWidget:

        bar = QWidget()
        bar.setStyleSheet(
            "background-color: #F5F5F5;"
            "border: 1px solid #D0D0D0;"
            "border-radius: 3px;"
        )

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        title = QLabel("Camera Qualification Tool")
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold;"
            "color: #1A1A1A;"
        )
        layout.addWidget(title)
        layout.addSpacing(16)

        self._start_all_btn = QPushButton("Start All")
        self._start_all_btn.clicked.connect(
            self._on_start_all
        )
        layout.addWidget(self._start_all_btn)

        self._stop_all_btn = QPushButton("Stop All")
        self._stop_all_btn.clicked.connect(
            self._on_stop_all
        )
        layout.addWidget(self._stop_all_btn)

        layout.addStretch()

        return bar

    def _apply_theme(self) -> None:

        self.setStyleSheet(LIGHT_THEME)

    # ---------------------------------------------------------
    # Camera Registration
    # ---------------------------------------------------------

    def add_camera(
        self,
        context: CameraContext,
    ) -> None:

        camera_id = context.camera_id

        if camera_id in self._tiles:
            return

        self._cameras.append(context)

        tile = CameraTile(
            camera_id=camera_id,
            camera_name=f"{camera_id}",
        )
        tile.clicked.connect(
            self._on_tile_clicked
        )

        self._tiles[camera_id] = tile

        self._rebuild_grid()

        logger.info(
            f"Camera tile added: {camera_id}"
        )

    def remove_camera(
        self,
        camera_id: str,
    ) -> None:

        tile = self._tiles.pop(
            camera_id,
            None,
        )

        if tile is None:
            return

        self._cameras = [
            c
            for c in self._cameras
            if c.camera_id != camera_id
        ]

        if (
            self._controller.selected_camera_id
            == camera_id
        ):
            self._controller.select_camera(None)
            self._control_panel.clear_selection()

        self._rebuild_grid()

    # ---------------------------------------------------------
    # Grid Layout
    # ---------------------------------------------------------

    def _rebuild_grid(self) -> None:

        while self._tile_grid.count():
            item = self._tile_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        count = len(self._tiles)

        if count == 0:

            self._empty_label = QLabel(
                "No cameras connected."
            )
            self._empty_label.setAlignment(
                Qt.AlignCenter
            )
            self._empty_label.setStyleSheet(
                "color: #999999; font-size: 16px;"
            )
            self._tile_grid.addWidget(
                self._empty_label,
                0,
                0,
            )
            self._camera_count_label.setText(
                "Cameras: 0"
            )
            return

        cols = self._grid_columns(count)

        for i, tile in enumerate(
            self._tiles.values()
        ):
            row = i // cols
            col = i % cols
            self._tile_grid.addWidget(
                tile,
                row,
                col,
            )

        self._camera_count_label.setText(
            f"Cameras: {count}"
        )

    @staticmethod
    def _grid_columns(
        count: int,
    ) -> int:

        if count <= 1:
            return 1
        if count <= 4:
            return 2
        if count <= 6:
            return 3
        return 4

    # ---------------------------------------------------------
    # Frame Polling
    # ---------------------------------------------------------

    def start_polling(self) -> None:

        self._poll_timer.start(
            self.POLL_INTERVAL_MS
        )

    def stop_polling(self) -> None:

        self._poll_timer.stop()

    def _poll_frames(self) -> None:

        for context in self._cameras:

            camera_id = context.camera_id
            tile = self._tiles.get(camera_id)

            if tile is None:
                continue

            try:

                raw = context.camera.get_frame()

                if raw is None:
                    continue

                rgb = self._process_frame(
                    raw,
                    context,
                )

                if rgb is not None:

                    tile.update_frame(
                        image=rgb,
                        frame_count=0,
                        sequence=0,
                        latency_ms=0.0,
                        dropped=0,
                        timeouts=0,
                        fps=0.0,
                    )

            except Exception:

                logger.exception(
                    f"Frame poll failed for {camera_id}"
                )

        #
        # Update selected camera info
        #

        self._update_selected_info()

    def _process_frame(
        self,
        raw: np.ndarray,
        context: CameraContext,
    ) -> np.ndarray | None:

        try:

            cal = context.camera.get_calibration_manager()

            display = cal.raw_to_display(raw)

            rgb = cal.apply_colormap(display)

            return rgb

        except Exception:

            logger.exception(
                "Frame processing failed"
            )
            return None

    # ---------------------------------------------------------
    # Tile Selection
    # ---------------------------------------------------------

    def _on_tile_clicked(
        self,
        camera_id: str,
    ) -> None:

        if self._controller.selected_camera_id == camera_id:
            return

        for cid, tile in self._tiles.items():
            tile.set_selected(cid == camera_id)

        try:

            self._controller.select_camera(camera_id)

            focus_dist = (
                self._controller.get_focus_distance_selected()
            )

            self._control_panel.show_selection(
                camera_id=camera_id,
                focus_distance=focus_dist,
            )

            self._status_label.setText(
                f"Selected camera: {camera_id}"
            )

        except Exception as exc:

            logger.exception(
                f"Failed to select camera {camera_id}"
            )

            self._control_panel.show_selection(
                camera_id=camera_id,
                focus_distance=None,
            )

    def _update_selected_info(self) -> None:

        selected = self._controller.selected_camera

        if selected is None:
            return

        try:

            focus_dist = (
                self._controller.get_focus_distance_selected()
            )

            self._control_panel.update_focus_distance(
                focus_dist
            )

        except Exception:
            pass

    # ---------------------------------------------------------
    # Toolbar Actions
    # ---------------------------------------------------------

    def _on_start_all(self) -> None:

        try:

            self._controller.connect_all()
            self._controller.start_all()

            self._status_label.setText(
                "Acquisition started."
            )

            self.start_polling()

        except Exception as exc:

            logger.exception("Start all failed")
            self._status_label.setText(
                f"Start failed: {exc}"
            )

    def _on_stop_all(self) -> None:

        self.stop_polling()

        try:

            self._controller.stop_all()
            self._controller.disconnect_all()

            self._status_label.setText(
                "Acquisition stopped."
            )

        except Exception as exc:

            logger.exception("Stop all failed")
            self._status_label.setText(
                f"Stop failed: {exc}"
            )

        for tile in self._tiles.values():
            tile.set_selected(False)

        self._controller.select_camera(None)
        self._control_panel.clear_selection()

    # ---------------------------------------------------------
    # NUC
    # ---------------------------------------------------------

    def _on_nuc_clicked(self) -> None:

        if self._nuc_busy:
            return

        selected = self._controller.selected_camera

        if selected is None:
            return

        self._nuc_busy = True
        self._control_panel.set_nuc_busy(True)
        self._status_label.setText(
            f"NUC in progress on {selected.camera_id}..."
        )

        QApplication.processEvents()

        try:

            self._controller.perform_nuc_selected()

            self._status_label.setText(
                f"NUC completed on {selected.camera_id}."
            )

        except Exception as exc:

            logger.exception("NUC failed")
            self._status_label.setText(
                f"NUC failed: {exc}"
            )

        finally:

            self._nuc_busy = False
            self._control_panel.set_nuc_busy(False)

    # ---------------------------------------------------------
    # Focus
    # ---------------------------------------------------------

    def _on_focus_near(self) -> None:

        self._execute_focus("near")

    def _on_focus_far(self) -> None:

        self._execute_focus("far")

    def _execute_focus(
        self,
        direction: str,
    ) -> None:

        if self._focus_busy:
            return

        selected = self._controller.selected_camera

        if selected is None:
            return

        self._focus_busy = True
        self._control_panel.set_focus_busy(True)
        self._status_label.setText(
            f"Focus {direction} on {selected.camera_id}..."
        )

        QApplication.processEvents()

        try:

            if direction == "near":

                requested, actual = (
                    self._controller.focus_near_selected()
                )

            else:

                requested, actual = (
                    self._controller.focus_far_selected()
                )

            self._control_panel.update_focus_distance(
                actual
            )

            self._status_label.setText(
                f"Focus {direction}: "
                f"requested={requested:.0f}mm, "
                f"actual={actual:.0f}mm"
            )

        except Exception as exc:

            logger.exception(
                f"Focus {direction} failed"
            )
            self._status_label.setText(
                f"Focus {direction} failed: {exc}"
            )

        finally:

            self._focus_busy = False
            self._control_panel.set_focus_busy(False)

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def closeEvent(
        self,
        event: QCloseEvent,
    ) -> None:

        self.stop_polling()

        try:

            self._controller.shutdown()

        except Exception:

            logger.exception(
                "Shutdown error"
            )

        event.accept()

    # ---------------------------------------------------------
    # Show
    # ---------------------------------------------------------

    def show(self) -> None:

        super().show()

        self.start_polling()
