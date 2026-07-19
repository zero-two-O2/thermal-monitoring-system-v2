"""
calibration_manager.py

Main calibration controller.

Responsible for:

    - Loading calibration
    - Building lookup tables
    - Providing temperature conversion
"""

import numpy as np

from calibration.calibration_models import CameraCalibration

from calibration.calibration_parser import CalibrationParser

from calibration.temperature_converter import TemperatureConverter

from configuration import settings

from utilities import logger


class CalibrationManager:

    """
    Main calibration manager.
    """

    def __init__(self):

        self._calibration = CameraCalibration()

        self._initialized = False

    # ======================================================
    # Initialization
    # ======================================================

    def initialize(self):

        logger.info("Loading camera calibration...")

        parser = CalibrationParser()

        self._calibration = parser.load(
            settings.CALIBRATION_FILE
        )

        logger.info("Building lookup tables...")

        TemperatureConverter.build_lookup_tables(
            self._calibration
        )

        self._initialized = True

        logger.info("Calibration initialized successfully.")

    # ======================================================
    # Calibration
    # ======================================================

    def get_calibration(self):

        return self._calibration

    # ======================================================
    # LUT
    # ======================================================

    def get_lookup_table(
        self,
        range_index: int = 0
    ):

        return self._calibration.get_lookup_table(
            range_index
        )

    # ======================================================
    # Temperature Conversion
    # ======================================================

    def raw_to_temperature(
        self,
        raw_image: np.ndarray,
        range_index: int = 0
    ):

        return TemperatureConverter.raw_to_temperature(
            raw_image,
            self._calibration,
            range_index
        )

    # ======================================================
    # Status
    # ======================================================

    def is_initialized(self):

        return self._initialized