## 2026-07-23 19:30
### What changed
- **Phase 2 - Multi-Camera Acquisition Analyzer**: Complete rewrite of the pipeline analyzer for multi-camera diagnostics.
- **MulticameraAnalyzerManager**: New orchestrator class managing N independent PipelineAnalyzers (one per camera). Single `poll_all()` call drives all cameras.
- **CrossCameraSyncMonitor**: Tracks frame timestamps across all cameras, measures synchronization drift in ms.
- **BottleneckDetector**: Automated analysis of all camera snapshots to identify the bottleneck (freeze, publishing, display conversion, Qt paint, camera acquisition, frame loss).
- **IsolationVerifier + IsolationResult**: Verifies NUC and focus operations on one camera don't pause others. Renders "isolation PASSED" or "isolation FAILED" verdicts.
- **EventLog**: Thread-safe per-camera event ring buffer (1000 entries) with timestamps.
- **CrossCameraSnapshot**: Aggregate dataclass with avg FPS, max latency, worst camera, sync drift, bottleneck.
- **CameraTile**: Clickable per-camera tile with thermal image, FPS (Cam/Pub/Dsp), seq loss, latency, freeze dot, NUC/focus buttons.
- **TileImageWidget**: Replaces old ThermalDisplayWidget - calls `analyzer.observe_paint_start/complete()` in paintEvent (fixes the "Paint FPS = 0.0" bug).
- **GlobalSummaryPanel**: Aggregate dashboard showing connected count, avg FPS, bottleneck, sync drift, worst camera.
- **TimelineView**: Cross-camera per-stage timing comparison table.
- **EventLogWidget**: Scrolling event log with timestamp+camera ID.
- **Focus isolation**: Focus near/far operations now check all other cameras for pauses, same as NUC isolation.
- **Focus buttons on tiles**: << and >> buttons visible only when `camera.focus_available()` returns True.
- **Per-camera NUC/focus**: Each tile has its own NUC and focus buttons. Operations run with isolation verification.
- **Reduced diagnostic overhead**: Diagnostics updated at 5Hz (200ms) instead of 30ms, graphs/tables only refresh 5x/sec.
- **Added `perform_nuc()`, `focus_near()`, `focus_far()`** to old `TV46LCamera` driver (was missing these public methods).
### Why
- Phase 1C only analyzed one selected camera. Actual problems only appear when multiple cameras acquire simultaneously.
- Paint FPS was never recorded (0.0) because `observe_paint_complete()` was never called from any paint event.
- Need to verify NUC and focus isolation across all cameras automatically.
- Need automated bottleneck identification without code inspection.
### Files Changed
- camera/tv46l_camera.py (added perform_nuc, focus_near, focus_far)
- tests/pipeline_analyzer/analyzer_core.py (added ~450 lines: MulticameraAnalyzerManager, CrossCameraSnapshot, BottleneckDetector, IsolationVerifier, CrossCameraSyncMonitor, EventLog)
- tests/pipeline_analyzer/analyzer_ui.py (complete rewrite 1090 -> 1463 lines: CameraTile, TileImageWidget, GlobalSummaryPanel, TimelineView, EventLogWidget, multi-camera AnalyzerWindow)
- CHANGELOG.md (updated)

## 2026-07-23 18:30
### What changed
- **Fixed blank GUI** in Pipeline Analyzer: replaced silent `except Exception: pass` in `_poll_frames()` and `_update_selected_display()` with `print()` logging so errors are visible in console.
- **Eliminated double `get_frame()`**: `_update_selected_display` now uses `analyzer.last_rgb` (pre-calibrated in `observe_gui_poll()`) instead of re-calling `get_frame()` and recalibrating.
- **Duplicate-frame guard**: `observe_gui_poll()` returns `None` immediately if `seq == self._last_gui_sequence`, preventing 3-4x processing of the same frame (30ms poll vs ~111ms frame interval).
- **Error messages on thermal widget**: `show_error()` displays calibration/display errors directly on the `ThermalDisplayWidget` instead of blank screen.
- **Display FPS accuracy**: `_display_fps` now only records when calibration produces a valid RGB image, not on every poll.
- **Reset hygiene**: `reset()` clears `_last_rgb` so display goes back to "Waiting for frame..." after reset.
### Why
- Silent exception handling made the analyzer uninformative when calibration fails or camera returns unexpected data.
- Double `get_frame()` could return a different frame than the one lifecycle timestamps were recorded for.
- Duplicate frame processing inflated FPS metrics and caused unnecessary recalibration cycles.
### Notes
- All remaining LSP errors are pre-existing false positives (Pyright vs PyQt6 dynamic typing, unknown `get_frame` return type).
### Files Changed
- tests/pipeline_analyzer/analyzer_core.py
- tests/pipeline_analyzer/analyzer_ui.py

## 2026-07-23 18:00
### What changed
- **Phase 1C — Acquisition Pipeline Analyzer**: New `tests/pipeline_analyzer/` module built as a dedicated engineering diagnostic application that observes the production acquisition pipeline without modifying it.
- **No new acquisition implementation**: Uses the existing `TV46LCamera` (`camera/tv46l_camera.py`) with `RawFrame` timestamps — no new camera driver, acquisition loop, or grabbing thread created.
- **Multi-FPS metrics**: Separate `Camera FPS`, `Published FPS`, `Display FPS`, `Paint FPS` tracked independently per stage, always shown together to pinpoint where frame loss occurs.
- **Per-frame lifecycle tracking**: `FrameLifecycle` dataclass records timestamps for every stage (Camera Exposure → HALCON Grab → NumPy Conversion → RawFrame Publish → GUI Receive → Calibration → Colormap → Qt Paint → Paint Complete) — all timestamps belong to the same frame.
- **Freeze detection**: `FreezeDetector` monitors acquisition age, GUI age, and paint age separately. Reports `Acquisition Freeze`, `GUI Freeze`, or `Paint Freeze` with duration. Automatically detects if acquisition continues but painting stops vs. acquisition itself stops.
- **Sequence integrity**: `SequenceAnalyzer` tracks expected/received sequence, gap size, lost frames, loss %, consecutive loss, duplicate frames. Statistics available over configurable windows.
- **Horizontal distortion detection**: Optional frame checksum comparison. Detects repeated rows, partial frame updates, and corruption via MD5 hash comparison.
- **Delay source identification**: `LatencyAnalyzer` computes percentage contribution per stage group (Camera Acquisition, NumPy, Publication, GUI, Calibration, Display Conversion, Qt Rendering) — immediately identifies the dominant bottleneck.
- **NUC isolation diagnostics**: `NucIsolationMonitor` records frame timestamps per camera, checks all other cameras BEFORE and AFTER NUC execution on any single camera. Generates `CameraPauseEvent` warnings if another camera pauses (with duration in ms and cause).
- **Network verification**: Reads transport layer statistics (packet loss, resend requests, duplicate packets, sequence loss %) from the camera's GigE Vision stream counters.
- **Lightweight mode**: Configurable to disable expensive operations (checksums, full lifecycle tracking) so the analyzer itself never becomes the bottleneck.
- **Real-time GUI**: Dark-theme diagnostic window with thermal preview, FPS panel, latency breakdown table, per-stage timing table, sequence integrity table, frame lifecycle view, NUC isolation panel, and network stats — all updated in real-time via Qt timers.
### Why
- Determine exactly where latency, freezes, horizontal distortion, skipped frames, and delays originate before modifying the production architecture further.
- NUC isolation testing verifies whether NUC on one camera causes other cameras to pause (shared HALCON lock, global mutex, or synchronous command execution hypothesis).
- Multi-camera independence verification ensures no camera ever blocks another during NUC, focus, reconnect, or disconnect.
### Files Changed
- tests/pipeline_analyzer/__init__.py (new)
- tests/pipeline_analyzer/__main__.py (new)
- tests/pipeline_analyzer/analyzer_core.py (new — 811 lines)
- tests/pipeline_analyzer/analyzer_ui.py (new — 1074 lines)
- CHANGELOG.md (updated)

## 2026-07-22 23:00
### What changed
- **Focus sentinel**: Added `FOCUS_UNAVAILABLE_MM = 1000000.0` constant, `focus_available()`, `get_focus_distance_or_none()` to `TV46LCamera`. UI now detects sentinel → disables focus buttons → displays "N/A mm".
- **Skipped frame counters**: Split single `skipped_frames` into `acquisition_drops` (camera sequence gaps), `gui_drops` (newest-frame-only drops), `rendering_drops` (duplicate sequence frames) in `PerCameraData`.
- **Rendering/timing instrumentation**: `_poll_one_camera` now times display, colormap, QImage, QPixmap stages and populates `TimingMonitor` + graph series. `CameraTileWidget` overrides `paintEvent` to capture paint timing, drained in `_update_diagnostics`.
- **Transport stats**: `evaluate_transport` now uses loss_ratio / resend_ratio relative to total seen packets instead of absolute thresholds.
- **Empty graphs**: Added graph points for `display_colormap`, `qimage_pixmap`, `total`, `paint` series.
- **Tile layout**: Grid now supports up to 5 columns for 8+ cameras.
- **Qualification report**: Added per-stage latency breakdown table (acquire, numpy, publish, gui_delay, display, colormap, qimage, pixmap). Transport summary now includes seen/dup counts.
### Why
- Fix 9 Phase 1B engineering issues identified during multi-camera qualification testing.
### Files Changed
- camera/tv46l_camera.py (focus sentinel detection)
- tests/camera_viewer.py (9 fixes across MainWindow, CameraTileWidget, PerCameraData, QualificationSession, _poll_one_camera, _update_diagnostics)
- CHANGELOG.md (updated)

## 2026-07-22 22:30
### What changed
- Phase 1B changes applied to `tests/camera_viewer.py`: multi-camera support, camera selection, NUC/Focus controls, compact tiles, light theme.
- Added `CameraTileWidget` — compact selectable tile with thermal image + compact stats (F, L, S), blue border on select, emits `selected(serial)`.
- Added `CameraControlPanel` — single panel for all cameras: Execute NUC, << Near / Far >> focus buttons, focus distance display, selected camera info. All disabled when no camera selected.
- Added `PerCameraData` dataclass — groups per-camera runtime state (TV46LCamera, TimingMonitor, FrameHistory, GraphManager, QualificationSession, QualificationMonitor).
- Rewrote `MainWindow`: responsive tile grid (1-4 cols based on camera count), left=tiles right=detail panels in horizontal splitter, bottom control panel, light engineering theme stylesheet.
- Camera selection via tile click: detail panels (tabs, timing table, graphs, event log) show selected camera's data. Qualification Report operates on selected camera.
- NUC: calls `TV46LCamera.manual_nuc()` (existing API) — never stops acquisition.
- Focus: discrete buttons, each click reads → calculates → calls `set_focus_distance()` → `wait_for_focus()` → reads back → displays camera-reported value.
- All camera controls operate exclusively on selected camera.
### Why
- Match the production MainWindow qualification tool behavior so camera_viewer.py can test multi-camera NUC/focus validation.
### Files Changed
- tests/camera_viewer.py (added CameraTileWidget, CameraControlPanel, PerCameraData; rewrote MainWindow)
- CHANGELOG.md (updated)

## 2026-07-22 22:00
- **HalconDriver**: Added `perform_nuc()` (manual NUC via HALCON params), focus API (`get_focus_distance`, `set_focus_distance`, `get_focus_limits`, `wait_for_focus`, `focus_busy`).
- **Service TV46LCamera**: Added `focus_near()`, `focus_far()`, `get_focus_distance()`, `get_focus_limits()`, `wait_for_focus()` — all delegate to HalconDriver. Fixed missing `_connected` init, fixed status enum usage. No camera control logic duplicated.
- **CameraStatus enum**: Added `DISCONNECTED`, `STREAMING`, `RUNNING` values.
- **ApplicationController**: Added `selected_camera_id` / `selected_camera` properties, `select_camera()`, `perform_nuc_selected()`, `focus_near_selected()`, `focus_far_selected()`, `get_focus_distance_selected()`, plus per-camera focus methods.
- **CameraTile widget** (`gui/widgets/camera_tile.py`): Compact selectable tile — thermal image ~80%, compact status bar (F, S, L, D, T, FPS), click-to-select with blue border + "SELECTED" label, emits `clicked(camera_id)`.
- **CameraControlPanel** (`gui/widgets/camera_control_panel.py`): Single control panel for all cameras — Execute NUC button, << Near / Far >> focus buttons, current focus distance display, selected camera info. All buttons disabled when no camera selected.
- **MainWindow** (`gui/main_window.py`): Light engineering theme (light bg, high contrast, neutral colors), responsive grid layout (1-4 cols based on 1-8 cameras), bottom control panel via QSplitter, toolbar (Start All / Stop All), QTimer-based frame polling at 30Hz, status bar with camera count.
- NUC: calls `HalconDriver.perform_nuc()` — never stops acquisition, never reconnects, never restarts streaming.
- Focus: buttons only (no slider), each click reads → calculates → calls API → waits → reads back → displays camera-reported value.
- All camera controls operate exclusively on `selected_camera`, never on every camera.
### Why
- Qualification tool needs to validate production camera control APIs (NUC, focus) while acquisition is running, before Phase 2 (ROI → Alarm) begins.
- Slider-based focus control proved unreliable; replaced with discrete button steps.
- Dark theme replaced with light engineering theme suitable for industrial environments.
- Tiles needed space-efficient layout to support 8 cameras comfortably.
### Files Changed
- camera/services/halcon_driver.py (added perform_nuc, focus API)
- camera/services/tv46l_camera.py (added focus API, fixed bugs)
- camera/models/camera_model.py (added DISCONNECTED, STREAMING, RUNNING statuses)
- app/application_controller.py (added selected_camera, focus methods)
- gui/widgets/camera_tile.py (new - compact selectable tile)
- gui/widgets/camera_control_panel.py (new - single control panel)
- gui/main_window.py (new - qualification tool main window)
- CHANGELOG.md (updated)

## 2026-07-22 21:00
### What changed
- Created `tests/focus_test.py` - standalone PyQt6 GUI tool for live TV46L focus diagnostics.
- Features: live thermal video, focus distance read/write timing, settle polling, busy detection, categorized step buttons (+25/+250/+1000 mm), slider/spin controls, keyboard shortcuts.
- Halcon_Parameters.md focus params wired via TV46LCamera.get_parameter/set_parameter.
- Three discovery modes: explicit CLI args, CameraDiscovery auto-detect, or inline defaults.
### Why
- Need a GUI tool to interactively diagnose focus command failure, supplementing CLI diagnose_focus.py.
### Notes
- Run: python -m tests.focus_test [--device --serial --model --ip]
### Files Changed
- tests/focus_test.py

## 2026-07-22 16:00
### What changed
- Transformed `tests/camera_viewer.py` into professional Phase 1 Camera Qualification Tool (3138 lines).
- Added per-frame `FrameTimeline` model — each frame tracks its own pipeline timestamps; paint events matched to correct frame by `frame_number` via `FrameHistory.find_by_frame_number()`. Impossible latency values eliminated.
- Created `tests/qualification/` package with: `frame_timeline.py` (FrameTimeline, TimelineCollector, StageStats), `focus_analyzer.py` (FocusAnalyzer — Laplacian variance + Tenengrad), `nuc_detector.py` (NUCDetector — histogram shift, sharpness recovery, freeze detection), `report_generator.py` (QualificationReportGenerator — text + JSON reports).
- Added real-time focus quality analysis — Laplacian variance computed every Nth frame; displays numeric score, SHARP/GOOD/SOFT/BLURRY status, trend arrow, automatic warning on sustained degradation.
- Added NUC event detection — monitors histogram shifts, global brightness changes, sharpness recovery to estimate NUC events; logs probable NUC with timestamp.
- Replaced minimal overlay with rich camera tile display: serial number, PASS/WARNING/FAIL badge, FPS, latency, dropped frames, timeouts, focus score + status, NUC count, frame number — all readable from several feet.
- Expanded detail tabs from 4 to 10 sections: Acquisition, Processing, Timing, Transport, Focus, NUC, Health, Resources, Thread, Queue.
- Transport tab shows all GigE Vision statistics (seen, lost, delivered, unavailable, duplicate, resend packets).
- All health evaluations return (status, reason) tuples — every PASS/WARNING/FAIL includes explanation.
- Added Thread tab showing acquisition thread running state, FPS, frame rate.
- Added Queue tab (future-proofed with N/A placeholders).
- Added Focus tab with current/average/min/max score, trend, health status.
- Added NUC tab with event count, last NUC time, average interval, manual NUC button.
- Added automatic qualification report generation on application closeEvent — saves `Qualification_Report_*.txt` and `*.json` to `reports/` directory with full session data, per-camera metrics, event timeline.
- Graphs automatically exported as PNG images on close.
- Event logging expanded: logs NUC events, focus degradation, focus recovery, reconnects, timeouts, stress test changes.
- All existing pipeline unchanged: TV46LCamera → RawFrame → Calibration → Display → Qt Rendering.
### Why
- The timing system previously mixed timestamps from different frames, producing physically impossible latency values.
- Real-world thermal camera NUC events and focus drift needed automatic detection during long qualification runs.
- Professional qualification requires comprehensive reporting with clear PASS/WARNING/FAIL reasons.
- Detail tabs needed to cover all pipeline stages for thorough diagnostics.
- Report generation must be automatic to prevent data loss on accidental close.
### Notes
- FrameTimeline replaces mixed-frame timing: each paint event carries `frame_number` to match to the correct FrameTimeline in history.
- All new modules in `tests/qualification/` package — no changes to production code.
- Reports directory created at `reports/` with `.gitkeep`.
- Manual NUC button is present but disabled by default; can be wired to camera API when NUC command support is confirmed for the specific camera.
### Files Changed
- tests/camera_viewer.py (complete rewrite with all new features)
- tests/qualification/__init__.py (new)
- tests/qualification/frame_timeline.py (new)
- tests/qualification/focus_analyzer.py (new)
- tests/qualification/nuc_detector.py (new)
- tests/qualification/report_generator.py (new)
- CHANGELOG.md (updated)

## 2026-07-22 16:00
### What changed
- Refactored `tests/camera_viewer.py` from single-camera to multi-camera qualification tool (Phase 1B).
- Added `CameraContext` dataclass — groups per-camera state: TV46LCamera, QualificationSession, TimingMonitor, FrameHistory, GraphManager, EventLogger, QualificationMonitor, ThermalWidget, tile widget, sequence tracking, frame counts, health status.
- Added `CameraTileWidget` (extends QFrame) — composite widget containing ThermalWidget + compact info bar displaying: camera name, connection status, FPS, latency, frame number, dropped/timeout count, PASS/WARNING/FAIL.
- Replaced single-camera `MainWindow` with data-driven `camera_contexts: list[CameraContext]` — all camera operations iterate over the list; no `camera1`/`camera2` patterns.
- Added dynamic grid layout for 1–8 camera tiles: 1 col for 1 cam, 2 cols for 2–4 cams, 3 cols for 5–6 cams, 4 cols for 7–8 cams.
- Added per-camera qualification reports via existing `QualificationSession` — each camera generates its own independent report.
- Added `_generate_system_report()` — aggregates all cameras: connected count, total/average/min/max FPS, total CPU/memory, maximum latency, worst camera identification, overall PASS/WARNING/FAIL.
- Added camera selector (QComboBox) to switch which camera's detail panels (Acquisition, Processing, Health, Timing) and graphs are displayed.
- Added system info bar showing aggregate metrics across all cameras.
- Added per-camera tab system in the qualification report dialog.
- Independent camera initialization — if one camera fails, remaining cameras continue initializing; failures don't block or cascade.
- Each camera runs its own acquisition thread (via existing TV46LCamera), own timing collection, own frame history.
- System-wide event log consolidates per-camera events with camera serial prefix.
- Updated `closeEvent` to stop/disconnect all cameras independently.
### Why
- Phase 1B: qualify and validate the existing camera subsystem under multiple simultaneous cameras using the same production classes (TV46LCamera → RawFrame → Calibration → Display).
- Validate that the acquisition subsystem scales correctly without introducing a parallel implementation.
### Notes
- Uses `CameraDiscovery` from `camera/camera_discovery.py` for full camera info (serial, model, vendor, IP).
- `CalibrationManager` is shared across all cameras (stateless, read-only).
- All existing diagnostic classes preserved: StageStats, FrameRecord, FrameHistory, EventLogger, TimingMonitor, GraphManager, GraphWidget, ThermalWidget, QualificationMonitor, HealthEvaluator, QualificationSession, QualificationEngine, AcquisitionPanel, ProcessingPanel, SystemPanel, HealthPanel, TimingTable.
### Files Changed
- tests/camera_viewer.py

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
