"""
statistics.py

HALCON-based temperature statistics extraction for ROIs.

This module encapsulates all HALCON operator calls for computing
temperature statistics inside a region. It is the only module
that calls HALCON statistical operators (intensity, min_max_gray)

The flow (Rule 5):
    HRegion + TemperatureImage
        ↓
    reduce_domain
        ↓
    intensity()       → mean, deviation
    min_max_gray()    → min, max
    area_center()     → pixel_count
    threshold + area_center → hotspot coordinates

Error handling (Rule 7):
    If the region is empty or invalid, the function returns
    statistics with valid=False. No exception propagates.
"""

from __future__ import annotations

import time
from datetime import datetime

import halcon as ha
import numpy as np

from roi.runtime import RuntimeROIStatistics


# Type for the temperature image input.
# The pipeline produces this as a numpy ndarray of floats.
TemperatureImage = np.ndarray


def extract_statistics(
    region: ha.HObject,
    temperature_image: TemperatureImage,
    frame_id: int,
) -> RuntimeROIStatistics:
    """
    Extract temperature statistics from an ROI region using HALCON.

    Parameters
    ----------
    region : ha.HRegion
        The cached HALCON region for this ROI.
    temperature_image : np.ndarray
        Full-frame temperature image (float32/float64).
    frame_id : int
        Current frame sequence number for tracing.

    Returns
    -------
    RuntimeROIStatistics
        Filled with HALCON-computed values, or valid=False
        if the region is empty.
    """
    start = time.perf_counter()

    try:
        # ----------------------------------------------------------
        # Convert numpy temperature image to HALCON image
        # ----------------------------------------------------------
        h_image = _numpy_to_himage(temperature_image)

        # ----------------------------------------------------------
        # Reduce domain to the ROI region (Rule 5)
        # ----------------------------------------------------------
        reduced = ha.reduce_domain(h_image, region)

        # ----------------------------------------------------------
        # Pixel count (area)
        # ----------------------------------------------------------
        _stat = ha.area_center(region)
        pixel_count = int(_stat[0][0])

        if pixel_count == 0:
            elapsed = (time.perf_counter() - start) * 1000.0
            return RuntimeROIStatistics(
                valid=False,
                pixel_count=0,
                frame_id=frame_id,
                processing_time_ms=elapsed,
            )

        # ----------------------------------------------------------
        # Mean and standard deviation via HALCON intensity()
        # ----------------------------------------------------------
        _intensity = ha.intensity(region, reduced)

        # ----------------------------------------------------------
        # Min and max via HALCON min_max_gray()
        # ----------------------------------------------------------
        _mmg = ha.min_max_gray(region, reduced, 0)

        # ----------------------------------------------------------
        # Hotspot — pixel with maximum temperature
        #
        # Uses HALCON threshold() to isolate max-temperature pixels,
        # then area_center() to find the hottest point.
        # If the max region has multiple pixels, the center is used.
        # ----------------------------------------------------------
        hotspot_region = ha.threshold(reduced, _mmg[1][0], _mmg[1][0])
        _hotspot = ha.area_center(hotspot_region)

        elapsed = (time.perf_counter() - start) * 1000.0

        return RuntimeROIStatistics(
            valid=True,
            minimum=float(_mmg[0][0]),
            maximum=float(_mmg[1][0]),
            mean=float(_intensity[0][0]),
            standard_deviation=float(_intensity[1][0]),
            hotspot_x=int(round(_hotspot[2][0])),
            hotspot_y=int(round(_hotspot[1][0])),
            pixel_count=pixel_count,
            processing_time_ms=elapsed,
            frame_id=frame_id,
            last_updated=datetime.now(),
        )

    except Exception:
        elapsed = (time.perf_counter() - start) * 1000.0
        return RuntimeROIStatistics(
            valid=False,
            frame_id=frame_id,
            processing_time_ms=elapsed,
        )


def _numpy_to_himage(image: np.ndarray) -> ha.HObject:
    return ha.himage_from_numpy_array(image)