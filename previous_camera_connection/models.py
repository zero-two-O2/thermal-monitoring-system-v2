"""
models.py

Data models used throughout the Thermal SDK.

Author : Shubham
"""

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


# ======================================================================
# Universe Segment
# ======================================================================

@dataclass
class UniverseSegment:
    """
    One inverse polynomial calibration segment.

    Temperature = f(Raw Power)
    """

    u0: float
    u1: float
    u2: float

    start_temp: float
    end_temp: float

    def contains(self, temperature: float) -> bool:
        """Return True if the temperature belongs to this segment."""
        return self.start_temp <= temperature <= self.end_temp


# ======================================================================
# Calibration Range
# ======================================================================

@dataclass
class CalibrationRange:
    """
    One calibration range.

    Example:
        Range 0 : -20°C -> 80°C
        Range 1 : -20°C -> 1200°C
        Range 2 : -20°C -> 3000°C
    """

    calibration_min: float
    calibration_max: float

    display_min: float
    display_max: float

    manual_palette_span: float
    auto_palette_span: float

    num_segments: int

    segments: List[UniverseSegment] = field(default_factory=list)

    def __str__(self):

        return (
            f"{self.calibration_min:.1f}°C -> "
            f"{self.calibration_max:.1f}°C "
            f"({self.num_segments} Segments)"
        )


# ======================================================================
# Camera Calibration
# ======================================================================

@dataclass
class CameraCalibration:
    """
    Complete camera calibration information.
    """

    #
    # Header Information
    #
    magic: int = 0

    enabled_ranges: int = 0

    enabled_mask: int = 0

    calibration_date: str = ""

    #
    # Calibration Ranges
    #
    ranges: List[CalibrationRange] = field(default_factory=list)

    #
    # Lookup Tables
    #
    # Key:
    #   0 = Range 0
    #   1 = Range 1
    #   2 = Range 2
    #
    lookup_tables: Dict[int, np.ndarray] = field(default_factory=dict)

    def get_range(self, index: int) -> CalibrationRange:
        """Return one calibration range."""
        return self.ranges[index]

    def set_lookup_table(self, range_index: int, lut: np.ndarray):
        """Store a LUT for a calibration range."""
        self.lookup_tables[range_index] = lut

    def get_lookup_table(self, range_index: int):
        """Return LUT for the specified range."""
        return self.lookup_tables.get(range_index, None)
    
    def lookup_temperature(self,
                        raw: int,
                        range_index: int = 0):

        lut = self.get_lookup_table(range_index)

        if lut is None:
            raise RuntimeError("Lookup table has not been built.")

        return float(lut[raw])

    def has_lookup_table(self, range_index: int) -> bool:
        """Check whether a LUT exists for the specified range."""
        return range_index in self.lookup_tables
    
# ======================================================================
# Camera Information
# ======================================================================

@dataclass
class CameraInfo:
    """
    Information about one detected GigE camera.
    """

    device: str
    serial: str
    model: str
    vendor: str
    ip: str
    interface: str
    status: str

    def __str__(self):

        return (
            f"{self.model} | "
            f"SN={self.serial} | "
            f"IP={self.ip}"
        )