"""
camera_factory.py

Factory responsible for creating fully initialized
CameraContext instances.
"""

from __future__ import annotations

from camera.models.camera_context import CameraContext
from camera.models.camera_model import CameraModel

from camera.manager.position_manager import PositionManager

from camera.services.tv46l_camera import TV46LCamera

from calibration.calibration_manager import CalibrationManager

from processing.processing_pipeline import ProcessingPipeline
from processing.roi_processor import ROIProcessor
from processing.alarm_processor import AlarmProcessor


class CameraFactory:
    """
    Factory responsible for constructing camera runtime objects.
    """

    def __init__(self) -> None:

        pass

    # ==========================================================
    # Public API
    # ==========================================================

    def create_camera(
        self,
        camera_model: CameraModel,
    ) -> CameraContext:
        """
        Create a fully initialized camera context.
        """

        #
        # Calibration
        #

        calibration_manager = CalibrationManager()

        #
        # Camera
        #

        camera = TV46LCamera(
            camera_model=camera_model,
            calibration_manager=calibration_manager,
        )

        #
        # Processing
        #

        roi_processor = ROIProcessor()

        alarm_processor = AlarmProcessor()

        processing_pipeline = ProcessingPipeline(
            calibration_manager=calibration_manager,
            roi_processor=roi_processor,
            alarm_processor=alarm_processor,
        )

        #
        # Position Manager
        #

        position_manager = PositionManager()

        #
        # Runtime Context
        #

        context = CameraContext(

            camera_model=camera_model,

            camera=camera,

            position_manager=position_manager,

            processing_pipeline=processing_pipeline,

        )

        

        return context