"""
logger.py

Central logging system for the application.

Usage
-----
from utilities import logger

logger.info("Application started")
logger.warning("Camera disconnected")
logger.error("Connection failed")
"""

import logging
from pathlib import Path

from configuration import settings


class Logger:

    def __init__(self):

        self._logger = logging.getLogger(settings.PROJECT_NAME)

        if self._logger.handlers:
            return

        self._logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )

        # Console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # File
        if settings.ENABLE_LOGGING:

            settings.LOG_FOLDER.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(
                Path(settings.LOG_FOLDER) / "application.log",
                encoding="utf-8"
            )

            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

        self._logger.propagate = False

    # ----------------------------------------------------------

    def debug(self, message: str):

        self._logger.debug(message)

    def info(self, message: str):

        self._logger.info(message)

    def warning(self, message: str):

        self._logger.warning(message)

    def error(self, message: str):

        self._logger.error(message)

    def critical(self, message: str):

        self._logger.critical(message)

    def exception(self, message: str):

        self._logger.exception(message)


logger = Logger()