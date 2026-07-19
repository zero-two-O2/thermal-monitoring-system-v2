"""
camera_manager.py

High-level manager for all cameras.

The manager owns CameraContext objects and provides
a single interface for the rest of the application.
"""

from __future__ import annotations

from typing import Dict

from camera.models.camera_context import CameraContext
from collections.abc import Callable
from utilities import logger


class CameraManager:
    """
    Multi-camera manager.
    """

    MAX_CAMERAS = 8

    def __init__(self) -> None:

        self._cameras: Dict[
            str,
            CameraContext,
        ] = {}

    # ==========================================================
    # CRUD
    # ==========================================================

    def add_camera(
        self,
        context: CameraContext,
    ) -> None:

        if len(self._cameras) >= self.MAX_CAMERAS:

            raise RuntimeError(
                "Maximum number of cameras reached."
            )

        camera_id = context.camera.camera.camera_id

        if camera_id in self._cameras:

            raise ValueError(
                f"Camera '{camera_id}' already exists."
            )

        self._cameras[camera_id] = context

        logger.info(
            f"Camera '{camera_id}' added."
        )

    def remove_camera(
        self,
        camera_id: str,
    ) -> None:

        context = self._cameras.pop(
            camera_id,
            None,
        )

        if context is None:

            return

        context.camera.disconnect()

        logger.info(
            f"Camera '{camera_id}' removed."
        )

    def get_camera(
        self,
        camera_id: str,
    ) -> CameraContext | None:

        return self._cameras.get(
            camera_id
        )

    def get_all_cameras(
        self,
    ) -> list[CameraContext]:

        return list(
            self._cameras.values()
        )

    @property
    def camera_count(
        self,
    ) -> int:

        return len(
            self._cameras
        )
    
    # ==========================================================
    # Camera Control
    # ==========================================================

    def connect_camera(
        self,
        camera_id: str,
    ) -> None:

        self._get_context(
            camera_id
        ).connect()

    def disconnect_camera(
        self,
        camera_id: str,
    ) -> None:

        self._get_context(
            camera_id
        ).disconnect()

    def start_camera(
        self,
        camera_id: str,
    ) -> None:

        self._get_context(
            camera_id
        ).start()

    def stop_camera(
        self,
        camera_id: str,
    ) -> None:

        self._get_context(
            camera_id
        ).stop()

    # ==========================================================
    # Bulk Operations
    # ==========================================================

    def for_each_camera(
        self,
        callback: Callable[[CameraContext], None],
    ) -> None:
        """
        Execute an operation on every camera.
        """

        for context in self._cameras.values():

            try:

                callback(context)

            except Exception:

                logger.exception(
                    f"Operation failed for camera "
                    f"'{context.camera_id}'."
                )

    def connect_all(
        self,
    ) -> None:

        self.for_each_camera(
            lambda context: context.connect()
        )

    def disconnect_all(
        self,
    ) -> None:

        self.for_each_camera(
            lambda context: context.disconnect()
        )

    def start_all(
        self,
    ) -> None:

        self.for_each_camera(
            lambda context: context.start()
        )

    def stop_all(
        self,
    ) -> None:

        self.for_each_camera(
            lambda context: context.stop()
        )

    # ==========================================================
    # Camera Queries
    # ==========================================================

    def connected_cameras(
        self,
    ) -> list[CameraContext]:

        return [

            context

            for context in self._cameras.values()

            if context.is_connected

        ]

    def running_cameras(
        self,
    ) -> list[CameraContext]:

        return [

            context

            for context in self._cameras.values()

            if context.is_running

        ]

    def enabled_cameras(
        self,
    ) -> list[CameraContext]:

        return [

            context

            for context in self._cameras.values()

            if context.enabled

        ]

    # ==========================================================
    # Internal Helpers
    # ==========================================================

    def _get_context(
        self,
        camera_id: str,
    ) -> CameraContext:

        context = self._cameras.get(
            camera_id
        )

        if context is None:

            raise KeyError(
                f"Camera '{camera_id}' not found."
            )

        return context