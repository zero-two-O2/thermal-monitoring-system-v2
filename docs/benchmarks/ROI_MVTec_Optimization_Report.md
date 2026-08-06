# ROI Prototype MVTec-Style Optimization Report

Generated 2026-08-06 14:30 by focused benchmarking of `halcon_roi_validation.py`
(`docs/benchmarks/ROI_MVTec_Optimization_Report.md`).

## Environment

| Item | Value |
|---|---|
| Python | 3.10.7 |
| mvtec-halcon | 24113.0.0 |
| opencv-python | 4.x |
| Synthetic image | 480x640 |
| Display | offscreen (Qt `offscreen`), real-window runs noted separately |
| Machine load | low; no competing heavy processes during runs |

## Objective

Validate the standalone ROI prototype against the MVTec-recommended batched-workflow
(12 principles) so the production files
(`roi_engine/`, `roi/`, `gui/`) stay untouched. Only
`halcon_roi_validation.py` was changed.

## MVTec Workflow Match Table

| # | Principle (MVTec utility) | Status | Notes |
|---|---|---|---|
| 1 | ROI creation once, reuse forever | PASS | Regions generated in `RegionCache._rebuild`, only on invalidate (create/edit/load/delete), never in the frame loop. |
| 2 | Group ROIs by type (arrays + one gen_* call) | PASS | `GroupedROIStorage` groups by shape type from v2; unchanged. |
| 3 | Batch statistics (intensity / min_max_gray / area_center) once per type | PASS | `StatisticsEngine.process` issues one batch call per type; no per-ROI loop on the hot path. |
| 4 | Never rebuild region tuples during streaming | PASS | Cache `rev` counter + dirty flags; frame path only reads cached objects. |
| 5 | Remove unnecessary overlay work | PASS | Overlay rebuild is now conditional (dirty flag OR `rev` change OR alarms changed). Per-frame cost ≈ a cached `select_obj` per color group. |
| 6 | ROI labels, only when stats change; separate display FPS from stats FPS | PASS | `_label_signature()` cache + `_stats_ran_since_labels`; label/stats cadence `STATS_INTERVAL_MS=200`, display cadence decoupled. |
| 7 | Display loop = acquire -> convert -> display -> cached overlays only | PASS | `_process_frame` does acquire, convert, stats, then overlay (cached) + label compose (cached) + display. |
| 8 | Geometry invalidation per shape (dirty flags per shape) | PASS | `update_geometry` marks only the moved shape dirty; delete/duplicate invalidate per shape. |
| 9 | RegionCache holds Rectangle1Regions/CircleRegions/... generated once | PASS | Verified during counting; each `RegionCache._rebuild()` regenerates all types but only when invalidated. |
| 10 | Internal profiler: per-stage breakdown | PARTIAL | Added `_stage_times` dict in `_process_frame` and `_process_benchmark_frame` (calibration, display_prep, himage, stats per shape, alarm, overlay, label, display sub-stages). Real-window HAL display costs measured separately; offscreen forces display=0. |
| 11 | Avoid excessive numpy<->HALCON<->QImage copies | PASS | Display conversion path is a single serialized RGB8 conversion (no per-ROI copies); label compose now `cv2.copyTo` one masked copy. Small numpy copy remains in `_build_display_image`. |
| 12 | Verify line-for-line against the supplied reference script | N/A | No reference script supplied. Validated behaviorally against the 12 principles + synthetic ground-truth + live camera. |

## Before / After Profiles

Profiles from `probe_roi_before.py` (baseline build) and `probe_roi_after.py`
(optimized build), offscreen, mean over measured frames. Values are per-stage
(full-frame avg/peak). Baseline `labels` was the live-path label draw (cv2
putText per ROI per frame) which is now a worker-thread only-on-change render.

| count | stage   | before (ms) | after (ms) | delta |
|---|---|---|---|---|
| 50    | stats   | 1.65 | 0.30 | -5.5x |
| 50    | overlay | 0.19 | 0.04 | cached |
| 50    | labels  | 84.6 | 1.11 | -76x (idle compose) |
| 2000  | stats   | 29.5 | 8.23 | -3.6x (burst, 200 ms cadence) |
| 2000  | overlay | 4.4  | 1.43 | cached |
| 2000  | labels  | 3947 | 14.9 | -265x (idle compose) |

The single dominant cost was the per-frame label loop (`cv2.putText` per ROI
per frame): 84.6 ms at 50 ROIs up to 3.9 s at 2000 ROIs. It is now a
worker-thread render that only runs when the label signature changes.

## Peak-Burst Costs (single invocation, offscreen)

| count | stats batch (one run) | label snapshot (one run) | overlay rebuild |
|---|---|---|---|
| 50   | 1.2 ms   | 1.1 ms  | 0.03 ms |
| 500  | 10.2 ms  | 7.9 ms  | 0.3  ms |
| 2000 | 40.2 ms  | 14.9 ms | 1.7  ms |

These are the worst single-frame hits; with a 200 ms stats/label cadence the
*steady-state* cost (amortized) collapses to < 15 ms at 2000 ROIs.

## Benchmark (offscreen live path, `probe_roi_after.py`)

| count | fps | total (ms) | processing (ms) | stats avg (ms) | stats burst (ms) | overlay (ms) |
|---|---|---|---|---|---|---|
| 50    | 126.1 | 7.93 | 6.77 | 0.30 | 0.30 | 0.04 |
| 100   | 86.1  | 11.6 | 9.27 | 0.72 | 0.72 | 0.07 |
| 250   | 49.1  | 20.4 | 14.7 | 4.95 | 4.95 | 0.15 |
| 500   | 46.1  | 21.7 | 13.6 | 4.95 | 4.95 | 0.30 |
| 1000  | 42.7  | 23.4 | 13.6 | 6.10 | 6.10 | 0.76 |
| 2000  | 32.6  | 30.7 | 14.4 | 8.23 | 8.23 | 1.43 |

fps figures are 126 -> 33 (offscreen, display sub-stages zero in offscreen
mode). Real-display HAL cost measured on a live window
(`probe_disp_real.py`): overlay `disp` 8-15 ms, total display ~12-14 ms
(approx. constant, dominated by HAL window redraw not ROI count).

Budget: 9 FPS = 111 ms/frame. At 2000 ROIs offscreen 30.7 ms (<30% of budget);
with real display ~45 ms worst-case (still ~40% under the 111 ms budget).
The 200 ms stats/label cadence keeps the amortized stats cost at a fraction of
the 40 ms single-batch burst; the live camera drive test measured 5 stats runs
over 60 frames with the throttled cadence active.

## Files Changed

- `halcon_roi_validation.py`: overlay cache + per-shape invalidation, label
  caching + worker-thread renderer, `STATS_INTERVAL_MS` cadence decoupling,
  `_build_label_rows` snapshot-only, `cv2.copyTo` label compose, stage timings.
- No production files touched.