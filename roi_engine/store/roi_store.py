"""
store/roi_store.py

Immutable per-camera-per-position snapshot of all type stores.

An ROIStore is built once by build_store() and never mutated after
construction; any configuration change requires a new snapshot with a
bumped generation. Consumers use store_for() to reach the per-type
parallel arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from roi_engine.types import ALL_SHAPES, ROIShape

if TYPE_CHECKING:
    from roi_engine.store.base import TypeStoreBase


@dataclass(frozen=True, slots=True)
class ROIStore:
    """Immutable snapshot: one TypeStoreBase per ROI shape."""

    camera_id: str
    position_id: str
    generation: int
    _stores: dict[ROIShape, TypeStoreBase] = field(
        default_factory=dict, compare=False, repr=False
    )
    _index: dict[str, tuple[ROIShape, int]] = field(
        init=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        """Freeze the per-type dict and precompute the roi index."""
        frozen = dict(self._stores)
        object.__setattr__(self, "_stores", frozen)
        index: dict[str, tuple[ROIShape, int]] = {}
        for shape in ALL_SHAPES:
            type_store = frozen.get(shape)
            if type_store is None:
                continue
            for i, roi_id in enumerate(type_store.roi_ids):
                index[roi_id] = (shape, i)
        object.__setattr__(self, "_index", index)

    def store_for(self, shape: ROIShape) -> TypeStoreBase | None:
        """Type store for a shape, or None when it has no ROIs."""
        return self._stores.get(shape)

    def roi_index(self) -> dict[str, tuple[ROIShape, int]]:
        """Map roi_id -> (shape, store index)."""
        return dict(self._index)

    def total_roi_count(self) -> int:
        """Number of ROIs in this snapshot (all shapes)."""
        return sum(s.count for s in self._stores.values())

    def enabled_roi_count(self) -> int:
        """Number of enabled ROIs in this snapshot."""
        return sum(s.enabled_count() for s in self._stores.values())

    def memory_bytes(self) -> int:
        """Approximate memory footprint of all type stores."""
        return sum(s.memory_bytes() for s in self._stores.values())

    def empty(self) -> bool:
        """True when the snapshot contains no ROIs at all."""
        return self.total_roi_count() == 0
