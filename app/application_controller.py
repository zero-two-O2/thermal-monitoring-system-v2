"""
application_controller.py

Main application controller.

Coordinates all backend components.
The GUI should only communicate with this class.
"""

from __future__ import annotations

from typing import Optional

from camera.manager.camera_manager import CameraManager
from camera.models.camera_context import CameraContext


class ApplicationController:
    """
    Main application controller.

    Owns the application's runtime objects and coordinates
    communication between the GUI and backend.
    """

    def __init__(self) -> None:

        self._camera_manager = CameraManager()

        self._initialized = False
        self._running = False

        self._selected_camera_id: str | None = None

    # ======================================================
    # Properties
    # ======================================================

    @property
    def initialized(self) -> bool:
        """True if the application has been initialized."""
        return self._initialized

    @property
    def running(self) -> bool:
        """True if acquisition has been started."""
        return self._running

    @property
    def camera_manager(self) -> CameraManager:
        """Return the camera manager."""
        return self._camera_manager

    @property
    def camera_count(self) -> int:
        """Number of registered cameras."""
        return self._camera_manager.camera_count

    # ======================================================
    # Lifecycle
    # ======================================================

    def initialize(self) -> None:
        """
        Initialize the application.

        This should be called once during application startup.
        """

        if self._initialized:
            return

        self._initialized = True

        print("[Application] Initialized.")

    def shutdown(self) -> None:
        """
        Shutdown the application safely.
        """

        if not self._initialized:
            return

        self.stop_all()
        self.disconnect_all()

        self._initialized = False

        print("[Application] Shutdown complete.")

    # ======================================================
    # Camera Access
    # ======================================================

    def get_camera(self, camera_id: str) -> Optional[CameraContext]:
        """
        Return a camera context.
        """

        return self._camera_manager.get_camera(camera_id)

    def get_all_cameras(self) -> list[CameraContext]:
        """
        Return all registered cameras.
        """

        return self._camera_manager.get_all_cameras()

    # ======================================================
    # Selected Camera
    # ======================================================

    @property
    def selected_camera_id(self) -> str | None:
        """
        Return the currently selected camera ID.
        """

        return self._selected_camera_id

    @property
    def selected_camera(self) -> CameraContext | None:
        """
        Return the currently selected camera context.
        """

        if self._selected_camera_id is None:
            return None

        return self.get_camera(
            self._selected_camera_id
        )

    def select_camera(
        self,
        camera_id: str | None,
    ) -> None:
        """
        Select a camera by ID.

        Pass None to clear selection.
        """

        if camera_id is not None:

            context = self.get_camera(camera_id)

            if context is None:

                raise ValueError(
                    f"Camera '{camera_id}' not found."
                )

        self._selected_camera_id = camera_id

    # ======================================================
    # Bulk Operations
    # ======================================================

    def connect_all(self) -> None:
        """
        Connect every enabled camera.
        """

        self._camera_manager.connect_all()

    def disconnect_all(self) -> None:
        """
        Disconnect every camera.
        """

        self._camera_manager.disconnect_all()

    def start_all(self) -> None:
        """
        Start acquisition on every connected camera.
        """

        self._camera_manager.start_all()

        self._running = True

    def stop_all(self) -> None:
        """
        Stop acquisition on every camera.
        """

        self._camera_manager.stop_all()

        self._running = False

    # ======================================================
    # Status
    # ======================================================

    def summary(self) -> dict:
        """
        Return a runtime summary.
        """

        return {

            "initialized": self._initialized,

            "running": self._running,

            "camera_count": self.camera_count,

            "connected_cameras": len(
                self._camera_manager.connected_cameras()
            ),

            "running_cameras": len(
                self._camera_manager.running_cameras()
            ),
        }

    def __repr__(self) -> str:

        return (
            f"{self.__class__.__name__}("
            f"initialized={self._initialized}, "
            f"running={self._running}, "
            f"cameras={self.camera_count})"
        )
    
        # ======================================================
    # Camera Management
    # ======================================================

    def add_camera(self, context: CameraContext) -> None:
        """
        Add a camera to the application.
        """

        self._camera_manager.add_camera(context)

    def remove_camera(self, camera_id: str) -> None:
        """
        Remove a camera.
        """

        self._camera_manager.remove_camera(camera_id)

    # ======================================================
    # Individual Camera Operations
    # ======================================================

    def connect_camera(self, camera_id: str) -> None:
        """
        Connect a single camera.
        """

        self._camera_manager.connect_camera(camera_id)

    def disconnect_camera(self, camera_id: str) -> None:
        """
        Disconnect a single camera.
        """

        self._camera_manager.disconnect_camera(camera_id)

    def start_camera(self, camera_id: str) -> None:
        """
        Start acquisition for one camera.
        """

        self._camera_manager.start_camera(camera_id)

    def stop_camera(self, camera_id: str) -> None:
        """
        Stop acquisition for one camera.
        """

        self._camera_manager.stop_camera(camera_id)

    # ======================================================
    # Camera Utilities
    # ======================================================

    def perform_nuc(self, camera_id: str) -> None:
        """
        Perform Non-Uniformity Correction.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        context.camera.perform_nuc()

    def perform_nuc_selected(self) -> None:
        """
        Perform NUC on the currently selected camera.
        """

        if self.selected_camera is None:
            raise RuntimeError("No camera selected.")

        self.selected_camera.camera.perform_nuc()

    # ======================================================
    # Focus Control
    # ======================================================

    def focus_near(
        self,
        camera_id: str,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus closer on a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.camera.focus_near(step_mm)

    def focus_far(
        self,
        camera_id: str,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus farther on a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.camera.focus_far(step_mm)

    def focus_near_selected(
        self,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus closer on the selected camera.
        """

        if self.selected_camera is None:
            raise RuntimeError("No camera selected.")

        return self.selected_camera.camera.focus_near(step_mm)

    def focus_far_selected(
        self,
        step_mm: int | None = None,
    ) -> tuple[float, float]:
        """
        Move focus farther on the selected camera.
        """

        if self.selected_camera is None:
            raise RuntimeError("No camera selected.")

        return self.selected_camera.camera.focus_far(step_mm)

    def get_focus_distance(
        self,
        camera_id: str,
    ) -> float:
        """
        Read current focus distance.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.camera.get_focus_distance()

    def get_focus_distance_selected(self) -> float:
        """
        Read focus distance on the selected camera.
        """

        if self.selected_camera is None:
            raise RuntimeError("No camera selected.")

        return self.selected_camera.camera.get_focus_distance()

    def get_focus_limits(
        self,
        camera_id: str,
    ) -> tuple[float, float]:
        """
        Return focus limits for a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.camera.get_focus_limits()

    def enable_camera(
        self,
        camera_id: str,
        enabled: bool = True,
    ) -> None:
        """
        Enable or disable a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        context.enabled = enabled

    def disable_camera(self, camera_id: str) -> None:
        """
        Disable a camera.
        """

        self.enable_camera(camera_id, False)

    # ======================================================
    # Camera Queries
    # ======================================================

    def connected_cameras(self) -> list[CameraContext]:
        """
        Return connected cameras.
        """

        return self._camera_manager.connected_cameras()

    def running_cameras(self) -> list[CameraContext]:
        """
        Return running cameras.
        """

        return self._camera_manager.running_cameras()

    def enabled_cameras(self) -> list[CameraContext]:
        """
        Return enabled cameras.
        """

        return self._camera_manager.enabled_cameras()
    
        # ======================================================
    # Position Management
    # ======================================================

    def select_position(
        self,
        camera_id: str,
        position_id: str,
    ) -> None:
        """
        Select the active position for a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        context.selected_position_id = position_id

    def current_position(
        self,
        camera_id: str,
    ):
        """
        Return the currently selected position.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.current_position

    def next_position(self, camera_id: str):
        """
        Move to next position.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.position_manager.next_position()

    def previous_position(self, camera_id: str):
        """
        Move to previous position.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.position_manager.previous_position()

    # ======================================================
    # Frame Processing
    # ======================================================

    def get_latest_frame(
        self,
        camera_id: str,
    ):
        """
        Return the newest frame from a camera.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")

        return context.camera.get_frame()

    def process_frame(
        self,
        camera_id: str,
    ):
        """
        Acquire and process one frame.
        """

        context = self.get_camera(camera_id)

        if context is None:
            raise ValueError(f"Camera '{camera_id}' not found.")


        frame = context.get_latest_frame()

        if frame is None:
            return None

        #return context.processing_pipeline.process(
        return context.process_latest_frame(
            frame,
            context.current_position,
        )

    # ======================================================
    # Application Status
    # ======================================================

    def status(self) -> dict:
        """
        Return application status.
        """

        return {

            "initialized": self._initialized,

            "running": self._running,

            "camera_count": self.camera_count,

            "connected_cameras":
                len(self.connected_cameras()),

            "running_cameras":
                len(self.running_cameras()),

            "enabled_cameras":
                len(self.enabled_cameras()),
        }