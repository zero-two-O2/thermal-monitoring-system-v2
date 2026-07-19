"""
camera_context.py

Runtime container for one physical camera.

A CameraContext groups together all services required to
operate a single camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from camera.manager.position_manager import PositionManager
from camera.models.camera_model import CameraModel
from camera.services.tv46l_camera import TV46LCamera

from processing.processing_pipeline import ProcessingPipeline


@dataclass(slots=True)
class CameraContext:
    """
    Runtime context for one camera.

    This object is created during application startup and
    managed by CameraManager.
    """

    #
    # Configuration
    #

    camera_model: CameraModel

    #
    # Runtime Services
    #

    camera: TV46LCamera

    position_manager: PositionManager

    processing_pipeline: ProcessingPipeline

    #
    # Runtime Information
    #

    selected_position_id: str | None = None

    enabled: bool = True

    #
    # User Data
    #

    metadata: dict = field(
        default_factory=dict
    )

    # ======================================================
    # Convenience Properties
    # ======================================================

    @property
    def camera_id(self) -> str:

        return self.camera_model.camera_id

    @property
    def current_position(self):

        return self.position_manager.get_current_position()

    @property
    def is_connected(self) -> bool:

        return self.camera.is_connected()

    @property
    def is_running(self) -> bool:

        return self.camera.is_running()

    @property
    def position_count(self) -> int:

        return self.position_manager.position_count

    # ======================================================
    # Helpers
    # ======================================================

    def start(self) -> None:

        self.camera.start()

    def stop(self) -> None:

        self.camera.stop()

    def connect(self) -> None:

        self.camera.connect()

    def disconnect(self) -> None:

        self.camera.disconnect()