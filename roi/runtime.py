"""
runtime.py

Runtime ROI models for the Thermal Monitoring System.

Runtime objects are temporary caches created when a camera
acquisition state becomes active. They are never serialized.

This is Layer 2 of the ROI subsystem (Runtime ROI Cache).

These classes contain ONLY data and lightweight state.
No HALCON region generation, no processing logic, no GUI code.

Layer structure
---------------
RuntimeROI
    configuration : ROIConfiguration   (Layer 1 — persistent data)
    statistics    : RuntimeROIStatistics | None
    state         : RuntimeROIState
    cache         : RuntimeROICache     (HALCON-derived data)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

from roi.configuration import ROIConfiguration
from roi.runtime_cache import RuntimeROICache


class RuntimeROIState(Enum):
    """
    Current runtime state of a cached ROI.

    INACTIVE : Loaded but not yet processed or cached.
    ACTIVE   : Has been processed and has valid statistics.
    ERROR    : Processing failed or region generation failed.
    """

    INACTIVE = auto()
    ACTIVE = auto()
    ERROR = auto()


@dataclass(slots=True)
class RuntimeROIStatistics:
    """
    Latest processing results for one RuntimeROI.

    Produced by the ROI Processor during pipeline execution.
    Replaced on every processing cycle.

    Responsibilities
    ----------------
    - Hold the most recent temperature statistics.
    - Hold processing metadata (frame_id, timing, validity).
    - Hold the current alarm evaluation result.

    Must never:
    - Persist across application restarts.
    - Reference the ROI configuration or geometry.
    - Contain HALCON or GUI code.
    - Accumulate history or trends.

    Notes
    -----
    - `valid` is False when the ROI could not be processed
      (e.g. empty region, invalid frame).
    - `alarm_active` and `alarm_since` are populated by the
      Alarm Processor after evaluation.
    """

    valid: bool = False

    minimum: float = 0.0

    maximum: float = 0.0

    mean: float = 0.0

    standard_deviation: float = 0.0

    hotspot_x: int = -1

    hotspot_y: int = -1

    pixel_count: int = 0

    processing_time_ms: float = 0.0

    frame_id: int = -1

    alarm_active: bool = False

    alarm_since: datetime | None = None

    last_updated: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class RuntimeROI:
    """
    Runtime cache for one ROI.

    Created by RuntimeROIManager when a camera acquisition state
    becomes active. Destroyed when the state changes or the camera
    is deactivated.

    Responsibilities
    ----------------
    - Hold the persistent ROIConfiguration.
    - Hold the cached RuntimeROICache (region, area, bounding box).
    - Hold the latest RuntimeROIStatistics.
    - Hold the current RuntimeROIState.
    - Record creation and update timestamps.

    Must never:
    - Generate HRegions (responsibility of RuntimeROIManager).
    - Process images or calculate statistics.
    - Evaluate alarm conditions.
    - Serialize itself to disk.
    - Reference other RuntimeROI instances.
    - Contain GUI or Drawing Object code.

    Ownership
    ---------
    - Owns its ROIConfiguration reference (read-only during runtime).
    - Owns its RuntimeROICache and RuntimeROIStatistics.
    - Belongs to exactly one RuntimeROIManager at a time.
    """

    configuration: ROIConfiguration

    state: RuntimeROIState = RuntimeROIState.INACTIVE

    statistics: RuntimeROIStatistics | None = None

    cache: RuntimeROICache = field(default_factory=RuntimeROICache)

    last_updated: datetime | None = None

    created_at: datetime = field(default_factory=datetime.now)
