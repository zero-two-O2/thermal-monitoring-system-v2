# Phase 6 — Performance Summary

Generated 2026-08-06 12:30.

## Reference points

- Baseline: `docs/benchmarks/ROI_Benchmark_raw_results_2026-08-05.json`,
  `docs/benchmarks/ROI_Benchmark_Report_2026-08-05.md`.
- Current: `docs/benchmarks/ROI_Benchmark_Report.md`,
  `docs/benchmarks/ROI_Benchmark_raw_results.json`.

## Per-frame latency (batched engine, seconds measured)

| ROIs | store (ms) | rebuild (ms) | median frame (ms) | p95 (ms) | FPS equiv. |
|---|---|---|---|---|---|
| 100 | 2.95 | 62.75 | 26.33 | 34.59 | 38 |
| 500 | 5.20 | 193.44 | 78.33 | 106.50 | 12.8 |
| 1000 | 15.68 | 439.66 | 156.36 | 175.88 | 6.4 |
| 1600 | 18.17 | 834.49 | 242.38 | 350.60 | 4.1 |

## Memory (900 s soak, 500 ROIs)

- RSS: 78.8 - 82.9 MB, slope 21.8 MB/h (limit 100).
- Engine/store memory flat.

## CPU

- System during benchmark: 20-80%.
- Soak process: ~1 core.

## Performance verdict

No regression vs baseline; 500/1000/1600 improved under reduced load. No code changes required.