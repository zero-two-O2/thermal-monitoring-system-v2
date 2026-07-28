"""
application.py

Main application bootstrap.

Responsibilities
----------------
- Create QApplication
- Create the ApplicationController
- Create the MainWindow
- Create CalibrationWindow and ObserverWindow on demand
- Initialize the backend
- Start the Qt event loop
- Shutdown the backend cleanly
"""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.application_controller import ApplicationController
from gui.main_window import MainWindow


class Application:
    """
    Main application object.

    Owns:
        - QApplication
        - ApplicationController
        - MainWindow
        - CalibrationWindow (lazy)
        - ObserverWindow (lazy)
    """

    def __init__(self) -> None:

        self._qt_app = QApplication(sys.argv)
        self._controller = ApplicationController()

        self._window = MainWindow(self._controller)

        self._calibration_window = None
        self._observation_window = None
        self._camera_detail_windows: dict = {}

        self._wire_window_signals()

    @property
    def qt_app(self) -> QApplication:
        return self._qt_app

    @property
    def controller(self) -> ApplicationController:
        return self._controller

    @property
    def window(self) -> MainWindow:
        return self._window

    # ---------------------------------------------------------
    # Signal Wiring
    # ---------------------------------------------------------

    def _wire_window_signals(self) -> None:
        self._window.calibration_requested.connect(self._open_calibration)
        self._window.observation_requested.connect(self._open_observation)
        self._window.camera_detail_requested.connect(self._open_camera_detail)
        self._window.discover_requested.connect(self._on_discover_requested)

    def _open_calibration(self) -> None:
        from gui.calibration.calibration_window import CalibrationWindow

        if self._calibration_window is None:
            self._calibration_window = CalibrationWindow(self._controller)
            self._calibration_window.destroyed.connect(self._on_calibration_closed)
        else:
            self._calibration_window.refresh_camera_list()

        self._calibration_window.show()
        self._calibration_window.raise_()
        self._calibration_window.start_polling()

    def _on_calibration_closed(self) -> None:
        if self._calibration_window is not None:
            self._calibration_window.stop_polling()
        self._calibration_window = None

    def _open_observation(self) -> None:
        from gui.observer.observer_window import ObserverWindow

        if self._observation_window is None:
            self._observation_window = ObserverWindow(self._controller)
            self._observation_window.destroyed.connect(self._on_observation_closed)

        self._observation_window.refresh_cameras()
        self._observation_window.show()
        self._observation_window.raise_()
        self._observation_window.start_polling()

    def _on_observation_closed(self) -> None:
        if self._observation_window is not None:
            self._observation_window.stop_polling()
        self._observation_window = None

    def _open_camera_detail(self, camera_id: str) -> None:
        from gui.camera_detail_window import CameraDetailWindow

        if camera_id in self._camera_detail_windows:
            w = self._camera_detail_windows[camera_id]
            if w is not None:
                try:
                    w.show()
                    w.raise_()
                    return
                except RuntimeError:
                    pass

        ctx = self._controller.get_camera(camera_id)
        name = ctx.camera_model.camera_name if ctx else camera_id

        detail = CameraDetailWindow(camera_id, name, self._controller)
        detail.setAttribute(Qt.WA_DeleteOnClose)
        detail.destroyed.connect(lambda: self._camera_detail_windows.pop(camera_id, None))
        self._camera_detail_windows[camera_id] = detail

        detail.show()
        detail.start_polling()

    def _on_discover_requested(self) -> None:
        self._discover_and_register_cameras()

    # ---------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------

    def initialize(self) -> None:
        self._controller.initialize()
        self._discover_and_register_cameras()

    def _discover_and_register_cameras(self) -> None:
        import halcon as ha

        from camera.factory.camera_factory import CameraFactory
        from camera.models.camera_model import CameraModel

        try:
            _info, boards = ha.info_framegrabber(
                "GigEVision2",
                "info_boards",
            )
        except Exception as exc:
            print(f"[WARN] HALCON board enumeration failed: {exc}")
            return

        factory = CameraFactory()

        for board in boards:

            try:
                fields: dict[str, str] = {}

                for item in str(board).split("|"):

                    item = item.strip()

                    if ":" not in item:
                        continue

                    key, value = item.split(":", 1)

                    fields[key.strip()] = value.strip()

                device = fields.get("device", "")

                if not device:
                    continue

                serial = fields.get("device_sn", "")

                camera_id = (
                    f"cam_{serial}" if serial else f"cam_{device}"
                )

                existing = self._controller.get_camera(camera_id)
                if existing is not None:
                    print(
                        f"[INFO] Camera already registered: "
                        f"{camera_id}"
                    )
                    continue

                model = CameraModel(
                    camera_id=camera_id,
                    camera_name=(
                        f"Camera {serial}"
                        if serial
                        else f"Camera {device}"
                    ),
                    vendor=fields.get("vendor", ""),
                    model=fields.get("model", ""),
                    serial_number=serial,
                    ip_address=fields.get("device_ip", ""),
                    device_identifier=device,
                )

                context = factory.create_camera(model)

                self._controller.add_camera(context)

                self._window.add_camera(
                    camera_id,
                    model.camera_name,
                    model.serial_number,
                    model.ip_address,
                    model.model,
                )

                print(
                    f"[INFO] Registered camera: "
                    f"{camera_id} ({fields.get('model', '')})"
                )

            except Exception as exc:

                print(
                    f"[WARN] Camera discovery failed for "
                    f"'{device}': {exc}"
                )

    # ---------------------------------------------------------
    # GUI
    # ---------------------------------------------------------

    def show(self) -> None:
        self._window.show()

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def shutdown(self) -> None:
        if self._calibration_window is not None:
            self._calibration_window.stop_polling()
            self._calibration_window.close()
        if self._observation_window is not None:
            self._observation_window.stop_polling()
            self._observation_window.close()
        for cid, w in list(self._camera_detail_windows.items()):
            try:
                w.stop_polling()
                w.close()
            except RuntimeError:
                pass
        self._camera_detail_windows.clear()
        if self._window is not None:
            try:
                self._window.shutdown_utility_windows()
            except Exception:
                pass
        self._controller.shutdown()

    # ---------------------------------------------------------
    # Run
    # ---------------------------------------------------------

    def run(self) -> int:
        self.initialize()
        self.show()

        try:
            return self._qt_app.exec_()
        finally:
            self.shutdown()
