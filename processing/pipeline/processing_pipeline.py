"""
processing_pipeline.py

Main processing pipeline.

Pipeline

Raw Frame
    │
    ▼
Calibration
    │
    ▼
Temperature Image
    │
    ▼
Processed Frame
    │
    ▼
ROI Processing
    │
    ▼
Alarm Processing
    │
    ▼
FrameResult
"""

from __future__ import annotations

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

    def __init__(
        self,
        calibration_manager: CalibrationManager,
        roi_processor: ROIProcessor,
        alarm_processor: AlarmProcessor,
    ):

        self._calibration = calibration_manager
        self._roi_processor = roi_processor
        self._alarm_processor = alarm_processor

    # ==========================================================
    # Public
    # ==========================================================

    def process(
        self,
        camera_id: str,
        position_id: str,
        raw_frame: RawFrame,
    ) -> FrameResult:
        """
        Process one thermal frame.
        """

        logger.debug("Processing frame...")

        calibration = self._calibration.get_calibration()

        #
        # Temperature image
        #

        temperature_image = (
            CalibrationProcessor.raw_to_temperature(
                raw_frame.image,
                calibration,
                raw_frame.range_index,
            )
        )

        #
        # Display image
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
        # Processed frame
        #

        processed_frame = ProcessedFrame(

            raw_frame=raw_frame,

            temperature_image=temperature_image,

            display_image=display_image,

        )

        #
        # ROI Processing
        #

        roi_results = self._roi_processor.process(
            processed_frame
        )

        #
        # Alarm Processing
        #

        alarms = self._alarm_processor.process(

            camera_id=camera_id,

            position_id=position_id,

            roi_results=roi_results,

        )

        #
        # Final result
        #

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

    @staticmethod
    def _build_statistics(
        temperature_image,
    ) -> CameraStatistics:
        """
        Calculate statistics for the complete frame.
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

        self._roi_processor.load(
            rois
        )

    def clear_rois(
        self,
    ) -> None:

        self._roi_processor.clear()

    # ==========================================================
    # Alarm
    # ==========================================================

    def clear_alarms(
        self,
    ) -> None:

        self._alarm_processor.clear()

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