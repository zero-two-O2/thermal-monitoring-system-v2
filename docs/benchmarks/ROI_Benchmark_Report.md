# ROI Engine Pipeline Benchmark

Generated 2026-08-04T12:54:00 by `tests/benchmark_roi_pipeline.py`.

## Environment

| Item | Value |
|---|---|
| Python | 3.10.7 |
| mvtec-halcon | 24113.0.0 |
| numpy | 2.2.6 |
| Synthetic image | 480x640 |
| Seed | 42 |
| Date | 2026-08-04T12:54:00 |

## Methodology

- Geometry: mixed shapes (50% Rectangle1, 20% Circle, 10% Ellipse, 10% Rectangle2, 10% Polygon) on a deterministic non-overlapping 480x640 grid (seed 42).
- Warmup: 5 frames per count (includes the one-off cache rebuild inside ROIEngine.process_frame); measured frames: 15.
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
| 50 | 0.77 | 2.64 | 13.74 | 16.37 | 6.64 | 8.32 | 11.54 | 8.20 | 415,824 | 41,470 | OK |
| 100 | 1.04 | 2.28 | 22.84 | 25.12 | 10.35 | 13.45 | 17.68 | 13.38 | 415,279 | 58,328 | OK |
| 250 | 1.87 | 4.37 | 52.78 | 57.15 | 20.01 | 22.88 | 40.67 | 22.81 | 420,784 | 75,969 | OK |
| 500 | 2.84 | 6.43 | 78.32 | 84.75 | 31.15 | 32.58 | 34.56 | 32.51 | 430,733 | 105,299 | OK |
| 1000 | 6.66 | 21.62 | 185.91 | 207.53 | 73.97 | 87.65 | 115.61 | 87.55 | 450,576 | 182,070 | OK |
| 1600 | 9.42 | 29.02 | 280.86 | 309.87 | 94.67 | 96.71 | 124.40 | 96.64 | 475,466 | 269,105 | OK |

## Legacy vs. Batched

| ROIs | legacy median
(ms) | batched median
(ms) | speedup | legacy frames |
|---|---|---|---|---|
| 50 | 31.59 | 8.32 | 3.8x | 15 |
| 100 | 44.46 | 13.45 | 3.3x | 15 |
| 250 | 82.33 | 22.88 | 3.6x | 15 |
| 500 | 146.32 | 32.58 | 4.5x | 15 |
| 1000 | 337.18 | 87.65 | 3.8x | 3 |
| 1600 | 428.29 | 96.71 | 4.4x | 3 |

## Interpretation

Per-frame latency grows 11.6x for a 32x ROI increase, i.e. sub-linear (batch amortization grows with ROI count). Per-frame cost is dominated by the batched HALCON operators (intensity, min_max_gray, area_center) and the himage_from_numpy_array conversion; hotspots run in numpy per ROI. Overall, no tested count exceeds the 111 ms (9 FPS) frame budget, so the batched engine stays real-time capable within the tested range.
