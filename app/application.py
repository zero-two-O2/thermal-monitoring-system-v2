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