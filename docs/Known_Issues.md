# Known Issues

Status snapshot: 2026-08-06 (Phase 6).

## 1. Stale ROI geometry tests fail against HALCON 24.11 (4 tests)

`tests/test_roi_phase2.py` — `TestGeometryToHRegion::test_rectangle1`,
`test_rectangle2`, `test_circle`, `test_polygon` (expect 25000 / 6000 / 100 / 10000 px,
get 25351 / 6161 / 99 / 10201).

- **Cause:** expectations assume exclusive pixel counting; HALCON 24.11 with
  `set_system("clip_region", "false")` counts inclusively.
- **Age:** failing since before commit 0f3fb5b; confirmed at 62aee35 and 6fc190e.
- **Fix:** update expected counts to the inclusive convention (no production code change).

## 2. Stale HRegion class-API tests (2 tests)

`tests/test_roi_phase2.py` — `TestStatisticsExtraction::test_extract_statistics_valid`
and `test_extract_statistics_hotspot`.

- **Cause:** tests use the removed `halcon.HRegion(...)` class constructor; Halcon 24
  removed this API.
- **Fix:** rewrite tests against the current HImage/operator-based API.

## 3. Stale alarm-threshold tests (2 tests)

`tests/test_processing_pipeline.py` — `test_high_alarm_pipeline`,
`test_multiple_alarm_pipeline`.

- **Cause:** alarm threshold 100 C is unreachable with the real calibration LUT (synthetic
  raw frames map to at most ~-85 C); `.active` stays False.
- **Fix:** use thresholds reachable by the synthetic calibration (e.g. below +80 C).

## 4. High ROI counts exceed the 9 FPS frame budget (no defect)

At 1000/1600 ROIs the batched engine exceeds the 111 ms per-frame budget on the current
i7-8550U platform. Documented architecture limit; not a regression (matches baseline).

## 5. Camera-dependent paths not yet verified on hardware

Discovery/connect/reconnect/streaming/observation/calibration were NOT EXECUTED during
Phase 6 (no TV46L camera connected; GigE scans returned no boards). These are not data
points of success — they are unverified.