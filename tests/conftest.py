"""
Shared fixtures and helpers for the roi_engine test suites.

The roi_engine store subpackage is built in parallel by another agent;
until its files land, importing the package fails. _ensure_roi_engine_modules()
falls back to loading the modules this test suite needs directly from
their files under their real dotted names (with stub packages), so
internal imports keep working. Once the parallel files exist, the
normal import path is used.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import numpy as np

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_ROI_ENGINE_MODULES: tuple[tuple[str, str], ...] = (
    ("roi_engine.types", "roi_engine/types.py"),
    ("roi_engine.runtime", "roi_engine/runtime.py"),
    ("roi_engine.store.base", "roi_engine/store/base.py"),
    ("roi_engine.masks", "roi_engine/masks.py"),
    ("roi_engine.region_cache", "roi_engine/region_cache.py"),
    ("roi_engine.statistics_engine", "roi_engine/statistics_engine.py"),
)


def _ensure_roi_engine_modules() -> None:
    """Import the roi_engine modules, with a direct file-loading fallback."""
    try:
        from roi_engine.masks import MaskCache  # noqa: F401

        return
    except ImportError:
        pass
    for package, rel_path in (
        ("roi_engine", "roi_engine"),
        ("roi_engine.store", "roi_engine/store"),
    ):
        stub = types.ModuleType(package)
        stub.__path__ = [_REPO_ROOT / rel_path]
        stub.__package__ = package
        sys.modules[package] = stub
    for name, rel_path in _ROI_ENGINE_MODULES:
        if name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            name, _REPO_ROOT / rel_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {name} from {rel_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


_ensure_roi_engine_modules()

from roi.acquisition_state import AcquisitionState  # noqa: E402
from roi.alarm_settings import ROIAlarmSettings  # noqa: E402
from roi.configuration import ROIConfiguration  # noqa: E402
from roi.geometry import (  # noqa: E402
    CircleROI,
    EllipseROI,
    PolygonROI,
    Rectangle1ROI,
    Rectangle2ROI,
)
from roi.recording_settings import ROIRecordingSettings  # noqa: E402
from roi.types import ROIShape  # noqa: E402
from roi_engine.store.base import (  # noqa: E402
    TypeStoreBase,
    build_common_arrays,
    geometry_bboxes,
)


class _TypeStore(TypeStoreBase):
    """TypeStoreBase that carries geometry arrays as plain attributes."""


class _ROIStore:
    """Minimal ROIStore contract used by the roi_engine tests."""

    def __init__(
        self,
        stores: dict[ROIShape, TypeStoreBase],
        generation: int = 1,
    ) -> None:
        self._stores = dict(stores)
        self.generation = generation

    def store_for(self, shape: ROIShape) -> TypeStoreBase | None:
        """Type store for a shape, or None when the type is empty."""
        return self._stores.get(shape)

    def roi_index(self) -> dict[ROIShape, list[str]]:
        """ROI ids per type, in store order."""
        return {
            shape: list(store.roi_ids)
            for shape, store in self._stores.items()
        }

    def total_roi_count(self) -> int:
        """Total configured ROIs across all types."""
        return sum(store.count for store in self._stores.values())

    def enabled_roi_count(self) -> int:
        """Total enabled ROIs across all types."""
        return sum(
            int(store.enabled_indices.size)
            for store in self._stores.values()
        )

    def memory_bytes(self) -> int:
        """Approximate memory footprint of all type stores."""
        return sum(store.memory_bytes() for store in self._stores.values())

    def empty(self) -> bool:
        """True when no ROIs are configured."""
        return not self._stores


def make_config(
    roi_id: str,
    geometry: CircleROI | EllipseROI | PolygonROI | Rectangle1ROI | Rectangle2ROI,
    enabled: bool = True,
) -> ROIConfiguration:
    """Build an ROIConfiguration with default style/alarm/recording."""
    return ROIConfiguration(
        roi_id=roi_id,
        name=f"roi_{roi_id}",
        acquisition_state=AcquisitionState(camera_id="cam_1", pan=0),
        geometry=geometry,
        enabled=enabled,
        visible=True,
        alarm=ROIAlarmSettings(),
        recording=ROIRecordingSettings(),
    )


def _attach_geometry(store: _TypeStore, configs: list[ROIConfiguration]) -> None:
    """Populate the geometry arrays of a test type store from configs."""
    geoms = [cfg.geometry for cfg in configs]
    shape = store.shape
    if shape is ROIShape.RECTANGLE1:
        store.row1s = np.array([g.row1 for g in geoms], dtype=np.float64)
        store.col1s = np.array([g.col1 for g in geoms], dtype=np.float64)
        store.row2s = np.array([g.row2 for g in geoms], dtype=np.float64)
        store.col2s = np.array([g.col2 for g in geoms], dtype=np.float64)
    elif shape is ROIShape.CIRCLE:
        store.rows = np.array([g.row for g in geoms], dtype=np.float64)
        store.cols = np.array([g.col for g in geoms], dtype=np.float64)
        store.radii = np.array([g.radius for g in geoms], dtype=np.float64)
    elif shape is ROIShape.ELLIPSE:
        store.rows = np.array([g.row for g in geoms], dtype=np.float64)
        store.cols = np.array([g.col for g in geoms], dtype=np.float64)
        store.phis = np.array([g.phi for g in geoms], dtype=np.float64)
        store.radius1s = np.array([g.radius1 for g in geoms], dtype=np.float64)
        store.radius2s = np.array([g.radius2 for g in geoms], dtype=np.float64)
    elif shape is ROIShape.RECTANGLE2:
        store.rows = np.array([g.row for g in geoms], dtype=np.float64)
        store.cols = np.array([g.col for g in geoms], dtype=np.float64)
        store.phis = np.array([g.phi for g in geoms], dtype=np.float64)
        store.length1s = np.array([g.length1 for g in geoms], dtype=np.float64)
        store.length2s = np.array([g.length2 for g in geoms], dtype=np.float64)
    elif shape is ROIShape.POLYGON:
        store.rows = [np.asarray(g.rows, dtype=np.float64) for g in geoms]
        store.cols = [np.asarray(g.cols, dtype=np.float64) for g in geoms]
    else:
        raise ValueError(f"Unsupported ROI shape: {shape}")


def build_test_store(
    configs: list[ROIConfiguration],
    generation: int = 1,
) -> _ROIStore:
    """Build a type-array ROI store from configurations (test contract)."""
    by_shape: dict[ROIShape, list[ROIConfiguration]] = {}
    for cfg in configs:
        by_shape.setdefault(cfg.geometry.shape, []).append(cfg)
    stores: dict[ROIShape, TypeStoreBase] = {}
    for shape, shape_configs in by_shape.items():
        bboxes = geometry_bboxes(shape_configs)
        common = build_common_arrays(shape, shape_configs, bboxes)
        common["enabled_indices"] = np.nonzero(common["enabled"])[0]
        store = _TypeStore(**common)
        _attach_geometry(store, shape_configs)
        stores[shape] = store
    return _ROIStore(stores, generation=generation)


def synthetic_image(height: int = 480, width: int = 640) -> np.ndarray:
    """
    Deterministic float32 image: 20.0 base plus a strictly monotone
    gradient in both axes, so every region's maximum is at its
    bottom-right-most pixel.
    """
    rows = np.arange(height, dtype=np.float32)
    cols = np.arange(width, dtype=np.float32)
    return 20.0 + rows[:, None] * 0.05 + cols[None, :] * 0.03
