# Phase 6 — System Verification Report

Generated 2026-08-06 12:30 by the Phase 6 verification pass.

## Scope

Verification and stabilization only. No new features, no architecture changes,
no ROI engine redesign, no threading changes, no GUI redesign, no API changes.

## Environment

| Item | Value |
|---|---|
| Python | 3.10.7 |
| mvtec-halcon | 24113.0.0 |
| numpy | 2.2.6 |
| OS | Windows (i7-8550U, 4C/8T, 16 GB RAM) |
| Background load during benchmarks | reduced (Teams/Widgets/SearchHost closed); sampled system CPU 20-80%, avg ~50-60% (VS Code/opencode are part of the session and cannot be closed) |

---

## 1. Benchmark Comparison (previous vs current)

Batched engine, 480x640 synthetic frames, 10 measured frames after 5 warmup frames.

| ROIs | Previous median (ms) | Current median (ms) | Delta | 111 ms budget |
|---|---|---|---|---|
| 100 | 25.21 | 26.33 | +4% (noise) | OK |
| 500 | 92.99 | 78.33 | -16% | OK |
| 1000 | 215.71 | 156.36 | -28% | EXCEEDS |
| 1600 | 297.33 | 242.38 | -18% | EXCEEDS |

- Legacy-to-batched speedup: 3.6x / 6.4x / 4.3x / 5.6x (consistent with baseline methodology).
- **Cause of improvement:** no code changed in `roi_engine` since the baseline. Improved
  timings are explained by reduced concurrent machine load during this run. Baseline report
  preserved at `docs/benchmarks/ROI_Benchmark_Report_2026-08-05.md` (and raw JSON).
- **Conclusion:** no performance regression; nothing to fix. The batched ROI engine
  stays real-time capable (≤ 111 ms) up to 500 ROIs; 1000/1600 exceed budget at 10 FPS
  synthetic throughput — same architectural limit recorded in the previous report.

## 2. Memory Verification (soak)

900 s continuous processing, 500 ROIs, 500+ session sample (14,205 frames):

| Metric | Value |
|---|---|
| Process RSS | stable 78.8 - 82.9 MB (delta 2.6 MB over 900 s) |
| Memory slope (tail 50%) | 21.8 MB/h (leak limit 100 MB/h, factor 4.6 below) |
| ROI engine memory | const 0.144 MB |
| Engine store memory | const 0.071 MB |
| Active ROI count | 500 (constant) |
| Exceptions | 0 |
| HALCON errors | 0 |
| Reconnect events | 0 |
| Frames processed / dropped | 14,205 / 0 |
| FPS | max 29.2, avg 16.0, min 4.1 (short dips only) |

**Verdict: PASS** - no leak, stable RAM, stable CPU, stable FPS, no growing object counts.

## 3. CPU Usage Summary

- Benchmark run: system-wide 20-80%, avg ~50-60% while closed non-essential apps back into the session resumption. Per-sample record: 66, 48, 43, 54, 49, 74 (%).
- Soak run: single-process load ~100% CPU of one logical core (normal for a single-threaded synthetic loop), stable.

## 4. Hardware Verification

**Status: NOT EXECUTED** — no camera hardware connected during this verification.

- GigE Vision discovery (`CameraDiscovery`, 3 retry scans) returned no boards.
- Therefore: discover / connect / disconnect / reconnect / stable streaming / observation /
  calibration were not exercisable and are **not** claimed as verified.
- The `camera_switch` validation scenario reported SKIPPED (no camera).

## 5. Logging Review

Verified no remaining per-frame, benchmark-time, or transient debug logging in production code:

- `camera/`, `processing/`, `roi_engine/`, `observation/`, `gui/` — clean.
- Fixed: `ProcessingPipeline.process()` no longer calls `logger.debug("Processing frame...")`
  on every frame (removed call + now-unused import).
- The one remaining `logger.debug` in `roi_engine/integration.py` is a single-shot
  "dual validation recovered" line, emitted only when the optional dual-validation flag is ON
  (default OFF, production disabled).
- Diagnostic `[DIAG]` `print()` statements remain only in the legacy camera driver
  (`camera/tv46l_camera.py`) used by test/diagnostic tools; the production camera path
  (`camera/services/tv46l_camera.py`) is print-free.
- All log noise is INFO/strategic; `Settings.LOG_LEVEL=INFO`.

## 5. Regression Summary

Full test suite:

- PASSED: 518
- FAILED: 8 (identical to pre-verification baseline)
  1. 4 pixel-convention tests (`tests/test_roi_phase2.py`) — incomplete HALCON 24.11 inclusive pixel counts vs stale expected values (pre-existing).
  2. 2 HRegion API tests (`tests/test_roi_phase2.py`) — HRegion class API removed in Halcon 24 (pre-existing).
  3. 2 alarm-threshold tests (`tests/test_processing_pipeline.py`) — unreachable alarm threshold vs real LUT (stale expectation, pre-existing).
- No new failures introduced by this phase. All 14 validation-harness tests PASS.

## 6. Remaining Known Issues

1. 8 stale tests (see regression summary) fail against Halcon 24.11 — needs updated expectations, not code.
2. 1000/1600 ROI counts exceed the 111 ms frame budget at 10 FPS target (architecture boundary, documented).
3. Camera-dependent paths (connect/stream/calibration/observation) not verified on hardware — hardware unavailable.

## 7. Code Changes Made During This Phase

Two bug fixes, each tied to a verified defect:

1. `gui/roi/roi_workspace.py` — remove recursive signal re-emission (infinite-loop /
   native stack overflow crash in validation harness). Verified before/after: scenarios PASS,
   harness tests PASS, full suite regression baseline preserved.
2. `processing/pipeline/processing_pipeline.py` — remove per-frame debug logging (verified
   logging hygiene defect). Verified: ruff clean, pipeline tests unchanged (2 stale failures only).

No optimization, refactor, architecture, or API changes were made.

---

## Verdict

**CONDITIONAL PASS**

All software-side verification objectives PASS; the blocking defect (signal recursion) was
fixed with zero regression. Go/no-go for production rollout is **conditional**: it depends on
executing the hardware verification block (connect/disconnect/reconnect, streaming, observation,
calibration) with an actual TV46L camera, which was not available during this phase.