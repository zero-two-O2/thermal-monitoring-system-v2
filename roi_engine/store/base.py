"""
store/base.py

Base class for per-type ROI stores (parallel arrays).

A TypeStoreBase holds the common metadata arrays shared by every
geometry type. Concrete subclasses add the geometry arrays.

Immutability contract
---------------------
Config arrays (geometry, metadata, bboxes) are set read-only after
building. The store is an immutable snapshot: any configuration change
requires rebuilding the whole store (atomic reference swap). This makes
array-vs-object index drift structurally impossible.

Runtime arrays (`runtime`) stay writeable — the statistics engine
overwrites them every frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from roi.alarm_settings import ROIAlarmCondition
from roi.configuration import ROIConfiguration
from roi_engine.runtime import RuntimeStatsArrays
from roi_engine.types import ROIShape


@dataclass(slots=True)
class TypeStoreBase:
    """Common metadata arrays shared by all geometry types."""

    shape: ROIShape
    roi_ids: list[str]
    names: list[str]
    position_ids: list[str]
    enabled: np.ndarray
    visible: np.ndarray
    alarm_enabled: np.ndarray
    alarm_condition: np.ndarray
    alarm_threshold: np.ndarray
    alarm_hysteresis: np.ndarray
    alarm_delay_ms: np.ndarray
    bboxes: np.ndarray
    enabled_indices: np.ndarray
    runtime: RuntimeStatsArrays = field(compare=False)
    count: int = 0

    def __post_init__(self) -> None:
        """Derive count and enabled indices; freeze config arrays."""
        self.count = len(self.roi_ids)
        self.enabled_indices = np.nonzero(self.enabled)[0]
        self._freeze_config_arrays()

    def _freeze_config_arrays(self) -> None:
        """Make config arrays read-only so drift is impossible."""
        for arr in (
            self.enabled, self.visible, self.alarm_enabled,
            self.alarm_condition, self.alarm_threshold,
            self.alarm_hysteresis, self.alarm_delay_ms, self.bboxes,
        ):
            arr.setflags(write=False)

    def enabled_count(self) -> int:
        """Number of enabled ROIs in this store."""
        return int(self.enabled_indices.size)

    def memory_bytes(self) -> int:
        """Approximate memory footprint of config + runtime arrays."""
        config_bytes = sum(
            a.nbytes for a in (
                self.enabled, self.visible, self.alarm_enabled,
                self.alarm_condition, self.alarm_threshold,
                self.alarm_hysteresis, self.alarm_delay_ms, self.bboxes,
            )
        )
        return config_bytes + self.runtime.memory_bytes()


def build_common_arrays(
    shape: ROIShape,
    configs: Sequence[ROIConfiguration],
    bboxes: np.ndarray,
) -> dict[str, object]:
    """
    Build the common metadata arrays from ROI configurations.

    Returns a dict of keyword arguments suitable for TypeStoreBase
    construction. `bboxes` must be an int64 (n, 4) array with
    (row_min, col_min, row_max, col_max) per ROI, derived from the
    geometry bounding box.
    """
    roi_ids: list[str] = []
    names: list[str] = []
    position_ids: list[str] = []
    enabled = np.zeros(len(configs), dtype=bool)
    visible = np.zeros(len(configs), dtype=bool)
    alarm_enabled = np.zeros(len(configs), dtype=bool)
    alarm_condition = np.zeros(len(configs), dtype=np.int64)
    alarm_threshold = np.zeros(len(configs), dtype=np.float64)
    alarm_hysteresis = np.zeros(len(configs), dtype=np.float64)
    alarm_delay_ms = np.zeros(len(configs), dtype=np.int64)

    for i, cfg in enumerate(configs):
        roi_ids.append(cfg.roi_id)
        names.append(cfg.name)
        position_ids.append(cfg.acquisition_state.position_id)
        enabled[i] = cfg.enabled
        visible[i] = cfg.visible
        alarm_enabled[i] = cfg.alarm.enabled
        alarm_condition[i] = int(cfg.alarm.condition.value)
        alarm_threshold[i] = cfg.alarm.value
        alarm_hysteresis[i] = cfg.alarm.hysteresis
        alarm_delay_ms[i] = cfg.alarm.delay_ms

    return {
        "shape": shape,
        "roi_ids": roi_ids,
        "names": names,
        "position_ids": position_ids,
        "enabled": enabled,
        "visible": visible,
        "alarm_enabled": alarm_enabled,
        "alarm_condition": alarm_condition,
        "alarm_threshold": alarm_threshold,
        "alarm_hysteresis": alarm_hysteresis,
        "alarm_delay_ms": alarm_delay_ms,
        "bboxes": bboxes,
        "runtime": RuntimeStatsArrays.empty(len(configs)),
        "count": len(configs),
    }


def geometry_bboxes(configs: Sequence[ROIConfiguration]) -> np.ndarray:
    """
    Compute integer bounding boxes from geometry for a config list.

    Uses the exact geometry bounding_box() math (never HALCON
    smallest_rectangle1, which is ~30x slower per call in batch).
    """
    bboxes = np.zeros((len(configs), 4), dtype=np.int64)
    for i, cfg in enumerate(configs):
        r_min, c_min, r_max, c_max = cfg.geometry.bounding_box()
        bboxes[i] = (
            int(round(r_min)), int(round(c_min)),
            int(round(r_max)), int(round(c_max)),
        )
    return bboxes


def alarm_condition_enum() -> dict[int, ROIAlarmCondition]:
    """Map condition code -> enum, for engine consumers."""
    return {c.value: c for c in ROIAlarmCondition}
