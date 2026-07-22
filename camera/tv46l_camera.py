"""
tv46l_camera.py

Fluke TV46L camera driver.

Responsibilities
----------------
- Open/close camera
- Configure GigE Vision stream
- Acquire thermal frames
- Manage acquisition thread
- Return RawFrame objects

This class DOES NOT perform:

- Calibration
- ROI processing
- Alarm processing
- Recording
"""

from __future__ import annotations
import sys
import threading
import time
from datetime import datetime
import halcon as ha
import numpy as np
from camera.camera_info import CameraInfo
from configuration.settings import Settings
from processing.models.processing_models import RawFrame
from utilities.logger import logger


def _scalar(value):
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


class TV46LCamera:
    """
    Driver for a single Fluke TV46L camera.
    """

    # ==========================================================
    # Constructor
    # ==========================================================
    def __init__(
        self,
        camera_info: CameraInfo,
        settings: Settings,
    ) ->None:
        self._info = camera_info
        self._settings = settings
        # HALCON
        self._acq = None
        # Threading
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        # Connection
        self._connected = False
        # Latest frame
        self._latest_frame: RawFrame | None = None
        # Statistics
        self._frame_counter = 0
        self._timeout_counter = 0
        self._last_frame_time = 0.0
        # FPS
        self._fps = 0
        self._fps_timer = time.time()
        self._fps_frame_counter = 0
        # Manual NUC
        self._nuc_requested = False
        # Diagnostics (timeout hypothesis verification)
        self._diag_calls = 0
        self._diag_success = 0
        self._diag_timeout = 0
        self._diag_other_errors = 0
        self._diag_grab_time = 0.0
        self._diag_grab_max = 0.0
        self._diag_conv_time = 0.0
        self._diag_conv_max = 0.0
        self._diag_total_time = 0.0
        self._diag_last_report = time.time()
        self._diag_int_calls = 0
        self._diag_int_success = 0
        self._diag_int_timeout = 0
        self._diag_int_other = 0
        self._diag_int_grab = 0.0
        self._diag_int_conv = 0.0
        self._diag_int_total = 0.0

    # ==========================================================
    # Properties
    # ==========================================================
    @property
    def connected(self) -> bool:
        return self._connected
    @property
    def running(self) -> bool:
        return self._running
    @property
    def serial(self) -> str:
        return self._info.serial
    @property
    def model(self) -> str:
        return self._info.model
    @property
    def vendor(self) -> str:
        return self._info.vendor
    @property
    def ip(self) -> str:
        return self._info.ip
    @property
    def frame_count(self) -> int:
        return self._frame_counter
    @property
    def timeout_count(self) -> int:
        return self._timeout_counter

    # ==========================================================
    # Connection
    # ==========================================================

    def connect(self) -> None:
        """
        Open the camera and configure acquisition.
        """
        if self._connected:
            return
        logger.info(
            f"Connecting to camera {self.serial}"
        )
        self._open_framegrabber()
        self._configure_stream()
        self._disable_automatic_nuc()
        self._start_acquisition()
        self._connected = True
        logger.info(
            f"{self.serial} connected successfully."
        )

    # ==========================================================
    # Disconnect
    # ==========================================================

    def disconnect(self) -> None:
        """
        Stop acquisition and close the camera.
        """
        self.stop()
        if self._acq is not None:
            try:
                ha.close_framegrabber(
                    self._acq
                )
            except Exception:
                logger.exception(
                    f"{self.serial}: Failed to close framegrabber."
                )
            finally:
                self._acq = None
        self._connected = False
        logger.info(
            f"{self.serial} disconnected."
        )

    # ==========================================================
    # Open Framegrabber
    # ==========================================================

    def _open_framegrabber(self) -> None:
        self._acq = ha.open_framegrabber(
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
            self._info.device,
            0,
            -1,
        )
    # ==========================================================
    # Configure Camera
    # ==========================================================

    def _configure_stream(self) -> None:
        """
        Configure TV46L stream.
        """
        #
        # Thermal stream
        #
        ha.set_framegrabber_param(
            self._acq,
            "FLK_TI_StreamDataSourceSelector",
            "IR_Data",
        )
        #
        # 16-bit thermal data
        #
        ha.set_framegrabber_param(
            self._acq,
            "bits_per_channel",
            16,
        )
        #
        # GigE Vision transport tuning (legacy from proven configuration)
        
        try:
            ha.set_framegrabber_param(
                self._acq,
                "[Stream]DeviceStreamChannelNegotiatePacketSize",
                1,
            )
        except Exception as exc:
            logger.warning(
                f"{self.serial}: Unable to negotiate packet size: {exc}"
            )
        try:
            ha.set_framegrabber_param(
                self._acq,
                "[Stream]GevStreamReceiveSocketSize",
                1048576,
            )
        except Exception as exc:
            logger.warning(
                f"{self.serial}: Unable to set socket buffer size: {exc}"
            )
        #
        # Increase internal buffering
        
        try:
            ha.set_framegrabber_param(
                self._acq,
                "num_buffers",
                32,
            )
        except Exception as exc:
            logger.warning(
                f"{self.serial}: Unable to set buffer count: {exc}"
            )

        #
        # Set frame rate to 9 FPS
        #
        try:
            ha.set_framegrabber_param(
                self._acq,
                "FLK_TI_ControlFeature_SetFrameRate",
                9,
            )
        except Exception:
            logger.warning(
                f"{self.serial}: Unable to set frame rate."
            )

    # ==========================================================
    # Disable Automatic NUC
    # ==========================================================

    def _disable_automatic_nuc(self) -> None:
        """
        Disable automatic fine-offset correction.
        """
        try:
            ha.set_framegrabber_param(
                self._acq,
                "FLK_TI_ControlFeature_REControlCmd",
                (
                    "FLK_TI_ControlFeature_"
                    "REControlCmd_DisableAutomaticFineOffsets"
                ),
            )
            logger.info(
                f"{self.serial}: Automatic NUC disabled."
            )
        except Exception:
            logger.warning(
                f"{self.serial}: Unable to disable automatic NUC."
            )
    # ==========================================================
    # Start Acquisition
    # ==========================================================

    def _start_acquisition(self) -> None:
        ha.grab_image_start(
            self._acq,
            -1,
        )
    # ==========================================================
    # Start Background Thread
    # ==========================================================

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._grab_loop,
            daemon=True,
            name=f"TV46L-{self.serial}",
        )
        self._thread.start()
        logger.info(
            f"{self.serial}: Acquisition thread started."
        )

        # ==========================================================
    # Acquisition Thread
    # ==========================================================

    def _grab_loop(self) -> None:
        """
        Background acquisition loop.
        """
        logger.info(
            f"{self.serial}: Acquisition loop started."
        )
        while self._running:
            now = time.time()
            if now - self._diag_last_report >= 1.0:
                ic = self._diag_int_calls
                isc = self._diag_int_success
                ito = self._diag_int_timeout
                ioe = self._diag_int_other
                ig = self._diag_int_grab
                icv = self._diag_int_conv
                itot = self._diag_int_total
                rate = (ito / ic * 100) if ic else 0.0
                print(
                    f"\n[DIAG] {self.serial}  "
                    f"Frames:{isc}  Calls:{ic}  "
                    f"Timeouts:{ito}  Other:{ioe}  "
                    f"Rate:{rate:.0f}%"
                )
                if ic:
                    print(
                        f"[DIAG]  "
                        f"Grab_avg:{ig/ic*1000:.1f}ms  "
                        f"Grab_max:{self._diag_grab_max*1000:.1f}ms  "
                        f"Conv_avg:{icv/ic*1000:.1f}ms  "
                        f"Conv_max:{self._diag_conv_max*1000:.1f}ms  "
                        f"Total_avg:{itot/ic*1000:.1f}ms"
                    )
                else:
                    print(f"[DIAG]  (no frames yet)")
                print(
                    f"[DIAG]  "
                    f"Loop_outer_timeout_cnt:{self._timeout_counter}  "
                    f"FPS:{self._fps}"
                )
                self._diag_int_calls = 0
                self._diag_int_success = 0
                self._diag_int_timeout = 0
                self._diag_int_other = 0
                self._diag_int_grab = 0.0
                self._diag_int_conv = 0.0
                self._diag_int_total = 0.0
                self._diag_last_report = now
            try:
                # Manual NUC
                if self._nuc_requested:
                    self._execute_manual_nuc()
                # Grab newest frame
                frame = self._grab_raw_frame()
                # Save newest frame
                frame.publish_time = time.perf_counter()
                
                with self._lock:
                    self._frame_counter += 1
                    frame.frame_number = self._frame_counter
                    frame.sequence = self._frame_counter
                    
                    self._latest_frame = frame
                # FPS
                self._update_fps()
            except Exception:
                self._timeout_counter += 1
                logger.exception(
                    f"{self.serial}: Frame grab failed "
                    f"(timeout count={self._timeout_counter})"
                )
                time.sleep(0.001)
        logger.info(
            f"{self.serial}: Acquisition loop stopped."
        )

    # ==========================================================
    # Grab Single Frame
    # ==========================================================

    def _grab_raw_frame(self) -> RawFrame:
        self._diag_calls += 1
        self._diag_int_calls += 1
        _t0 = time.perf_counter()
        try:
            image = ha.grab_image_async(
                self._acq,
                200,
            )
            _t1 = time.perf_counter()
            self._diag_success += 1
            self._diag_int_success += 1
            _gd = _t1 - _t0
            self._diag_grab_time += _gd
            self._diag_int_grab += _gd
            if _gd > self._diag_grab_max:
                self._diag_grab_max = _gd
        except Exception as _exc:
            _t1 = time.perf_counter()
            _gd = _t1 - _t0
            self._diag_grab_time += _gd
            self._diag_int_grab += _gd
            if _gd > self._diag_grab_max:
                self._diag_grab_max = _gd
            if isinstance(_exc, ha.HOperatorError):
                self._diag_timeout += 1
                self._diag_int_timeout += 1
            else:
                self._diag_other_errors += 1
                self._diag_int_other += 1
            logger.exception(
                f"{self.serial}: grab_image_async FAILED"
            )
            raise

        _t2 = time.perf_counter()
        try:
            frame = ha.himage_as_numpy_array(
                image
            )
        except Exception:
            logger.exception(
                f"{self.serial}: himage_as_numpy_array FAILED"
            )
            raise
        _t3 = time.perf_counter()
        _cd = _t3 - _t2
        self._diag_conv_time += _cd
        self._diag_int_conv += _cd
        if _cd > self._diag_conv_max:
            self._diag_conv_max = _cd

        _td = _t3 - _t0
        self._diag_total_time += _td
        self._diag_int_total += _td

        return RawFrame(
            image=frame.copy(),
            range_index=0,
            timestamp=datetime.now(),
            frame_number=self._frame_counter,
            acquisition_timestamp=time.perf_counter(),
            grab_start_time=_t0,
            grab_complete_time=_t1,
            numpy_complete_time=_t3,
        )


    # ==========================================================
    # Public Frame Grab
    # ==========================================================

    def grab_frame(
        self,
        timeout: float | None = None,
    ) -> RawFrame | None:
        """
        Return the newest available frame.
        If timeout is None:
            Returns immediately.
        Otherwise waits until a frame becomes available.
        """
        if timeout is None:
            with self._lock:
                latest = self._latest_frame
            if latest is None:
                return None
            return self._copy_frame(latest)
        start = time.time()
        while True:
            with self._lock:
                latest = self._latest_frame
            if latest is not None:
                return self._copy_frame(latest)
            if time.time() - start >= timeout:
                return None
            time.sleep(0.001)

    # ==========================================================
    # Latest Frame
    # ==========================================================

    def get_latest_frame(
        self,
    ) -> RawFrame | None:
        """
        Return the latest frame without waiting.
        """
        with self._lock:
            latest = self._latest_frame
        if latest is None:
            return None
        return self._copy_frame(latest)

    # ==========================================================
    # Latest Frame Reference (diagnostic, no copy)
    # ==========================================================

    def get_latest_frame_reference(self) -> RawFrame | None:
        """
        Returns the latest RawFrame without copying.
        Diagnostic use only.
        """
        with self._lock:
            return self._latest_frame

    # ==========================================================
    # Internal Copy
    # ==========================================================

    @staticmethod
    def _copy_frame(
        frame: RawFrame,
    ) -> RawFrame:
        return RawFrame(
            image=frame.image.copy(),
            range_index=frame.range_index,
            timestamp=frame.timestamp,
            frame_number=frame.frame_number,
            acquisition_timestamp=frame.acquisition_timestamp,
            grab_start_time=frame.grab_start_time,
            grab_complete_time=frame.grab_complete_time,
            numpy_complete_time=frame.numpy_complete_time,
            publish_time=frame.publish_time,
            sequence=frame.sequence,
        )

    # ==========================================================
    # Manual NUC Request
    # ==========================================================

    def manual_nuc(self) -> None:
        """
        Request a manual NUC.
        The actual execution happens inside the acquisition
        thread to avoid interrupting other threads.
        """
        self._nuc_requested = True

    # ==========================================================
    # Execute Manual NUC
    # ==========================================================

    def _execute_manual_nuc(self) -> None:
        logger.info(
            f"{self.serial}: Executing manual NUC."
        )
        try:
            ha.set_framegrabber_param(
                self._acq,
                "FLK_TI_ControlFeature_REControlCmd",
                (
                    "FLK_TI_ControlFeature_"
                    "REControlCmd_RequestFineOffset"
                ),
            )
            ha.set_framegrabber_param(
                self._acq,
                "FLK_TI_ControlFeature_REControlCmd",
                (
                    "FLK_TI_ControlFeature_"
                    "REControlCmd_ExecuteFineOffset"
                ),
            )
            # Give firmware time to finish.
            time.sleep(0.05)

            for _ in range(3):
                try:
                    ha.grab_image_async(
                        self._acq,
                        0,
                    )
                except Exception:
                    logger.warning(
                        f"{self.serial}: NUC flush grab failed (iteration {_})"
                    )
        finally:
            self._nuc_requested = False

    # ==========================================================
    # FPS Calculation
    # ==========================================================

    def _update_fps(self) -> None:
        now = time.time()
        if now - self._fps_timer >= 1.0:
            self._fps = (
                self._frame_counter
                - self._fps_frame_counter
            )
            self._fps_frame_counter = self._frame_counter
            self._fps_timer = now
        # ==========================================================
    # Stop Acquisition Thread
    # ==========================================================

    def stop(self) -> None:
        """
        Stop the background acquisition thread.
        """
        if not self._running:
            return
        logger.info(
            f"{self.serial}: Stopping acquisition thread."
        )
        self._running = False
        if self._thread is not None:
            self._thread.join(
                timeout=2.0
            )
            self._thread = None

    # ==========================================================
    # Camera Alive
    # ==========================================================

    def is_alive(self) -> bool:
        """
        Returns True if frames are still arriving.
        """
        if self._last_frame_time == 0:
            return False
        return (
            time.time() - self._last_frame_time
            < 2.0
        )

    # ==========================================================
    # FPS
    # ==========================================================

    def get_fps(self) -> int:
        """
        Current acquisition FPS.
        """
        return self._fps

    # ==========================================================
    # Stream Statistics
    # ==========================================================

    def get_stream_statistics(self) -> dict[str, int | bool]:
        statistics = {}
        parameters = [
            "[Stream]GevStreamSeenPacketCount",
            "[Stream]GevStreamLostPacketCount",
            "[Stream]GevStreamDeliveredPacketCount",
            "[Stream]GevStreamUnavailablePacketCount",
            "[Stream]GevStreamDuplicatePacketCount",
            "[Stream]GevStreamResendPacketCount",
        ]
        for parameter in parameters:
            try:
                statistics[parameter] = _scalar(
                    ha.get_framegrabber_param(
                        self._acq,
                        parameter,
                    )
                )
            except Exception:
                statistics[parameter] = -1
        statistics["frame_count"] = (
            self._frame_counter
        )
        statistics["timeout_count"] = (
            self._timeout_counter
        )
        statistics["fps"] = self._fps
        statistics["alive"] = self.is_alive()
        return statistics

    # ==========================================================
    # Acquisition Diagnostics
    # ==========================================================

    def acquisition_diagnostics(self) -> dict:
        grab_avg = self._diag_grab_time / self._diag_calls * 1000 if self._diag_calls else 0.0
        convert_avg = self._diag_conv_time / self._diag_calls * 1000 if self._diag_calls else 0.0
        total_avg = self._diag_total_time / self._diag_calls * 1000 if self._diag_calls else 0.0
        return {
            "frames": self._frame_counter,
            "fps": self._fps,
            "timeouts": self._timeout_counter,
            "alive": self.is_alive(),
            "grab_avg_ms": grab_avg,
            "grab_max_ms": self._diag_grab_max * 1000,
            "convert_avg_ms": convert_avg,
            "convert_max_ms": self._diag_conv_max * 1000,
            "total_avg_ms": total_avg,
        }

    # ==========================================================
    # Camera Information
    # ==========================================================

    def camera_information(self) -> dict:
        return {
            "serial": self.serial,
            "model": self.model,
            "vendor": self.vendor,
            "ip": self.ip,
            "firmware": self._info.firmware,
            "user_name": self._info.user_name,
            "connected": self.connected,
            "running": self.running,
            "alive": self.is_alive(),
            "fps": self._fps,
            "frame_count": self._frame_counter,
            "timeout_count": self._timeout_counter,
        }

    # ==========================================================
    # Reconnect
    # ==========================================================

    def reconnect(self) -> None:
        """
        Reconnect the camera.
        """
        logger.warning(
            f"{self.serial}: Reconnecting camera."
        )
        try:
            self.disconnect()
        except Exception:
            pass
        time.sleep(
            self._settings.RECONNECT_INTERVAL
        )
        self.connect()
        self.start()

    # ==========================================================
    # Stream Health
    # ==========================================================

    def stream_healthy(self) -> bool:
        """
        Returns True if the camera appears healthy.
        """
        if not self.connected:
            return False
        if not self.running:
            return False
        if not self.is_alive():
            return False
        return True

    # ==========================================================
    # Read Camera Parameter
    # ==========================================================

    def get_parameter(
        self,
        name: str,
    ):
        if not self.connected:
            raise RuntimeError(
                "Camera is not connected."
            )
        return _scalar(
            ha.get_framegrabber_param(
                self._acq,
                name,
            )
        )

    # ==========================================================
    # Write Camera Parameter
    # ==========================================================

    def set_parameter(
        self,
        name: str,
        value,
    ) -> None:
        if not self.connected:
            raise RuntimeError(
                "Camera is not connected."
            )
        ha.set_framegrabber_param(
            self._acq,
            name,
            value,
        )

    # ==========================================================
    # Focus Control
    # ==========================================================

    def get_focus_distance(self) -> float:
        return float(
            self.get_parameter(
                "FLK_TI_ControlFeature_CurrentFocusDistanceMm"
            )
        )

    def set_focus_distance(self, distance_mm: float) -> None:
        self.set_parameter(
            "FLK_TI_ControlFeature_SetFocusDistanceMm",
            distance_mm,
        )

    def wait_for_focus(
        self,
        target_mm: float,
        tolerance_mm: float = 10,
        timeout: float = 2.0,
    ) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            current = self.get_focus_distance()
            if abs(current - target_mm) <= tolerance_mm:
                return True
            time.sleep(0.02)
        return False

    def focus_busy(self) -> bool:
        a = self.get_focus_distance()
        time.sleep(0.05)
        b = self.get_focus_distance()
        return abs(b - a) > 1.0

    def get_focus_limits(self) -> tuple[float, float]:
        return (
            float(
                self.get_parameter(
                    "FLK_TI_ControlFeature_FocusDistanceMm_Min"
                )
            ),
            float(
                self.get_parameter(
                    "FLK_TI_ControlFeature_FocusDistanceMm_Max"
                )
            ),
        )

    # ==========================================================
    # Current Device Temperature
    # ==========================================================

    def device_temperature(self) -> float:
        return float(
            self.get_parameter(
                "FLK_TI_Info_CurrentDeviceTemperatureC"
            )
        )

    # ==========================================================
    # Critical Device Temperature
    # ==========================================================

    def critical_temperature(self) -> float:
        return float(
            self.get_parameter(
                "FLK_TI_Info_CriticalDeviceTemperatureC"
            )
        )

    # ==========================================================
    # Firmware Version
    # ==========================================================

    def firmware_version(self) -> str:
        return str(
            self.get_parameter(
                "[Device]DeviceVersion"
            )
        )

    # ==========================================================
    # Frame Rate
    # ==========================================================

    def frame_rate(self) -> int:
        try:
            return int(
                self.get_parameter(
                    "FLK_TI_ControlFeature_SetFrameRate"
                )
            )
        except Exception:
            return 0

    def frame_rate_capabilities(self) -> dict:
        candidates = {
            "current": "FLK_TI_ControlFeature_SetFrameRate",
            "minimum": "FLK_TI_ControlFeature_SetFrameRate_Min",
            "maximum": "FLK_TI_ControlFeature_SetFrameRate_Max",
            "increment": "FLK_TI_ControlFeature_SetFrameRate_Inc",
        }
        result = {}
        for key, param in candidates.items():
            try:
                val = _scalar(
                    ha.get_framegrabber_param(self._acq, param)
                )
                result[key] = val
            except Exception:
                result[key] = None
        try:
            result["writable"] = "read_only" not in str(
                _scalar(ha.get_framegrabber_param(
                    self._acq,
                    "FLK_TI_ControlFeature_SetFrameRate_Writeable",
                ))
            ).lower()
        except Exception:
            result["writable"] = None
        return result

    # ==========================================================
    # Camera Status
    # ==========================================================

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "running": self.running,
            "alive": self.is_alive(),
            "fps": self.get_fps(),
            "frames": self._frame_counter,
            "timeouts": self._timeout_counter,
            "device_temperature": (
                self.device_temperature()
            ),
            "critical_temperature": (
                self.critical_temperature()
            ),
        }
        # ==========================================================
    # Wait For First Frame
    # ==========================================================

    def wait_for_first_frame(
        self,
        timeout: float = 5.0,
    ) -> bool:
        """
        Wait until the first frame is received.
        """
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                if self._latest_frame is not None:
                    return True
            time.sleep(0.01)
        return False

    # ==========================================================
    # Clear Frame Buffer
    # ==========================================================

    def clear_latest_frame(self) -> None:
        """
        Remove the currently cached frame.
        """
        with self._lock:
            self._latest_frame = None

    # ==========================================================
    # Reset Statistics
    # ==========================================================

    def reset_statistics(self) -> None:
        self._frame_counter = 0
        self._timeout_counter = 0
        self._fps = 0
        self._fps_timer = time.time()
        self._fps_frame_counter = 0

    # ==========================================================
    # Flush Internal Buffers
    # ==========================================================

    def flush_buffers(
        self,
        count: int = 3,
    ) -> None:
        """
        Flush stale frames from the camera.
        """
        if not self.connected:
            return
        for i in range(count):
            try:
                ha.grab_image_async(
                    self._acq,
                    0,
                )
            except Exception:
                logger.warning(
                    f"{self.serial}: flush_buffers grab failed (iteration {i})"
                )
                break

    # ==========================================================
    # Restart Acquisition
    # ==========================================================

    def restart(self) -> None:
        """
        Restart streaming without reconnecting.
        """
        logger.info(
            f"{self.serial}: Restarting acquisition."
        )
        self.stop()
        try:
            ha.grab_image_start(
                self._acq,
                -1,
            )
        except Exception:
            logger.exception(
                f"{self.serial}: Failed to restart acquisition."
            )
            raise
        self.start()
    # ==========================================================
    # Context Manager
    # ==========================================================

    def __enter__(self):
        self.connect()
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ):
        self.disconnect()

    # ==========================================================
    # String Representation
    # ==========================================================

    def __str__(self) -> str:

        return (
            f"{self.model} "
            f"(SN={self.serial}, "
            f"IP={self.ip})"
        )

    # ==========================================================
    # Representation
    # ==========================================================

    def __repr__(self) -> str:

        return (
            f"TV46LCamera("
            f"serial='{self.serial}', "
            f"ip='{self.ip}', "
            f"connected={self.connected}, "
            f"running={self.running})"
        )

    # ==========================================================
    # Destructor
    # ==========================================================

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
