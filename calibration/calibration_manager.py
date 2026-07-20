"""
calibration_manager.py

Main calibration controller.

Responsibilities
----------------
- Load calibration from file
- Build lookup tables
- Convert raw images to temperature
- Provide access to calibration data
"""

from __future__ import annotations
import numpy as np
from calibration.calibration_models import CameraCalibration
from calibration.calibration_parser import CalibrationParser
from calibration.calibration_processor import CalibrationProcessor
from configuration import settings
from utilities import logger


class CalibrationManager:
    """
    High-level interface to the calibration subsystem.
    This class owns the CameraCalibration object and delegates
    all processing work to CalibrationProcessor.
    """

    def __init__(self) -> None:
        self._calibration = CameraCalibration()
        self._initialized = False

    # ==========================================================
    # Initialization
    # ==========================================================

    def initialize(self) -> None:
        logger.info("=" * 60)
        logger.info("Initializing Calibration")
        logger.info("=" * 60)
        parser = CalibrationParser()
        self._calibration = parser.load(
            settings.CALIBRATION_FILE
        )
        CalibrationProcessor.build_lookup_tables(
            self._calibration
        )
        self._initialized = True
        logger.info("Calibration initialized successfully.")


    # ==========================================================
    # Status
    # ==========================================================

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ==========================================================
    # Calibration
    # ==========================================================

    @property
    def calibration(self) -> CameraCalibration:
        return self._calibration
    def get_calibration(self) -> CameraCalibration:
        return self._calibration

    # ==========================================================
    # Lookup Tables
    # ==========================================================

    def get_lookup_table(
        self,
        range_index: int = 0,
    ) -> np.ndarray | None:
        return self._calibration.get_lookup_table(
            range_index
        )
    def rebuild_lookup_tables(self) -> None:
        CalibrationProcessor.rebuild_lookup_tables(
            self._calibration
        )
    def clear_lookup_tables(self) -> None:
        CalibrationProcessor.clear_lookup_tables(
            self._calibration
        )
    def validate_lookup_tables(self) -> bool:
        return CalibrationProcessor.validate_lookup_tables(
            self._calibration
        )

    # ==========================================================
    # Temperature Conversion
    # ==========================================================

    def raw_to_temperature(
        self,
        raw_image: np.ndarray,
        range_index: int = 0,
    ) -> np.ndarray:
        return CalibrationProcessor.raw_to_temperature(
            raw_image,
            self._calibration,
            range_index,
        )

    def raw_to_display(
        self,
        raw_image: np.ndarray,
        range_index: int = 0,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> np.ndarray:
        return CalibrationProcessor.raw_to_display(
            raw_image,
            self._calibration,
            range_index,
            minimum,
            maximum,
        )

    # ==========================================================
    # Statistics
    # ==========================================================

    def get_temperature_statistics(
        self,
        temperature_image: np.ndarray,
    ) -> dict:
        return CalibrationProcessor.get_temperature_statistics(
            temperature_image
        )

    def get_roi_statistics(
        self,
        temperature_image: np.ndarray,
        roi_mask: np.ndarray,
    ) -> dict:
        return CalibrationProcessor.get_roi_statistics(
            temperature_image,
            roi_mask,
        )

    # ==========================================================
    # Display Utilities
    # ==========================================================

    def temperature_to_display(
        self,
        temperature_image: np.ndarray,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> np.ndarray:
        return CalibrationProcessor.temperature_to_display(
            temperature_image,
            minimum,
            maximum,
        )

    def apply_colormap(
        self,
        display_image: np.ndarray,
        colormap: int,
    ) -> np.ndarray:
        return CalibrationProcessor.apply_colormap(
            display_image,
            colormap,
        )