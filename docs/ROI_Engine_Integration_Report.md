# ROI Engine Integration Report — Phase 3

Date: 2026-08-04

Scope: integrate the production `roi_engine` into the Calibration Window, replacing the legacy per-ROI statistics path behind the GUI. Backend replacement only — no layout changes, no new features, no optimization work.

---

## 1. Integration Summary

### What was integrated

The Calibration Window's per-frame ROI statistics path now runs on the batched ROI engine instead of the legacy `RuntimeROIManagerImpl` per-ROI loop.

| Layer | Before | After |
|---|---|---|
| CalibrationWindow | `ROIWorkspace.process_frame` | unchanged (same calls) |
| ROIWorkspace | `RuntimeROIManagerImpl` (per camera) | `ROIEngineManager` adapter (per camera) |
| Backend | per-ROI HALCON loop | `ROIEngine` + `ROIEnginePool` (batched, type-array) |
| Legacy code | in use | kept intact, untouched (still referenced by tests) |

### New/modified files

- `roi_engine/integration.py` (new) — `ROIEngineManager` adapter.
- `roi_engine/__init__.py` — exports `ROIEngineManager`.
- `gui/roi/roi_workspace.py` — swaps the manager factory, owns an `ROIEnginePool`, passes the workspace config dict as the adapter's config provider, and reorders the delete path (pop before `mark_dirty`).
- `configuration/settings.py` — new flag `ROI_ENGINE_DUAL_VALIDATION` (default `False`).
- `tests/test_roi_engine_integration.py` (new) — 17 tests.

### How it works

`ROIWorkspace` creates one `ROIEngineManager` per camera (wrapping one pooled `ROIEngine`). The manager mirrors the legacy `RuntimeROIManagerImpl` API (`load`, `add_configuration`, `unload`, `get_active`, `get_by_id`, `get_all`, `mark_dirty`, `rebuild_dirty_regions`, `update_state`, `refresh_statistics`, `process_frame`), so neither `CalibrationWindow` nor `ROIWorkspace.process_frame`/signal handlers changed semantics.

- `process_frame` → engine batch processing → fresh `RuntimeROIStatistics` objects (one per enabled ROI) attached to lightweight `RuntimeROI` views, exactly like the legacy manager.
- `mark_dirty(roi_id)` consults the workspace's config dict via the provider:
  - config removed → ROI dropped, store snapshot rebuilt;
  - config object replaced (geometry edit) → store snapshot rebuilt;
  - config unchanged (appearance/recording-only paths) → `engine.invalidate()` only.
- Deletes/creates/edits produce a new immutable store snapshot (the store is frozen by design); cache-only changes never rebuild the store.

### GUI contract preserved

- `workspace.process_frame(camera_id, temperature_image, frame_id)` — same signature, same return type.
- `workspace.get_runtime_manager(camera_id)` → `get_active()` → `roi.statistics` — same shape (`RuntimeROI` / `RuntimeROIStatistics`).
- Signals, alarm evaluation (`AlarmManager`), ROI list updates, save/load, dirty tracking — untouched.

---

## 2. Architecture Diagram

```
CalibrationWindow (_poll_frame, _on_roi_statistics_updated)
        │  process_frame / get_runtime_manager / get_active / roi.statistics
        ▼
ROIWorkspace ────────────────────────────┐
        │  per-camera managers           │ config provider (self._configs.get)
        ▼                                ▼
ROIEngineManager (roi_engine/integration.py)  ◄── reads current ROIConfiguration
   │  one per camera                     (detects edits / deletes on mark_dirty)
   ├──► ROIEngine (from ROIEnginePool)
   │        ├── ROIStore (immutable snapshot, generation+1 on change)
   │        ├── RegionCache / MaskCache (HALCON regions, lazy rebuild)
   │        └── StatisticsEngine (batched HALCON per frame)
   └──► [optional] RuntimeROIManagerImpl (dual-validation mode, OFF by default)
                     │
                     └─► RuntimeROIStatistics (legacy model) ──► GUI / AlarmManager

No GUI module touches ROIStore / RegionCache / MaskCache / StatisticsEngine.
The adapter is the only bridge.
```

Data flow per frame:

```
temperature_image (float)
   └► ROIEngine.process_frame ─► FrameStats (live arrays)
        └► ROIEngineManager._build_statistics ─► fresh RuntimeROIStatistics per
             enabled ROI (values copied; arrays are reused by the engine)
                  └► attached to RuntimeROI views ─► workspace alarm eval ─► GUI
```

---

## 3. Validation Report

### 3.1 Statistics parity

`tests/test_roi_engine_integration.py::test_statistics_match_legacy*` run the engine and a fresh legacy `RuntimeROIManagerImpl` on the same deterministic gradient and uniform frames (all 5 shape types, one disabled ROI):

- `minimum`, `maximum`, `mean`, `standard_deviation`, `pixel_count` — match legacy within `1e-6`.
- `valid` flags — identical.
- `hotspot` — position may differ by a few pixels when several pixels share the maximum temperature (see 3.2); the hotspot pixel always carries the max temperature (`IMAGE[y, x] == maximum`).

Parity holds on repeated frames (region cache reuse).

### 3.2 Hotspot semantics (engine vs legacy)

- Legacy: `threshold(reduced, max, max)` → `area_center` → **center of the max-temperature plateau**.
- Engine: numpy masked `argmax` over the ROI crop → **first pixel of the plateau** (row-major).

On float32 images many pixels can share the rounded max value, so the two coordinates can differ by several pixels while the temperature value is identical. This is a documented engine design decision, not a bug. Validation therefore tolerates up to 16 px per axis (`_HOTSPOT_TOLERANCE_PX`); larger deltas warn.

### 3.3 Dual validation mode

`Settings.ROI_ENGINE_DUAL_VALIDATION = True` runs the legacy manager in parallel per frame and compares Minimum/Maximum/Average/Area/Hotspot/Valid:

- One WARNING per mismatching ROI per mismatch occurrence; no repetition while the mismatch persists (no console flooding).
- Recovery logs one DEBUG line and clears the warning state.
- Default `False` — production runs engine-only.

Verified: clean run logs zero warnings; sabotaged legacy geometry logs exactly one warning across two frames and recovers on the third.

### 3.4 Behavior fixes surfaced by the integration

- **Geometry edits now reach statistics.** Legacy `RuntimeROIManagerImpl` kept the pre-edit `ROIConfiguration` in its `RuntimeROI` objects (`get_updated_configuration()` returns a `replace()`d copy that the legacy manager never received), so edited geometry was not reflected in measurements until a reload. The adapter's config-provider + store-reload design picks up edits immediately. Verified by `test_workspace_geometry_edit_updates_statistics` (gradient minimum changes exactly as the moved rect predicts).
- **Delete ordering.** `_on_delete_roi` now pops the workspace config before `mark_dirty`, so the provider reports the ROI as removed.

---

## 4. Regression Report

Full suite: **504 passed, 8 failed** (134 s).

The 8 failures are the exact pre-existing baseline (verified previously via `git stash`: identical failures on the committed code, caused by HALCON 24.11 environment, unrelated to `roi_engine`):

- `test_processing_pipeline.py` ×2 — alarm-active assertions.
- `test_roi_phase2.py::TestGeometryToHRegion` ×4 — HALCON 24.11 rasterization areas differ from older HALCON.
- `test_roi_phase2.py::TestStatisticsExtraction` ×2 — `halcon.HRegion` attribute removed in HALCON 24.11.

Baseline comparison:

| Suite | Before | After |
|---|---|---|
| Full suite | 487 passed / 8 failed | 504 passed / 8 failed |
| `test_roi_integration.py` (workspace, now on adapter) | pass | pass |
| `test_roi_gui.py` (workspace) | pass | pass |
| `test_roi_engine.py` + `test_roi_engine_integration.py` | 38 + 0 | 38 + 17 |
| `test_roi_phase2.py` (legacy) | 8 fail (baseline) | 8 fail (unchanged) |

Lint: `ruff check` clean on all touched files.

Note: `Settings` is a `slots=True` dataclass — class-level attribute access returns the member descriptor, so the new flag is read from a `Settings()` instance (the rest of the codebase does not yet read `Settings` this way; watch out for the same trap when adding other flags).

---

## 5. Go / No-Go

### Verdict: GO (pilot integration)

| Criterion | Result |
|---|---|
| Statistics parity with legacy | PASS (1e-6) |
| Full suite regression | No new failures (8 baseline failures unchanged) |
| GUI behavior preserved | PASS — window code untouched; workspace API unchanged |
| Geometry-edit correctness | IMPROVED vs legacy (legacy had a stale-region bug) |
| Dual-validation safety net | Available off-by-default |
| Performance | Engine-only path (no legacy loop) — see benchmark report |

### What to test next (on hardware)

1. Calibration window with a real camera: ROI statistics and alarm states must behave identically to before.
2. Create / edit / delete / duplicate ROIs while streaming — measurements must follow immediately.
3. Switch cameras and positions — per-camera engines must stay independent.
4. Optional: set `ROI_ENGINE_DUAL_VALIDATION = True` for one session and confirm zero warnings on a real image.

### Known limitations (accepted)

- One invalid ROI geometry makes the engine return an empty `FrameStats` for that frame (engine-level never-crash guard; per-ROI isolation is a future engine improvement, not part of this phase).
- Hotspot coordinates follow the engine's first-max-pixel convention (see 3.2).
- Alarm thresholds/`enabled` edited in the property panel do not reach the engine store (same as legacy — the panel only emits signals; configs are updated on save). Engine alarm arrays are not used for evaluation in this phase.
- `ROIEngineManager` is not thread-safe (same contract as the legacy manager — one camera, one thread).

---

## Appendix A — Files Changed

- `roi_engine/integration.py` (new)
- `roi_engine/__init__.py`
- `gui/roi/roi_workspace.py`
- `configuration/settings.py`
- `tests/test_roi_engine_integration.py` (new)
- `CHANGELOG.md`
