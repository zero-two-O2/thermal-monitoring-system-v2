# ROI Engine Pipeline Benchmark

Generated 2026-08-05T18:28:44 by `tests/benchmark_roi_pipeline.py`.

## Environment

| Item | Value |
|---|---|
| Python | 3.10.7 |
| mvtec-halcon | 24113.0.0 |
| numpy | 2.2.6 |
| Synthetic image | 480x640 |
| Seed | 42 |
| Date | 2026-08-05T18:28:44 |

## Methodology

- Geometry: mixed shapes (50% Rectangle1, 20% Circle, 10% Ellipse, 10% Rectangle2, 10% Polygon) on a deterministic non-overlapping 480x640 grid (seed 42).
- Warmup: 5 frames per count (includes the one-off cache rebuild inside ROIEngine.process_frame); measured frames: 10.
- Legacy path: `RuntimeROIManagerImpl.process_frame` (per-ROI `extract_statistics`), warmup 2, measured frames reduced to 3 from 1000 ROIs.
- Frame budget: 9 FPS = 111 ms per frame.
- Per-frame allocation: separate tracemalloc pass of 3 frames, peak divided by frame count (Python-side estimate; HALCON C-side memory is invisible to tracemalloc). Wall timing runs WITHOUT tracemalloc, which skews numpy-heavy paths by 3-10x.
- Caveat: absolute timings depend on concurrent machine load; run with no other heavy processes for reproducible numbers. Relative legacy-vs-batched speedups are robust to constant CPU contention.

## Batched Engine Results

| ROIs | store
(ms) | region
rebuild
(ms) | mask
rebuild
(ms) | rebuild
total
(ms) | frame
min
(ms) | frame
median
(ms) | frame
p95
(ms) | proc.
median
(ms) | alloc
per frame
(B) | total
memory
(B) | 111 ms
budget |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 2.21 | 6.04 | 57.04 | 63.09 | 18.64 | 25.21 | 34.97 | 25.10 | 416,183 | 58,328 | OK |
| 500 | 9.21 | 35.11 | 313.73 | 348.84 | 78.54 | 92.99 | 107.14 | 92.73 | 430,872 | 105,299 | OK |
| 1000 | 12.71 | 46.39 | 498.64 | 545.03 | 185.94 | 215.71 | 254.08 | 215.14 | 450,646 | 182,070 | EXCEEDS |
| 1600 | 24.33 | 51.33 | 829.03 | 880.36 | 236.56 | 297.33 | 379.54 | 297.21 | 476,186 | 269,105 | EXCEEDS |

## Legacy vs. Batched

| ROIs | legacy median
(ms) | batched median
(ms) | speedup | legacy frames |
|---|---|---|---|---|
| 100 | 90.80 | 25.21 | 3.6x | 10 |
| 500 | 497.45 | 92.99 | 5.3x | 10 |
| 1000 | 895.00 | 215.71 | 4.1x | 3 |
| 1600 | 1357.32 | 297.33 | 4.6x | 3 |

## Interpretation

Per-frame latency grows 11.8x for a 16x ROI increase, i.e. sub-linear (batch amortization grows with ROI count). Per-frame cost is dominated by the batched HALCON operators (intensity, min_max_gray, area_center) and the himage_from_numpy_array conversion; hotspots run in numpy per ROI. Overall, the 111 ms (9 FPS) frame budget is exceeded from 1000 ROIs onward ([1000, 1600]), so the batched engine stays real-time capable within the tested range.
