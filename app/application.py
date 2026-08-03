"""
application.py

Main application bootstrap.

Responsibilities
----------------
- Create QApplication
- Create the ApplicationController
- Own every window through the WindowRegistry
- Centralize navigation between windows
- Initialize the backend
- Start the Qt event loop
- Shutdown the backend cleanly

Windows are created, shown and closed only through the registry.
No window constructs or manipulates another window.
"""

from __future__ import annotations

import sys
import weakref

from PyQt5.QtWidgets import QApplication

from app.application_controller import ApplicationController
from app.window_registry import WindowID, WindowRegistry
from gui.main_window import MainWindow


class Application:
    """
    Main application object.

    Owns:
        - QApplication
        - ApplicationController
        - WindowRegistry (single owner of every window)
    """

    def __init__(self) -> None:

        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._controller = ApplicationController()
        self._registry = WindowRegistry()
        self._wired_main_windows: weakref.WeakSet = weakref.WeakSet()
        self._wired_observation_windows: weakref.WeakSet = weakref.WeakSet()

        self._register_windows()
        self.open_main()

    # ---------------------------------------------------------
    # Window Registry
    # ---------------------------------------------------------

    def _register_windows(self) -> None:
        controller = self._controller

        self._registry.register(
            WindowID.MAIN,
            lambda: MainWindow(controller),
            on_open=self._wire_main_window,
        )
        self._registry.register(
            WindowID.CALIBRATION,
            lambda: self._make_calibration_window(),
            on_open=lambda window: (
                window.refresh_camera_list(),
                window.start_polling(),
            ),
            on_close=lambda window: window.stop_polling(),
        )
        self._registry.register(
            WindowID.OBSERVATION,
            lambda: self._make_observation_window(),
            on_open=lambda window: (
                self._populate_observation_window(window),
                window.start_polling(),
            ),
            on_close=lambda window: window.stop_polling(),
        )
        self._registry.register(
            WindowID.CAMERA_DETAIL,
            lambda camera_id, camera_name: self._make_camera_detail_window(
                camera_id, camera_name
            ),
            on_open=lambda window: window.start_polling(),
            on_close=lambda window: window.stop_polling(),
        )

    # Window modules are imported lazily so that starting the
    # application never depends on optional modules (e.g. ROI/HALCON).
    def _make_calibration_window(self):
        from gui.calibration.calibration_window import CalibrationWindow

        return CalibrationWindow(self._controller)

    def _make_observation_window(self):
        from gui.observer.observer_window import ObserverWindow

        return ObserverWindow(self._controller)

    def _make_camera_detail_window(self, camera_id: str, camera_name: str):
        from gui.camera_detail_window import CameraDetailWindow

        return CameraDetailWindow(camera_id, camera_name, self._controller)

    def _wire_main_window(self, main_window: MainWindow) -> None:
        if main_window in self._wired_main_windows:
            return
        self._wired_main_windows.add(main_window)
        main_window.calibration_requested.connect(self.open_calibration)
        main_window.observation_requested.connect(self.open_observation)
        main_window.discover_requested.connect(self._on_discover_requested)
        main_window.cameras_disconnected.connect(self._on_cameras_disconnected)

    def _populate_observation_window(self, window) -> None:
        if window not in self._wired_observation_windows:
            self._wired_observation_windows.add(window)
            window.camera_detail_requested.connect(self.open_camera_detail)
        for context in self._controller.get_all_cameras():
            window.add_camera(context)

    # ---------------------------------------------------------
    # Properties
    # ---------------------------------------------------------

    @property
    def qt_app(self) -> QApplication:
        return self._qt_app

    @property
    def controller(self) -> ApplicationController:
        return self._controller

    @property
    def registry(self) -> WindowRegistry:
        return self._registry

    @property
    def window(self) -> MainWindow:
        return self._registry.get(WindowID.MAIN)

    # ---------------------------------------------------------
    # Navigation
    # ---------------------------------------------------------

    def open_main(self) -> None:
        self._registry.open(WindowID.MAIN)

    def open_calibration(self) -> None:
        self._registry.open(WindowID.CALIBRATION)

    def open_observation(self) -> None:
        self._registry.open(WindowID.OBSERVATION)

    def open_camera_detail(self, camera_id: str) -> None:
        context = self._controller.get_camera(camera_id)
        name = context.camera_model.camera_name if context else camera_id
        self._registry.open(
            WindowID.CAMERA_DETAIL,
            instance_key=camera_id,
            camera_id=camera_id,
            camera_name=name,
        )

    def close_camera_detail(self, camera_id: str) -> None:
        self._registry.close(WindowID.CAMERA_DETAIL, instance_key=camera_id)

    def close_all_windows(self) -> None:
        self._registry.close_all()

    # ---------------------------------------------------------
    # Window Signal Handling
    # ---------------------------------------------------------

    def _on_cameras_disconnected(self, camera_ids: list) -> None:
        for camera_id in camera_ids:
            self.close_camera_detail(camera_id)

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

                main_window = self.window
                if main_window is not None:
                    main_window.add_camera(
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
        self.open_main()

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def shutdown(self) -> None:
        self.close_all_windows()
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
