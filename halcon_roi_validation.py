"""
halcon_roi_validation.py

ROI Calibration & Performance Prototype
=======================================

This file was originally a HALCON Drawing Object validation tool.
It is now a **standalone architecture prototype** for the batched ROI
processing engine recommended by MVTec.

Goal
----
Validate, in isolation, the architectural decisions that the production
ROI Engine (`roi_engine/`) is built around, before anything is merged:

- batched ROI processing (one operator call per geometry type)
- grouped, type-array ROI storage (parallel tuples, not objects)
- high ROI counts (50 .. 2000)
- the camera calibration workflow (raw -> temperature -> display)
- statistics correctness (HALCON batch vs. numpy reference)
- GUI usability for an engineering operator

This prototype is intentionally *not* wired into the production
application. It imports production camera + calibration code only
(camera layer and calibration subsystem). It must never import:

- `roi_engine.*`       (the production batch engine)
- `roi.*`              (legacy ROI runtime / configuration classes)
- `gui.calibration.*`  (Calibration Window)
- `gui.observer.*`     (Observation Window)
- any other production ROI class or window

If a decision made here is accepted, the same behaviour is reproduced
inside `roi_engine/`; the prototype is thrown away or becomes a
regression test fixture.

----------------------------------------------------------------------------
Architecture (as implemented)
----------------------------------------------------------------------------

1. Grouped ROI storage ..................... GroupedROIStorage
2. Cached region objects ................... RegionCache
3. Batched statistics ..................... . StatisticsEngine
4. Threshold alarm ......................... AlarmEngine
5. Editing bridge .......................... drawing-object polling
6. Frame pipeline .......................... _process_frame()
7. Display / interaction ................... ThermalView
8. Benchmark ............................... _run_benchmark()

----------------------------------------------------------------------------
1. Grouped ROI storage
----------------------------------------------------------------------------

ROIs are no longer individual `_draw_objects`. They live in parallel
lists grouped by geometry type, exactly as recommended by MVTec:

    Rectangle1:  row1[]  col1[]  row2[]  col2[]
                 + name[], enabled[], visible[], threshold[], color[],
                   drawing_object[]
    Rectangle2:  row[]   col[]   phi[]   length1[]  length2[]
    Circle:      row[]   col[]   radius[]
    Ellipse:     row[]   col[]   phi[]   radius1[]  radius2[]
    Polygon:     points[]                                   (one [rows, cols] pair per ROI)

The GUI can still display ROIs individually (ROI table). Internally
the arrays are the source of truth.

2. Drawing objects are ONLY for editing
---------------------------------------

A drawing object is a transient editing tool. It is created for the
selected ROI, used to drag/resize, then detached and destroyed. It is
never read for statistics.

HALCON Python 24.11 `set_drawing_object_callback` only accepts integer
callback IDs; Python callables are rejected
(`HTupleConversionError`). A `QTimer` therefore polls the active
drawing object's geometry (every EDIT_POLL_MS) and synchronises any
change back into the grouped arrays immediately. Statistics geometry
always comes from the cached arrays, never from drawing objects.

3. Cached HALCON regions (RegionCache)
--------------------------------------

After any geometry mutation (create/move/resize/delete/load) the
affected type is marked dirty. The next access regenerates that type's
region tuple with ONE batched operator call:

    ha.gen_rectangle1(row1[], col1[], row2[], col2[])   # one call, N regions
    ha.gen_rectangle2(row[], col[], phi[], l1[], l2[])
    ha.gen_circle(row[], col[], radius[])
    ha.gen_ellipse(row[], col[], phi[], r1[], r2[])
    ha.gen_region_polygon(rows, cols) per polygon + concat_obj reduce

Regions are reused until the next edit. They are NEVER recreated in the
frame loop.

4. Batch statistics (one call per type)
---------------------------------------

The old per-ROI loop

    for roi:
        reduce_domain()
        min_max_gray()
        intensity()

is gone. Statistics operate directly on the cached region tuples:

    mean, dev    = ha.intensity(regions, Image)     # one call
    min, max, r  = ha.min_max_gray(regions, Image)  # one call
    area, r, col = ha.area_center(regions)          # one call

`reduce_domain` is never used (on a region tuple it silently reduces to
only the first region) and no temporary images are created.

5. Frame pipeline
-----------------

`_poll_frame()` is a thin, observable stage driver. Each stage is its
own method and its timing is published to the Processing Information
Panel:

    Acquire Frame --> Calibration --> Display Preparation
    --> ROI Statistics --> Alarm --> GUI Update

6. Mouse temperature
--------------------

A 33 ms poll reads the cursor position with `get_mposition`, which is
the exact inverse transform HALCON uses to draw (no offset, no scaling
error). The temperature under the pixel is read from the float32
temperature image that was used for statistics. A vectorised numpy
hit-test (same geometry convention as the HALCON regions) reports
whether the pixel is inside any ROI and names it.

7. Display
----------

The thermal image keeps its aspect ratio inside a letterbox. The HALCON
window is moved inside the widget with `set_window_extents` to the
centered 640x480 rect; unused areas render black. Zoom is implemented
with `set_part` (anchored on the cursor). Regions are drawn as overlays
on top of the image; raw thermal data is never modified.

8. Benchmark
------------

The Benchmark button creates 50/100/250/500/1000/2000 Rectangle1 ROIs,
measures processing/statistics/display/total time per frame plus FPS,
cross-checks the batch statistics against a numpy reference, and
exports a CSV to `benchmarks/prototype_roi_benchmark_<timestamp>.csv`.

----------------------------------------------------------------------------
Known limitations (prototype status)
----------------------------------------------------------------------------

- All processing runs on the GUI thread (single-threaded pipeline).
  Production binds one ROI engine per camera acquisition thread.
- Editing is polled (150 ms) instead of event-driven because Python
  callbacks are not supported by this HALCON build.
- Only one ROI has an active drawing object at a time (MVTec sample
  behaviour); benchmark layouts never create drawing objects.
- Without a loaded calibration the temperature image falls back to raw
  detector counts (units are shown accordingly).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
import halcon as ha
from halcon import HObject, HHandle

from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo
from camera.tv46l_camera import TV46LCamera
from calibration.calibration_manager import CalibrationManager
from configuration.settings import Settings

# ==========================================================
# Constants
# ==========================================================

FEED_W = 640
FEED_H = 480

POLL_MS = 33                # frame pipeline cadence
MOUSE_POLL_MS = 33          # cursor -> image temperature read-out
EDIT_POLL_MS = 150          # drawing-object geometry synchronisation
TABLE_REFRESH_MS = 500      # ROI table throttle
STATS_INTERVAL_MS = 200     # statistics cadence (display FPS is decoupled)
LABEL_THROTTLE_MS = 200     # min interval between label re-renders

DEFAULT_THRESHOLD = 80.0    # °C, settings.DEFAULT_HIGH_TEMPERATURE
DEFAULT_COLOR = "green"
SELECTED_COLOR = "yellow"
ALARM_COLOR = "red"

BENCHMARK_COUNTS = (50, 100, 250, 500, 1000, 2000)
BENCHMARK_WARMUP = 5
BENCHMARK_FRAMES = 15
BENCHMARK_FOLDER = Path("benchmarks")

SHAPES = ("Rectangle1", "Rectangle2", "Circle", "Ellipse", "Polygon")

COMMON_FIELDS = ("name", "enabled", "visible", "threshold", "color", "draw_object")

SHAPE_GEOMETRY: dict[str, tuple[str, ...]] = {
    "Rectangle1": ("row1", "col1", "row2", "col2"),
    "Rectangle2": ("row", "col", "phi", "length1", "length2"),
    "Circle": ("row", "col", "radius"),
    "Ellipse": ("row", "col", "phi", "radius1", "radius2"),
    "Polygon": ("points",),
}

TABLE_COLUMNS = (
    "Name", "Shape", "Enabled", "Visible", "Alarm",
    "Min", "Avg", "Max", "Area", "Threshold", "Color", "Position",
)

# ==========================================================
# Geometry helpers (HALCON-compatible conventions)
# ==========================================================


def _inside_rectangle2(row: float, col: float, center_row: float, center_col: float,
                       phi: float, length1: float, length2: float) -> bool:
    """Point-in-rotated-rectangle test.

    Uses the HALCON axis convention verified in roi_engine/masks.py:
    length1 runs along (-sin(phi), cos(phi)) and length2 along
    (cos(phi), sin(phi)); the rotation mapping flips orientation.
    """
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)
    d_r = row - center_row
    d_c = col - center_col
    rp = -d_r * sin_p + d_c * cos_p
    cp = d_r * cos_p + d_c * sin_p
    return abs(rp) <= length1 and abs(cp) <= length2


def _inside_ellipse(row: float, col: float, center_row: float, center_col: float,
                    phi: float, radius1: float, radius2: float) -> bool:
    """Point-in-ellipse test in the HALCON axis convention."""
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)
    d_r = row - center_row
    d_c = col - center_col
    rp_axis = -d_r * sin_p + d_c * cos_p
    cp_axis = d_r * cos_p + d_c * sin_p
    return (rp_axis / radius1) ** 2 + (cp_axis / radius2) ** 2 <= 1.0


def _point_in_polygon(row: float, col: float, poly_rows, poly_cols) -> bool:
    """Even-odd ray casting point-in-polygon test."""
    inside = False
    n = len(poly_rows)
    j = n - 1
    for i in range(n):
        y_i, y_j = poly_rows[i], poly_rows[j]
        x_i, x_j = poly_cols[i], poly_cols[j]
        if (y_i > row) != (y_j > row):
            xint = (x_j - x_i) * (row - y_i) / (y_j - y_i) + x_i
            if col < xint:
                inside = not inside
        j = i
    return inside


def _synthetic_frame(seed: int) -> np.ndarray:
    """Deterministic 480x640 uint16 thermal test frame."""
    rng = np.random.default_rng(seed)
    rows = np.linspace(0.0, 1.0, FEED_H, dtype=np.float32)[:, None]
    cols = np.linspace(0.0, 1.0, FEED_W, dtype=np.float32)[None, :]
    base = 12000.0 + 12000.0 * (0.4 * rows + 0.6 * cols)
    noise = rng.normal(0.0, 300.0, size=(FEED_H, FEED_W)).astype(np.float32)
    hot = np.zeros((FEED_H, FEED_W), dtype=np.float32)
    hot[180:260, 300:380] = 9000.0
    img = np.clip(base + noise + hot, 0, 65535).astype(np.uint16)
    return img


def _now_tag() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ==========================================================
# Grouped ROI storage (MVTec type-array layout)
# ==========================================================


class GroupedROIStorage:
    """Parallel type-arrays holding every ROI.

    One dict of lists per geometry type.  ``draw_object`` entries exist
    only while a ROI is being edited and are never used for statistics.
    """

    def __init__(self) -> None:
        self._types: dict[str, dict[str, list]] = {}
        self._names: dict[str, tuple[str, int]] = {}
        self._counter = 0
        self._rev = 0
        for shape in SHAPES:
            fields = COMMON_FIELDS + SHAPE_GEOMETRY[shape]
            self._types[shape] = {field: [] for field in fields}

    @property
    def rev(self) -> int:
        """Increments on any mutation; used to invalidate caches."""
        return self._rev

    # ----------------------------------------------------------
    # Introspection
    # ----------------------------------------------------------

    def count(self, shape: str) -> int:
        return len(self._types[shape]["name"])

    def total(self) -> int:
        return sum(self.count(shape) for shape in SHAPES)

    def counts(self) -> dict[str, int]:
        return {shape: self.count(shape) for shape in SHAPES}

    def arrays(self, shape: str) -> dict[str, list]:
        """Reference to the parallel arrays of one type."""
        return self._types[shape]

    def entries(self) -> Iterator[tuple[str, int, dict]]:
        """Yield (shape, index, merged meta+geometry row) for every ROI."""
        for shape in SHAPES:
            arrays = self._types[shape]
            fields = COMMON_FIELDS + SHAPE_GEOMETRY[shape]
            for index in range(len(arrays["name"])):
                row = {field: arrays[field][index] for field in fields}
                yield shape, index, row

    def find_by_name(self, name: str) -> tuple[str, int] | None:
        return self._names.get(name)

    # ----------------------------------------------------------
    # Mutations
    # ----------------------------------------------------------

    def next_name(self, shape: str) -> str:
        self._counter += 1
        return f"{shape}_{self._counter}"

    def add(
        self,
        shape: str,
        geometry: dict,
        name: str | None = None,
        enabled: bool = True,
        visible: bool = True,
        threshold: float = DEFAULT_THRESHOLD,
        color: str = DEFAULT_COLOR,
    ) -> tuple[str, int]:
        arrays = self._types[shape]
        roi_name = name or self.next_name(shape)
        while roi_name in self._names:
            roi_name = self.next_name(shape)
        self._rev += 1
        arrays["name"].append(roi_name)
        arrays["enabled"].append(bool(enabled))
        arrays["visible"].append(bool(visible))
        arrays["threshold"].append(float(threshold))
        arrays["color"].append(str(color))
        arrays["draw_object"].append(None)
        for field in SHAPE_GEOMETRY[shape]:
            if field == "points":
                value = geometry.get("points", ([], []))
                arrays["points"].append((list(value[0]), list(value[1])))
            else:
                arrays[field].append(float(geometry.get(field, 0.0)))
        index = len(arrays["name"]) - 1
        self._names[roi_name] = (shape, index)
        return shape, index

    def duplicate(self, shape: str, source_index: int) -> tuple[str, int]:
        geometry = self.get_geometry(shape, source_index)
        return self.add(
            shape,
            geometry,
            enabled=self._types[shape]["enabled"][source_index],
            visible=self._types[shape]["visible"][source_index],
            threshold=self._types[shape]["threshold"][source_index],
            color=self._types[shape]["color"][source_index],
        )

    def remove(self, shape: str, index: int) -> None:
        arrays = self._types[shape]
        if index < 0 or index >= len(arrays["name"]):
            raise IndexError(f"ROI index {index} out of range for {shape}")
        self._rev += 1
        name = arrays["name"][index]
        for field, values in arrays.items():
            del values[index]
        self._names.pop(name, None)

    def remove_by_name(self, name: str) -> bool:
        location = self._names.pop(name, None)
        if location is None:
            return False
        self._rev += 1
        shape, index = location
        arrays = self._types[shape]
        for field, values in arrays.items():
            if index < len(values):
                del values[index]
        return True

    def update_geometry(self, shape: str, index: int, geometry: dict) -> None:
        arrays = self._types[shape]
        self._rev += 1
        for key, value in geometry.items():
            if key in SHAPE_GEOMETRY[shape]:
                if key == "points":
                    arrays["points"][index] = (list(value[0]), list(value[1]))
                else:
                    arrays[key][index] = float(value)

    def get_geometry(self, shape: str, index: int) -> dict:
        arrays = self._types[shape]
        result = {}
        for field in SHAPE_GEOMETRY[shape]:
            value = arrays[field][index]
            result[field] = (list(value[0]), list(value[1])) if field == "points" else value
        return result

    def set_meta(self, shape: str, index: int, field: str, value: Any) -> None:
        self._rev += 1
        if field == "name":
            old = self._types[shape]["name"][index]
            self._names.pop(old, None)
            self._types[shape]["name"][index] = value
            self._names[value] = (shape, index)
            return
        if field not in self._types[shape]:
            raise KeyError(f"Unknown meta field {field!r}")
        self._types[shape][field][index] = value

    def get_meta(self, shape: str, index: int, field: str) -> Any:
        return self._types[shape][field][index]

    def rename(self, name: str, new_name: str) -> bool:
        location = self._names.get(name)
        if location is None or new_name in self._names:
            return False
        self._rev += 1
        shape, index = location
        self._types[shape]["name"][index] = new_name
        self._names.pop(name)
        self._names[new_name] = (shape, index)
        return True

    # ----------------------------------------------------------
    # Hit test (vectorised over the grouped arrays)
    # ----------------------------------------------------------

    def hit_test(self, row: float, col: float) -> tuple[str, int, str] | None:
        """Return (shape, index, name) of the ROI containing (row, col).

        Uses the same geometry conventions as the HALCON region
        generation so the result matches what is displayed.
        """
        for shape in SHAPES:
            index = self._hit_index(shape, row, col)
            if index >= 0:
                return shape, index, self._types[shape]["name"][index]
        return None

    def _hit_index(self, shape: str, row: float, col: float) -> int:
        arrays = self._types[shape]
        n = len(arrays["name"])
        if n == 0:
            return -1
        if shape == "Rectangle1":
            r1 = np.asarray(arrays["row1"], dtype=np.float64)
            r2 = np.asarray(arrays["row2"], dtype=np.float64)
            c1 = np.asarray(arrays["col1"], dtype=np.float64)
            c2 = np.asarray(arrays["col2"], dtype=np.float64)
            mask = (row >= r1) & (row <= r2) & (col >= c1) & (col <= c2)
            return int(np.argmax(mask)) if mask.any() else -1
        if shape == "Rectangle2":
            rows = np.asarray(arrays["row"], dtype=np.float64)
            cols = np.asarray(arrays["col"], dtype=np.float64)
            for i in range(n):
                if _inside_rectangle2(row, col, rows[i], cols[i],
                                      arrays["phi"][i], arrays["length1"][i],
                                      arrays["length2"][i]):
                    return i
            return -1
        if shape == "Circle":
            rows = np.asarray(arrays["row"], dtype=np.float64)
            cols = np.asarray(arrays["col"], dtype=np.float64)
            radii = np.asarray(arrays["radius"], dtype=np.float64)
            mask = (row - rows) ** 2 + (col - cols) ** 2 <= radii ** 2
            return int(np.argmax(mask)) if mask.any() else -1
        if shape == "Ellipse":
            rows = np.asarray(arrays["row"], dtype=np.float64)
            cols = np.asarray(arrays["col"], dtype=np.float64)
            for i in range(n):
                if _inside_ellipse(row, col, rows[i], cols[i],
                                   arrays["phi"][i], arrays["radius1"][i],
                                   arrays["radius2"][i]):
                    return i
            return -1
        for i in range(n):
            poly_rows, poly_cols = arrays["points"][i]
            if _point_in_polygon(row, col, poly_rows, poly_cols):
                return i
        return -1

    # ----------------------------------------------------------
    # Snapshot / persistence
    # ----------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "counter": self._counter,
            "types": {
                shape: {
                    field: list(values) for field, values in arrays.items()
                    if field != "draw_object"
                }
                for shape, arrays in self._types.items()
            },
        }

    def restore(self, snap: dict) -> None:
        self.clear()
        self._counter = int(snap.get("counter", 0))
        self._rev += 1
        for shape in SHAPES:
            arrays = snap.get("types", {}).get(shape)
            if not arrays:
                continue
            fields = COMMON_FIELDS + SHAPE_GEOMETRY[shape]
            for field in fields:
                if field == "draw_object":
                    self._types[shape][field] = []
                    continue
                self._types[shape][field] = list(arrays.get(field, []))
            for index, name in enumerate(self._types[shape]["name"]):
                self._names[name] = (shape, index)
        self._counter = max(self._counter, self.total())

    def serialize(self) -> dict:
        """JSON-safe representation (drawing objects excluded)."""
        return {
            "counter": self._counter,
            "types": {
                shape: {
                    field: list(values) for field, values in arrays.items()
                    if field != "draw_object"
                }
                for shape, arrays in self._types.items()
            },
        }

    def from_dict(self, data: dict) -> None:
        self.clear()
        self._counter = int(data.get("counter", 0))
        self._rev += 1
        for shape in SHAPES:
            arrays = data.get("types", {}).get(shape)
            if not arrays:
                continue
            fields = COMMON_FIELDS + SHAPE_GEOMETRY[shape]
            for field in fields:
                if field == "draw_object":
                    self._types[shape][field] = []
                    continue
                self._types[shape][field] = list(arrays.get(field, []))
            for index, name in enumerate(self._types[shape]["name"]):
                self._names[name] = (shape, index)
        self._counter = max(self._counter, self.total())

    def clear(self) -> None:
        self._rev += 1
        for shape in SHAPES:
            for field in COMMON_FIELDS + SHAPE_GEOMETRY[shape]:
                self._types[shape][field] = []
        self._names.clear()
        self._counter = 0


# ==========================================================
# Cached HALCON region generation (dirty-region cache)
# ==========================================================


class RegionCache:
    """Per-type HALCON region tuples, rebuilt lazily on geometry change.

    A type is marked dirty on create/move/resize/delete/load.  While
    clean, the exact cached object tuple is returned forever.  Region
    generation therefore happens only on real changes, never in the
    frame loop.
    """

    def __init__(self, log_error: Callable[[str], None] | None = None) -> None:
        self._log_error = log_error
        self._regions: dict[str, HObject | None] = {s: None for s in SHAPES}
        self._outlines: dict[str, HObject | None] = {s: None for s in SHAPES}
        self._dirty: dict[str, bool] = {s: True for s in SHAPES}
        self.batch_calls = 0
        self.rebuild_s = 0.0
        try:
            # Avoid silent empty regions when geometry is loaded before
            # any image is read (design note in ROI_Architecture.md).
            ha.set_system("clip_region", "false")
        except Exception:
            pass

    def invalidate(self, shape: str) -> None:
        self._dirty[shape] = True

    def invalidate_all(self) -> None:
        for shape in SHAPES:
            self._dirty[shape] = True

    def is_dirty(self, shape: str) -> bool:
        return self._dirty[shape]

    def dirty_types(self) -> list[str]:
        return [shape for shape in SHAPES if self._dirty[shape]]

    def cached_types(self) -> list[str]:
        return [shape for shape in SHAPES if self._regions[shape] is not None]

    def regions(self, shape: str, store: GroupedROIStorage) -> HObject | None:
        """Return the cached tuple, rebuilding it only when dirty."""
        if self._dirty[shape]:
            self._rebuild(shape, store)
        return self._regions[shape]

    def outlines(self, shape: str, store: GroupedROIStorage) -> HObject | None:
        """Return the cached 1 px outline contours (display only).

        Generated once per rebuild from the exact cached regions, so the
        overlay follows the same geometry without per-frame boundary().
        """
        if self._dirty[shape]:
            self._rebuild(shape, store)
        return self._outlines[shape]

    def _rebuild(self, shape: str, store: GroupedROIStorage) -> None:
        arrays = store.arrays(shape)
        n = len(arrays["name"])
        if n == 0:
            self._regions[shape] = None
            self._outlines[shape] = None
            self._dirty[shape] = False
            return
        t0 = time.perf_counter()
        try:
            if shape == "Rectangle1":
                regions = ha.gen_rectangle1(
                    arrays["row1"], arrays["col1"], arrays["row2"], arrays["col2"])
            elif shape == "Rectangle2":
                regions = ha.gen_rectangle2(
                    arrays["row"], arrays["col"], arrays["phi"],
                    arrays["length1"], arrays["length2"])
            elif shape == "Circle":
                regions = ha.gen_circle(
                    arrays["row"], arrays["col"], arrays["radius"])
            elif shape == "Ellipse":
                regions = ha.gen_ellipse(
                    arrays["row"], arrays["col"], arrays["phi"],
                    arrays["radius1"], arrays["radius2"])
            else:  # Polygon
                parts = [ha.gen_region_polygon(r, c) for r, c in arrays["points"]]
                regions = parts[0]
                for part in parts[1:]:
                    regions = ha.concat_obj(regions, part)
            self.batch_calls += 1 if shape != "Polygon" else n
            try:
                self._outlines[shape] = ha.boundary(regions, "inner")
            except Exception:
                self._outlines[shape] = None
            self._regions[shape] = regions
        except Exception as exc:
            self._regions[shape] = None
            self._outlines[shape] = None
            if self._log_error is not None:
                self._log_error(f"Region generation failed for {shape}: {exc}")
        finally:
            self._dirty[shape] = False
            self.rebuild_s = time.perf_counter() - t0


# ==========================================================
# Batch statistics engine (one operator call per type)
# ==========================================================


class StatisticsEngine:
    """Runs intensity / min_max_gray / area_center once per type.

    No reduce_domain, no cropping, no temporary images.  Regions are
    passed as tuples straight to the batch operators; tuple results are
    aligned with the type's arrays by index.
    """

    def __init__(self, log_error: Callable[[str], None] | None = None) -> None:
        self._log_error = log_error
        self.batch_calls = 0
        self.last_ms = 0.0
        self.last_shape_ms: dict[str, float] = {}
        self.last_results: dict[str, dict] = {}

    def process(
        self,
        image: HObject,
        store: GroupedROIStorage,
        cache: RegionCache,
    ) -> dict[str, dict]:
        t0 = time.perf_counter()
        results: dict[str, dict] = {}
        self.last_shape_ms = {}
        for shape in SHAPES:
            arrays = store.arrays(shape)
            n = len(arrays["name"])
            if n == 0:
                continue
            regions = cache.regions(shape, store)
            if regions is None:
                continue
            st = time.perf_counter()
            try:
                mean, deviation = ha.intensity(regions, image)
                minimum, maximum, _range = ha.min_max_gray(regions, image, 0)
                area, r_row, c_col = ha.area_center(regions)
                self.batch_calls += 3
            except Exception as exc:
                if self._log_error is not None:
                    self._log_error(f"Statistics failed for {shape}: {exc}")
                continue
            self.last_shape_ms[shape] = (time.perf_counter() - st) * 1000.0
            for i, name in enumerate(arrays["name"]):
                results[name] = {
                    "shape": shape,
                    "index": i,
                    "min": float(minimum[i]),
                    "max": float(maximum[i]),
                    "mean": float(mean[i]),
                    "dev": float(deviation[i]),
                    "area": float(area[i]),
                    "row": float(r_row[i]),
                    "col": float(c_col[i]),
                }
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        self.last_results = results
        return results


# ==========================================================
# Threshold alarm (prototype)
# ==========================================================


class AlarmEngine:
    """Per-ROI threshold alarm over the batch results.

    A ROI is in ALARM when it is enabled and ``max >= threshold``.
    """

    def __init__(self, store: GroupedROIStorage) -> None:
        self._store = store
        self._alarms: dict[str, bool] = {}

    @property
    def alarms(self) -> dict[str, bool]:
        return dict(self._alarms)

    def evaluate(self, results: dict[str, dict]) -> dict[str, bool]:
        for name, stats in results.items():
            location = self._store.find_by_name(name)
            if location is None:
                self._alarms[name] = False
                continue
            shape, index = location
            enabled = bool(self._store.get_meta(shape, index, "enabled"))
            if not enabled:
                self._alarms[name] = False
                continue
            threshold = float(self._store.get_meta(shape, index, "threshold"))
            self._alarms[name] = stats["max"] >= threshold
        return dict(self._alarms)


# ==========================================================
# Thermal view: letterboxed HALCON window with exact mouse coords
# ==========================================================


class ThermalView(QFrame):
    """Embedded HALCON graphics window with aspect-ratio letterbox.

    The image is always displayed 4:3 centered; the unused area stays
    black.  Zoom is a window ``set_part`` anchored at the cursor.
    """

    def __init__(self, parent: QWidget | None = None,
                 log_fn: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self._log_fn = log_fn
        self._handle: HHandle | None = None
        self._image_size = (FEED_H, FEED_W)            # (rows, cols)
        self._part = (0.0, 0.0, float(FEED_H - 1), float(FEED_W - 1))
        self._zoom = 1.0
        self.setMinimumSize(FEED_W // 2, FEED_H // 2)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #000000; border: 1px solid #3C3C3C;")

    # ----------------------------------------------------------
    # Window lifecycle
    # ----------------------------------------------------------

    def create_window(self) -> bool:
        if self._handle is not None:
            return True
        try:
            self._handle = ha.open_window(
                0, 0, max(self.width(), 1), max(self.height(), 1),
                int(self.winId()), "visible", "")
            ha.set_window_param(self._handle, "flush", "true")
            self._apply_extents()
            return True
        except Exception as exc:
            self._handle = None
            if self._log_fn is not None:
                self._log_fn(f"Failed to create HALCON window: {exc}")
            return False

    @property
    def handle(self) -> HHandle | None:
        return self._handle

    def is_handle_valid(self) -> bool:
        return self._handle is not None

    def close_window(self) -> None:
        if self._handle is not None:
            try:
                ha.close_window(self._handle)
            except Exception:
                pass
            self._handle = None

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._handle is None:
            self.create_window()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._handle is not None:
            self._apply_extents()

    # ----------------------------------------------------------
    # Letterbox / zoom
    # ----------------------------------------------------------

    def _letterbox_rect(self) -> QRect:
        w, h = self.width(), self.height()
        if w <= 1 or h <= 1:
            return QRect(0, 0, 1, 1)
        target = FEED_W / float(FEED_H)
        aw = float(w)
        ah = aw / target
        if ah > h:
            ah = float(h)
            aw = ah * target
        x = int((w - aw) / 2.0)
        y = int((h - ah) / 2.0)
        return QRect(x, y, int(aw), int(ah))

    def _apply_extents(self) -> None:
        rect = self._letterbox_rect()
        try:
            ha.set_window_extents(
                self._handle, rect.y(), rect.x(), rect.width(), rect.height())
        except Exception:
            pass

    def set_zoom(self, factor: float, center_row: float | None = None,
                 center_col: float | None = None) -> None:
        self._zoom = min(32.0, max(1.0, factor))
        if center_row is None or center_col is None:
            center_row, center_col = self._center()
        image_h, image_w = self._image_size
        half_h = (image_h / self._zoom) / 2.0
        half_w = (image_w / self._zoom) / 2.0
        r1 = center_row - half_h
        r2 = center_row + half_h
        c1 = center_col - half_w
        c2 = center_col + half_w
        if r1 < 0:
            r2 += -r1
            r1 = 0.0
        if r2 > image_h - 1:
            r1 -= r2 - (image_h - 1)
            r2 = float(image_h - 1)
        if c1 < 0:
            c2 += -c1
            c1 = 0.0
        if c2 > image_w - 1:
            c1 -= c2 - (image_w - 1)
            c2 = float(image_w - 1)
        self._part = (r1, c1, r2, c2)

    def zoom(self, factor: float) -> None:
        center_row, center_col = self._center()
        self.set_zoom(factor, center_row, center_col)

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    def _center(self) -> tuple[float, float]:
        r1, c1, r2, c2 = self._part
        return ((r1 + r2) / 2.0, (c1 + c2) / 2.0)

    def fit(self) -> None:
        self._zoom = 1.0
        image_h, image_w = self._image_size
        self._part = (0.0, 0.0, float(image_h - 1), float(image_w - 1))

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        anchor = self.poll_mouse()
        if anchor is not None:
            center_row, center_col = float(anchor[0]), float(anchor[1])
        else:
            center_row, center_col = self._center()
        self.set_zoom(self._zoom * (1.25 ** steps), center_row, center_col)
        event.accept()

    # ----------------------------------------------------------
    # Display
    # ----------------------------------------------------------

    @staticmethod
    def _numpy_to_halcon(rgb: np.ndarray) -> HObject:
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        if rgb.ndim == 2:
            return ha.gen_image1("byte", w, h, int(rgb.ctypes.data))
        r = np.ascontiguousarray(rgb[:, :, 0])
        g = np.ascontiguousarray(rgb[:, :, 1])
        b = np.ascontiguousarray(rgb[:, :, 2])
        return ha.gen_image3("byte", w, h,
                             int(r.ctypes.data), int(g.ctypes.data), int(b.ctypes.data))

    def display_rgb(self, rgb: np.ndarray,
                    overlays: list[tuple[HObject | None, Any]]) -> float:
        """Display an RGB frame plus overlay pieces. Returns elapsed ms.

        Each overlay piece is (regions, color); ``color`` may be a
        single color string or one color per region.  The elapsed time
        is broken down per sub-stage in ``last_breakdown`` so the
        benchmark can report exactly where the display budget goes.
        """
        if self._handle is None:
            self.last_breakdown = {}
            return 0.0
        t0 = time.perf_counter()
        breakdown = {"convert_ms": 0.0, "image_ms": 0.0, "overlay_ms": 0.0, "flush_ms": 0.0}
        try:
            image_h, image_w = rgb.shape[:2]
            if self._image_size != (image_h, image_w):
                self._image_size = (image_h, image_w)
                self.fit()
            tb = time.perf_counter()
            obj = self._numpy_to_halcon(rgb)
            breakdown["convert_ms"] = (time.perf_counter() - tb) * 1000.0
            tb = time.perf_counter()
            ha.clear_window(self._handle)
            ha.set_part(self._handle, *self._part)
            ha.disp_obj(obj, self._handle)
            breakdown["image_ms"] = (time.perf_counter() - tb) * 1000.0
            tb = time.perf_counter()
            for regions, color in overlays:
                if regions is None or not color:
                    continue
                ha.set_color(self._handle, color)
                ha.disp_obj(regions, self._handle)
            breakdown["overlay_ms"] = (time.perf_counter() - tb) * 1000.0
            tb = time.perf_counter()
            ha.flush_buffer(self._handle)
            breakdown["flush_ms"] = (time.perf_counter() - tb) * 1000.0
        except Exception:
            pass
        self.last_breakdown = breakdown
        return (time.perf_counter() - t0) * 1000.0

    def clear_display(self) -> None:
        if self._handle is not None:
            try:
                ha.clear_window(self._handle)
            except Exception:
                pass

    # ----------------------------------------------------------
    # Mouse -> image coordinates (exact)
    # ----------------------------------------------------------

    def poll_mouse(self) -> tuple[int, int, int] | None:
        """Return (row, col, button) of the cursor in image coordinates.

        Uses HALCON's own inverse part transform (get_mposition), so the
        coordinates exactly denote the pixel whose temperature is read.
        Falls back to a manual inverse of the letterbox + part mapping.
        """
        if self._handle is None:
            return None
        try:
            row, col, button = ha.get_mposition(self._handle)
            image_h, image_w = self._image_size
            if 0 <= row < image_h and 0 <= col < image_w:
                return int(row), int(col), int(button)
        except Exception:
            pass
        global_pos = QCursor.pos()
        local = self.mapFromGlobal(global_pos)
        rect = self._letterbox_rect()
        if not rect.contains(local):
            return None
        r1, c1, r2, c2 = self._part
        image_h, image_w = self._image_size
        fx = (local.x() - rect.x()) / float(rect.width())
        fy = (local.y() - rect.y()) / float(rect.height())
        col = max(0.0, min(float(image_w - 1), c1 + fx * (c2 - c1)))
        row = max(0.0, min(float(image_h - 1), r1 + fy * (r2 - r1)))
        return int(round(row)), int(round(col)), 0

    def closeEvent(self, event) -> None:  # noqa: N802
        self.close_window()
        super().closeEvent(event)


# ==========================================================
# Main prototype window
# ==========================================================


class ROICalibrationPrototype(QMainWindow):
    """Standalone MVTec-architecture prototype (see module docstring)."""

    def __init__(self) -> None:
        super().__init__()
        self._store = GroupedROIStorage()
        self._cache = RegionCache(log_error=self._log_error)
        self._stats_engine = StatisticsEngine(log_error=self._log_error)
        self._alarm_engine = AlarmEngine(self._store)

        self._camera: TV46LCamera | None = None
        self._calibration: CalibrationManager | None = None
        self._camera_infos: list[CameraInfo] = []
        self._settings = Settings()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_MS)
        self._poll_timer.timeout.connect(self._poll_frame)

        self._mouse_timer = QTimer(self)
        self._mouse_timer.setInterval(MOUSE_POLL_MS)
        self._mouse_timer.timeout.connect(self._poll_mouse)

        self._edit_timer = QTimer(self)
        self._edit_timer.setInterval(EDIT_POLL_MS)
        self._edit_timer.timeout.connect(self._sync_editing_object)

        self._table_timer = QTimer(self)
        self._table_timer.setInterval(TABLE_REFRESH_MS)
        self._table_timer.timeout.connect(self._refresh_table)

        self._selected_name: str | None = None
        self._editing: tuple[str, int] | None = None

        self._last_stats: dict[str, dict] = {}
        self._alarms: dict[str, bool] = {}
        self._temp_image: np.ndarray | None = None
        self._frame_number = 0
        self._fps_frames = 0
        self._fps_start = time.perf_counter()
        self._fps = 0.0
        self._last_timing: dict[str, float] = {}
        self._benchmarking = False
        self._table_dirty = True

        self._overlay_stale = True
        self._overlay_pieces: list[tuple[HObject | None, Any]] | None = None
        self._overlay_store_rev = -1
        self._drawn_alarms: frozenset | None = None
        self._label_canvas: np.ndarray | None = None
        self._label_rgb: np.ndarray | None = None
        self._label_alpha: np.ndarray | None = None
        self._label_canvas_sig: tuple | None = None
        self._label_pending_sig: tuple | None = None
        self._label_pending_rows: list[tuple] | None = None
        self._label_request_time = 0.0
        self._label_render_last_ms = 0.0
        self._label_store_rev = -1
        self._stats_ran_since_labels = True
        self._last_stats_time = 0.0
        self._label_lock = threading.Lock()
        self._label_stop = threading.Event()
        self._label_thread = threading.Thread(
            target=self._label_worker, name="label-render", daemon=True)
        self._label_thread.start()

        self._build_ui()
        self._mouse_timer.start()
        self._edit_timer.start()
        self._table_timer.start()

    # ==================================================================
    # UI Construction
    # ==================================================================

    def _build_ui(self) -> None:
        self.setWindowTitle("ROI Calibration & Performance Prototype")
        self.resize(1500, 940)
        self._build_toolbar()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)   # 75%
        splitter.setStretchFactor(1, 1)   # 25%
        splitter.setSizes([1020, 340])
        layout.addWidget(splitter, 1)

        layout.addWidget(self._build_event_log())
        self._build_status_bar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._discover_btn = QPushButton("Discover")
        self._discover_btn.clicked.connect(self._on_discover)
        toolbar.addWidget(self._discover_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect)
        self._connect_btn.setEnabled(False)
        toolbar.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.setEnabled(False)
        toolbar.addWidget(self._disconnect_btn)

        toolbar.addSeparator()

        self._focus_near_btn = QPushButton("Focus -")
        self._focus_near_btn.clicked.connect(self._on_focus_near)
        self._focus_near_btn.setEnabled(False)
        toolbar.addWidget(self._focus_near_btn)

        self._focus_far_btn = QPushButton("Focus +")
        self._focus_far_btn.clicked.connect(self._on_focus_far)
        self._focus_far_btn.setEnabled(False)
        toolbar.addWidget(self._focus_far_btn)

        self._autofocus_btn = QPushButton("Auto Focus")
        self._autofocus_btn.setEnabled(False)
        self._autofocus_btn.setToolTip("Auto focus is not supported by the TV46L.")
        toolbar.addWidget(self._autofocus_btn)

        self._nuc_btn = QPushButton("Manual NUC")
        self._nuc_btn.clicked.connect(self._on_manual_nuc)
        self._nuc_btn.setEnabled(False)
        toolbar.addWidget(self._nuc_btn)

        toolbar.addSeparator()

        self._shape_combo = QComboBox()
        for shape in SHAPES:
            self._shape_combo.addItem(shape)
        toolbar.addWidget(QLabel("Create ROI:"))
        toolbar.addWidget(self._shape_combo)
        create_btn = QPushButton("Create ROI")
        create_btn.clicked.connect(self._on_create_roi)
        toolbar.addWidget(create_btn)

        toolbar.addSeparator()

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_load)
        toolbar.addWidget(load_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        toolbar.addWidget(save_btn)

        toolbar.addSeparator()

        self._benchmark_btn = QPushButton("Benchmark")
        self._benchmark_btn.clicked.connect(self._on_benchmark)
        toolbar.addWidget(self._benchmark_btn)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._view = ThermalView(log_fn=self._log_error)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._view, 1)
        return panel

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self._mouse_label = QLabel("X: --   Y: --   T: --   ROI: --   Frame: --")
        bar.addWidget(self._mouse_label, 1)

        zoom_out = QPushButton("-")
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self._view.zoom(self._view.zoom_factor / 1.5))
        bar.addPermanentWidget(zoom_out)
        bar.addPermanentWidget(QLabel("Zoom:"))
        self._zoom_label = QLabel("100%")
        bar.addPermanentWidget(self._zoom_label)
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(lambda: self._view.zoom(self._view.zoom_factor * 1.5))
        bar.addPermanentWidget(zoom_in)
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(self._view.fit)
        bar.addPermanentWidget(fit_btn)

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._build_table_group(), 2)
        layout.addWidget(self._build_selected_group())
        layout.addWidget(self._build_processing_group())
        return panel

    def _build_table_group(self) -> QWidget:
        group = QGroupBox("ROI Table")
        layout = QVBoxLayout(group)

        controls = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter by name...")
        self._search_edit.textChanged.connect(self._on_filter_changed)
        controls.addWidget(self._search_edit, 1)

        self._shape_filter = QComboBox()
        self._shape_filter.addItem("All")
        for shape in SHAPES:
            self._shape_filter.addItem(shape)
        self._shape_filter.currentTextChanged.connect(self._on_filter_changed)
        controls.addWidget(self._shape_filter)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._on_delete_selected)
        controls.addWidget(delete_btn)
        duplicate_btn = QPushButton("Duplicate Selected")
        duplicate_btn.clicked.connect(self._on_duplicate_selected)
        controls.addWidget(duplicate_btn)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._on_clear_all)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        self._table = QTableWidget(0, len(TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(TABLE_COLUMNS))
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self._table)
        return group

    def _build_selected_group(self) -> QWidget:
        group = QGroupBox("Selected ROI")
        form = QFormLayout(group)
        self._sel_name = QLabel("---")
        self._sel_shape = QLabel("---")
        self._sel_geometry = QLabel("---")
        self._sel_stats = QLabel("---")
        self._sel_alarm = QLabel("---")

        self._sel_color_btn = QPushButton(DEFAULT_COLOR)
        self._sel_color_btn.setStyleSheet("background-color: yellow; color: black;")
        self._sel_color_btn.clicked.connect(self._on_pick_selected_color)
        self._sel_enabled = QCheckBox("Enabled")
        self._sel_enabled.toggled.connect(self._on_selected_meta_changed)
        self._sel_visible = QCheckBox("Visible")
        self._sel_visible.toggled.connect(self._on_selected_visible_changed)
        self._sel_threshold = QDoubleSpinBox()
        self._sel_threshold.setRange(-50.0, 2000.0)
        self._sel_threshold.setDecimals(1)
        self._sel_threshold.setValue(DEFAULT_THRESHOLD)
        self._sel_threshold.valueChanged.connect(self._on_selected_threshold_changed)

        form.addRow("Name", self._sel_name)
        form.addRow("Shape", self._sel_shape)
        form.addRow("Geometry", self._sel_geometry)
        form.addRow("Statistics", self._sel_stats)
        form.addRow("Alarm", self._sel_alarm)
        form.addRow("Color", self._sel_color_btn)
        form.addRow("Enabled", self._sel_enabled)
        form.addRow("Visible", self._sel_visible)
        form.addRow("Threshold", self._sel_threshold)
        return group

    def _build_processing_group(self) -> QWidget:
        group = QGroupBox("Processing Information")
        grid = QGridLayout(group)
        r = 0
        self._shape_count_labels: dict[str, QLabel] = {}
        for shape in SHAPES:
            grid.addWidget(QLabel(f"{shape}:"), r, 0)
            label = QLabel("0")
            label.setAlignment(Qt.AlignRight)
            grid.addWidget(label, r, 1)
            self._shape_count_labels[shape] = label
            r += 1
        grid.addWidget(QLabel("Total ROIs:"), r, 0)
        self._total_label = QLabel("0")
        self._total_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._total_label, r, 1)
        r += 1
        grid.addWidget(QLabel("Cached Regions:"), r, 0)
        self._cached_label = QLabel("0/5")
        self._cached_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._cached_label, r, 1)
        r += 1
        grid.addWidget(QLabel("Dirty Regions:"), r, 0)
        self._dirty_label = QLabel("none")
        self._dirty_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._dirty_label, r, 1)
        r += 1
        grid.addWidget(QLabel("Batch Calls:"), r, 0)
        self._batch_label = QLabel("0")
        self._batch_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._batch_label, r, 1)
        r += 1
        grid.addWidget(QLabel("Processing Time:"), r, 0)
        self._processing_label = QLabel("--")
        self._processing_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._processing_label, r, 1)
        r += 1
        grid.addWidget(QLabel("FPS:"), r, 0)
        self._fps_label = QLabel("--")
        self._fps_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._fps_label, r, 1)
        r += 1
        grid.addWidget(QLabel("Frame Number:"), r, 0)
        self._frame_label = QLabel("0")
        self._frame_label.setAlignment(Qt.AlignRight)
        grid.addWidget(self._frame_label, r, 1)
        return group

    def _build_event_log(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        self._event_log = QPlainTextEdit()
        self._event_log.setReadOnly(True)
        self._event_log.setFixedHeight(160)
        self._event_log.setMaximumBlockCount(400)
        self._event_log.setPlaceholderText(
            "Prototype — warnings, errors and user actions only.")
        row.addWidget(self._event_log, 1)
        return wrapper

    # ==================================================================
    # Camera operations
    # ==================================================================

    def _on_discover(self) -> None:
        self._log_action("Discovering cameras...")
        self._discover_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            discovery = CameraDiscovery()
            self._camera_infos = discovery.discover()
            self._log_action(f"Discovered {len(self._camera_infos)} camera(s).")
        except Exception as exc:
            self._log_error(f"Discovery error: {exc}")
            traceback.print_exc()
        finally:
            self._discover_btn.setEnabled(True)
            self._connect_btn.setEnabled(len(self._camera_infos) > 0)

    def _on_connect(self) -> None:
        if not self._camera_infos:
            self._log_warning("No camera to connect to.")
            return
        info = self._camera_infos[0]
        self._log_action(f"Connecting to {info.model} ({info.serial})...")
        self._connect_btn.setEnabled(False)
        try:
            self._camera = TV46LCamera(info, self._settings)
            self._camera.connect()
            self._camera.start()
            if not self._camera.wait_for_first_frame(timeout=10.0):
                raise RuntimeError("No frames received within 10 s.")
            self._calibration = CalibrationManager()
            try:
                self._calibration.initialize()
                self._log_action("Calibration loaded.")
            except Exception as exc:
                self._calibration = None
                self._log_warning(f"Calibration unavailable (raw mode): {exc}")
            self._disconnect_btn.setEnabled(True)
            self._focus_near_btn.setEnabled(True)
            self._focus_far_btn.setEnabled(True)
            self._nuc_btn.setEnabled(True)
            self._log_action(f"Camera {info.serial} streaming.")
            self._poll_timer.start()
        except Exception as exc:
            self._log_error(f"Connection failed: {exc}")
            traceback.print_exc()
            self._connect_btn.setEnabled(True)

    def _on_focus_near(self) -> None:
        self._run_focus("Focus -", lambda camera: camera.focus_near())

    def _on_focus_far(self) -> None:
        self._run_focus("Focus +", lambda camera: camera.focus_far())

    def _run_focus(self, label: str, command: Callable[[TV46LCamera], tuple[float, float]]) -> None:
        camera = self._camera
        if camera is None:
            return
        if not camera.focus_available():
            self._log_warning("Focus not available on this camera.")
            self._focus_near_btn.setEnabled(False)
            self._focus_far_btn.setEnabled(False)
            return
        try:
            target, actual = command(camera)
            self._log_action(f"{label} -> target {target:.0f} mm, actual {actual:.0f} mm")
        except Exception as exc:
            self._log_error(f"{label} failed: {exc}")

    def _on_manual_nuc(self) -> None:
        camera = self._camera
        if camera is None:
            return
        try:
            camera.manual_nuc()
            self._log_action("Manual NUC triggered.")
        except Exception as exc:
            self._log_error(f"Manual NUC failed: {exc}")

    def _on_disconnect(self) -> None:
        self._poll_timer.stop()
        self._log_action("Disconnecting camera...")
        self._finish_editing()

        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.disconnect()
            except Exception as exc:
                self._log_warning(f"Disconnect error: {exc}")
            self._camera = None
        self._calibration = None
        self._view.clear_display()
        self._disconnect_btn.setEnabled(False)
        self._focus_near_btn.setEnabled(False)
        self._focus_far_btn.setEnabled(False)
        self._nuc_btn.setEnabled(False)
        self._connect_btn.setEnabled(len(self._camera_infos) > 0)
        self._fps = 0.0

    # ==================================================================
    # Pipeline (separated stages)
    # ==================================================================

    def _poll_frame(self) -> None:
        if self._camera is None or self._benchmarking:
            return
        frame = self._camera.grab_frame()
        if frame is None:
            return
        acquire_ms = max(0.0, (frame.publish_time - frame.grab_start_time) * 1000.0)
        self._process_frame(frame.image, acquire_ms)

    def _process_frame(self, raw: np.ndarray, acquire_ms: float) -> bool:
        """Run the full pipeline on one frame and update the panel.

        The display loop performs acquire -> convert -> display -> cached
        overlays.  Region generation, geometry reads and label rendering
        never run here: the region cache is only rebuilt on edits and the
        label canvas only when the rounded statistics change.
        """
        if self._benchmarking:
            return False
        if raw is None or raw.size == 0:
            return False
        t0 = time.perf_counter()

        # 1. Calibration (raw -> temperature -> display, colormap).
        temp = self._build_temperature_image(raw)
        display = self._build_display_image(temp)
        t1 = time.perf_counter()

        # 2. Statistics path (throttled; display FPS is decoupled).
        run_stats = self._store.total() > 0
        now_stats = time.perf_counter()
        run_stats = run_stats and (now_stats - self._last_stats_time) * 1000.0 >= STATS_INTERVAL_MS
        if run_stats:
            self._last_stats_time = now_stats
            himage = self._temperature_to_himage(temp)
            t2 = time.perf_counter()
            self._stats_engine.process(himage, self._store, self._cache)
            t3 = time.perf_counter()
            self._alarms = self._alarm_engine.evaluate(
                self._stats_engine.last_results)
            self._stats_ran_since_labels = True
        else:
            t2 = t3 = t1
            if self._store.total() == 0:
                self._stats_engine.last_results = {}
                self._alarms = {}
        t4 = time.perf_counter()

        # 3. Labels (cached canvas; rendered on the worker thread).
        self._request_labels()
        self._compose_labels(display)
        t5 = time.perf_counter()

        # 4. Display: cached overlay pieces + HALCON window.
        overlays = self._overlay_rows()
        display_ms = self._view.display_rgb(display, overlays)
        t6 = time.perf_counter()

        self._temp_image = temp
        self._frame_number += 1
        self._update_fps()

        breakdown = getattr(self._view, "last_breakdown", {}) or {}
        self._last_timing = {
            "acquire_ms": float(acquire_ms),
            "calibration_ms": (t1 - t0) * 1000.0,
            "himage_ms": (t2 - t1) * 1000.0,
            "stats_ms": (t3 - t2) * 1000.0,
            "alarm_ms": (t4 - t3) * 1000.0,
            "label_ms": (t5 - t4) * 1000.0,
            "overlay_ms": 0.0,
            "display_convert_ms": float(breakdown.get("convert_ms", 0.0)),
            "display_image_ms": float(breakdown.get("image_ms", 0.0)),
            "display_overlay_ms": float(breakdown.get("overlay_ms", 0.0)),
            "display_flush_ms": float(breakdown.get("flush_ms", 0.0)),
            "processing_ms": (t4 - t0) * 1000.0,
            "display_ms": display_ms,
            "total_ms": (t6 - t0) * 1000.0,
        }
        self._update_processing_labels()
        self._table_dirty = True
        return True

    def _build_temperature_image(self, raw: np.ndarray) -> np.ndarray:
        """Convert raw detector frame to float32 temperature.

        With a loaded calibration this is °C; without, raw counts.
        """
        if self._calibration is not None and self._calibration.is_initialized:
            try:
                temp = self._calibration.raw_to_temperature(raw)
                return np.nan_to_num(temp, nan=0.0, posinf=0.0, neginf=0.0)
            except Exception:
                pass
        return raw.astype(np.float32)

    def _build_display_image(self, temp: np.ndarray) -> np.ndarray:
        """Build the 8-bit false-colour display; never modifies raw data."""
        finite = temp[np.isfinite(temp)]
        normalized = np.zeros(temp.shape, dtype=np.uint8)
        if finite.size > 0:
            minimum = float(finite.min())
            maximum = float(finite.max())
            if maximum <= minimum:
                maximum = minimum + 1.0
            normalized = np.clip((temp - minimum) / (maximum - minimum), 0.0, 1.0)
            normalized = (normalized * 255.0).astype(np.uint8)
        return cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)

    def _temperature_to_himage(self, temp: np.ndarray) -> HObject:
        temp = np.ascontiguousarray(temp.astype(np.float32, copy=False))
        h, w = temp.shape
        return ha.gen_image1("real", w, h, int(temp.ctypes.data))

    def _overlay_rows(self) -> list[tuple[HObject | None, Any]]:
        """Overlay pieces: 1 px outline contours of the cached regions.

        Only the OUTLINE is displayed — the filled regions exist
        internally for statistics and are never shown. The ROI that is
        currently being edited is skipped: its drawing object is rendered
        by HALCON itself. Hidden ROIs are skipped. Alarm ROIs are drawn
        red, everything else uses its stored colour.

        The pieces are cached and rebuilt only when geometry, visibility,
        colour, selection or the alarm state changes — never per frame.
        """
        if (not self._overlay_stale
                and self._overlay_store_rev == self._store.rev
                and self._drawn_alarms == frozenset(self._alarms.items())
                and self._overlay_pieces is not None):
            return self._overlay_pieces
        self._overlay_pieces = self._build_overlay_pieces()
        self._drawn_alarms = frozenset(self._alarms.items())
        self._overlay_stale = False
        self._overlay_store_rev = self._store.rev
        return self._overlay_pieces

    def _mark_overlay_stale(self) -> None:
        self._overlay_stale = True

    def _build_overlay_pieces(self) -> list[tuple[HObject | None, Any]]:
        """Group visible outlines by colour, one ``select_obj`` per group.

        The number of groups is small (stored colour + red for alarms),
        so this runs only when the overlay actually changes.
        """
        pieces: list[tuple[HObject | None, Any]] = []
        for shape in SHAPES:
            outlines = self._cache.outlines(shape, self._store)
            if outlines is None:
                continue
            arrays = self._store.arrays(shape)
            groups: dict[str, list[int]] = {}
            for i, name in enumerate(arrays["name"]):
                if not arrays["visible"][i]:
                    continue
                if arrays["draw_object"][i] is not None:
                    continue
                colour = ALARM_COLOR if self._alarms.get(name, False) else str(arrays["color"][i])
                groups.setdefault(colour, []).append(i + 1)
            for colour, indices in groups.items():
                try:
                    visible = ha.select_obj(outlines, indices)
                except Exception:
                    continue
                pieces.append((visible, colour))
        return pieces

    @staticmethod
    def _label_anchor(shape: str, arrays: dict, index: int) -> tuple[float, float]:
        """Top-left corner of a ROI's bounding box (label placement)."""
        if shape == "Rectangle1":
            return float(arrays["row1"][index]), float(arrays["col1"][index])
        if shape == "Rectangle2":
            return (float(arrays["row"][index]) - float(arrays["length1"][index]),
                    float(arrays["col"][index]) - float(arrays["length2"][index]))
        if shape == "Circle":
            return (float(arrays["row"][index]) - float(arrays["radius"][index]),
                    float(arrays["col"][index]) - float(arrays["radius"][index]))
        if shape == "Ellipse":
            return (float(arrays["row"][index]) - float(arrays["radius1"][index]),
                    float(arrays["col"][index]) - float(arrays["radius2"][index]))
        rows_p, cols_p = arrays["points"][index]
        return float(min(rows_p)), float(min(cols_p))

    def _draw_roi_labels(self, display: np.ndarray) -> None:
        """Synchronous render + compose (used by smoke/harness tests).

        The live pipeline calls ``_request_labels()`` + ``_compose_labels()``
        instead, which render on a worker thread and never block the GUI.
        """
        _, rows = self._build_label_rows()
        canvas = self._render_label_canvas(rows)
        self._publish_label_canvas(canvas, self._label_signature())
        self._compose_labels(display)

    def _publish_label_canvas(self, canvas: np.ndarray, sig: tuple) -> None:
        """Swap in a freshly rendered canvas (renderer thread or sync)."""
        rgb = np.ascontiguousarray(canvas[:, :, :3])
        alpha = canvas[:, :, 3]
        with self._label_lock:
            self._label_canvas = canvas
            self._label_rgb = rgb
            self._label_alpha = alpha
            self._label_canvas_sig = sig

    def _build_label_rows(self) -> tuple[tuple, list[tuple]]:
        """Snapshot the visible ROIs' anchors + rounded stats.

        Runs on the GUI thread (float + tuple work only); the result is
        consumed by the renderer thread.
        """
        results = self._stats_engine.last_results
        sig_parts: list[tuple] = []
        rows: list[tuple] = []
        for shape in SHAPES:
            arrays = self._store.arrays(shape)
            for i, name in enumerate(arrays["name"]):
                if not arrays["visible"][i]:
                    continue
                stats = results.get(name)
                if stats is None:
                    continue
                row, col = self._label_anchor(shape, arrays, i)
                sig_parts.append((
                    int(round(row * 10.0)), int(round(col * 10.0)),
                    int(round(stats["min"] * 10.0)),
                    int(round(stats["mean"] * 10.0)),
                    int(round(stats["max"] * 10.0)),
                ))
                rows.append((name, row, col, stats["min"], stats["mean"], stats["max"]))
        return tuple(sig_parts), rows

    def _label_signature(self) -> tuple:
        """Compact fingerprint of every visible ROI's anchor + stats.

        Built with integer rounding (0.1) so a stable thermal scene
        yields a stable signature and the text is never re-rendered.
        """
        sig, _ = self._build_label_rows()
        return sig

    def _request_labels(self) -> None:
        """Queue a label re-render when content or geometry changed.

        O(1) on the GUI thread in the steady state: without fresh
        statistics or a geometry edit nothing is re-rendered.  The
        snapshot build (O(n)) and the ``cv2.putText`` rendering happen
        at most every ``LABEL_THROTTLE_MS`` and off the GUI thread.
        """
        if not self._stats_ran_since_labels and self._label_store_rev == self._store.rev:
            return
        self._label_store_rev = self._store.rev
        self._stats_ran_since_labels = False
        now = time.perf_counter()
        if (now - self._label_request_time) * 1000.0 < LABEL_THROTTLE_MS:
            return
        self._label_request_time = now
        sig, rows = self._build_label_rows()
        if sig == self._label_canvas_sig:
            return
        with self._label_lock:
            self._label_pending_sig = sig
            self._label_pending_rows = rows

    def _label_worker(self) -> None:
        """Render label canvases off the GUI thread."""
        while not self._label_stop.is_set():
            with self._label_lock:
                sig = self._label_pending_sig
                rows = self._label_pending_rows
                if rows is not None:
                    self._label_pending_sig = None
                    self._label_pending_rows = None
            if rows is None:
                time.sleep(0.05)
                continue
            t0 = time.perf_counter()
            canvas = self._render_label_canvas(rows)
            self._label_render_last_ms = (time.perf_counter() - t0) * 1000.0
            self._publish_label_canvas(canvas, sig)

    def _render_label_canvas(self, rows: list[tuple]) -> np.ndarray:
        """Render every ROI label into an alpha canvas (BGRA, 0 = empty).

        Pure function over the snapshot rows; safe to call off-thread.
        """
        canvas = np.zeros((FEED_H, FEED_W, 4), dtype=np.uint8)
        for name, row, col, min_v, mean_v, max_v in rows:
            lines = (
                name,
                f"Min : {min_v:.1f}",
                f"Avg : {mean_v:.1f}",
                f"Max : {max_v:.1f}",
            )
            y = float(max(0.0, min(float(FEED_H), float(row))))
            for line in lines:
                y += 14.0
                if y > float(FEED_H) - 3.0:
                    break
                (metrics_w, _), _ = cv2.getTextSize(
                    line, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                x = float(max(0, min(int(col),
                                     max(0, FEED_W - metrics_w - 2))))
                pos = (int(round(x)), int(round(y)))
                cv2.putText(canvas, line, pos, cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (0, 0, 0, 255), 3, cv2.LINE_AA)
                cv2.putText(canvas, line, pos, cv2.FONT_HERSHEY_SIMPLEX,
                            0.4, (255, 255, 255, 255), 1, cv2.LINE_AA)
        return canvas

    def _compose_labels(self, display: np.ndarray) -> None:
        """Blit the cached label canvas onto the display (fast path).

        A single OpenCV masked copy: the alpha channel of the cached
        canvas is the mask, so only text pixels are touched.
        """
        alpha = self._label_alpha
        if alpha is None or not alpha.any():
            return
        cv2.copyTo(self._label_rgb, alpha, display)

    def _update_fps(self) -> None:
        now = time.perf_counter()
        self._fps_frames += 1
        elapsed = now - self._fps_start
        if elapsed >= 1.0:
            self._fps = self._fps_frames / elapsed
            self._fps_frames = 0
            self._fps_start = now

    # ==================================================================
    # ROI creation / editing (drawing objects are editing-only)
    # ==================================================================

    def _on_create_roi(self) -> None:
        shape = self._shape_combo.currentText()
        geometry = self._default_geometry(shape)
        _, index = self._store.add(shape, geometry)
        name = self._store.get_meta(shape, index, "name")
        self._cache.invalidate(shape)
        self._mark_overlay_stale()
        self._table_dirty = True
        self._selected_name = name
        self._start_editing(shape, index)
        self._log_action(f"ROI {name} created ({shape}).")
        self._update_selected_panel()

    def _default_geometry(self, shape: str) -> dict:
        if shape == "Rectangle1":
            return {
                "row1": FEED_H * 0.30, "col1": FEED_W * 0.30,
                "row2": FEED_H * 0.70, "col2": FEED_W * 0.70,
            }
        if shape == "Rectangle2":
            return {"row": FEED_H / 2.0, "col": FEED_W / 2.0, "phi": 0.0,
                    "length1": 80.0, "length2": 50.0}
        if shape == "Circle":
            return {"row": FEED_H / 2.0, "col": FEED_W / 2.0, "radius": 50.0}
        if shape == "Ellipse":
            return {"row": FEED_H / 2.0, "col": FEED_W / 2.0, "phi": 0.0,
                    "radius1": 80.0, "radius2": 45.0}
        return {"points": (
            [FEED_H * 0.30, FEED_H * 0.30, FEED_H * 0.70, FEED_H * 0.70],
            [FEED_W * 0.30, FEED_W * 0.70, FEED_W * 0.70, FEED_W * 0.30])}

    def _start_editing(self, shape: str, index: int) -> None:
        self._editing = self._create_editing_object(shape, index)

    def _create_editing_object(self, shape: str, index: int) -> tuple[str, int] | None:
        """Attach a transient drawing object for one ROI (editing only)."""
        if not self._view.is_handle_valid():
            if not self._view.create_window():
                return None
        geometry = self._store.get_geometry(shape, index)
        try:
            if shape == "Rectangle1":
                obj = ha.create_drawing_object_rectangle1(
                    geometry["row1"], geometry["col1"],
                    geometry["row2"], geometry["col2"])
            elif shape == "Rectangle2":
                obj = ha.create_drawing_object_rectangle2(
                    geometry["row"], geometry["col"], geometry["phi"],
                    geometry["length1"], geometry["length2"])
            elif shape == "Circle":
                obj = ha.create_drawing_object_circle(
                    geometry["row"], geometry["col"], geometry["radius"])
            elif shape == "Ellipse":
                obj = ha.create_drawing_object_ellipse(
                    geometry["row"], geometry["col"], geometry["phi"],
                    geometry["radius1"], geometry["radius2"])
            else:  # Polygon
                rows, cols = geometry["points"]
                obj = ha.create_drawing_object_xld(rows, cols)
            ha.attach_drawing_object_to_window(self._view.handle, obj)
            ha.set_drawing_object_params(obj, "color", SELECTED_COLOR)
        except Exception as exc:
            self._log_warning(f"Could not create drawing object: {exc}")
            return None
        self._store.set_meta(shape, index, "draw_object", obj)
        return shape, index

    def _finish_editing(self) -> None:
        """Detach and destroy the active drawing object.

        Geometry is already synchronised into the arrays by the edit
        poll timer; the object is only an editing tool.
        """
        if self._editing is None:
            return
        shape, index = self._editing
        obj = self._store.get_meta(shape, index, "draw_object")
        self._store.set_meta(shape, index, "draw_object", None)
        self._editing = None
        if obj is not None and self._view.is_handle_valid():
            try:
                ha.detach_drawing_object_from_window(obj, self._view.handle)
                ha.clear_drawing_object(obj)
                self._cache.invalidate(shape)
                self._mark_overlay_stale()
            except Exception:
                pass

    def _sync_editing_object(self) -> None:
        """Poll the active drawing object for edits.

        Drawing objects are ONLY for editing. When their geometry does
        not match the arrays, the arrays are updated immediately and the
        region cache for that type is invalidated. Statistics always
        read geometry from the cached arrays.
        """
        if self._editing is None or self._benchmarking:
            return
        shape, index = self._editing
        obj = self._store.get_meta(shape, index, "draw_object")
        if obj is None:
            return
        try:
            geometry = self._drawing_geometry(shape, obj)
        except Exception:
            return
        if geometry is None:
            return
        current = self._store.get_geometry(shape, index)
        if not self._geometry_differs(current, geometry):
            return
        self._store.update_geometry(shape, index, geometry)
        self._cache.invalidate(shape)
        self._mark_overlay_stale()
        self._table_dirty = True
        self._update_selected_panel()
        name = self._store.get_meta(shape, index, "name")
        self._log_action(f"ROI {name} geometry updated.")

    def _drawing_geometry(self, shape: str, obj: Any) -> dict | None:
        """Read geometry out of a drawing object (editing bridge only).

        ``get_drawing_object_params`` with a parameter list returns one
        flat list in the requested order. HALCON names columns "column",
        the storage uses "col"; values are mapped to storage keys so the
        arrays stay the single source of truth.
        """
        if shape == "Rectangle1":
            values = ha.get_drawing_object_params(
                obj, ["row1", "column1", "row2", "column2"])
            return {"row1": float(values[0]), "col1": float(values[1]),
                    "row2": float(values[2]), "col2": float(values[3])}
        if shape == "Rectangle2":
            values = ha.get_drawing_object_params(
                obj, ["row", "column", "phi", "length1", "length2"])
            return {"row": float(values[0]), "col": float(values[1]),
                    "phi": float(values[2]), "length1": float(values[3]),
                    "length2": float(values[4])}
        if shape == "Circle":
            values = ha.get_drawing_object_params(obj, ["row", "column", "radius"])
            return {"row": float(values[0]), "col": float(values[1]),
                    "radius": float(values[2])}
        if shape == "Ellipse":
            values = ha.get_drawing_object_params(
                obj, ["row", "column", "phi", "radius1", "radius2"])
            return {"row": float(values[0]), "col": float(values[1]),
                    "phi": float(values[2]), "radius1": float(values[3]),
                    "radius2": float(values[4])}
        iconic = ha.get_drawing_object_iconic(obj)
        rows, cols = ha.get_contour_xld(iconic)
        return {"points": (list(rows), list(cols))}

    @staticmethod
    def _geometry_differs(current: dict, new: dict, epsilon: float = 1e-6) -> bool:
        for key, value in new.items():
            if key == "points":
                cur_rows, cur_cols = current[key]
                new_rows, new_cols = value
                if (len(cur_rows) != len(new_rows)
                        or not all(abs(a - b) < epsilon for a, b in zip(cur_rows, new_rows))
                        or not all(abs(a - b) < epsilon for a, b in zip(cur_cols, new_cols))):
                    return True
                continue
            if abs(float(current[key]) - float(value)) >= epsilon:
                return True
        return False

    # ==================================================================
    # Selection / table / panel
    # ==================================================================

    def _on_table_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._selected_name = None
            self._finish_editing()
            self._update_selected_panel()
            return
        item0 = self._table.item(rows[0].row(), 0)
        if item0 is None:
            return
        name = item0.data(Qt.UserRole) or item0.text()
        if name == self._selected_name:
            return
        self._selected_name = name
        self._finish_editing()
        location = self._store.find_by_name(name)
        if location is not None:
            self._start_editing(*location)
        self._update_selected_panel()

    def _update_selected_panel(self) -> None:
        name = self._selected_name
        if name is None:
            for widget in (self._sel_name, self._sel_shape, self._sel_geometry,
                           self._sel_stats, self._sel_alarm):
                widget.setText("---")
            self._sel_enabled.setChecked(False)
            self._sel_visible.setChecked(False)
            self._sel_threshold.setValue(DEFAULT_THRESHOLD)
            self._sel_color_btn.setText(DEFAULT_COLOR)
            self._sel_color_btn.setStyleSheet(
                f"background-color: {DEFAULT_COLOR}; color: black;")
            return
        location = self._store.find_by_name(name)
        if location is None:
            return
        shape, index = location
        geometry = self._store.get_geometry(shape, index)
        self._sel_name.setText(name)
        self._sel_shape.setText(shape)
        self._sel_geometry.setText(self._geometry_text(shape, geometry))
        stats = self._stats_engine.last_results.get(name)
        if stats is None:
            self._sel_stats.setText("--")
        else:
            self._sel_stats.setText(
                f"min {stats['min']:.2f}  avg {stats['mean']:.2f}  "
                f"max {stats['max']:.2f}  area {stats['area']:.0f}")
        alarm = self._alarms.get(name, False)
        self._sel_alarm.setText("ALARM" if alarm else "OK")
        self._sel_alarm.setStyleSheet("color: red;" if alarm else "color: green;")
        self._sel_enabled.setChecked(bool(self._store.get_meta(shape, index, "enabled")))
        self._sel_visible.setChecked(bool(self._store.get_meta(shape, index, "visible")))
        self._sel_threshold.setValue(float(self._store.get_meta(shape, index, "threshold")))
        color = str(self._store.get_meta(shape, index, "color"))
        self._sel_color_btn.setText(color)
        self._sel_color_btn.setStyleSheet(f"background-color: {color}; color: black;")

    def _geometry_text(self, shape: str, geometry: dict) -> str:
        try:
            if shape == "Rectangle1":
                return (f"r1={geometry['row1']:.1f} c1={geometry['col1']:.1f} "
                        f"r2={geometry['row2']:.1f} c2={geometry['col2']:.1f}")
            if shape == "Rectangle2":
                return (f"r={geometry['row']:.1f} c={geometry['col']:.1f} "
                        f"phi={geometry['phi']:.3f} l1={geometry['length1']:.1f} "
                        f"l2={geometry['length2']:.1f}")
            if shape == "Ellipse":
                return (f"r={geometry['row']:.1f} c={geometry['col']:.1f} "
                        f"phi={geometry['phi']:.3f} r1={geometry['radius1']:.1f} "
                        f"r2={geometry['radius2']:.1f}")
            if shape == "Circle":
                return (f"r={geometry['row']:.1f} c={geometry['col']:.1f} "
                        f"radius={geometry['radius']:.1f}")
            rows_c, _ = geometry["points"]
            return f"({len(rows_c)} pts)"
        except Exception:
            return "?"

    def _on_pick_selected_color(self) -> None:
        if self._selected_name is None:
            return
        location = self._store.find_by_name(self._selected_name)
        if location is None:
            return
        shape, index = location
        current = str(self._store.get_meta(shape, index, "color"))
        color = QColorDialog.getColor(QColor(current), self, "Pick ROI Color")
        if not color.isValid():
            return
        self._store.set_meta(shape, index, "color", color.name())
        self._mark_overlay_stale()
        editing_obj = self._store.get_meta(shape, index, "draw_object")
        if editing_obj is not None and self._view.is_handle_valid():
            try:
                ha.set_drawing_object_params(editing_obj, "color", color.name())
            except Exception as exc:
                self._log_warning(f"Could not apply colour to drawing object: {exc}")
        self._table_dirty = True
        self._update_selected_panel()

    def _on_selected_meta_changed(self, checked: bool) -> None:
        if self._selected_name is None:
            return
        location = self._store.find_by_name(self._selected_name)
        if location is None:
            return
        shape, index = location
        self._store.set_meta(shape, index, "enabled", checked)
        self._table_dirty = True

    def _on_selected_visible_changed(self, checked: bool) -> None:
        if self._selected_name is None:
            return
        location = self._store.find_by_name(self._selected_name)
        if location is None:
            return
        shape, index = location
        self._store.set_meta(shape, index, "visible", checked)
        self._mark_overlay_stale()
        self._table_dirty = True

    def _on_selected_threshold_changed(self, value: float) -> None:
        if self._selected_name is None:
            return
        location = self._store.find_by_name(self._selected_name)
        if location is None:
            return
        shape, index = location
        self._store.set_meta(shape, index, "threshold", float(value))
        self._table_dirty = True

    # ==================================================================
    # ROI table refresh (throttled)
    # ==================================================================

    def _on_filter_changed(self) -> None:
        self._table_dirty = True
        self._refresh_table()

    def _refresh_table(self) -> None:
        if not self._table_dirty:
            return
        self._table_dirty = False
        search = self._search_edit.text().strip().lower()
        shape_filter = self._shape_filter.currentText()

        rows = []
        for shape, index, entry in self._store.entries():
            if shape_filter != "All" and shape != shape_filter:
                continue
            name = entry["name"]
            if search and search not in name.lower():
                continue
            rows.append((shape, entry))

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row_index, (shape, entry) in enumerate(rows):
            name = entry["name"]
            stats = self._stats_engine.last_results.get(name)
            alarm = self._alarms.get(name, False)
            min_v = avg_v = max_v = area_v = "--"
            if stats is not None:
                min_v = f"{stats['min']:.2f}"
                avg_v = f"{stats['mean']:.2f}"
                max_v = f"{stats['max']:.2f}"
                area_v = f"{stats['area']:.0f}"
            values = [
                name,
                shape,
                "yes" if entry["enabled"] else "no",
                "yes" if entry["visible"] else "no",
                "ALARM" if alarm else "no",
                min_v,
                avg_v,
                max_v,
                area_v,
                f"{entry['threshold']:.1f}",
                entry["color"],
                self._position_text(shape, entry),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, name)
                if col == 4 and alarm:
                    item.setForeground(QColor("red"))
                self._table.setItem(row_index, col, item)
        self._table.setSortingEnabled(True)

    def _position_text(self, shape: str, entry: dict) -> str:
        if shape == "Rectangle1":
            return (f"({entry['row1']:.0f},{entry['col1']:.0f})-"
                    f"({entry['row2']:.0f},{entry['col2']:.0f})")
        if shape in ("Rectangle2", "Ellipse", "Circle"):
            return f"({entry['row']:.0f},{entry['col']:.0f})"
        poly_rows, _ = entry["points"]
        return f"{len(poly_rows)} pts"

    def _on_delete_selected(self) -> None:
        names = set()
        touched: set[str] = set()
        for index in self._table.selectionModel().selectedRows():
            item = self._table.item(index.row(), 0)
            if item is not None:
                names.add(item.data(Qt.UserRole) or item.text())
        if not names:
            return
        if QMessageBox.question(self, "Delete", f"Delete {len(names)} ROI(s)?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for name in names:
            location = self._store.find_by_name(name)
            if location is not None:
                touched.add(location[0])
            self._store.remove_by_name(name)
        if self._selected_name in names:
            self._selected_name = None
            self._finish_editing()
        for shape in touched:
            self._cache.invalidate(shape)
        self._mark_overlay_stale()
        self._table_dirty = True
        self._update_selected_panel()
        self._log_action(f"Deleted {len(names)} ROI(s).")

    def _on_duplicate_selected(self) -> None:
        names = set()
        touched: set[str] = set()
        for index in self._table.selectionModel().selectedRows():
            item = self._table.item(index.row(), 0)
            if item is not None:
                names.add(item.data(Qt.UserRole) or item.text())
        if not names:
            return
        for name in names:
            location = self._store.find_by_name(name)
            if location is None:
                continue
            shape, index = location
            self._store.duplicate(shape, index)
            touched.add(shape)
        for shape in touched:
            self._cache.invalidate(shape)
        self._mark_overlay_stale()
        self._table_dirty = True
        self._log_action(f"Duplicated {len(names)} ROI(s).")

    def _on_clear_all(self) -> None:
        if self._store.total() == 0:
            return
        if QMessageBox.question(self, "Clear All", "Remove ALL ROIs?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._finish_editing()
        self._store.clear()
        self._cache.invalidate_all()
        self._mark_overlay_stale()
        self._selected_name = None
        self._table_dirty = True
        self._update_selected_panel()
        self._log_action("Cleared all ROIs.")

    # ==================================================================
    # Save / Load
    # ==================================================================

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROI Layout", "roi_layout.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._store.serialize(), fh, indent=2)
            self._log_action(f"Saved {self._store.total()} ROIs to {path}.")
        except Exception as exc:
            self._log_error(f"Save failed: {exc}")

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load ROI Layout", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._finish_editing()
            self._store.from_dict(data)
            self._cache.invalidate_all()
            self._mark_overlay_stale()
            self._table_dirty = True
            self._selected_name = None
            self._update_selected_panel()
            self._log_action(f"Loaded {self._store.total()} ROIs from {path}")
        except Exception as exc:
            self._log_error(f"Load failed: {exc}")

    # ==================================================================
    # Benchmark
    # ==================================================================

    def _on_benchmark(self) -> None:
        if self._benchmarking:
            return
        self._benchmarking = True
        self._benchmark_btn.setEnabled(False)
        self._finish_editing()
        snap = self._store.snapshot()
        try:
            rows = []
            for count in BENCHMARK_COUNTS:
                row = self._run_benchmark_count(count)
                if row is not None:
                    rows.append(row)
                    self._log_action(
                        f"Bench {count} ROIs: total {row['total_ms']:.1f} ms "
                        f"({row['fps']:.1f} FPS), stats {row['stats_ms']:.1f} ms, "
                        f"max stat error {row['max_stat_error']:.2e}")
                QApplication.processEvents()
            if rows:
                self._export_benchmark_csv(rows)
        finally:
            self._store.restore(snap)
            self._cache.invalidate_all()
            self._mark_overlay_stale()
            self._label_canvas_sig = None
            self._table_dirty = True
            self._benchmarking = False
            self._benchmark_btn.setEnabled(True)
        self._log_action("Benchmark finished; previous layout restored.")

    def _export_benchmark_csv(self, rows: list[dict]) -> None:
        folder = BENCHMARK_FOLDER
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            folder = Path(".")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / f"prototype_roi_benchmark_{stamp}.csv"
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            self._log_action(f"Benchmark CSV: {path}")
        except Exception as exc:
            self._log_error(f"CSV export failed: {exc}")

    def _run_benchmark_count(self, count: int) -> dict | None:
        self._store.clear()
        self._create_benchmark_grid(count)
        self._cache.invalidate_all()
        self._table_dirty = True
        seed = 10000 + count
        for i in range(BENCHMARK_WARMUP):
            self._process_benchmark_frame(_synthetic_frame(seed + i), count)
        frames = []
        for i in range(BENCHMARK_FRAMES):
            row = self._process_benchmark_frame(_synthetic_frame(seed + 100 + i), count)
            if row is not None:
                frames.append(row)
        if not frames:
            return None
        aggregated: dict[str, float] = {}
        keys = (
            "calibration_ms", "display_prep_ms", "himage_ms", "stats_ms",
            "stats_peak_ms", "stats_rect1_ms", "alarm_ms", "label_main_ms",
            "overlay_ms", "display_convert_ms", "display_image_ms",
            "display_overlay_ms", "display_flush_ms", "verify_ms",
            "processing_ms", "display_ms", "total_ms",
        )
        for key in keys:
            values = sorted(f[key] for f in frames)
            aggregated[key] = values[len(values) // 2]
        aggregated["stats_peak_ms"] = max(f["stats_peak_ms"] for f in frames)
        aggregated["roi_count"] = count
        aggregated["fps"] = 1000.0 / aggregated["total_ms"] if aggregated["total_ms"] > 0 else 0.0
        aggregated["max_stat_error"] = max(f["max_stat_error"] for f in frames)
        aggregated["batch_calls"] = int(frames[-1]["batch_calls"])
        return aggregated

    def _process_benchmark_frame(self, raw: np.ndarray, count: int) -> dict | None:
        """One measured frame: calibration -> stats -> alarm -> display.

        Uses the same decoupled cadence as the live pipeline (statistics
        every ``STATS_INTERVAL_MS``).  ``stats_ms`` is the amortized
        per-frame cost, ``stats_peak_ms`` the cost of a single batch run.
        ``verify_ms`` (numpy cross-check) is reported separately and is
        NOT part of the pipeline timings: it is benchmark tooling, not
        production work.
        """
        t0 = time.perf_counter()
        temp = self._build_temperature_image(raw)
        t_cal = time.perf_counter()
        display = self._build_display_image(temp)
        t1 = time.perf_counter()
        stats_ms = 0.0
        stats_peak_ms = 0.0
        verify_ms = 0.0
        error = 0.0
        now_stats = time.perf_counter()
        if (now_stats - self._last_stats_time) * 1000.0 >= STATS_INTERVAL_MS:
            self._last_stats_time = now_stats
            himage = self._temperature_to_himage(temp)
            t2 = time.perf_counter()
            results = self._stats_engine.process(himage, self._store, self._cache)
            t3 = time.perf_counter()
            self._alarms = self._alarm_engine.evaluate(results)
            t4 = time.perf_counter()
            self._stats_ran_since_labels = True
            stats_ms = (t3 - t2) * 1000.0
            stats_peak_ms = stats_ms
            tv = time.perf_counter()
            error = self._verify_rect1_statistics(results, temp)
            verify_ms = (time.perf_counter() - tv) * 1000.0
        else:
            t2 = t3 = t4 = t1
        self._request_labels()
        self._compose_labels(display)
        t5 = time.perf_counter()
        overlays = self._overlay_rows()
        t6 = time.perf_counter()
        display_ms = self._view.display_rgb(display, overlays)
        t7 = time.perf_counter()
        self._temp_image = temp
        self._frame_number += 1
        breakdown = getattr(self._view, "last_breakdown", {}) or {}
        return {
            "calibration_ms": (t_cal - t0) * 1000.0,
            "display_prep_ms": (t1 - t_cal) * 1000.0,
            "himage_ms": (t2 - t1) * 1000.0,
            "stats_ms": stats_ms,
            "stats_peak_ms": stats_peak_ms,
            "stats_rect1_ms": float(self._stats_engine.last_shape_ms.get("Rectangle1", 0.0)),
            "alarm_ms": (t4 - t3) * 1000.0,
            "label_main_ms": (t5 - t4) * 1000.0,
            "overlay_ms": (t6 - t5) * 1000.0,
            "display_convert_ms": float(breakdown.get("convert_ms", 0.0)),
            "display_image_ms": float(breakdown.get("image_ms", 0.0)),
            "display_overlay_ms": float(breakdown.get("overlay_ms", 0.0)),
            "display_flush_ms": float(breakdown.get("flush_ms", 0.0)),
            "verify_ms": verify_ms,
            "processing_ms": (t4 - t0) * 1000.0,
            "display_ms": display_ms,
            "total_ms": (t7 - t0) * 1000.0,
            "max_stat_error": error,
            "batch_calls": self._stats_engine.batch_calls + self._cache.batch_calls,
        }

    def _verify_rect1_statistics(self, results: dict[str, dict],
                                 temp: np.ndarray) -> float:
        """Cross-check batch mean/min/max against a numpy reference.

        For Rectangle1 the bbox slice IS the region, so the comparison
        is exact; this validates that the batch HALCON results are
        correct at every ROI count.
        """
        max_error = 0.0
        arrays = self._store.arrays("Rectangle1")
        for i, name in enumerate(arrays["name"]):
            r1 = int(round(arrays["row1"][i]))
            r2 = int(round(arrays["row2"][i]))
            c1 = int(round(arrays["col1"][i]))
            c2 = int(round(arrays["col2"][i]))
            if not (0 <= r1 <= r2 < temp.shape[0] and 0 <= c1 <= c2 < temp.shape[1]):
                continue
            patch = temp[r1:r2 + 1, c1:c2 + 1]
            stats = results.get(name)
            if stats is None:
                continue
            max_error = max(
                max_error,
                abs(stats["mean"] - float(np.mean(patch))),
                abs(stats["min"] - float(np.min(patch))),
                abs(stats["max"] - float(np.max(patch))),
            )
        return float(max_error)

    def _create_benchmark_grid(self, count: int) -> None:
        cols = max(1, min(64, count))
        rows_needed = max(1, math.ceil(count / cols))
        cell_w = FEED_W / cols
        cell_h = FEED_H / rows_needed
        rect_w = max(2.0, cell_w * 0.5)
        rect_h = max(2.0, cell_h * 0.5)
        for i in range(count):
            x = (i % cols) * cell_w + (cell_w - rect_w) / 2.0
            y = (i // cols) * cell_h + (cell_h - rect_h) / 2.0
            r1, c1 = int(round(y)), int(round(x))
            r2, c2 = int(round(y + rect_h)), int(round(x + rect_w))
            self._store.add(
                "Rectangle1",
                {"row1": r1, "col1": c1, "row2": r2, "col2": c2},
                name=f"Bench_{count}_{i}")

    # ==================================================================
    # Mouse temperature read-out
    # ==================================================================

    def _poll_mouse(self) -> None:
        if self._benchmarking:
            return
        point = self._view.poll_mouse()
        if point is None:
            self._mouse_label.setText(
                "X: --   Y: --   T: --   ROI: --   Frame: --")
            return
        row, col, _button = point
        temp_str = "--"
        if self._temp_image is not None:
            try:
                temp_val = float(self._temp_image[row, col])
                if math.isfinite(temp_val):
                    temp_str = f"{temp_val:.2f} °C"
            except Exception:
                temp_str = "--"
        hit = self._store.hit_test(row, col)
        roi_name = hit[2] if hit else "--"
        self._mouse_label.setText(
            f"X: {int(col)}   Y: {int(row)}   T: {temp_str}   "
            f"ROI: {roi_name}   Frame: {self._frame_number}")
        self._zoom_label.setText(f"{int(round(self._view.zoom_factor * 100))}%")

    # ==================================================================
    # Processing information panel
    # ==================================================================

    def _update_processing_labels(self) -> None:
        counts = self._store.counts()
        for shape in SHAPES:
            self._shape_count_labels[shape].setText(str(counts[shape]))
        self._total_label.setText(str(self._store.total()))
        self._cached_label.setText(f"{len(self._cache.cached_types())}/5")
        dirty = self._cache.dirty_types()
        self._dirty_label.setText(", ".join(dirty) if dirty else "none")
        self._batch_label.setText(
            str(self._stats_engine.batch_calls + self._cache.batch_calls))
        timing = self._last_timing
        if timing:
            self._processing_label.setText(f"{timing['processing_ms']:.1f} ms")
            self._fps_label.setText(f"{self._fps:.1f}")
        self._frame_label.setText(str(self._frame_number))

    # ==================================================================
    # Single-line event log (actions / warnings / errors only)
    # ==================================================================

    def _set_event_log(self, tag: str, msg: str) -> None:
        self._event_log.appendPlainText(f"[{_now_tag()}] {tag}: {msg}")

    def _log_action(self, msg: str) -> None:
        self._set_event_log("ACTION", msg)

    def _log_warning(self, msg: str) -> None:
        self._set_event_log("WARN", msg)

    def _log_error(self, msg: str) -> None:
        self._set_event_log("ERROR", msg)

    # ==================================================================
    # Cleanup
    # ==================================================================

    def closeEvent(self, event) -> None:  # noqa: N802
        self._poll_timer.stop()
        self._mouse_timer.stop()
        self._edit_timer.stop()
        self._table_timer.stop()
        self._label_stop.set()
        self._label_thread.join(timeout=1.0)
        self._finish_editing()
        if self._camera is not None:
            try:
                self._camera.stop()
                self._camera.disconnect()
            except Exception:
                pass
            self._camera = None
        self._view.close_window()
        event.accept()


# ==========================================================
# Entry point
# ==========================================================


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ROICalibrationPrototype()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
