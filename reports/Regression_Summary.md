# Phase 6 — Regression Summary

Generated 2026-08-06 12:30.

## Test suite

`python -m pytest tests -q`

**518 passed, 8 failed** — identical to the pre-Phase-6 baseline at commit 6fc190e.

## The 8 failures (all pre-existing, stale tests)

| Test | Category | Cause |
|---|---|---|
| `test_roi_phase2.py::TestGeometryToHRegion::test_rectangle1` | Pixel convention | expects 25000 px, HALCON 24.11 inclusive clip gives 25351 |
| `test_roi_phase2.py::TestGeometryToHRegion::test_rectangle2` | Pixel convention | expects 6000, gets 6161 |
| `test_roi_phase2.py::TestGeometryToHRegion::test_circle` | Pixel convention | expects 100, gets 99 |
| `test_roi_phase2.py::TestGeometryToHRegion::test_polygon` | Pixel convention | expects 10000, gets 10201 |
| `test_roi_phase2.py::TestStatisticsExtraction::test_extract_statistics_valid` | API | `ha.HRegion(...)` class API removed in Halcon 24 |
| `test_roi_phase2.py::TestStatisticsExtraction::test_extract_statistics_hotspot` | API | same HRegion API removal |
| `test_processing_pipeline.py::test_high_alarm_pipeline` | Alarm threshold | threshold 100 C unreachable with real LUT (raw values map to -85 C max) |
| `test_processing_pipeline.py::test_multiple_alarm_pipeline` | Alarm threshold | same stale expectation |

These were confirmed failing at 0f3fb5b, 62aee35, and 6fc190e (pre-existing), and are
documented in `docs/Known_Issues.md` / Phase 6 report rather than "fixed" by changing tests.

## Validation harness (Phase 4/6)

`python -m tests.validation --scenario all` and the 14 harness unit tests:

- Soak, dual_validation, position_switch, roi_editing, high_count, error_recovery: PASS
- camera_switch: SKIPPED (no hardware)
- 14 harness tests: PASS

## Changes in this phase and their regression impact

| Change | Impact |
|---|---|
| `roi_workspace.py` remove self-re-emit | 518/8 unchanged; harness RecursionError gone |
| `processing_pipeline.py` remove per-frame log | no behavioral impact; only the log call removed |