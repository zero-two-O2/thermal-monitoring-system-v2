"""
overlay.py

ROI overlay rendering for observation camera tiles.

ROI outlines, alarm colors, and name labels are drawn directly into
the 8-bit BGR/RGB colormap frame (numpy + cv2) before the tile
displays it. The Observation Window's tiles are plain pixmap labels
without a drawing layer; baking the overlays into the frame keeps the
GUI layout untouched and costs a few cv2 calls per ROI.

Colors follow the design system: normal ROIs use the configured
ROIStyle color (default yellow), alarm ROIs switch to the alarm color
(default red). Geometry-to-pixel mapping is an approximation of the
HALCON convention; the engine's region rasterization remains the
ground truth for statistics.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import cv2
import numpy as np

from roi.geometry import (
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.runtime import RuntimeROI

_LABEL_BACKGROUND_BGR = (32, 32, 32)


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    """Parse "#RRGGBB" (or "RRGGBB") into a BGR tuple."""
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return blue, green, red


def _draw_geometry(frame: np.ndarray, roi: RuntimeROI, color_bgr: tuple[int, int, int]) -> None:
    geometry = roi.configuration.geometry
    line_width = max(1, roi.configuration.style.line_width)
    if isinstance(geometry, Rectangle1ROI):
        cv2.rectangle(
            frame,
            (int(geometry.col1), int(geometry.row1)),
            (int(geometry.col2), int(geometry.row2)),
            color_bgr,
            line_width,
        )
    elif isinstance(geometry, CircleROI):
        cv2.circle(
            frame,
            (int(geometry.col), int(geometry.row)),
            int(geometry.radius),
            color_bgr,
            line_width,
        )
    elif isinstance(geometry, EllipseROI):
        # HALCON phi (radians, row-axis convention) approximated as a
        # cv2 angle: columns/rows map to x/y, so swap the radii.
        angle_deg = -math.degrees(geometry.phi)
        cv2.ellipse(
            frame,
            (int(geometry.col), int(geometry.row)),
            (int(geometry.radius2), int(geometry.radius1)),
            angle_deg,
            0.0,
            360.0,
            color_bgr,
            line_width,
        )
    elif isinstance(geometry, Rectangle2ROI):
        # Half-lengths in row/col space: cv2 expects (width, height).
        box = cv2.boxPoints(
            (
                (float(geometry.col), float(geometry.row)),
                (float(geometry.length2) * 2.0, float(geometry.length1) * 2.0),
                -math.degrees(geometry.phi),
            )
        )
        cv2.polylines(
            frame,
            [np.int32(box)],
            isClosed=True,
            color=color_bgr,
            thickness=line_width,
        )
    elif isinstance(geometry, PolygonROI):
        points = np.int32([(c, r) for r, c in geometry.points])
        cv2.polylines(
            frame,
            [points],
            isClosed=True,
            color=color_bgr,
            thickness=line_width,
        )


def _draw_label(
    frame: np.ndarray,
    roi: RuntimeROI,
    color_bgr: tuple[int, int, int],
) -> None:
    if not roi.configuration.style.label_visible or not roi.configuration.name:
        return
    row_min, col_min, _, _ = roi.configuration.geometry.bounding_box()
    text = roi.configuration.name
    scale = max(0.3, roi.configuration.style.label_size / 32.0)
    thickness = 1
    (text_w, text_h), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
    )
    height, width = frame.shape[:2]
    label_col = min(max(int(col_min), 0), max(width - text_w, 0))
    label_row = min(max(int(row_min) - text_h - baseline - 2, 0), max(height - text_h - baseline, 0))
    cv2.rectangle(
        frame,
        (label_col, label_row),
        (label_col + text_w + 4, label_row + text_h + baseline + 2),
        _LABEL_BACKGROUND_BGR,
        -1,
    )
    cv2.putText(
        frame,
        text,
        (label_col + 2, label_row + text_h),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color_bgr,
        thickness,
        cv2.LINE_AA,
    )


def draw_roi_overlays(
    frame: np.ndarray,
    rois: Sequence[RuntimeROI],
    alarm_roi_ids: Iterable[str] = (),
) -> np.ndarray:
    """Draw ROI outlines and labels into an 8-bit 3-channel frame.

    Draws in place (the caller passes the fresh colormap output) and
    returns the same array. Hidden ROIs are skipped; ROIs whose id is
    in ``alarm_roi_ids`` use the alarm color.
    """
    alarm_ids = set(alarm_roi_ids)
    for roi in rois:
        if not roi.configuration.visible:
            continue
        style = roi.configuration.style
        color = _hex_to_bgr(style.alarm_color if roi.configuration.roi_id in alarm_ids else style.color)
        _draw_geometry(frame, roi, color)
        _draw_label(frame, roi, color)
    return frame
