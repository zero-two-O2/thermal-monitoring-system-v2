"""
camera_discovery.py

Discovers Fluke TV46L cameras available on the GigE Vision network.
"""
from __future__ import annotations
import halcon as ha
from camera.camera_info import CameraInfo
from utilities.logger import logger


class CameraDiscovery:
    """
    Discovers all available TV46L cameras.
    """
    def __init__(self) -> None:
        self._cameras: list[CameraInfo] = []

    # ---------------------------------------------------------
    # Public
    # ---------------------------------------------------------

    def discover(self) -> list[CameraInfo]:
        """
        Scan the network and return all discovered cameras.
        """
        self._cameras.clear()
        try:
            devices = ha.info_framegrabber(
                "GigEVision2",
                "device"
            )
            if not devices:
                logger.warning("No GigE Vision cameras found.")
                return []
            for device in devices:
                try:
                    info = self._read_camera(device)
                    if info is not None:
                        self._cameras.append(info)
                except Exception as exc:
                    logger.exception(
                        f"Failed to read camera '{device}': {exc}"
                    )
        except Exception as exc:
            logger.exception(
                f"Camera discovery failed: {exc}"
            )
        logger.info(
            f"Discovered {len(self._cameras)} camera(s)."
        )
        return self._cameras.copy()
    # ---------------------------------------------------------

    @property
    def cameras(self) -> list[CameraInfo]:
        return self._cameras.copy()
    # ---------------------------------------------------------
    # Private
    # ---------------------------------------------------------

    def _read_camera(
        self,
        device: str
    ) -> CameraInfo | None:
        """
        Read information from a single camera.
        """
        acq = None
        try:
            acq = ha.open_framegrabber(
                "GigEVision2",
                0,
                0,
                0,
                0,
                0,
                0,
                "progressive",
                -1,
                "default",
                -1,
                "false",
                "default",
                device,
                0,
                -1,
            )
            serial = ha.get_framegrabber_param(
                acq,
                "[Device]DeviceSerialNumber"
            )
            model = ha.get_framegrabber_param(
                acq,
                "[Device]DeviceModelName"
            )
            vendor = ha.get_framegrabber_param(
                acq,
                "[Device]DeviceVendorName"
            )
            ip = ha.get_framegrabber_param(
                acq,
                "[Device]GevDeviceIPAddress"
            )
            firmware = ha.get_framegrabber_param(
                acq,
                "[Device]DeviceVersion"
            )
            user_name = ha.get_framegrabber_param(
                acq,
                "[Device]DeviceUserID"
            )
            return CameraInfo(
                device=device,
                serial=str(serial),
                model=str(model),
                vendor=str(vendor),
                ip=str(ip),
                firmware=str(firmware),
                user_name=str(user_name),
            )

        finally:

            if acq is not None:

                try:
                    ha.close_framegrabber(acq)
                except Exception:
                    pass