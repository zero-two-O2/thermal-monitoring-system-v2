"""
roi_engine package.

Production batched ROI processing engine (MVTec type-array architecture).

This package is a parallel implementation that does NOT modify the legacy
roi/ pipeline or the GUI. It depends only on the legacy *models*:
    - roi.types.ROIShape
    - roi.configuration.ROIConfiguration
    - roi.geometry.* (read-only)
    - roi.acquisition_state.AcquisitionState
    - roi.alarm_settings.ROIAlarmSettings / ROIAlarmCondition

Public API
----------
    ROIEngine                — per-camera engine facade (multi-camera ready)
    ROIEnginePool            — camera_id -> ROIEngine registry
    ROIEngineManager         — GUI-facing adapter (runtime manager facade)
    ROIStore / build_store   — immutable type-array configuration snapshot
    StatisticsEngine         — pure batch HALCON statistics (no GUI/Qt/window)
    RegionCache              — per-type cached HALCON region tuples
    MaskCache                — cached bbox-limited hotspot masks
    FrameStats / TypeFrameStats / RuntimeStatsArrays — per-frame results
"""

from __future__ import annotations

from roi_engine.engine import ROIEngine, ROIEnginePool
from roi_engine.integration import ROIEngineManager
from roi_engine.masks import MaskCache
from roi_engine.region_cache import RegionCache
from roi_engine.runtime import FrameStats, RuntimeStatsArrays, TypeFrameStats
from roi_engine.statistics_engine import StatisticsEngine
from roi_engine.store.factory import build_store
from roi_engine.store.roi_store import ROIStore
from roi_engine.types import ALL_SHAPES, BBox, ROIShape

__all__ = [
    "ALL_SHAPES",
    "BBox",
    "ROIShape",
    "ROIStore",
    "build_store",
    "RegionCache",
    "MaskCache",
    "StatisticsEngine",
    "ROIEngine",
    "ROIEnginePool",
    "ROIEngineManager",
    "FrameStats",
    "TypeFrameStats",
    "RuntimeStatsArrays",
]
