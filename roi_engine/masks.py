"""
masks.py

Cached bbox-limited boolean hotspot masks for the roi_engine package.

Masks are generated ONLY when geometry changes (store generation or image
size) and are reused every frame. Each mask is a boolean array over the
ROI's clamped bounding box: True where the pixel lies inside the ROI
geometry. The statistics engine uses them to restrict the numpy argmax
(hotspot search) to the ROI's pixels.

Rasterization rules (empirically verified against HALCON 24.11, see the
probe scripts documented in the task report):

    - RECTANGLE1: no mask (None) -- the bounding-box slice IS the region.
    - CIRCLE:     pixel-center test, integer pixel grid. HALCON
                  gen_circle rasterizes with pixel centers at integer
                  coordinates (measured error 0.0-0.7%).
    - ELLIPSE:    2x2 supersampled pixel-center test. Empirically HALCON's
                  gen_ellipse places radius1 on the (-sin(phi), cos(phi))
                  axis and radius2 on the (cos(phi), sin(phi)) axis; the
                  2x2 supersample reproduces HALCON's boundary behavior
                  within ~2.4% (measured max over practical geometries).
    - RECTANGLE2: polygon fill of the four corners. HALCON's gen_rectangle2
                  rasterizes length1 on the (-sin(phi), cos(phi)) axis and
                  length2 on the (cos(phi), sin(phi)) axis and matches
                  gen_region_polygon_filled of the corners pixel-wise
                  (measured error ~0.2%).
    - POLYGON:    4x4 supersampled even-odd ray casting (measured error
                  0.3-0.8%, including triangles).

Pure numpy: no HALCON, no GUI. This module must stay importable without
the HALCON runtime.

Contract note: the concrete type stores (Rectangle1Store, ...) are built
by the store package; their geometry array names are read through
type_geometry() with documented fallbacks so this module does not depend
on the exact attribute names of the parallel implementation.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

import numpy as np

from roi_engine.runtime import RuntimeStatsArrays
from roi_engine.types import ALL_SHAPES, ROIShape

logger = logging.getLogger(__name__)

# Sub-pixel sample offsets for the supersampled masks (pixel centers).
# HALCON's gen_ellipse rasterization is closest to a 2x2 supersampled
# pixel-center test (measured max |error| 2.4% over practical geometries),
# so the ellipse uses 2x2. Polygons use 4x4 (measured 0.3-0.8%).
_SUP_OFFSETS_2X2: tuple[float, ...] = (0.25, 0.75)
_SUP_OFFSETS_4X4: tuple[float, ...] = (0.125, 0.375, 0.625, 0.875)

# Canonical geometry field names per shape, with fallback attribute names
# (first existing attribute wins). Kept aligned with the store contract.
_GEOMETRY_FIELDS: dict[ROIShape, tuple[tuple[str, tuple[str, ...]], ...]] = {
    ROIShape.RECTANGLE1: (
        ("row1s", ("rows1",)), ("col1s", ("cols1",)),
        ("row2s", ("rows2",)), ("col2s", ("cols2",)),
    ),
    ROIShape.RECTANGLE2: (
        ("rows", ()), ("cols", ()), ("phis", ()),
        ("length1s", ("lengths1",)), ("length2s", ("lengths2",)),
    ),
    ROIShape.CIRCLE: (("rows", ()), ("cols", ()), ("radii", ())),
    ROIShape.ELLIPSE: (
        ("rows", ()), ("cols", ()), ("phis", ()),
        ("radius1s", ("radii1",)), ("radius2s", ("radii2",)),
    ),
    ROIShape.POLYGON: (("rows", ()), ("cols", ())),
}


class TypeStoreProtocol(Protocol):
    """Minimal type-store surface consumed by the engine caches."""

    shape: ROIShape
    bboxes: np.ndarray
    enabled_indices: np.ndarray
    runtime: RuntimeStatsArrays


class ROIStoreProtocol(Protocol):
    """Minimal ROIStore surface consumed by the engine caches."""

    generation: int

    def store_for(self, shape: ROIShape) -> TypeStoreProtocol | None:
        """Return the type store for a shape, or None if empty."""


def type_geometry(store: TypeStoreProtocol) -> dict[str, object]:
    """
    Read a type store's geometry arrays under canonical field names.

    For POLYGON the "rows"/"cols" values are per-ROI vertex containers
    (lists/arrays of float coordinates); all other fields are arrays
    parallel to the store's roi_ids. Raises AttributeError with the
    expected names if no store attribute matches.
    """
    result: dict[str, object] = {}
    candidates = _GEOMETRY_FIELDS[store.shape]
    for field, alt_names in candidates:
        value: object = None
        for name in (field, *alt_names):
            value = getattr(store, name, None)
            if value is not None:
                result[field] = value
                break
        if field not in result:
            raise AttributeError(
                f"{type(store).__name__} ({store.shape}) is missing geometry "
                f"field {field!r}; expected one of {(field, *alt_names)}"
            )
    return result


def _circle_mask(
    row: float, col: float, radius: float, r0: int, c0: int, r1: int, c1: int
) -> np.ndarray:
    """Boolean mask of the disk over rows [r0, r1] x cols [c0, c1]."""
    rr, cc = np.ogrid[r0 : r1 + 1, c0 : c1 + 1]
    return (rr - row) ** 2 + (cc - col) ** 2 <= radius**2


def _ellipse_mask(
    row: float,
    col: float,
    phi: float,
    radius1: float,
    radius2: float,
    r0: int,
    c0: int,
    r1: int,
    c1: int,
) -> np.ndarray:
    """Supersampled mask of the ellipse in the HALCON axis convention."""
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)
    mask = np.zeros((r1 - r0 + 1, c1 - c0 + 1), dtype=bool)
    for dr in _SUP_OFFSETS_2X2:
        for dc in _SUP_OFFSETS_2X2:
            rr = np.arange(r0, r1 + 1, dtype=np.float64)[:, None] + dr
            cc = np.arange(c0, c1 + 1, dtype=np.float64)[None, :] + dc
            d_r = rr - row
            d_c = cc - col
            rp = -d_r * sin_p + d_c * cos_p
            cp = d_r * cos_p + d_c * sin_p
            mask |= (rp / radius1) ** 2 + (cp / radius2) ** 2 <= 1.0
    return mask


def _rectangle2_mask(
    row: float,
    col: float,
    phi: float,
    length1: float,
    length2: float,
    r0: int,
    c0: int,
    r1: int,
    c1: int,
) -> np.ndarray:
    """Polygon-fill mask of the rotated rectangle (HALCON-compatible)."""
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)
    # Perimeter order in absolute (row, col) space. The rotation mapping
    # (r', c') -> (r, c) is orientation-reversing, so (l1,l2), (l1,-l2),
    # (-l1,l2), (-l1,-l2) would emit a bow-tie; the last two pairs must be
    # emitted as (-l1,-l2), (-l1,l2) to keep the polygon simple.
    corners: list[tuple[float, float]] = []
    for s1, s2 in (
        (length1, length2),
        (length1, -length2),
        (-length1, -length2),
        (-length1, length2),
    ):
        corners.append(
            (
                row + s1 * (-sin_p) + s2 * cos_p,
                col + s1 * cos_p + s2 * sin_p,
            )
        )
    rows = [p[0] for p in corners]
    cols = [p[1] for p in corners]
    return _polygon_mask(rows, cols, r0, c0, r1, c1)


def _polygon_mask(
    rows: object,
    cols: object,
    r0: int,
    c0: int,
    r1: int,
    c1: int,
) -> np.ndarray:
    """Supersampled even-odd ray-casting mask of the polygon."""
    rows_f = [float(v) for v in rows]
    cols_f = [float(v) for v in cols]
    mask = np.zeros((r1 - r0 + 1, c1 - c0 + 1), dtype=bool)
    edge_count = len(rows_f)
    for dr in _SUP_OFFSETS_4X4:
        for dc in _SUP_OFFSETS_4X4:
            rr = np.arange(r0, r1 + 1, dtype=np.float64)[:, None] + dr
            cc = np.arange(c0, c1 + 1, dtype=np.float64)[None, :] + dc
            inside = np.zeros(rr.shape, dtype=bool)
            j = edge_count - 1
            for i in range(edge_count):
                ri, ci = rows_f[i], cols_f[i]
                rj, cj = rows_f[j], cols_f[j]
                cross = (ci > cc) != (cj > cc)
                slope = (rj - ri) * (cc - ci) / (cj - ci + 1e-30) + ri
                inside = np.logical_xor(inside, cross & (rr > slope))
                j = i
            mask |= inside
    return mask


class MaskCache:
    """Cached bbox-limited boolean hotspot masks, rebuilt on geometry change."""

    def __init__(self) -> None:
        self._masks: dict[tuple[ROIShape, int], np.ndarray | None] = {}
        self._origins: dict[tuple[ROIShape, int], tuple[int, int]] = {}
        self._generation: int | None = None
        self._image_shape: tuple[int, int] | None = None
        self._memory_bytes: int = 0

    def rebuild(self, store: ROIStoreProtocol, image_shape: tuple[int, int]) -> None:
        """(Re)build masks for all enabled ROIs from the store snapshot."""
        self._masks.clear()
        self._origins.clear()
        self._memory_bytes = 0
        height = int(image_shape[0])
        width = int(image_shape[1])
        for shape in ALL_SHAPES:
            type_store = store.store_for(shape)
            if type_store is None:
                continue
            geometry = type_geometry(type_store)
            for idx in type_store.enabled_indices:
                key = (shape, int(idx))
                mask, origin = self._build_mask(
                    shape, geometry, idx, type_store.bboxes, height, width
                )
                self._masks[key] = mask
                self._origins[key] = origin
                if mask is not None and mask.size > 0:
                    self._memory_bytes += int(mask.nbytes)
        self._generation = store.generation
        self._image_shape = image_shape

    def needs_rebuild(
        self, store: ROIStoreProtocol, image_shape: tuple[int, int]
    ) -> bool:
        """True when the store generation or the image size changed."""
        return (
            not self._masks
            or self._generation != store.generation
            or self._image_shape != image_shape
        )

    def mask(self, shape: ROIShape, index: int) -> tuple[np.ndarray | None, int, int]:
        """
        Return (mask, bbox_row_min, bbox_col_min) for one enabled ROI.

        Mask None means "whole bounding box" (Rectangle1). Disabled or
        unknown ROIs return (None, 0, 0).
        """
        key = (shape, index)
        if key not in self._masks:
            return None, 0, 0
        origin = self._origins[key]
        return self._masks[key], origin[0], origin[1]

    def memory_bytes(self) -> int:
        """Total bytes held by all masks."""
        return self._memory_bytes

    def clear(self) -> None:
        """Drop all masks and forget the rebuild baseline."""
        self._masks.clear()
        self._origins.clear()
        self._generation = None
        self._image_shape = None
        self._memory_bytes = 0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_mask(
        self,
        shape: ROIShape,
        geometry: dict[str, object],
        index: int,
        bboxes: np.ndarray,
        height: int,
        width: int,
    ) -> tuple[np.ndarray | None, tuple[int, int]]:
        """Build one mask, clamped to the image; (None, (0, 0)) if outside."""
        r_min, c_min, r_max, c_max = (
            int(bboxes[index][0]),
            int(bboxes[index][1]),
            int(bboxes[index][2]),
            int(bboxes[index][3]),
        )
        r0 = max(r_min, 0)
        c0 = max(c_min, 0)
        r1 = min(r_max, height - 1)
        c1 = min(c_max, width - 1)
        if r0 > r1 or c0 > c1:
            return None, (0, 0)
        if shape is ROIShape.RECTANGLE1:
            return None, (r0, c0)

        rows = geometry["rows"]
        cols = geometry["cols"]
        if shape is ROIShape.CIRCLE:
            mask = _circle_mask(
                float(rows[index]),
                float(cols[index]),
                float(geometry["radii"][index]),
                r0, c0, r1, c1,
            )
        elif shape is ROIShape.ELLIPSE:
            mask = _ellipse_mask(
                float(rows[index]),
                float(cols[index]),
                float(geometry["phis"][index]),
                float(geometry["radius1s"][index]),
                float(geometry["radius2s"][index]),
                r0, c0, r1, c1,
            )
        elif shape is ROIShape.RECTANGLE2:
            mask = _rectangle2_mask(
                float(rows[index]),
                float(cols[index]),
                float(geometry["phis"][index]),
                float(geometry["length1s"][index]),
                float(geometry["length2s"][index]),
                r0, c0, r1, c1,
            )
        elif shape is ROIShape.POLYGON:
            mask = _polygon_mask(
                rows[index], cols[index], r0, c0, r1, c1
            )
        else:
            raise ValueError(f"Unsupported ROI shape: {shape}")
        return mask, (r0, c0)
