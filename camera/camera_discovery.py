"""
camera_discovery.py

Discovers Fluke TV46L cameras available on the GigE Vision network.
"""
from __future__ import annotations
import time
import halcon as ha
from camera.camera_info import CameraInfo
from camera.tv46l_camera import _scalar
from utilities.logger import logger


def _parse_halcon_devices(devices):
    if not isinstance(devices, tuple) or len(devices) < 2:
        return []
    device_list = devices[1]
    if not isinstance(device_list, (list, tuple)):
        return []
    result = []
    PREFIX = "device:"
    for entry in device_list:
        if not isinstance(entry, str):
            continue
        idx = entry.find(PREFIX)
        if idx == -1:
            continue
        start = idx + len(PREFIX)
        end = entry.find(" |", start)
        if end == -1:
            end = len(entry)
        device_str = entry[start:end].strip()
        if device_str:
            result.append(device_str)
    return result


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
        Retries if only the HALCON info string is returned
        (common after a recent disconnect).
        """
        self._cameras.clear()
        try:
            for attempt in range(3):
                try:
                    devices = ha.info_framegrabber(
                        "GigEVision2",
                        "device",
                    )
                except Exception as exc:
                    logger.error(
                        f"info_framegrabber failed (attempt {attempt+1}): {exc}"
                    )
                    devices = ()

                parsed = _parse_halcon_devices(devices)
                if parsed:
                    break
                if attempt < 2:
                    logger.info(
                        f"Re-scanning GigE network (attempt {attempt+1}/3)..."
                    )
                    time.sleep(3)
            else:
                logger.warning("No GigE Vision cameras found.")
                return []

            for device in parsed:
                try:
                    info = self._read_camera(device)
                    if info is not None:
                        self._cameras.append(info)
                except Exception as exc:
                    logger.error(
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
            serial = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]DeviceSerialNumber"
            ))
            model = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]DeviceModelName"
            ))
            vendor = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]DeviceVendorName"
            ))
            ip = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]GevDeviceIPAddress"
            ))
            firmware = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]DeviceVersion"
            ))
            user_name = _scalar(ha.get_framegrabber_param(
                acq,
                "[Device]DeviceUserID"
            ))
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