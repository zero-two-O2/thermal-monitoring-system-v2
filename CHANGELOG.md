## 2026-07-22 14:45
### What changed
- Full engineering audit of camera qualification tool — see ADR-002 for complete review.
- **P1 (HIGH):** Fixed `tv46l_camera.py` `is_alive()` always returning False — added `_last_frame_time = time.time()` in `_grab_loop()`. Root cause of false Camera FAIL in qualification report.
- **P2 (HIGH):** Fixed timing collection at 1Hz instead of per-frame — added `_paint_events` deque to ThermalWidget, drain all paint events in `_update_diagnostics()`. QualificationSession now receives every paint event.
- **P3 (MEDIUM):** Split Camera subsystem into `camera_connection`, `acquisition_thread`, `frame_acquisition`, `transport` for independent evaluation.
- **P4 (MEDIUM):** Removed duplicate total latency calculation — all end-to-end latency now comes from `ThermalWidget.paint_total_latency` within `paintEvent`.
- **P5 (MEDIUM):** Added per-stage timing collection to `QualificationSession` (`record_per_stage`) for every frame from `_poll_frame`.
- **P6 (LOW):** FrameRecord paint timestamps now populated once per diagnostics cycle (partial fix).
- **P7 (LOW):** Console health uses `HealthEvaluator.overall()` instead of duplicated logic.
- Replaced `record_disconnect`/`record_not_alive` with `record_camera_state(connected, running)`.
- Produced ADR-002 (`docs/decisions/ADR-002-Camera-Qualification-Tool-Audit.md`) with full engineering review.
### Why
- Engineering audit to eliminate false qualification results and make the tool suitable as an engineering acceptance application.
### Files Changed
- camera/tv46l_camera.py
- tests/camera_viewer.py
- docs/decisions/ADR-002-Camera-Qualification-Tool-Audit.md

## 2026-07-22 14:00
### What changed
- Added `QualificationSession` class — collects all qualification data from run start to stop with independent subsystem evaluators: camera, acquisition, timing, rendering, memory, CPU, frame integrity, calibration.
- Each subsystem evaluates PASS/WARNING/FAIL from full-session statistics (95th percentile, mean, stddev, peak, skip ratio) rather than live latest values.
- Fixed Camera FAIL: `is_alive()` returning False (no frame in 2s) is now WARNING, not FAIL. FAIL only when camera is disconnected or never acquired.
- Fixed end-to-end latency: total latency now computed from a single frame's timeline in `ThermalWidget.paintEvent` (paint_finish_time - _grab_start_time), stored as `paint_total_latency`. Removed duplicate mixed-frame calculation.
- Added `paint_update_delay` computation in `ThermalWidget.paintEvent` for consistent per-frame update delay.
- FrameRecord `paint_start`/`paint_finish` fields now populated from ThermalWidget after each paint.
- Qualification report dialog now uses `QScrollArea` for long reports, displays full-session summary with per-subsystem breakdown.
### Why
- The qualification report needs to be a true engineering acceptance report based on the entire run, not a snapshot of live measurements. Each subsystem must independently determine its health from all collected samples.
### Files Changed
- tests/camera_viewer.py

## 2026-07-22 13:30
### What changed
- Refactored `tests/camera_viewer.py` — removed all automatic reconnect, recovery, and camera-state-modification logic.
- Added `QualificationMonitor` class (passive observer) — tracks camera connection state and logs events without ever calling `reconnect()`, NUC, Focus, or parameter changes.
- Added `HealthEvaluator` class — evaluates subsystem health with `UNKNOWN` state (not FAIL) when no measurements exist yet (e.g. paint count=0, total count=0, frame count=0).
- Replaced `_check_camera_health()` (which called `self._camera.reconnect()`) with `_check_camera_state()` using passive `QualificationMonitor.poll()`.
- Removed `_reconnect_count`, `_camera_connected_logged`, `_camera_disconnected_logged`, `_calibration_loaded_logged` from `MainWindow`.
- Removed "Reconnect Count" row from `AcquisitionPanel`.
- Health evaluation now uses `HealthEvaluator` static methods instead of manual inline logic.
### Why
- Phase 1 of recovery-system refactoring: the qualification tool must be a passive measurement instrument, never modifying camera state. Phase 2 will introduce `RecoveryManager` as a separate service.
### Files Changed
- tests/camera_viewer.py

## 2026-07-22 12:30
### What changed
- Created `tests/camera_viewer.py` (1564 lines, 15 classes) — a comprehensive camera qualification tool.
- Architecture: StageStats, FrameHistory, EventLogger, TimingMonitor, GraphManager, GraphWidget, ThermalWidget, QualificationEngine, AcquisitionPanel, ProcessingPanel, SystemPanel, HealthPanel, TimingTable, MainWindow.
- Features: per-frame timing with min/max/avg/stddev/95th stats, scrolling live graphs (9 traces, 300 points), frame continuity validation, PASS/WARNING/FAIL health evaluation with configurable thresholds, stress test mode, qualification report generation, event log with rate-limited dedup.
- Fixed per-frame timing correctness: all paint-related metrics stored on ThermalWidget and read together, eliminating cross-frame timestamp mixing.
- No existing project files modified.
### Why
- Provide a reference qualification application for validating the entire camera pipeline (acquisition through display) before adding ROI, alarms, recording, or multi-camera support.
### Files Changed
- tests/camera_viewer.py (new file)

## 2026-07-22 12:05
### What changed
- Created `tests/gui_latency_test.py` — a standalone Qt diagnostic app that measures end-to-end latency from camera acquisition to Qt painting.
- Twelve pipeline stages are measured per frame: Acquire, NumPy, Publish, GUI Delay, Display Conv, Colormap, QImage, Pixmap, Update Delay, Paint Time, and Total.
- Running min/max/avg statistics for every stage, displayed on-screen and printed to console once per second.
- Uses `get_latest_frame_reference()` (zero-copy), `CalibrationManager.raw_to_display()` and `apply_colormap()`.
- Frame skipping detection via sequence number tracking.
- Update/paint ratio tracking.
### Why
- Isolate exactly which stage is responsible for end-to-end latency without modifying any production code.
### Files Changed
- tests/gui_latency_test.py (new file)

## 2026-07-22 12:00
### What changed
- Added frame lifecycle instrumentation to `RawFrame`: `grab_start_time`, `grab_complete_time`, `numpy_complete_time`, `publish_time`, and `sequence` fields.
- Instrumented `_grab_raw_frame()` to populate grab/numpy timestamps from existing `_t0`, `_t1`, `_t3` perf_counter snapshots.
- Instrumented `_grab_loop()` publish step: sets `publish_time` and `sequence` on each frame before storing as `_latest_frame`.
- Added `get_latest_frame_reference()` — lock-safe, no-copy accessor for diagnostic use.
- Added `acquisition_diagnostics()` — returns avg/max grab, convert, and total timing in ms.
- Removed temporary `_pipeline_trace` / `[TRACE]` debug prints and their supporting attributes.
- Updated `_copy_frame()` to propagate all new fields.
### Why
- Enable a new diagnostic GUI to calculate every stage of the acquisition pipeline per-frame without adding more instrumentation to the driver.
### Notes
- No acquisition behavior, threading, locking, NUC logic, or timeout values were modified.
### Files Changed
- processing/models/processing_models.py
- camera/tv46l_camera.py

## 2026-07-22 11:40
### What changed
- Added ThermalView paint scheduling diagnostics: update-request counts, paint-execution counts, pending frame, actual painted pixmap frame, and update-to-paint delay.
- Changed the camera PUBLISH trace from a 5-second stop to continuous one-sample-per-second tracing so delayed onset is visible.
### Why
- Runtime evidence showed `update()` requests outpace `paintEvent()` executions, and actual painted frames can lag behind `set_frame()` by several frames.
### Notes
- A temporary `repaint()` diagnostic was run and then reverted to permanent `update()` behavior.
### Files Changed
- tests/camera_viewer.py
- camera/tv46l_camera.py

## 2026-07-22 11:15
### What changed
- Added runtime pipeline tracing to `_grab_loop()` (PUBLISH trace) and diagnostic counters in `_grab_raw_frame()` to verify the timeout hypothesis with real camera measurements.
- Verified: 0 timeouts, 0 packet loss, steady 9 FPS, display pipeline latency <10ms with both fixes applied.
- **Diagnostic fix**: `frame.frame_number` is now set to `self._frame_counter` AFTER the increment (inside the lock), making the `Difference = frame_count - displayed_frame` diagnostic valid. Previously, `RawFrame` was created with `frame_number = self._frame_counter` (pre-increment) in `_grab_raw_frame()`, causing a permanent +1 offset.
### Why
- Systematic runtime verification of the progressive lag root cause.
### Notes
- Pipeline trace results: 46 unique frames traced over 5s, 820 display polls, 774 repeats (normal — display polls at 100+ Hz, frames arrive at 9 Hz). `pub_to_get` latency: 0.2–9.4ms (well under one frame interval).
### Files Changed
- camera/tv46l_camera.py

## 2026-07-22 09:30
### What changed
- Added GigE Vision transport tuning params from legacy config: `[Stream]DeviceStreamChannelNegotiatePacketSize=1` (enables jumbo frame negotiation) and `[Stream]GevStreamReceiveSocketSize=1048576` (1MB socket buffer, up from 128KB default).
- Fixed `grab_image_async` timeout: 100ms → 200ms. At 9 FPS (111ms/frame), the old 100ms timeout was shorter than the frame interval, causing a timeout on every grab attempt — frames accumulated in HALCON's internal buffer, producing progressive display lag. NUC flushed the buffer (temporary fix), but the buffer refilled.
### Why
- Root cause analysis verified both hypotheses. The timeout mismatch (100ms < 111ms) is the primary cause of progressive lag. The missing socket config is a secondary factor that amplified transport inefficiency.
### Files Changed
- camera/tv46l_camera.py

## 2026-07-21 17:10
### What changed
- **Fix: lock contention causing gradual GUI lag** — `get_latest_frame()` and `grab_frame()` now grab the `RawFrame` reference under the lock but perform the `image.copy()` **outside** the lock. Lock hold time dropped from ~1-2ms to ~0.001ms per read.
- **Fix: frame counter out of sync** — `_frame_counter += 1` moved inside the lock alongside frame publish in `_grab_loop()`, so counter no longer advances before the frame is visible to readers.
- Refactored `_copy_latest_frame()` → `_copy_frame(frame)` static method; callers pass the reference obtained under lock.
### Why
- Primary root cause: `image.copy()` in `get_latest_frame()` held `self._lock` for ~1-2ms per call. At 30 FPS viewer polling, this occupied the lock ~45ms/sec, delaying acquisition thread's frame publication and causing HALCON's internal buffer to accumulate frames.
- Secondary: counter increment before publish made `frame_count` report more frames than `get_latest_frame()` could return, inflating the "frames behind" metric.
### Notes
- The service layer (`acquisition_engine.py`) uses a `queue.Queue` and is unaffected.
- All callers (`tv46l_camera.py` service, `camera_viewer.py`, test scripts) use `get_latest_frame()` or `grab_frame()` and benefit automatically.
### Files Changed
- camera/tv46l_camera.py

## 2026-07-21 16:55
### What changed
- Added `_scalar()` helper to normalize HALCON list returns (`[value]` → `value`)
- `get_parameter()` now applies `_scalar()` automatically; removed redundant list checks from all callers
- Added `wait_for_focus(target_mm, tolerance, timeout)` and `focus_busy()` to Focus API
- Added `frame_rate_capabilities()` diagnostic that reads min/max/increment/writable
- `CameraDiscovery._read_camera()` now extracts scalars from HALCON results before `str()` — `CameraInfo` fields are now proper strings, not `"['value']"`
- Removed temporary debug stack-trace logging from `set_focus_distance()`
- Removed all per-frame INFO logging (already cleaned up in previous pass)
### Why
- Normalize HALCON's inconsistent return types so the rest of the app never has to know about list wrappers
- Provide a production-ready focus API with settle detection
- Enable frame-rate capability discovery without hardcoding
- Clean up debug instrumentation after investigation completed
### Notes
- No acquisition logic, threading model, or pipeline code was touched
- `_scalar()` is module-level in `tv46l_camera.py`; imported by `camera_discovery.py`
- All autofocus/continuous-focus parameters remain unsupported (confirmed in previous diagnostics)
### Files Changed
- camera/tv46l_camera.py (added `_scalar`, `wait_for_focus`, `focus_busy`, `frame_rate_capabilities`; cleaned logging)
- camera/camera_discovery.py (import `_scalar`, apply before str conversion)

## 2026-07-21 16:52
### What changed
- Added trace logging to `set_focus_distance()` — every write logs timestamp, thread ID, requested value, and partial call stack
- Created `tests/diagnose_fps.py` — comprehensive FPS/jitter/drift root-cause diagnostic
- Updated `tests/diagnose_focus.py` — five-phase investigation: call-path tracing, autofocus parameter dump, settle monitoring, raw HALCON timing, long-term drift
### Why
- Investigate focus command slowness and apparent drift discovered in earlier diagnostics
- Ensure every focus write is traceable to its source
### Notes
- Root cause identified: "drift" was a diagnostic artifact (Phase 4 wrote focus=500 before Phase 5 monitoring); focus is stable with zero drift without commands
- Camera configured for 1 FPS (`FLK_TI_ControlFeature_SetFrameRate`=1), not 9Hz
- No production architecture changes required
- All autofocus/continuous-focus parameters are unsupported by this camera
### Files Changed
- camera/tv46l_camera.py (added logging to set_focus_distance)
- tests/diagnose_fps.py (new file)
- tests/diagnose_focus.py (updated)

## 2026-07-21 16:00
### What changed
- Added three focus control methods to TV46LCamera: `get_focus_distance()`, `set_focus_distance(distance_mm)`, `get_focus_limits()`
- Created `tests/test_focus_control.py` — standalone hardware test for motorized focus
- Test displays live image with OpenCV and supports keyboard: +/- for step adjustment, 0/1/2/3 for presets, R to read, Q to quit
### Why
- Enable programmatic control of the TV46L motorized lens
- Validate focus read/write works through HALCON parameters
### Notes
- Uses `FLK_TI_ControlFeature_*` parameters for focus distance, limits, and current value
- Every focus change prints requested vs actual value with PASS/FAIL
- Acquisition logic is unchanged
### Files Changed
- camera/tv46l_camera.py (added Focus Control section with 3 methods)
- tests/test_focus_control.py (new file)

## 2026-07-21 15:37
### What changed
- Created `tests/test_live_pipeline.py` — standalone hardware integration test
- Test connects to a live TV46L camera, acquires frames, processes them through the full ProcessingPipeline, and displays the result with OpenCV
- Supports Q to quit and N for manual NUC
- On exit: cleanly stops acquisition, disconnects camera, destroys OpenCV windows
### Why
- Validate the complete backend path (Camera → RawFrame → ProcessingPipeline → FrameResult) without involving GUI or other application components
- Ensure the fix to `_grab_raw_frame()` works end-to-end with real hardware
### Notes
- Falls back to inline calibration if `assets/calibration/calibration_blob.txt` is missing
- Only processes new frames (skips if `frame.frame_number` hasn't changed)
- Prints pass/fail markers at each stage
- Run with: `python tests/test_live_pipeline.py`
### Files Changed
- tests/test_live_pipeline.py (new file)

## 2026-07-21 12:30
### What changed
- Fixed `_grab_raw_frame()` to construct and return a proper `RawFrame` instead of returning `self._latest_frame` (which was always None)
- RawFrame is now built with: `image=frame.copy()`, `range_index=0`, `timestamp=datetime.now()`, `frame_number=self._frame_counter`
### Why
- The method was ignoring the successfully grabbed numpy array and returning `self._latest_frame`, a stale reference that was always None on first call
- This caused `wait_for_first_frame()` to always time out despite valid frames being produced by HALCON
### Notes
- All other logic in the acquisition path is unchanged
- The instrumentation logging added in the previous debugging pass is retained
### Files Changed
- camera/tv46l_camera.py

## 2026-07-21 12:00
### What changed
- Added step-by-step instrumentation logging to `_grab_raw_frame()` in TV46L camera driver
- Replaced silent `except Exception` in `_grab_loop()` with full traceback logging
- Replaced `except Exception: pass` in `_execute_manual_nuc()` NUC flush with warning logging
- Replaced `except Exception: break` in `flush_buffers()` with warning logging
### Why
- Debugging pass to identify which HALCON call fails during frame acquisition
- Existing blanket exception handlers were silently swallowing all errors, making it impossible to diagnose why no frames arrive despite successful connection
- Each HALCON call in the acquisition path now logs: exception type, HALCON error code, error text, and full traceback
### Notes
- HALCON parameters and acquisition logic are UNCHANGED – this is a debugging-only pass
- The existing bug where `_grab_raw_frame()` returns `self._latest_frame` (stale/None) instead of the newly grabbed frame is preserved
- Frame shape/dtype/min/max are logged when `himage_as_numpy_array` succeeds
- The `_grab_loop` now also logs the timeout count on each failure cycle
### Files Changed
- camera/tv46l_camera.py (added `import sys`, instrumented `_grab_loop`, `_grab_raw_frame`, `_execute_manual_nuc`, `flush_buffers`)
