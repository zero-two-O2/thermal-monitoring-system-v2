"""
roi_processor.py

ROI processing engine.

Responsibilities
----------------
- ROI management
- ROI mask cache
- ROI processing
- Statistics calculation
"""

from __future__ import annotations
from typing import Dict
import cv2
import numpy as np
from processing.models.roi_models import (
    ROI,
    ROIResult,
    ROIType,
    ROIStatistics,
    AlarmCondition,
)

from processing.models.processing_models import (
    ProcessedFrame,
)
from utilities import logger


class ROIProcessor:
    """
    Region Of Interest processing engine.
    """
    def __init__(self) -> None:
        
        # ROI configuration
        
        self._rois: Dict[str, ROI] = {}
        
        # Cached masks
        
        self._mask_cache: Dict[str, np.ndarray] = {}
        
        # Image size used when masks were built
        
        self._mask_size: tuple[int, int] | None = None

    # ==========================================================
    # ROI Management
    # ==========================================================

    def load(
        self,
        rois: list[ROI],
    ) -> None:
        """
        Load ROI configuration.
        """
        self.clear()
        for roi in rois:
            self._rois[roi.roi_id] = roi
        logger.info(
            f"Loaded {len(rois)} ROIs."
        )
    def add_roi(
        self,
        roi: ROI,
    ) -> None:
        self._rois[roi.roi_id] = roi
        self.invalidate_cache()
    def remove_roi(
        self,
        roi_id: str,
    ) -> None:
        if roi_id in self._rois:
            del self._rois[roi_id]
        self.invalidate_cache()

    def update_roi(
        self,
        roi: ROI,
    ) -> None:
        self._rois[roi.roi_id] = roi
        self.invalidate_cache()

    def clear(
        self,
    ) -> None:
        self._rois.clear()
        self.invalidate_cache()

    # ==========================================================
    # Processing
    # ==========================================================

    def process(
        self,
        frame: ProcessedFrame,
    ) -> list[ROIResult]:
        """
        Process all enabled ROIs.
        """
        image = frame.temperature_image
        if image is None:
            return []
        self._ensure_masks(
            image.shape
        )
        results: list[ROIResult] = []
        for roi in self._rois.values():
            if not roi.enabled:
                continue
            mask = self._mask_cache.get(
                roi.roi_id
            )
            if mask is None:
                continue
            result = self._process_roi(
                roi,
                image,
                mask,
            )
            results.append(
                result
            )
        return results

    # ==========================================================
    # Cache
    # ==========================================================

    def invalidate_cache(
        self,
    ) -> None:
        self._mask_cache.clear()
        self._mask_size = None

    def _ensure_masks(
        self,
        image_shape: tuple[int, int],
    ) -> None:
        if (
            self._mask_size == image_shape
            and
            len(self._mask_cache) == len(self._rois)
        ):
            return
        logger.info(
            "Building ROI mask cache..."
        )
        self._mask_cache.clear()
        self._mask_size = image_shape
        for roi in self._rois.values():
            self._mask_cache[roi.roi_id] = (
                self._build_mask(
                    roi,
                    image_shape,
                )
            )
        logger.info(
            f"Cached {len(self._mask_cache)} ROI masks."
        )

        # ==========================================================
    # Mask Builder
    # ==========================================================

    def _build_mask(
        self,
        roi: ROI,
        image_shape: tuple[int, int],
    ) -> np.ndarray:
        """
        Build a binary mask for one ROI.
        """
        height, width = image_shape
        mask = np.zeros(
            (height, width),
            dtype=np.uint8,
        )
        if roi.roi_type == ROIType.RECTANGLE:
            self._draw_rectangle(
                mask,
                roi,
            )
        elif roi.roi_type == ROIType.POLYGON:
            self._draw_polygon(
                mask,
                roi,
            )
        elif roi.roi_type == ROIType.CIRCLE:
            self._draw_circle(
                mask,
                roi,
            )
        return mask.astype(bool)

    # ==========================================================
    # Rectangle
    # ==========================================================

    @staticmethod
    def _draw_rectangle(
        mask: np.ndarray,
        roi: ROI,
    ) -> None:
        """
        Draw a filled rectangle.
        """
        if len(roi.points) != 2:
            return
        (x1, y1), (x2, y2) = roi.points
        cv2.rectangle(
            mask,
            (int(x1), int(y1)),
            (int(x2), int(y2)),
            255,
            thickness=-1,
        )

    # ==========================================================
    # Polygon
    # ==========================================================

    @staticmethod
    def _draw_polygon(
        mask: np.ndarray,
        roi: ROI,
    ) -> None:
        """
        Draw a filled polygon.
        """
        if len(roi.points) < 3:
            return
        polygon = np.asarray(
            roi.points,
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        cv2.fillPoly(
            mask,
            [polygon],
            255,
        )

    # ==========================================================
    # Circle
    # ==========================================================

    @staticmethod
    def _draw_circle(
        mask: np.ndarray,
        roi: ROI,
    ) -> None:
        """
        Draw a filled circle.
        """

        if len(roi.points) != 1:

            return

        center = (

            int(roi.points[0][0]),

            int(roi.points[0][1]),

        )

        radius = int(
            roi.radius
        )

        if radius <= 0:

            return

        cv2.circle(

            mask,

            center,

            radius,

            255,

            thickness=-1,

        )

    # ==========================================================
    # Utilities
    # ==========================================================

    @staticmethod
    def _mask_pixel_count(
        mask: np.ndarray,
    ) -> int:
        """
        Number of pixels inside the ROI.
        """

        return int(
            np.count_nonzero(mask)
        )
        # ==========================================================
    # ROI Processing
    # ==========================================================

    def _process_roi(
        self,
        roi: ROI,
        image: np.ndarray,
        mask: np.ndarray,
    ) -> ROIResult:
        """
        Process one ROI.
        """

        values = image[mask]

        values = values[np.isfinite(values)]

        if values.size == 0:

            statistics = ROIStatistics()

            return ROIResult(

                roi=roi,

                statistics=statistics,

            )

        #
        # Statistics
        #

        minimum = float(values.min())

        maximum = float(values.max())

        mean = float(values.mean())

        median = float(np.median(values))

        standard_deviation = float(values.std())

        #
        # Hotspot
        #

        hotspot_x, hotspot_y = self._find_hotspot(

            image,

            mask,

        )

        statistics = ROIStatistics(

            minimum=minimum,

            maximum=maximum,

            mean=mean,

            median=median,

            standard_deviation=standard_deviation,

            hotspot_x=hotspot_x,

            hotspot_y=hotspot_y,

            pixel_count=values.size,

        )

        alarm_active = self._check_alarm(

            roi,

            statistics,

        )

        return ROIResult(

            roi=roi,

            statistics=statistics,

            alarm_active=alarm_active,

        )

    # ==========================================================
    # Hotspot
    # ==========================================================

    @staticmethod
    def _find_hotspot(
        image: np.ndarray,
        mask: np.ndarray,
    ) -> tuple[int, int]:
        """
        Return coordinates of the hottest pixel
        inside the ROI.
        """

        rows, cols = np.where(mask)

        if rows.size == 0:

            return -1, -1

        temperatures = image[rows, cols]

        temperatures = np.nan_to_num(

            temperatures,

            nan=-np.inf,

        )

        hottest = int(

            np.argmax(temperatures)

        )

        return (

            int(cols[hottest]),

            int(rows[hottest]),

        )

    # ==========================================================
    # Alarm Evaluation
    # ==========================================================

    @staticmethod
    def _check_alarm(
        roi: ROI,
        statistics: ROIStatistics,
    ) -> bool:
        """
        Simple alarm evaluation.

        Advanced alarm logic will be moved to
        AlarmProcessor.
        """

        alarm = roi.alarm

        if not alarm.enabled:

            return False

        if alarm.condition == AlarmCondition.HIGH:

            return (

                statistics.maximum

                >=

                alarm.value

            )

        elif alarm.condition == AlarmCondition.LOW:

            return (

                statistics.minimum

                <=

                alarm.value

            )

        elif alarm.condition == AlarmCondition.RANGE:

            return (

                statistics.minimum

                <

                alarm.value

                or

                statistics.maximum

                >

                alarm.value

            )

        return False
