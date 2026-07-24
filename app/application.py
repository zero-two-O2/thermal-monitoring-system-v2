"""
application.py

Main application bootstrap.

Responsibilities
----------------
- Create QApplication
- Create the ApplicationController
- Create the MainWindow
- Initialize the backend
- Start the Qt event loop
- Shutdown the backend cleanly
"""

from __future__ import annotations

import sys

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
    """

    def __init__(self) -> None:

        # Create Qt application
        self._qt_app = QApplication(sys.argv)

        # Create backend controller
        self._controller = ApplicationController()

        # Create GUI
        self._window = MainWindow(self._controller)

    # ==========================================================
    # Properties
    # ==========================================================

    @property
    def qt_app(self) -> QApplication:
        """Return QApplication."""
        return self._qt_app

    @property
    def controller(self) -> ApplicationController:
        """Return ApplicationController."""
        return self._controller

    @property
    def window(self) -> MainWindow:
        """Return MainWindow."""
        return self._window

    # ==========================================================
    # Initialization
    # ==========================================================

    def initialize(self) -> None:
        """
        Initialize backend services.

        Called once before showing the GUI.
        """

        self._controller.initialize()

        self._discover_and_register_cameras()

    def _discover_and_register_cameras(self) -> None:
        """
        Discover GigE Vision cameras and register them with the
        controller and main window.
        """

        try:

            import halcon as ha

            from camera.factory.camera_factory import CameraFactory
            from camera.models.camera_model import CameraModel

            _info, boards = ha.info_framegrabber(
                "GigEVision2",
                "info_boards",
            )

            factory = CameraFactory()

            for board in boards:

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

                self._window.add_camera(context)

                print(
                    f"[INFO] Registered camera: "
                    f"{camera_id} ({fields.get('model', '')})"
                )

        except Exception as exc:

            print(
                f"[WARN] Camera discovery failed: {exc}"
            )

    # ==========================================================
    # GUI
    # ==========================================================

    def show(self) -> None:
        """
        Show the main window.
        """

        self._window.show()

    # ==========================================================
    # Shutdown
    # ==========================================================

    def shutdown(self) -> None:
        """
        Shutdown backend cleanly.
        """

        self._controller.shutdown()

    # ==========================================================
    # Run
    # ==========================================================

    def run(self) -> int:
        """
        Run the application.
        """

        self.initialize()

        self.show()

        try:
            return self._qt_app.exec_()

        finally:
            self.shutdown()