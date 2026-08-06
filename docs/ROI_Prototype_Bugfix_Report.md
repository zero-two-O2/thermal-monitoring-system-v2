# ROI Calibration Prototype — Bug-Fix Report

Date: 2026-08-06
Scope: `halcon_roi_validation.py` (standalone prototype)
Constraint: no architectural changes, no production ROI Engine changes.

---

## 1. Root cause: filled ROI appearing in the image centre

**Confirmed.** `_overlay_rows()` displayed the statistics `RegionCache` regions
directly (`ha.disp_obj(regions, ...)`). Those regions are **filled** — they are
the exact objects used by `intensity` / `min_max_gray`. New ROIs are created
with default geometry near the image centre (Rectangle1 at 30-70%, Circle /
Rectangle2 / Ellipse at 50%), so every creation immediately showed a filled
patch there. The filled region is an internal statistics object and must never
be rendered.

**Fix:** the overlay now renders 1 px outline contours only:
`RegionCache` generates `ha.boundary(regions, "inner")` once per rebuild
(cached outlines), and `_overlay_rows` displays them via `select_obj`. The
filled regions remain internal (statistics only). Per-ROI colours are applied
with `set_color` before display.

## 2. Root cause: RegionCache / statistics staying fixed when an ROI is moved

**Confirmed (two stacked bugs).** The hypothesis was right:

1. `_drawing_geometry()` returned HALCON parameter names
   (`column1`, `column`) that do not match the storage keys (`col1`, `col`).
   `GroupedROIStorage.update_geometry()` filters with
   `if key in SHAPE_GEOMETRY[shape]`, so every edit was silently dropped —
   the geometry arrays never changed.
2. `get_drawing_object_params(obj, [list])` returns a **flat** value list in
   this HALCON binding (verified: `[10.5, 20.5, 50.0, 60.0]`), but the code
   indexed `values[0][0]` → `TypeError` → the sync method returned early.

Net effect: drawing object moved → arrays unchanged → cache never invalidated
→ statistics, overlay and table read stale geometry forever.

**Fix:** `_drawing_geometry()` unpacks the flat list and maps
`column1 -> col1`, `column -> col` for all four shapes (Polygon unchanged).
The chain now runs end-to-end on every edit poll (150 ms):

```
drawing object edit
  -> _sync_editing_object()
  -> arrays updated (single source of truth)
  -> RegionCache invalidated -> regions + outlines regenerated
  -> StatisticsEngine (per frame) -> fresh min/avg/max/area
  -> overlay outline + ROI labels + table follow the new position
```

Verified on the real display: move Rectangle1 to (300,400)-(350,450) →
arrays `(300,400)-(350,450)`, stats `max=100, area=2601`, table position
`(300,400)-(350,450)`.

## 3. HALCON drawing-object colour support

**Supported.** Verified against this build (mvtec-halcon, `open_window`
buffer):
- `set_drawing_object_params(obj, "color", ...)` works per object;
- two attached objects can hold different colours independently
  (`['yellow']` vs `['green']`).

**Decision:** the colour editor stays. The colour is now applied both to the
stored geometry array (overlay colour for non-selected ROIs, table column) and
to the live drawing object, so the change is visible immediately. Selection is
still unambiguous: on selection the drawing object is yellow until a colour is
picked. No colour support is faked.

## 4. Focus / Manual NUC APIs on the TV46L driver

**Exist** in `camera/tv46l_camera.py` (production driver, reused by the
prototype; the driver was not modified):

| Feature | API | Integrated |
|---|---|---|
| Focus in (nearer) | `focus_near(step_mm=250) -> (target, actual)` | `Focus -` button |
| Focus out (farther) | `focus_far(step_mm=250) -> (target, actual)` | `Focus +` button |
| Availability gate | `focus_available() -> bool` | buttons warn + disable if False |
| Auto focus | none (no autofocus operator on TV46L) | `Auto Focus` permanently disabled with tooltip |
| Manual NUC | `manual_nuc()` (sets a flag consumed by the acquisition thread; safe to call from the GUI thread) | `Manual NUC` button |

All three enabled only while a camera is connected (enabled in `_on_connect`,
disabled in `_on_disconnect`).

## 5. Event log

Was a single-line `QLineEdit`. Now a read-only `QPlainTextEdit`, fixed height
160 px (≈ 10-15 entries), capped at 400 blocks, appends instead of replacing.
Verified: 3 logged messages appear on 3 lines.

## 6. ROI labels

Drawn into the RGB display frame before HALCON display (`_draw_roi_labels`),
one label per visible ROI with statistics: name + `Min : x` / `Avg : x` /
`Max : x`, anchored at the ROI's top-left bounding-box corner (Rectangle1:
`(row1, col1)`; Rectangle2: `(row-length1, col-length2)`; Circle:
`(row-radius, col-radius)`; Ellipse: `(row-radius1, col-radius2)`; Polygon:
`min(rows), min(cols)`), clamped into the image, dark outline for readability.
Labels are computed every frame from the arrays + `last_results`, so they move
with the ROI and disappear when the ROI is hidden or deleted. Not drawn on the
benchmark path (no benchmark impact).

## 7. Selection, statistics, table, mouse, coordinate consistency

- **Selection:** selected ROI = yellow drawing object; others green by
  default (stored colour), alarms red. Verified in tests.
- **Statistics:** recomputed every frame from the regenerated regions; they
  follow the ROI immediately after an edit (verified numerically).
- **Table:** Position and statistics columns are filled from the arrays and
  `last_results` on the existing 500 ms refresh; no manual refresh needed.
- **Mouse info:** moved to the main-window status bar — `X`, `Y`, `T`,
  `ROI`, `Frame`, `Zoom` update continuously without clicks; frame counter
  added.
- **Coordinate consistency:** one source of truth — the geometry arrays.
  Drawing objects are read-only editing tools; `RegionCache` regions, cached
  outlines, statistics, overlay, table and labels all derive from the arrays.

## 8. Files modified

- `halcon_roi_validation.py` (all fixes; the only code file changed)
- `CHANGELOG.md`
- `docs/ROI_Prototype_Bugfix_Report.md` (this report)

Production modules (`camera/*`, `roi_engine/*`, `gui/*`) were **not**
modified.

## 9. Before / After screenshots

Not practical in this session (automated, headless/display tests). The visual
change is: filled region → 1 px outline; new ROIs start as outlines only;
selected ROI is yellow; labels appear at the ROI top-left. Reproduction of
before-state: any version prior to this fix displays filled regions.

## 10. Ruff and test status

- `ruff check halcon_roi_validation.py` → **All checks passed!** (two
  pre-existing F401/F841 fixed)
- `python -m py_compile` → OK
- Offscreen smoke suite 1 (storage/cache/stats/alarms) → 31/31 PASS
- Offscreen smoke suite 2 (geometry bridge for all 5 shapes, overlay
  outline/hidden/alarm rules, labels, buttons, log, status bar) → 17/17 PASS
- Real-display end-to-end (create → simulate drag → arrays → cache → stats →
  overlay → table → colour change → finish editing) → 12/12 PASS
- Live camera test (3 cameras discovered; connect; real calibrated stats
  27.1/27.9/28.8 °C; focus/NUC enabled; disconnect disables) → PASS
- Benchmark self-check (50/500/2000 ROIs, numpy cross-check error
  ≤ 0.003) → PASS; overlay FPS at 2000 ROIs improved 5.4 → 15.4 after
  caching the outlines in `RegionCache`.
