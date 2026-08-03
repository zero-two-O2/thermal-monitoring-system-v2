"""
store/factory.py

build_store(): group ROIConfigurations by shape and assemble an
immutable ROIStore snapshot with parallel per-type arrays.

The snapshot is immutable: any configuration change requires a new
build_store call (the engine bumps the generation). Runtime arrays are
pre-allocated per type and reused across frames.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Sequence

import numpy as np

from roi.configuration import ROIConfiguration
from roi_engine.store.base import build_common_arrays, geometry_bboxes
from roi_engine.store.circle_store import CircleStore
from roi_engine.store.ellipse_store import EllipseStore
from roi_engine.store.polygon_store import PolygonStore
from roi_engine.store.rectangle1_store import Rectangle1Store
from roi_engine.store.rectangle2_store import Rectangle2Store
from roi_engine.store.roi_store import ROIStore
from roi_engine.types import ALL_SHAPES, ROIShape

logger = logging.getLogger(__name__)

# Canonical geometry array names per shape (see masks.type_geometry).
_SHAPE_STORE = {
    ROIShape.RECTANGLE1: Rectangle1Store,
    ROIShape.RECTANGLE2: Rectangle2Store,
    ROIShape.CIRCLE: CircleStore,
    ROIShape.ELLIPSE: EllipseStore,
    ROIShape.POLYGON: PolygonStore,
}


def _geometry_kwargs(
    shape: ROIShape, configs: Sequence[ROIConfiguration]
) -> dict[str, object]:
    """Extract per-type geometry arrays from configurations."""
    if shape is ROIShape.RECTANGLE1:
        return {
            "row1s": np.array([c.geometry.row1 for c in configs], dtype=np.float64),
            "col1s": np.array([c.geometry.col1 for c in configs], dtype=np.float64),
            "row2s": np.array([c.geometry.row2 for c in configs], dtype=np.float64),
            "col2s": np.array([c.geometry.col2 for c in configs], dtype=np.float64),
        }
    if shape is ROIShape.RECTANGLE2:
        return {
            "rows": np.array([c.geometry.row for c in configs], dtype=np.float64),
            "cols": np.array([c.geometry.col for c in configs], dtype=np.float64),
            "phis": np.array([c.geometry.phi for c in configs], dtype=np.float64),
            "length1s": np.array(
                [c.geometry.length1 for c in configs], dtype=np.float64
            ),
            "length2s": np.array(
                [c.geometry.length2 for c in configs], dtype=np.float64
            ),
        }
    if shape is ROIShape.CIRCLE:
        return {
            "rows": np.array([c.geometry.row for c in configs], dtype=np.float64),
            "cols": np.array([c.geometry.col for c in configs], dtype=np.float64),
            "radii": np.array(
                [c.geometry.radius for c in configs], dtype=np.float64
            ),
        }
    if shape is ROIShape.ELLIPSE:
        return {
            "rows": np.array([c.geometry.row for c in configs], dtype=np.float64),
            "cols": np.array([c.geometry.col for c in configs], dtype=np.float64),
            "phis": np.array([c.geometry.phi for c in configs], dtype=np.float64),
            "radius1s": np.array(
                [c.geometry.radius1 for c in configs], dtype=np.float64
            ),
            "radius2s": np.array(
                [c.geometry.radius2 for c in configs], dtype=np.float64
            ),
        }
    if shape is ROIShape.POLYGON:
        return {
            "rows": [
                np.array([r for r, _ in c.geometry.points], dtype=np.float64)
                for c in configs
            ],
            "cols": [
                np.array([c_ for _, c_ in c.geometry.points], dtype=np.float64)
                for c in configs
            ],
        }
    raise ValueError(f"Unsupported ROI shape: {shape}")


def _valid_configs(
    configurations: Sequence[ROIConfiguration],
) -> list[ROIConfiguration]:
    """
    Filter out configurations whose geometry fails validation.

    Invalid ROIs are skipped with a warning so a single bad ROI cannot
    invalidate the whole position snapshot (same policy as the legacy
    geometry_to_hregion, which raises per-ROI).
    """
    valid: list[ROIConfiguration] = []
    for cfg in configurations:
        try:
            cfg.geometry.validate()
        except ValueError:
            logger.warning(
                "Skipping ROI %s (%s) with invalid geometry for shape %s",
                cfg.roi_id,
                cfg.name,
                cfg.geometry.shape,
                exc_info=True,
            )
            continue
        valid.append(cfg)
    return valid


def build_store(
    camera_id: str,
    position_id: str,
    configurations: Sequence[ROIConfiguration],
    generation: int = 1,
) -> ROIStore:
    """Build an immutable ROIStore snapshot grouped by geometry shape."""
    configurations = _valid_configs(configurations)
    by_shape: dict[ROIShape, list[ROIConfiguration]] = defaultdict(list)
    for cfg in configurations:
        by_shape[cfg.geometry.shape].append(cfg)

    stores: dict[ROIShape, object] = {}
    for shape in ALL_SHAPES:
        configs = by_shape.get(shape, [])
        if not configs:
            continue
        bboxes = geometry_bboxes(configs)
        common = build_common_arrays(shape, configs, bboxes)
        # enabled_indices is recomputed in TypeStoreBase.__post_init__.
        common["enabled_indices"] = np.zeros(0, dtype=np.int64)
        geometry = _geometry_kwargs(shape, configs)
        store_cls = _SHAPE_STORE[shape]
        stores[shape] = store_cls(**geometry, **common)

    return ROIStore(
        camera_id=camera_id,
        position_id=position_id,
        generation=generation,
        _stores=stores,
    )
