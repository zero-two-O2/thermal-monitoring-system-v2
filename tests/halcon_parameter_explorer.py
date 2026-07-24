"""
halcon_parameter_explorer.py

Standalone engineering tool for exploring every HALCON framegrabber
parameter on Fluke TV46L / GigE Vision cameras.

Safe for experimentation — does NOT touch any production code,
production GUI, or camera acquisition pipeline.

Usage:
    python -m tests.halcon_parameter_explorer

============================================================================
QUICK TEST — set this to a single parameter name to auto-test on startup
============================================================================
"""

from __future__ import annotations

TEST_PARAMETER: str = ""
#   Examples:
#   TEST_PARAMETER = "FLK_TI_Info_CurrentDeviceTemperatureC"
#   TEST_PARAMETER = "FLK_TI_ControlFeature_SetFocusDistanceMm"
#   TEST_PARAMETER = "FLK_TI_ControlFeature_REControlCmd"
#   Leave as "" for normal interactive mode.

# ==========================================================================
# Imports
# ==========================================================================

import csv
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import halcon as ha
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont, QColor, QBrush, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ==========================================================================
# Constants
# ==========================================================================

APP_NAME = "HALCON Parameter Explorer"
APP_VERSION = "1.0.0"
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}  —  Fluke TV46L"
GEV_NAME = "GigEVision2"

# Default open-framegrabber args (matching TV46LCamera convention)
# This HALCON version (24.11+) expects 16 parameters for GigEVision2
FG_ARGS: list[Any] = [
    "GigEVision2",
    0, 0, 0, 0, 0, 0,
    "progressive",
    -1,
    "default",
    -1,
    "false",
    "default",
    "default",
    0,
    -1,
]

HISTORY_MAX = 500
LOG_MAX = 2000

ACCESS_READ_ONLY = "Read Only"
ACCESS_READ_WRITE = "Read / Write"
ACCESS_WRITE_ONLY = "Write Only"
ACCESS_UNSUPPORTED = "Unsupported"

# ==========================================================================
# Quick-test setting (also settable via constant above)
# ==========================================================================

_quick_test_param: str = TEST_PARAMETER

# ==========================================================================
# Known Parameters Registry
# ==========================================================================
# Hand-curated list of TV46L / HALCON parameters with expected access.
# Used as fallback / supplement when auto-discovery cannot determine access.
# Extend this list as new parameters are discovered.
# Format: (name, access, halcon_type_hint, description)

KNOWN_PARAMETERS: list[tuple[str, str, str, str]] = [
    # --- Device info (Read Only) ---
    ("DeviceManufacturerInfo", ACCESS_READ_ONLY, "string", "Device manufacturer info string"),
    ("DeviceModelName", ACCESS_READ_ONLY, "string", "Camera model name"),
    ("DeviceSFNCVersionMajor", ACCESS_READ_ONLY, "int", "SFNC major version"),
    ("DeviceSFNCVersionMinor", ACCESS_READ_ONLY, "int", "SFNC minor version"),
    ("DeviceSFNCVersionSubMinor", ACCESS_READ_ONLY, "int", "SFNC sub-minor version"),
    ("DeviceStreamChannelCount", ACCESS_READ_ONLY, "int", "Number of stream channels"),
    ("DeviceType", ACCESS_READ_ONLY, "string", "Device type (e.g. Transmitter)"),
    ("DeviceVendorName", ACCESS_READ_ONLY, "string", "Vendor name"),

    # --- Fluke TI Info (Read Only) ---
    ("FLK_TI_CalibrationInfo", ACCESS_READ_ONLY, "string", "Raw calibration info blob"),
    ("FLK_TI_ControlFeature_CurrentFocusDistanceMm", ACCESS_READ_ONLY, "float", "Current focus distance (mm)"),
    ("FLK_TI_ControlFeature_FocusDistanceMm_Max", ACCESS_READ_ONLY, "float", "Max focus distance (mm)"),
    ("FLK_TI_ControlFeature_FocusDistanceMm_Min", ACCESS_READ_ONLY, "float", "Min focus distance (mm)"),
    ("FLK_TI_InfoString", ACCESS_READ_ONLY, "string", "Info string (firmware version)"),
    ("FLK_TI_Info_CalibrationRangeInfoQuery", ACCESS_READ_ONLY, "string", "Cal range query selector"),
    ("FLK_TI_Info_CalibrationRangeInfo_RangeSpan_LowerBoundary", ACCESS_READ_ONLY, "float", "Cal range lower boundary (°C)"),
    ("FLK_TI_Info_CalibrationRangeInfo_RangeSpan_UpperBoundary", ACCESS_READ_ONLY, "float", "Cal range upper boundary (°C)"),
    ("FLK_TI_Info_CriticalDeviceTemperatureC", ACCESS_READ_ONLY, "float", "Critical device temperature (°C)"),
    ("FLK_TI_Info_CurrentDeviceTemperatureC", ACCESS_READ_ONLY, "float", "Current device temperature (°C)"),
    ("FLK_TI_Info_PlatformId", ACCESS_READ_ONLY, "int", "Platform ID"),
    ("FLK_TI_Info_REDataProviderAvailable", ACCESS_READ_ONLY, "int", "RE data provider available"),
    ("FLK_TI_Info_REDataRate", ACCESS_READ_ONLY, "int", "RE data rate"),
    ("FLK_TI_Info_REDataSize", ACCESS_READ_ONLY, "int", "RE data size"),
    ("FLK_TI_Info_RE_Capabilities0", ACCESS_READ_ONLY, "int", "RE capabilities bitfield"),
    ("FLK_TI_Info_RE_Platform_Id", ACCESS_READ_ONLY, "int", "RE platform ID"),
    ("FLK_TI_Info_RE_TPM_Validity_Code", ACCESS_READ_ONLY, "int", "RE TPM validity code"),
    ("FLK_TI_Info_SecuredDataStreamingOnly", ACCESS_READ_ONLY, "int", "Secured streaming only flag"),
    ("FLK_TI_Info_VLDataProviderAvailable", ACCESS_READ_ONLY, "int", "VL data provider available"),
    ("FLK_TI_Info_VLDataSize", ACCESS_READ_ONLY, "int", "VL data size"),

    # --- Fluke TI Control (Read/Write) ---
    ("FLK_TI_ControlFeature_SetFocusDistanceMm", ACCESS_READ_WRITE, "float", "Set focus distance (mm)"),
    ("FLK_TI_ControlFeature_SetFrameRate", ACCESS_READ_WRITE, "int", "Set frame rate (Hz)"),
    ("FLK_TI_ControlFeature_REControlCmd", ACCESS_READ_WRITE, "string", "RE control command (NUC / offset)"),
    ("FLK_TI_StreamDataSourceSelector", ACCESS_READ_WRITE, "string", "Select stream source (IR_Data / VL_Data)"),

    # --- GigE Vision (Read Only) ---
    ("GevCurrentPhysicalLinkConfiguration", ACCESS_READ_ONLY, "string", "Current link configuration"),
    ("GevPrimaryApplicationIPAddress", ACCESS_READ_ONLY, "int", "Primary app IP address"),
    ("GevPrimaryApplicationSocket", ACCESS_READ_ONLY, "int", "Primary app socket"),
    ("GevSupportedOption", ACCESS_READ_ONLY, "int", "Supported options bitfield"),
    ("GevSupportedOptionSelector", ACCESS_READ_ONLY, "string", "Supported option selector"),

    # --- Image geometry (Read Only) ---
    ("Height", ACCESS_READ_ONLY, "int", "Image height (pixels)"),
    ("HeightMax", ACCESS_READ_ONLY, "int", "Max image height"),
    ("HeightMin", ACCESS_READ_ONLY, "int", "Min image height"),
    ("SensorHeight", ACCESS_READ_ONLY, "int", "Sensor height"),
    ("SensorWidth", ACCESS_READ_ONLY, "int", "Sensor width"),
    ("Width", ACCESS_READ_ONLY, "int", "Image width (pixels)"),
    ("WidthMax", ACCESS_READ_ONLY, "int", "Max image width"),
    ("WidthMin", ACCESS_READ_ONLY, "int", "Min image width"),
    ("PayloadSize", ACCESS_READ_ONLY, "int", "Payload size (bytes)"),
    ("PixelFormat", ACCESS_READ_ONLY, "string", "Pixel format"),
    ("TransmitAs", ACCESS_READ_ONLY, "string", "Transmission format"),
    ("ImageCompressionMode", ACCESS_READ_ONLY, "string", "Image compression mode"),
    ("AcquisitionMode", ACCESS_READ_ONLY, "string", "Acquisition mode"),

    # --- HALCON internal (usually Read Only) ---
    ("bits_per_channel", ACCESS_READ_WRITE, "int", "Bits per channel"),
    ("color_space", ACCESS_READ_ONLY, "string", "Color space"),
    ("confidence_mode", ACCESS_READ_ONLY, "string", "Confidence mode"),
    ("confidence_threshold", ACCESS_READ_ONLY, "float", "Confidence threshold"),
    ("coordinate_transform_mode", ACCESS_READ_ONLY, "string", "Coordinate transform mode"),
    ("grab_timeout", ACCESS_READ_WRITE, "int", "Grab timeout (ms)"),
    ("image_available", ACCESS_READ_ONLY, "int", "Image available flag"),
    ("image_width", ACCESS_READ_ONLY, "int", "Current image width"),
    ("image_height", ACCESS_READ_ONLY, "int", "Current image height"),
    ("image_pixel_format", ACCESS_READ_ONLY, "string", "Current pixel format"),
    ("num_buffers", ACCESS_READ_WRITE, "int", "Number of acquisition buffers"),
    ("num_buffers_await_delivery", ACCESS_READ_ONLY, "int", "Buffers awaiting delivery"),
    ("num_buffers_underrun", ACCESS_READ_ONLY, "int", "Buffer underrun count"),
    ("streaming_mode", ACCESS_READ_ONLY, "int", "Streaming mode"),
    ("revision", ACCESS_READ_ONLY, "string", "HALCON revision"),
    ("volatile", ACCESS_READ_WRITE, "string", "Volatile mode"),
    ("direct_connection", ACCESS_READ_WRITE, "string", "Direct connection mode"),
    ("device_access", ACCESS_READ_WRITE, "string", "Device access mode"),
    ("clear_buffer", ACCESS_WRITE_ONLY, "command", "Clear internal buffer"),
    ("delay_after_stop", ACCESS_READ_WRITE, "int", "Delay after stop (ms)"),
    ("do_abort_grab", ACCESS_WRITE_ONLY, "command", "Abort current grab"),
    ("do_load_settings", ACCESS_WRITE_ONLY, "command", "Load camera settings"),
    ("do_write_settings", ACCESS_WRITE_ONLY, "command", "Write camera settings"),
    ("do_write_configuration", ACCESS_WRITE_ONLY, "command", "Write configuration"),
    ("start_async_after_grab_async", ACCESS_READ_WRITE, "string", "Start async after grab"),
    ("settings_selector", ACCESS_READ_WRITE, "string", "Settings selector"),
    ("split_param_values_into_dwords", ACCESS_READ_WRITE, "string", "Split param values flag"),

    # --- Device-scoped parameters (Read Only) ---
    ("[Device]DeviceAccessStatus", ACCESS_READ_ONLY, "string", "Device access status"),
    ("[Device]DeviceEndianessMechanism", ACCESS_READ_ONLY, "string", "Endianness"),
    ("[Device]DeviceID", ACCESS_READ_ONLY, "string", "Device ID"),
    ("[Device]DeviceLinkHeartbeatMode", ACCESS_READ_ONLY, "string", "Link heartbeat mode"),
    ("[Device]DeviceLinkHeartbeatTimeout", ACCESS_READ_ONLY, "float", "Link heartbeat timeout"),
    ("[Device]DeviceManufacturerInfo", ACCESS_READ_ONLY, "string", "Device manufacturer info"),
    ("[Device]DeviceModelName", ACCESS_READ_ONLY, "string", "Device model name"),
    ("[Device]DeviceSerialNumber", ACCESS_READ_ONLY, "string", "Device serial number"),
    ("[Device]DeviceType", ACCESS_READ_ONLY, "string", "Device type"),
    ("[Device]DeviceUserID", ACCESS_READ_ONLY, "string", "Device user ID"),
    ("[Device]DeviceVendorName", ACCESS_READ_ONLY, "string", "Device vendor name"),
    ("[Device]DeviceVersion", ACCESS_READ_ONLY, "string", "Device firmware version"),
    ("[Device]ForceSocketDriver", ACCESS_READ_WRITE, "int", "Force socket driver flag"),
    ("[Device]GevDeviceGateway", ACCESS_READ_ONLY, "int", "Device gateway"),
    ("[Device]GevDeviceIPAddress", ACCESS_READ_ONLY, "int", "Device IP address"),
    ("[Device]GevDeviceMACAddress", ACCESS_READ_ONLY, "int", "Device MAC address"),
    ("[Device]GevDeviceSubnetMask", ACCESS_READ_ONLY, "int", "Device subnet mask"),
    ("[Device]LinkCommandRetryCount", ACCESS_READ_WRITE, "int", "Link command retry count"),
    ("[Device]LinkCommandTimeout", ACCESS_READ_WRITE, "float", "Link command timeout"),
    ("[Device]StreamID", ACCESS_READ_ONLY, "string", "Stream ID"),
    ("[Device]StreamSelector", ACCESS_READ_WRITE, "int", "Stream selector"),

    # --- Interface-scoped parameters (Read Only most) ---
    ("[Interface]DeviceAccessStatus", ACCESS_READ_ONLY, "string", "Interface device access"),
    ("[Interface]DeviceID", ACCESS_READ_ONLY, "string", "Interface device ID"),
    ("[Interface]GevDeviceForceIP", ACCESS_READ_WRITE, "int", "Force IP flag"),
    ("[Interface]GevDeviceForceIPAddress", ACCESS_READ_WRITE, "int", "Force IP address"),
    ("[Interface]GevDeviceForceSubnetMask", ACCESS_READ_WRITE, "int", "Force subnet mask"),
    ("[Interface]GevDeviceProposeIP", ACCESS_READ_WRITE, "int", "Propose IP address"),
    ("[Interface]InterfaceID", ACCESS_READ_ONLY, "string", "Interface ID"),
    ("[Interface]InterfaceType", ACCESS_READ_ONLY, "string", "Interface type"),

    # --- Stream-scoped parameters ---
    ("[Stream]DeviceStreamChannelPacketSize", ACCESS_READ_WRITE, "int", "Stream packet size"),
    ("[Stream]DeviceStreamChannelPacketSizeInc", ACCESS_READ_ONLY, "int", "Packet size increment"),
    ("[Stream]DeviceStreamChannelPacketSizeMax", ACCESS_READ_ONLY, "int", "Max packet size"),
    ("[Stream]DeviceStreamChannelPacketSizeMin", ACCESS_READ_ONLY, "int", "Min packet size"),
    ("[Stream]GevStreamDeliveredPacketCount", ACCESS_READ_ONLY, "int", "Delivered packet count"),
    ("[Stream]GevStreamDiscardedBlockCount", ACCESS_READ_ONLY, "int", "Discarded block count"),
    ("[Stream]GevStreamDuplicatePacketCount", ACCESS_READ_ONLY, "int", "Duplicate packet count"),
    ("[Stream]GevStreamIncompleteBlockCount", ACCESS_READ_ONLY, "int", "Incomplete block count"),
    ("[Stream]GevStreamLostPacketCount", ACCESS_READ_ONLY, "int", "Lost packet count"),
    ("[Stream]GevStreamReceiveSocketSize", ACCESS_READ_WRITE, "int", "Receive socket buffer size"),
    ("[Stream]GevStreamResendCommandCount", ACCESS_READ_ONLY, "int", "Resend command count"),
    ("[Stream]GevStreamResendPacketCount", ACCESS_READ_ONLY, "int", "Resend packet count"),
    ("[Stream]GevStreamRingBufferSize", ACCESS_READ_WRITE, "int", "Ring buffer size"),
    ("[Stream]GevStreamSeenPacketCount", ACCESS_READ_ONLY, "int", "Seen packet count"),
    ("[Stream]StreamBufferHandlingMode", ACCESS_READ_WRITE, "string", "Buffer handling mode"),
    ("[Stream]StreamID", ACCESS_READ_ONLY, "string", "Stream ID"),
    ("[Stream]StreamType", ACCESS_READ_ONLY, "string", "Stream type"),

    # --- System-scoped ---
    ("[System]TLID", ACCESS_READ_ONLY, "string", "Transport layer ID"),
    ("[System]TLModelName", ACCESS_READ_ONLY, "string", "TL model name"),
    ("[System]TLType", ACCESS_READ_ONLY, "string", "TL type"),
    ("[System]TLVendorName", ACCESS_READ_ONLY, "string", "TL vendor name"),
    ("[System]TLVersion", ACCESS_READ_ONLY, "string", "TL version"),
]

# Additional params that were seen in the Halcon_Parameters.md dump but
# not yet confirmed. The scanner will discover these at runtime.
EXTRA_CANDIDATES: list[str] = [
    "buffer_frameid", "buffer_is_incomplete", "buffer_reallocation_mode",
    "buffer_timestamp", "buffer_timestamp_ns",
    "create_objectmodel3d", "data_contents", "data_purpose_id",
    "data_region_id", "data_source_id",
    "device_event_handling", "device_timestamp_frequency",
    "do_fileaccess_delete", "do_fileaccess_download", "do_fileaccess_upload",
    "event_data", "event_message_queue", "event_notification_helper",
    "event_selector", "fileaccess_file_path", "fileaccess_remote_name",
    "force_ip", "force_sockdrv",
    "image_contents", "image_pixel_format", "image_purpose_id",
    "image_raw_buffer_padding_bytes", "image_raw_buffer_type",
    "image_region_id", "image_source_id",
    "tl_displayname", "tl_filename", "tl_id", "tl_model",
    "tl_pathname", "workarounds",
    "add_objectmodel3d_overlay_attrib",
]


# ==========================================================================
# Utilities
# ==========================================================================

def _scalar(value: Any) -> Any:
    """Unwrap single-element lists (HALCON convention)."""
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


def _format_value(value: Any) -> str:
    """Safely format a value for display."""
    if value is None:
        return "<None>"
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return str(value)


def _halcon_type_name(value: Any) -> str:
    """Return a human-readable HALCON type name."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        elements = set(type(v).__name__ for v in value)
        return f"list[{','.join(sorted(elements))}]"
    return type(value).__name__


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ==========================================================================
# HalconSession — low-level HALCON wrapper for this tool
# ==========================================================================

class HalconSession:
    """Opens and manages a single HALCON framegrabber connection."""

    def __init__(self) -> None:
        self._fg = None
        self._connected = False
        self._device_name: str = ""
        self._device_list: list[str] = []
        self._log_callback = None

    def set_log_callback(self, cb) -> None:
        self._log_callback = cb

    def _log(self, direction: str, param: str, value: Any, result: str, detail: str = "") -> None:
        if self._log_callback:
            self._log_callback(direction, param, value, result, detail)

    # --- Discovery ---

    def discover_devices(self) -> list[str]:
        self._device_list = []
        try:
            raw = ha.info_framegrabber(GEV_NAME, "device")
            parsed = self._parse_devices(raw)
            self._device_list = parsed
        except Exception as exc:
            self._log("DISCOVER", "", "", "FAILED", str(exc))
        return self._device_list.copy()

    @staticmethod
    def _parse_devices(devices) -> list[str]:
        if not isinstance(devices, tuple) or len(devices) < 2:
            return []
        device_list = devices[1]
        if not isinstance(device_list, (list, tuple)):
            return []
        result = []
        prefix = "device:"
        for entry in device_list:
            if not isinstance(entry, str):
                continue
            idx = entry.find(prefix)
            if idx == -1:
                continue
            start = idx + len(prefix)
            end = entry.find(" |", start)
            if end == -1:
                end = len(entry)
            device_str = entry[start:end].strip()
            if device_str:
                result.append(device_str)
        return result

    # --- Connection ---

    def connect(self, device: str = "") -> bool:
        if self._connected:
            return True

        target = device if device else "default"
        args = list(FG_ARGS)
        # FG_ARGS layout (16-param GigEVision2):
        #   [0]=Name  [1-6]=W/H/SR/SC/Fld/BPC  [7]=CS  [8]=Gain
        #   [9]=ExtTrig  [10]=CamType  [11]=Device  [12]=?
        #   [13]=Port  [14]=LineIn  [15]=Info
        if target != "default":
            args[11] = "false"    # Device = "false" → use Port
            args[12] = "default"  # per TV46LCamera convention
            args[13] = target     # Port = device identifier
        else:
            args[11] = "false"
            args[12] = "default"
            args[13] = "default"

        try:
            self._fg = ha.open_framegrabber(*args)
            self._connected = True
            self._device_name = target
            self._log("CONNECT", "", "", "SUCCESS", f"Device: {target}")
            return True
        except Exception as exc:
            self._log("CONNECT", "", "", "FAILED", str(exc))
            self._fg = None
            return False

    def disconnect(self) -> None:
        if not self._connected or self._fg is None:
            return
        try:
            ha.close_framegrabber(self._fg)
            self._log("DISCONNECT", "", "", "SUCCESS")
        except Exception as exc:
            self._log("DISCONNECT", "", "", "FAILED", str(exc))
        finally:
            self._fg = None
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def fg(self):
        return self._fg

    # --- Parameter Operations ---

    def get_parameter(self, name: str) -> tuple[Any, str, str]:
        """Returns (value, status, error_message). Status is 'SUCCESS' or error string."""
        try:
            raw = ha.get_framegrabber_param(self._fg, name)
            value = _scalar(raw)
            self._log("GET", name, value, "SUCCESS")
            return value, "SUCCESS", ""
        except Exception as exc:
            msg = str(exc).strip()
            self._log("GET", name, "", "FAILED", msg)
            return None, "FAILED", msg

    def set_parameter(self, name: str, value: Any) -> tuple[bool, str]:
        """Returns (success, error_message)."""
        try:
            ha.set_framegrabber_param(self._fg, name, value)
            self._log("SET", name, value, "SUCCESS")
            return True, ""
        except Exception as exc:
            msg = str(exc).strip()
            self._log("SET", name, value, "FAILED", msg)
            return False, msg

    def discover_parameters(self) -> list[str]:
        """Return list of available parameter names from the camera."""
        candidates: set[str] = set()
        try:
            raw = ha.get_framegrabber_param(self._fg, "available_param_names")
            if isinstance(raw, (list, tuple)):
                for p in raw:
                    if isinstance(p, str):
                        candidates.add(p)
            self._log("DISCOVER", "available_param_names", len(candidates), "SUCCESS")
        except Exception as exc:
            self._log("DISCOVER", "available_param_names", "", "FAILED", str(exc))

        try:
            easy_raw = ha.get_framegrabber_param(self._fg, "available_easyparam_names")
            if isinstance(easy_raw, (list, tuple)):
                for p in easy_raw:
                    if isinstance(p, str):
                        candidates.add(p)
        except Exception:
            pass

        for p in EXTRA_CANDIDATES:
            candidates.add(p)

        return sorted(candidates)

    def get_info_framegrabber(self, query: str, param: str = "") -> Any:
        """Call ha.info_framegrabber on the open framegrabber."""
        try:
            result = ha.info_framegrabber(self._fg, query, param)
            return result
        except Exception:
            return None


# ==========================================================================
# History Entry
# ==========================================================================

@dataclass
class HistoryEntry:
    timestamp: str = ""
    action: str = ""       # GET / SET / EXECUTE / CONNECT / DISCONNECT / DISCOVER / SCAN
    param: str = ""
    value: str = ""
    result: str = ""       # SUCCESS / FAILED / error msg
    detail: str = ""


# ==========================================================================
# Parameter Classification
# ==========================================================================

def classify_parameters(
    session: HalconSession,
    param_names: list[str],
    known_map: dict[str, tuple[str, str, str]],
    progress_cb=None,
) -> dict[str, dict]:
    """
    Attempt to classify each parameter by reading and (cautiously) writing.

    Returns dict: param_name -> {
        "access": ACCESS_READ_ONLY | ACCESS_READ_WRITE | ACCESS_WRITE_ONLY | ACCESS_UNSUPPORTED,
        "value": current value (if readable),
        "halcon_type": type string,
        "error": error message (if any),
    }
    """
    results: dict[str, dict] = {}
    total = len(param_names)

    for idx, name in enumerate(param_names):
        if progress_cb:
            progress_cb(idx + 1, total, name)

        info: dict[str, Any] = {
            "access": ACCESS_UNSUPPORTED,
            "value": None,
            "halcon_type": "unknown",
            "error": "",
        }

        # Check known registry first
        if name in known_map:
            hint_access, hint_type, _desc = known_map[name]
            info["access"] = hint_access
            info["halcon_type"] = hint_type

        # Try to read
        value, status, err = session.get_parameter(name)
        if status == "SUCCESS":
            info["value"] = value
            info["halcon_type"] = _halcon_type_name(value)
            if info["access"] in (ACCESS_UNSUPPORTED, ACCESS_WRITE_ONLY):
                info["access"] = ACCESS_READ_ONLY
        else:
            info["error"] = err
            # If known as write-only, keep that; if known as read/write, check again
            if info["access"] not in (ACCESS_WRITE_ONLY, ACCESS_READ_WRITE):
                # Try writing to see if it's write-only
                test_val = 1 if info["halcon_type"] == "int" else "trigger"
                ok, _ = session.set_parameter(name, test_val)
                if ok:
                    info["access"] = ACCESS_WRITE_ONLY
                    info["value"] = test_val
                else:
                    info["access"] = ACCESS_UNSUPPORTED

        # If read succeeded and marked Read Only, try writing current value back to confirm RW
        if status == "SUCCESS" and info["access"] == ACCESS_READ_ONLY:
            if _is_likely_writable(name, value):
                ok, _ = session.set_parameter(name, value)
                if ok:
                    info["access"] = ACCESS_READ_WRITE

        results[name] = info

    return results


def _is_likely_writable(name: str, value: Any) -> bool:
    """Heuristic: parameters that are safe to write their current value back."""
    # Skip parameters that look like info/status
    low = name.lower()
    skip_patterns = [
        "serial", "version", "manufacturer", "vendor", "model",
        "temperature", "capabilities", "platform", "calibration",
        "height", "width", "sensor", "payload", "pixelformat",
        "deviceaccess", "deviceid", "macaddress", "ipaddress",
        "subnet", "gateway", "streamid", "interfaceid",
        "tl", "revision", "count", "rate", "size",
    ]
    for pat in skip_patterns:
        if pat in low:
            return False
    # Also skip read-only indicators
    if isinstance(value, str) and len(value) > 50:
        return False
    return True


# ==========================================================================
# Log / History widget
# ==========================================================================

class LogWidget(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 9))
        self.setMaximumBlockCount(LOG_MAX)

    def append_log(self, text: str, color: str = "#000000") -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.setTextCursor(cursor)


# ==========================================================================
# History Table
# ==========================================================================

class HistoryTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["Time", "Action", "Parameter", "Value", "Result"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setColumnWidth(0, 70)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 200)
        self.setColumnWidth(3, 200)

    def add_entry(self, entry: HistoryEntry) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, 0, QTableWidgetItem(entry.timestamp))
        self.setItem(row, 1, QTableWidgetItem(entry.action))
        self.setItem(row, 2, QTableWidgetItem(entry.param))
        self.setItem(row, 3, QTableWidgetItem(entry.value))
        result_item = QTableWidgetItem(entry.result)
        if entry.result == "SUCCESS":
            result_item.setForeground(QBrush(QColor("#006600")))
        elif "FAILED" in entry.result or "ERROR" in entry.result.upper():
            result_item.setForeground(QBrush(QColor("#CC0000")))
        else:
            result_item.setForeground(QBrush(QColor("#CC6600")))
        self.setItem(row, 4, result_item)
        self.scrollToBottom()

    def clear_entries(self) -> None:
        self.setRowCount(0)


# ==========================================================================
# Inspector Panel
# ==========================================================================

class InspectorPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._fields: dict[str, QLabel] = {}
        labels = [
            "Parameter Name", "Current Value", "HALCON Type",
            "Python Type", "Access", "Last Read Time", "Last Write Time",
            "Read Success", "Write Success", "Error Message",
        ]
        grid = QGridLayout()
        for i, label in enumerate(labels):
            name_lbl = QLabel(f"<b>{label}:</b>")
            val_lbl = QLabel("-")
            val_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            val_lbl.setWordWrap(True)
            grid.addWidget(name_lbl, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(val_lbl, i, 1)
            self._fields[label] = val_lbl

        layout.addLayout(grid)
        layout.addStretch()

    def show_parameter(self, name: str, value: Any, access: str,
                       last_read: str, last_write: str,
                       read_ok: bool, write_ok: bool,
                       error: str) -> None:
        self._fields["Parameter Name"].setText(name)
        self._fields["Current Value"].setText(_format_value(value))
        self._fields["HALCON Type"].setText(_halcon_type_name(value) if value is not None else "-")
        self._fields["Python Type"].setText(type(value).__name__ if value is not None else "-")
        self._fields["Access"].setText(access)
        self._fields["Last Read Time"].setText(last_read if last_read else "-")
        self._fields["Last Write Time"].setText(last_write if last_write else "-")
        self._fields["Read Success"].setText("Yes" if read_ok else "No")
        self._fields["Write Success"].setText("Yes" if write_ok else "No")
        self._fields["Error Message"].setText(error if error else "-")

    def clear_display(self) -> None:
        for lbl in self._fields.values():
            lbl.setText("-")


# ==========================================================================
# Manual Test Box
# ==========================================================================

class ManualTestBox(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__("Manual Parameter Test", parent)
        layout = QHBoxLayout(self)

        layout.addWidget(QLabel("Parameter:"))
        self.param_input = QLineEdit()
        self.param_input.setPlaceholderText("e.g. FLK_TI_Info_CurrentDeviceTemperatureC")
        self.param_input.setMinimumWidth(200)
        layout.addWidget(self.param_input)

        layout.addWidget(QLabel("Value:"))
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Value for write / execute")
        self.value_input.setMinimumWidth(150)
        layout.addWidget(self.value_input)

        self.read_btn = QPushButton("Read")
        self.read_btn.setStyleSheet("background-color: #4A90D9; color: white;")
        self.write_btn = QPushButton("Write")
        self.write_btn.setStyleSheet("background-color: #D98A4A; color: white;")
        self.execute_btn = QPushButton("Execute")
        self.execute_btn.setStyleSheet("background-color: #8A4AD9; color: white;")
        layout.addWidget(self.read_btn)
        layout.addWidget(self.write_btn)
        layout.addWidget(self.execute_btn)


# ==========================================================================
# Parameter Browser Tree
# ==========================================================================

class ParameterBrowser(QWidget):
    param_selected = None  # will be set to a pyqtSignal later

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._param_data: dict[str, dict] = {}

        layout = QVBoxLayout(self)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to filter parameters...")
        self.search_input.textChanged.connect(self._filter_tree)
        search_layout.addWidget(self.search_input)
        self.clear_search_btn = QPushButton("Clear")
        self.clear_search_btn.clicked.connect(lambda: self.search_input.clear())
        search_layout.addWidget(self.clear_search_btn)
        layout.addLayout(search_layout)

        # Refresh button
        refresh_layout = QHBoxLayout()
        self.refresh_params_btn = QPushButton("Refresh Parameter List")
        self.refresh_params_btn.setStyleSheet("background-color: #4A90D9; color: white;")
        refresh_layout.addWidget(self.refresh_params_btn)
        refresh_layout.addStretch()
        counter_layout = QHBoxLayout()
        counter_layout.addWidget(QLabel("Parameters:"))
        self.count_label = QLabel("0")
        counter_layout.addWidget(self.count_label)
        counter_layout.addStretch()
        layout.addLayout(refresh_layout)
        layout.addLayout(counter_layout)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Parameter", "Value", "Access", "Type"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 200)
        self.tree.setColumnWidth(2, 100)
        self.tree.setIndentation(16)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(True)
        layout.addWidget(self.tree)

    def set_param_data(self, data: dict[str, dict]) -> None:
        self._param_data = data
        self._rebuild_tree()

    def _rebuild_tree(self, filter_text: str = "") -> None:
        self.tree.clear()

        filtered: dict[str, dict[str, dict]] = {
            ACCESS_READ_ONLY: {},
            ACCESS_READ_WRITE: {},
            ACCESS_WRITE_ONLY: {},
            ACCESS_UNSUPPORTED: {},
        }

        for name, info in self._param_data.items():
            if filter_text and filter_text.lower() not in name.lower():
                continue
            access = info.get("access", ACCESS_UNSUPPORTED)
            if access not in filtered:
                access = ACCESS_UNSUPPORTED
            filtered[access][name] = info

        category_order = [
            (ACCESS_READ_WRITE, "Read / Write"),
            (ACCESS_READ_ONLY, "Read Only"),
            (ACCESS_WRITE_ONLY, "Write Only"),
            (ACCESS_UNSUPPORTED, "Unsupported"),
        ]

        total_count = 0
        for key, label in category_order:
            items = filtered[key]
            if not items:
                continue
            count = len(items)
            total_count += count
            cat_item = QTreeWidgetItem([f"{label}  ({count})", "", "", ""])
            cat_item.setExpanded(True)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            self.tree.addTopLevelItem(cat_item)

            for name in sorted(items.keys()):
                info = items[name]
                val = _format_value(info.get("value", ""))
                acc = info.get("access", "")
                htype = info.get("halcon_type", "")
                child = QTreeWidgetItem([name, val, acc, htype])
                child.setData(0, Qt.ItemDataRole.UserRole, name)
                cat_item.addChild(child)

        self.count_label.setText(str(total_count))

    def _filter_tree(self, text: str) -> None:
        self._rebuild_tree(text)

    def get_selected_param(self) -> str | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name is None:
            parent = item.parent()
            if parent:
                return parent.data(0, Qt.ItemDataRole.UserRole)
            return None
        return name

    def get_param_data(self, name: str) -> dict | None:
        return self._param_data.get(name)


# ==========================================================================
# Parameter Scanner Tab
# ==========================================================================

class ScannerTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # Controls
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start Scan")
        self.start_btn.setStyleSheet("background-color: #D94A4A; color: white; font-weight: bold;")
        self.export_csv_btn = QPushButton("Export CSV")
        self.export_json_btn = QPushButton("Export JSON")
        self.export_csv_btn.setEnabled(False)
        self.export_json_btn.setEnabled(False)

        controls.addWidget(self.start_btn)
        controls.addWidget(self.export_csv_btn)
        controls.addWidget(self.export_json_btn)
        controls.addStretch()
        layout.addLayout(controls)

        # Progress
        prog_layout = QHBoxLayout()
        prog_layout.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel("Idle")
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.progress_label)
        layout.addLayout(prog_layout)

        # Stats
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)

        # Results table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Parameter", "Access", "Value", "Type", "Error"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 200)
        self.table.setColumnWidth(3, 80)
        layout.addWidget(self.table)

        self._scan_results: list[dict] = []
        self._scanning = False

    def set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        self.start_btn.setEnabled(not scanning)
        self.start_btn.setText("Stop Scan" if scanning else "Start Scan")

    @property
    def scanning(self) -> bool:
        return self._scanning

    def update_progress(self, current: int, total: int, name: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"[{current}/{total}] {name}")

    def add_result(self, info: dict) -> None:
        self._scan_results.append(info)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(info.get("name", "")))
        self.table.setItem(row, 1, QTableWidgetItem(info.get("access", "")))
        self.table.setItem(row, 2, QTableWidgetItem(_format_value(info.get("value", ""))))
        self.table.setItem(row, 3, QTableWidgetItem(info.get("type", "")))
        self.table.setItem(row, 4, QTableWidgetItem(info.get("error", "")))
        self.table.scrollToBottom()

        # Update stats
        counts: dict[str, int] = {}
        for r in self._scan_results:
            acc = r.get("access", "")
            counts[acc] = counts.get(acc, 0) + 1
        stats_parts = [f"{k}: {v}" for k, v in sorted(counts.items())]
        self.stats_label.setText("  |  ".join(stats_parts))

    def clear_results(self) -> None:
        self._scan_results.clear()
        self.table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Idle")
        self.stats_label.setText("")
        self.export_csv_btn.setEnabled(False)
        self.export_json_btn.setEnabled(False)

    def finish_scan(self) -> None:
        self._scanning = False
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Start Scan")
        self.export_csv_btn.setEnabled(bool(self._scan_results))
        self.export_json_btn.setEnabled(bool(self._scan_results))
        self.progress_label.setText(f"Complete — {len(self._scan_results)} parameters")

    def get_results(self) -> list[dict]:
        return self._scan_results.copy()


# ==========================================================================
# Quick Test Panel
# ==========================================================================

class QuickTestPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setStyleSheet("QFrame { border: 2px solid #D94A4A; border-radius: 4px; padding: 4px; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        icon_label = QLabel("⚡")
        icon_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(icon_label)

        layout.addWidget(QLabel("<b>Quick Test:</b>"))
        self.param_label = QLabel("(not set)")
        self.param_label.setStyleSheet("color: #CC0000; font-weight: bold;")
        layout.addWidget(self.param_label)

        layout.addWidget(QLabel("Value:"))
        self.value_label = QLabel("-")
        self.value_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.value_label)

        self.read_btn = QPushButton("Read")
        self.read_btn.setStyleSheet("background-color: #4A90D9; color: white;")
        layout.addWidget(self.read_btn)

        layout.addStretch()


# ==========================================================================
# Live Refresh Bar
# ==========================================================================

class LiveRefreshBar(QFrame):
    refresh_rate_changed = None  # pyqtSignal(int) — 0 = off

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        layout.addWidget(QLabel("<b>Live Refresh:</b>"))
        self.off_btn = QRadioButton("Off")
        self.ms500_btn = QRadioButton("500 ms")
        self.s1_btn = QRadioButton("1 s")
        self.s2_btn = QRadioButton("2 s")
        self.s5_btn = QRadioButton("5 s")
        self.off_btn.setChecked(True)

        layout.addWidget(self.off_btn)
        layout.addWidget(self.ms500_btn)
        layout.addWidget(self.s1_btn)
        layout.addWidget(self.s2_btn)
        layout.addWidget(self.s5_btn)
        layout.addStretch()

        self._buttons = [self.off_btn, self.ms500_btn, self.s1_btn, self.s2_btn, self.s5_btn]
        self._intervals = [0, 500, 1000, 2000, 5000]

        for btn in self._buttons:
            btn.toggled.connect(self._on_change)

        self.current_value_label = QLabel("Last: -")
        layout.addWidget(self.current_value_label)

    def _on_change(self) -> None:
        for btn, interval in zip(self._buttons, self._intervals):
            if btn.isChecked():
                if self.refresh_rate_changed:
                    self.refresh_rate_changed(interval)
                break

    def set_current_value(self, value: str) -> None:
        self.current_value_label.setText(f"Last: {value}")

    def set_refresh_rate(self, ms: int) -> None:
        for btn, interval in zip(self._buttons, self._intervals):
            if interval == ms and ms > 0:
                btn.setChecked(True)
                return
        self.off_btn.setChecked(True)


# ==========================================================================
# Main Window
# ==========================================================================

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 850)

        self._session = HalconSession()
        self._session.set_log_callback(self._on_halcon_log)
        self._history: list[HistoryEntry] = []
        self._param_data: dict[str, dict] = {}
        self._known_map: dict[str, tuple[str, str, str]] = {}
        self._last_read_time: dict[str, str] = {}
        self._last_write_time: dict[str, str] = {}
        self._read_success: dict[str, bool] = {}
        self._write_success: dict[str, bool] = {}
        self._last_error: dict[str, str] = {}

        # Build known map
        for name, access, htype, desc in KNOWN_PARAMETERS:
            self._known_map[name] = (access, htype, desc)

        self._build_known_desc_map()

        self._live_interval = 0
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._on_live_refresh)
        self._live_param: str | None = None

        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._on_scan_step)
        self._scan_params: list[str] = []
        self._scan_idx = 0

        self._setup_ui()
        self._connect_signals()

        # Auto-start quick test if set
        if _quick_test_param:
            self._quick_test_param_name = _quick_test_param
            self.quick_test_panel.param_label.setText(_quick_test_param)
            self.quick_test_panel.setVisible(True)
        else:
            self._quick_test_param_name = ""
            self.quick_test_panel.setVisible(False)

        self._update_connection_ui()

    def _build_known_desc_map(self) -> None:
        self._known_desc: dict[str, str] = {}
        for name, _access, _htype, desc in KNOWN_PARAMETERS:
            self._known_desc[name] = desc

    # ----------------------------------------------------------
    # UI Setup
    # ----------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # === Connection Bar ===
        conn_bar = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 6px 20px;")
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setStyleSheet("background-color: #f44336; color: white; padding: 6px 20px;")
        self.disconnect_btn.setEnabled(False)
        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 6px 20px;")
        self.reconnect_btn.setEnabled(False)
        conn_bar.addWidget(self.connect_btn)
        conn_bar.addWidget(self.disconnect_btn)
        conn_bar.addWidget(self.reconnect_btn)
        conn_bar.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.setEditable(True)
        self.device_combo.setPlaceholderText("Discover or type device...")
        conn_bar.addWidget(self.device_combo)
        self.discover_devices_btn = QPushButton("Scan")
        self.discover_devices_btn.setStyleSheet("padding: 4px 12px;")
        conn_bar.addWidget(self.discover_devices_btn)
        conn_bar.addStretch()
        self.conn_status_label = QLabel("Disconnected")
        self.conn_status_label.setStyleSheet("color: #CC0000; font-weight: bold;")
        conn_bar.addWidget(self.conn_status_label)
        main_layout.addLayout(conn_bar)

        # === Quick Test Panel ===
        self.quick_test_panel = QuickTestPanel()
        main_layout.addWidget(self.quick_test_panel)

        # === Manual Test Box ===
        self.manual_box = ManualTestBox()
        main_layout.addWidget(self.manual_box)

        # === Tab Widget ===
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)

        # Tab 1: Parameter Browser
        self.param_browser = ParameterBrowser()
        self.tabs.addTab(self.param_browser, "Parameters")

        # Tab 2: Inspector
        self.inspector = InspectorPanel()
        self.tabs.addTab(self.inspector, "Inspector")

        # Tab 3: History
        hist_widget = QWidget()
        hist_layout = QVBoxLayout(hist_widget)
        hist_btn_layout = QHBoxLayout()
        self.clear_history_btn = QPushButton("Clear History")
        hist_btn_layout.addWidget(self.clear_history_btn)
        hist_btn_layout.addStretch()
        hist_layout.addLayout(hist_btn_layout)
        self.history_table = HistoryTable()
        hist_layout.addWidget(self.history_table)
        self.tabs.addTab(hist_widget, "History")

        # Tab 4: Log
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_btn_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("Clear Log")
        log_btn_layout.addWidget(self.clear_log_btn)
        log_btn_layout.addStretch()
        log_layout.addLayout(log_btn_layout)
        self.log_view = LogWidget()
        log_layout.addWidget(self.log_view)
        self.tabs.addTab(log_widget, "Log")

        # Tab 5: Scanner
        self.scanner_tab = ScannerTab()
        self.tabs.addTab(self.scanner_tab, "Scanner")

        # === Live Refresh Bar ===
        self.live_refresh_bar = LiveRefreshBar()
        main_layout.addWidget(self.live_refresh_bar)

        # === Status Bar ===
        self._status("Ready")

        # Log startup
        self._append_log(f"{APP_NAME} v{APP_VERSION} started", "#006600")

    def _connect_signals(self) -> None:
        # Connection
        self.connect_btn.clicked.connect(self._on_connect)
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        self.reconnect_btn.clicked.connect(self._on_reconnect)
        self.discover_devices_btn.clicked.connect(self._on_discover_devices)

        # Manual test box
        self.manual_box.read_btn.clicked.connect(self._on_manual_read)
        self.manual_box.write_btn.clicked.connect(self._on_manual_write)
        self.manual_box.execute_btn.clicked.connect(self._on_manual_execute)

        # Quick test
        self.quick_test_panel.read_btn.clicked.connect(self._on_quick_test_read)

        # Parameter browser
        self.param_browser.refresh_params_btn.clicked.connect(self._on_refresh_params)
        self.param_browser.tree.currentItemChanged.connect(self._on_param_selected)

        # History
        self.clear_history_btn.clicked.connect(self._clear_history)

        # Log
        self.clear_log_btn.clicked.connect(lambda: self.log_view.clear())

        # Scanner
        self.scanner_tab.start_btn.clicked.connect(self._on_toggle_scan)
        self.scanner_tab.export_csv_btn.clicked.connect(self._on_export_csv)
        self.scanner_tab.export_json_btn.clicked.connect(self._on_export_json)

        # Live refresh
        self.live_refresh_bar.refresh_rate_changed = self._on_live_rate_changed

    # ----------------------------------------------------------
    # Connection Methods
    # ----------------------------------------------------------

    def _on_discover_devices(self) -> None:
        self._status("Scanning for GigE Vision devices...")
        self._append_log("Scanning for devices...", "#004080")
        devices = self._session.discover_devices()
        self.device_combo.clear()
        if devices:
            for d in devices:
                self.device_combo.addItem(d)
            self.device_combo.setCurrentIndex(0)
            self._append_log(f"Found {len(devices)} device(s)", "#006600")
            self._status(f"Found {len(devices)} device(s)")
        else:
            self._append_log("No devices found", "#CC6600")
            self._status("No devices found")

    def _on_connect(self) -> None:
        try:
            if self._session.connected:
                self._status("Already connected")
                return
            device = self.device_combo.currentText().strip()
            if not device:
                device = "default"
            self._append_log(f"Connecting (device={device})...", "#004080")
            ok = self._session.connect(device)
            if ok:
                self._add_history(HistoryEntry(
                    timestamp=_now_str(), action="CONNECT", param="",
                    value="", result="SUCCESS", detail=f"Device: {device}"
                ))
                self._append_log("Connected successfully", "#006600")
                self._status("Connected")
                self._on_refresh_params()
            else:
                err_msg = "Connection returned false (check Log tab for details)"
                self._add_history(HistoryEntry(
                    timestamp=_now_str(), action="CONNECT", param="",
                    value="", result="FAILED", detail=device
                ))
                self._append_log(f"Connection FAILED: {err_msg}", "#CC0000")
                self._status(err_msg)
            self._update_connection_ui()

            if ok and self._quick_test_param_name:
                self._on_quick_test_read()
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self._append_log(f"CONNECT CRASHED: {exc}\n{tb}", "#CC0000")
            QMessageBox.critical(self, "Connection Error", f"{exc}\n\nSee Log tab for details.")
            self._status(f"Error: {exc}")

    def _status(self, msg: str) -> None:
        sb = self.statusBar()
        if sb is not None:
            sb.showMessage(msg)

    def _on_disconnect(self) -> None:
        try:
            self._stop_live_refresh()
            self._session.disconnect()
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="DISCONNECT", param="",
                value="", result="SUCCESS"
            ))
            self._append_log("Disconnected", "#CC6600")
            self._status("Disconnected")
        except Exception as exc:
            self._append_log(f"Disconnect error: {exc}", "#CC0000")
        self._update_connection_ui()

    def _on_reconnect(self) -> None:
        try:
            self._append_log("Reconnecting...", "#004080")
            self._stop_live_refresh()
            device = self.device_combo.currentText().strip()
            self._session.disconnect()
            ok = self._session.connect(device if device else "default")
            if ok:
                self._add_history(HistoryEntry(
                    timestamp=_now_str(), action="RECONNECT", param="",
                    value="", result="SUCCESS", detail=f"Device: {device}"
                ))
                self._append_log("Reconnected", "#006600")
                self._status("Reconnected")
                self._on_refresh_params()
            else:
                self._add_history(HistoryEntry(
                    timestamp=_now_str(), action="RECONNECT", param="",
                    value="", result="FAILED", detail=device
                ))
                self._append_log("Reconnect FAILED", "#CC0000")
                self._status("Reconnect failed")
        except Exception as exc:
            import traceback
            self._append_log(f"RECONNECT CRASHED: {exc}\n{traceback.format_exc()}", "#CC0000")
            QMessageBox.critical(self, "Reconnect Error", str(exc))
        self._update_connection_ui()

    def _update_connection_ui(self) -> None:
        connected = self._session.connected
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.reconnect_btn.setEnabled(connected)
        self.conn_status_label.setText("Connected" if connected else "Disconnected")
        self.conn_status_label.setStyleSheet(
            "color: #006600; font-weight: bold;" if connected
            else "color: #CC0000; font-weight: bold;"
        )
        # Enable/disable parameter-dependent controls
        has_data = bool(self._param_data)
        self.param_browser.refresh_params_btn.setEnabled(connected)
        self.manual_box.read_btn.setEnabled(connected)
        self.manual_box.write_btn.setEnabled(connected)
        self.manual_box.execute_btn.setEnabled(connected)
        self.quick_test_panel.read_btn.setEnabled(connected)
        self.scanner_tab.start_btn.setEnabled(connected)

    # ----------------------------------------------------------
    # Parameter Discovery
    # ----------------------------------------------------------

    def _on_refresh_params(self) -> None:
        if not self._session.connected:
            return
        self._status("Discovering parameters...")
        self._append_log("Discovering parameters...", "#004080")
        names = self._session.discover_parameters()
        # Merge with known parameters
        all_names = set(names)
        for name in self._known_map:
            all_names.add(name)
        sorted_names = sorted(all_names)

        # Classify
        def progress_cb(current, total, name):
            self._status(f"Classifying [{current}/{total}]: {name}")

        results = classify_parameters(
            self._session, sorted_names, self._known_map, progress_cb
        )
        self._param_data = results
        self.param_browser.set_param_data(results)
        self._append_log(f"Discovered/classified {len(results)} parameters", "#006600")
        self._status(f"{len(results)} parameters")
        self._update_connection_ui()

    # ----------------------------------------------------------
    # Parameter Selection
    # ----------------------------------------------------------

    def _on_param_selected(self, current, previous) -> None:
        name = self.param_browser.get_selected_param()
        if name is None:
            self.inspector.clear_display()
            self._live_param = None
            return

        info = self.param_browser.get_param_data(name)
        if info is None:
            return

        access = info.get("access", ACCESS_UNSUPPORTED)
        value = info.get("value")
        error = info.get("error", "")

        # Show in inspector
        self.inspector.show_parameter(
            name=name,
            value=value,
            access=access,
            last_read=self._last_read_time.get(name, ""),
            last_write=self._last_write_time.get(name, ""),
            read_ok=self._read_success.get(name, True),
            write_ok=self._write_success.get(name, True),
            error=error,
        )
        self._live_param = name
        self.tabs.setCurrentIndex(1)  # Switch to inspector tab

    # ----------------------------------------------------------
    # Manual Test Box
    # ----------------------------------------------------------

    def _get_manual_param_value(self) -> tuple[str, str]:
        param = self.manual_box.param_input.text().strip()
        value = self.manual_box.value_input.text().strip()
        return param, value

    def _on_manual_read(self) -> None:
        param, _ = self._get_manual_param_value()
        if not param:
            self._status("Enter a parameter name")
            return
        self._read_and_display(param)

    def _on_manual_write(self) -> None:
        param, value_str = self._get_manual_param_value()
        if not param:
            self._status("Enter a parameter name")
            return
        value = self._parse_value(value_str)
        ok, err = self._session.set_parameter(param, value)
        self._last_write_time[param] = _now_str()
        self._write_success[param] = ok
        if ok:
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="SET", param=param,
                value=_format_value(value), result="SUCCESS"
            ))
            self._status(f"Set {param} = {value}")
            # Re-read to show result
            self._read_and_display(param)
        else:
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="SET", param=param,
                value=_format_value(value), result="FAILED", detail=err
            ))
            self._status(f"Write FAILED: {err}")

    def _on_manual_execute(self) -> None:
        param, value_str = self._get_manual_param_value()
        if not param:
            self._status("Enter a parameter name")
            return
        value = self._parse_value(value_str) if value_str else 1
        ok, err = self._session.set_parameter(param, value)
        if ok:
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="EXECUTE", param=param,
                value=_format_value(value), result="SUCCESS"
            ))
            self._status(f"Execute {param}")
        else:
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="EXECUTE", param=param,
                value=_format_value(value), result="FAILED", detail=err
            ))
            self._status(f"Execute FAILED: {err}")

    # ----------------------------------------------------------
    # Quick Test
    # ----------------------------------------------------------

    def _on_quick_test_read(self) -> None:
        if not self._quick_test_param_name:
            return
        self._read_and_display(self._quick_test_param_name, quick_test=True)

    def _read_and_display(self, param: str, quick_test: bool = False) -> None:
        value, status, err = self._session.get_parameter(param)
        self._last_read_time[param] = _now_str()
        self._read_success[param] = (status == "SUCCESS")

        if status == "SUCCESS":
            formatted = _format_value(value)
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="GET", param=param,
                value=formatted, result="SUCCESS"
            ))
            if quick_test:
                self.quick_test_panel.value_label.setText(formatted)
            self._status(f"{param} = {formatted}")
            # Also fill manual box for convenience
            self.manual_box.param_input.setText(param)
            self.manual_box.value_input.setText(formatted)
        else:
            self._add_history(HistoryEntry(
                timestamp=_now_str(), action="GET", param=param,
                value="", result="FAILED", detail=err
            ))
            if quick_test:
                self.quick_test_panel.value_label.setText("FAILED")
            self._status(f"Read FAILED: {err}")

    # ----------------------------------------------------------
    # Live Refresh
    # ----------------------------------------------------------

    def _on_live_rate_changed(self, interval_ms: int) -> None:
        self._stop_live_refresh()
        self._live_interval = interval_ms
        if interval_ms > 0:
            self._live_timer.start(interval_ms)
            self._append_log(f"Live refresh started every {interval_ms}ms", "#004080")

    def _stop_live_refresh(self) -> None:
        self._live_timer.stop()
        self._live_interval = 0

    def _on_live_refresh(self) -> None:
        if not self._session.connected or not self._live_param:
            self._stop_live_refresh()
            self.live_refresh_bar.off_btn.setChecked(True)
            return
        # Read silently (no logging to avoid spam)
        try:
            raw = ha.get_framegrabber_param(self._session.fg, self._live_param)
            value = _scalar(raw)
            formatted = _format_value(value)
            self.live_refresh_bar.set_current_value(formatted)
            # Update browser if param is there
            if self._live_param in self._param_data:
                self._param_data[self._live_param]["value"] = value
            self.param_browser.set_param_data(self._param_data)
        except Exception:
            pass

    # ----------------------------------------------------------
    # Parameter Scanner
    # ----------------------------------------------------------

    def _on_toggle_scan(self) -> None:
        if self.scanner_tab.scanning:
            self._scan_timer.stop()
            self.scanner_tab.set_scanning(False)
            self._append_log("Scan stopped by user", "#CC6600")
            return

        if not self._session.connected:
            QMessageBox.warning(self, "Not Connected", "Connect to a camera first.")
            return

        self.scanner_tab.clear_results()
        self._append_log("Starting parameter scan...", "#004080")

        # Get parameters to scan
        names = self._session.discover_parameters()
        for name in self._known_map:
            if name not in names:
                names.append(name)
        self._scan_params = sorted(names)
        self._scan_idx = 0
        self.scanner_tab.set_scanning(True)
        self._scan_timer.start(10)  # Process one param per tick

    def _on_scan_step(self) -> None:
        if self._scan_idx >= len(self._scan_params):
            self._scan_timer.stop()
            self.scanner_tab.finish_scan()
            self._append_log(
                f"Scan complete — {len(self.scanner_tab.get_results())} parameters",
                "#006600"
            )
            return

        name = self._scan_params[self._scan_idx]
        self._scan_idx += 1
        self.scanner_tab.update_progress(self._scan_idx, len(self._scan_params), name)

        # Read
        value, status, err = self._session.get_parameter(name)
        info: dict[str, Any] = {
            "name": name,
            "value": value,
            "access": ACCESS_UNSUPPORTED,
            "type": _halcon_type_name(value) if value is not None else "unknown",
            "error": "",
        }

        if status == "SUCCESS":
            info["access"] = ACCESS_READ_ONLY
            info["type"] = _halcon_type_name(value)
            # Try writing current value back to check RW
            if _is_likely_writable(name, value):
                ok, werr = self._session.set_parameter(name, value)
                if ok:
                    info["access"] = ACCESS_READ_WRITE
        else:
            info["error"] = err
            # Try write-only
            test_val = 1
            ok, werr = self._session.set_parameter(name, test_val)
            if ok:
                info["access"] = ACCESS_WRITE_ONLY
                info["value"] = test_val
                info["type"] = "command"

        # Check known map
        if name in self._known_map:
            hint_access, hint_type, _desc = self._known_map[name]
            if hint_access == ACCESS_WRITE_ONLY:
                info["access"] = ACCESS_WRITE_ONLY
            elif hint_access == ACCESS_READ_WRITE and info["access"] == ACCESS_UNSUPPORTED:
                info["access"] = ACCESS_READ_WRITE

        self.scanner_tab.add_result(info)

    # ----------------------------------------------------------
    # Export
    # ----------------------------------------------------------

    def _on_export_csv(self) -> None:
        results = self.scanner_tab.get_results()
        if not results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "halcon_parameters.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["name", "access", "value", "type", "error"])
                writer.writeheader()
                for r in results:
                    writer.writerow({
                        "name": r["name"],
                        "access": r["access"],
                        "value": _format_value(r["value"]),
                        "type": r["type"],
                        "error": r.get("error", ""),
                    })
            self._append_log(f"Exported CSV: {path}", "#006600")
            self._status(f"CSV exported: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_export_json(self) -> None:
        results = self.scanner_tab.get_results()
        if not results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", "halcon_parameters.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            serializable = []
            for r in results:
                val = r.get("value")
                if isinstance(val, (bytes, bytearray)):
                    val = val.decode("utf-8", errors="replace")
                serializable.append({
                    "name": r["name"],
                    "access": r["access"],
                    "value": _format_value(val) if val is not None else None,
                    "type": r["type"],
                    "error": r.get("error", ""),
                })
            with open(path, "w") as f:
                json.dump(serializable, f, indent=2)
            self._append_log(f"Exported JSON: {path}", "#006600")
            self._status(f"JSON exported: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _parse_value(s: str) -> Any:
        s = s.strip()
        if not s:
            return ""
        # Try int
        try:
            return int(s)
        except ValueError:
            pass
        # Try float
        try:
            return float(s)
        except ValueError:
            pass
        # Bool
        if s.lower() in ("true", "false", "1", "0"):
            return s.lower() in ("true", "1")
        # String
        return s

    def _add_history(self, entry: HistoryEntry) -> None:
        self._history.append(entry)
        if len(self._history) > HISTORY_MAX:
            self._history.pop(0)
        self.history_table.add_entry(entry)

    def _clear_history(self) -> None:
        self._history.clear()
        self.history_table.clear_entries()

    def _on_halcon_log(self, direction: str, param: str, value: Any,
                       result: str, detail: str) -> None:
        """Called on every HALCON operation."""
        if direction in ("GET", "SET", "EXECUTE"):
            value_str = _format_value(value) if value is not None else "-"
            if result == "SUCCESS":
                self._append_log(
                    f"{direction} {param} → {value_str}  [{result}]",
                    "#006600"
                )
            else:
                self._append_log(
                    f"{direction} {param}  [{result}] {detail}",
                    "#CC0000"
                )
        else:
            if result == "SUCCESS":
                self._append_log(f"{direction}: {detail if detail else result}", "#004080")
            else:
                self._append_log(f"{direction}: FAILED — {detail}", "#CC0000")

    def _append_log(self, text: str, color: str = "#000000") -> None:
        self.log_view.append_log(text, color)

    # ----------------------------------------------------------
    # Window Events
    # ----------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._stop_live_refresh()
        self._scan_timer.stop()
        self._session.disconnect()
        super().closeEvent(event)


# ==========================================================================
# Entry Point
# ==========================================================================

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Global stylesheet
    app.setStyleSheet("""
        QMainWindow { background-color: #F5F5F5; }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #CCCCCC;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 16px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QPushButton {
            padding: 4px 12px;
            border: 1px solid #BBBBBB;
            border-radius: 3px;
            background-color: #F0F0F0;
        }
        QPushButton:hover {
            background-color: #E0E0E0;
        }
        QLineEdit, QComboBox {
            padding: 3px 6px;
            border: 1px solid #BBBBBB;
            border-radius: 3px;
        }
        QTreeWidget, QTableWidget, QTextEdit {
            border: 1px solid #CCCCCC;
            border-radius: 3px;
            background-color: white;
        }
        QTabWidget::pane {
            border: 1px solid #CCCCCC;
            border-radius: 3px;
            background-color: white;
        }
        QStatusBar {
            background-color: #E8E8E8;
            border-top: 1px solid #CCCCCC;
        }
        QRadioButton {
            spacing: 4px;
        }
    """)

    win = MainWindow()
    win.show()

    # Auto-discover devices on startup
    win._on_discover_devices()

    if _quick_test_param:
        win._append_log(
            f"Quick-test mode: parameter = '{_quick_test_param}'",
            "#CC0000"
        )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
