"""
processing_pipeline.py

Main processing pipeline for one thermal frame.

Pipeline

Raw Frame
    │
    ▼
Calibration
    │
    ▼
Temperature Image
    │
    ├── Statistics
    ├── ROI Processing
    ├── Alarm Processing
    └── Display Image
"""

from __future__ import annotations

from typing import Optional

from calibration.calibration_manager import CalibrationManager
from calibration.calibration_processor import CalibrationProcessor

from processing.models.processing_models import (
    RawFrame,
    ProcessedFrame,
    CameraStatistics,
    FrameResult,
)

from processing.roi_processor import ROIProcessor
from processing.alarm_processor import AlarmProcessor

from utilities import logger


class ProcessingPipeline:
    """
    High-level frame processing pipeline.

    This class coordinates the individual processors.

    It does not implement ROI or Alarm logic itself.
    """

    def __init__(
        self,
        calibration_manager: CalibrationManager,
    ) -> None:

        self._calibration = calibration_manager

        self._roi_processor = ROIProcessor()

        self._alarm_processor = AlarmProcessor()

    # ==========================================================
    # Public
    # ==========================================================

    def process(
        self,
        raw_frame: RawFrame,
    ) -> FrameResult:
        """
        Process one camera frame.
        """

        logger.debug(
            "Processing frame..."
        )

        calibration = self._calibration.get_calibration()

        #
        # Raw -> Temperature
        #

        temperature_image = (
            CalibrationProcessor.raw_to_temperature(

                raw_frame.image,

                calibration,

                raw_frame.range_index,

            )
        )

        #
        # Display Image
        #

        display_image = (
            CalibrationProcessor.raw_to_display(

                raw_frame.image,

                calibration,

                raw_frame.range_index,

            )
        )

        #
        # Statistics
        #

        statistics = self._build_statistics(
            temperature_image
        )

        #
        # Processed Frame
        #

        processed_frame = ProcessedFrame(

            raw_frame=raw_frame,

            temperature_image=temperature_image,

            display_image=display_image,

        )

        #
        # ROI Analysis
        #

        roi_results = (
            self._roi_processor.process(

                processed_frame

            )
        )

        #
        # Alarm Evaluation
        #

        alarms = (
            self._alarm_processor.process(

                roi_results

            )
        )

        return FrameResult(

            raw_frame=raw_frame,

            processed_frame=processed_frame,

            statistics=statistics,

            roi_results=roi_results,

            alarms=alarms,

        )
        # ==========================================================
    # Statistics
    # ==========================================================

    def _build_statistics(
        self,
        temperature_image,
    ) -> CameraStatistics:
        """
        Calculate frame statistics.
        """

        statistics = (
            CalibrationProcessor.get_temperature_statistics(
                temperature_image
            )
        )

        return CameraStatistics(

            minimum=statistics["minimum"],

            maximum=statistics["maximum"],

            mean=statistics["mean"],

            median=statistics["median"],

            standard_deviation=statistics["std"],

        )

    # ==========================================================
    # ROI Configuration
    # ==========================================================

    def load_rois(
        self,
        rois,
    ) -> None:
        """
        Load ROI configuration into the ROI processor.
        """

        self._roi_processor.load(
            rois
        )

    def clear_rois(
        self,
    ) -> None:
        """
        Remove all configured ROIs.
        """

        self._roi_processor.clear()

    # ==========================================================
    # Alarm Configuration
    # ==========================================================

    def load_alarm_configuration(
        self,
        configuration,
    ) -> None:
        """
        Load alarm configuration.
        """

        self._alarm_processor.load(
            configuration
        )

    def reset_alarms(
        self,
    ) -> None:
        """
        Reset all active alarms.
        """

        self._alarm_processor.reset()

    # ==========================================================
    # Accessors
    # ==========================================================

    @property
    def calibration_manager(
        self,
    ) -> CalibrationManager:

        return self._calibration

    @property
    def roi_processor(
        self,
    ) -> ROIProcessor:

        return self._roi_processor

    @property
    def alarm_processor(
        self,
    ) -> AlarmProcessor:

        return self._alarm_processor
    
    