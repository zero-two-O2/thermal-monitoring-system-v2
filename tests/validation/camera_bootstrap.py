"""
camera_bootstrap.py

Real-camera rig for the validation harness.

Mirrors the camera discovery/bootstrap logic in app/application.py
(points 215-274): parses HALCON GigEVision2 board info, builds a
CameraModel per device (camera_id = cam_{serial}), constructs the full
camera context through CameraFactory, and registers it in a
CameraManager.

Usage
-----
    rig = CameraRig()
    rig.connect_all()
    source = rig.frame_source("cam_HB25100002")
    ...
    rig.shutdown()

If no cameras are reachable, `CameraRig.available()` is empty and
scenarios fall back to SimulatedFrameSource automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import halcon as ha

# Seed camera.models before camera.services: their import order is
# order-dependent (camera_context <-> tv46l_camera cycle) and the app
# relies on entering camera.models first.
import camera.models  # noqa: E402, F401
from camera.factory.camera_factory import CameraFactory
from camera.manager.camera_manager import CameraManager
from camera.models.camera_model import CameraModel
from camera.services.tv46l_camera import TV46LCamera
from calibration.calibration_manager import CalibrationManager
from utilities import logger


@dataclass(slots=True)
class CameraRig:
    """Owns the camera contexts needed by the scenarios."""

    camera_ids: list[str] = field(default_factory=list)
    manager: CameraManager = field(default_factory=CameraManager)
    contexts: dict[str, object] = field(default_factory=dict)
    models: dict[str, CameraModel] = field(default_factory=dict)
    factory: CameraFactory = field(default_factory=CameraFactory)

    @staticmethod
    def discover_models() -> list[CameraModel]:
        """Discover GigE Vision devices and build CameraModel objects.

        Mirrors app/application.py discovery. Returns an empty list when
        no devices are reachable.
        """
        models: list[CameraModel] = []
        try:
            _info, boards = ha.info_framegrabber(
                "GigEVision2", "info_boards"
            )
        except Exception:
            logger.exception("GigEVision2 board discovery failed")
            return models

        for board in boards:
            fields: dict[str, str] = {}
            for item in str(board).split("|"):
                item = item.strip()
                if ":" not in item:
                    continue
                key, value = item.split(":", 1)
                fields[key.strip()] = value.strip()

            device = fields.get("device", "")
            if not device:
                continue

            serial = fields.get("device_sn", "")
            camera_id = f"cam_{serial}" if serial else f"cam_{device}"
            models.append(
                CameraModel(
                    camera_id=camera_id,
                    camera_name=(
                        f"Camera {serial}" if serial else f"Camera {device}"
                    ),
                    vendor=fields.get("vendor", ""),
                    model=fields.get("model", ""),
                    serial_number=serial,
                    ip_address=fields.get("device_ip", ""),
                    device_identifier=device,
                )
            )
        return models

    @classmethod
    def build(
        cls,
        camera_ids: list[str] | None = None,
        factory: CameraFactory | None = None,
    ) -> "CameraRig":
        """Build a rig for the given camera_ids (default: all discovered).

        Camera creation is deferred until connect_all(); this keeps
        synthetic-only runs cheap.
        """
        factory = factory or CameraFactory()
        models = cls.discover_models()
        if camera_ids is not None:
            models = [m for m in models if m.camera_id in camera_ids]

        rig = cls(camera_ids=[m.camera_id for m in models], factory=factory)
        rig.models = {m.camera_id: m for m in models}
        return rig

    @property
    def available(self) -> bool:
        """True when at least one camera was discovered."""
        return bool(self.camera_ids)

    def connect_all(self) -> int:
        """Create, register, and connect every camera; returns count.

        The connection step performs the actual HALCON device open and
        starts the acquisition thread.
        """
        connected = 0
        for camera_id, model in self.models.items():
            try:
                context = self.factory.create_camera(model)
                self.contexts[camera_id] = context
                self.manager.add_camera(context)
                context.camera.connect()
                context.camera.start()
                connected += 1
                logger.info(f"validation rig connected {camera_id}")
            except Exception:
                logger.exception(f"failed to connect rig camera {camera_id}")
        return connected

    def frame_source(self, camera_id: str, calibration: CalibrationManager | None = None):
        """Return a CameraFrameSource for `camera_id`.

        Parameters
        ----------
        camera_id : str
            Rig camera key (cam_{serial}).
        calibration : CalibrationManager | None
            Calibration to use for raw -> temperature conversion. When
            None the camera context's calibration manager is used.
        """
        context = self.contexts[camera_id]
        calibration = calibration or context.calibration_manager
        return CameraFrameSource(context.camera, calibration)

    def camera(self, camera_id: str) -> TV46LCamera:
        """The TV46LCamera service for `camera_id`."""
        return self.contexts[camera_id].camera

    def calibration(self, camera_id: str) -> CalibrationManager:
        """The CalibrationManager for `camera_id`."""
        return self.contexts[camera_id].calibration_manager

    def disconnect_all(self) -> None:
        """Stop acquisition and disconnect every connected camera."""
        for camera_id, context in self.contexts.items():
            try:
                context.camera.stop()
                context.camera.disconnect()
                logger.info(f"validation rig disconnected {camera_id}")
            except Exception:
                logger.exception(f"failed to disconnect rig camera {camera_id}")

    def shutdown(self) -> None:
        """Disconnect cameras and clear manager state."""
        self.disconnect_all()
        for camera_id in list(self.contexts):
            del self.contexts[camera_id]
        for camera_id in list(self.manager.get_all_cameras()):
            self.manager.remove_camera(camera_id)
        logger.info("validation rig shut down")
