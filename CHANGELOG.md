# Changelog

## 2026-08-15 10:00

### What changed
- Added a Time-sliced strategy (now the default) to `halcon_camera_diagnosis.py`. The camera has one GigE stream channel and a camera-global source selector, and live tests showed both dual-handle (visible lags, IR disturbed by selector flap) and rapid switching (feed badly disturbed) are disruptive. Time-sliced keeps IR streaming continuously at full rate for 2 s, then flips to VL_Data for a 0.6 s visible burst and back - only two source switches per cycle, so IR stays smooth and visible updates periodically. This restores the stable-IR behaviour that was lost when the earlier single-handle fallback was removed. Strategies that pause IR by design now get a longer wedge window (`wedge_recovery_s`) so the visible phase does not trigger a spurious reconnect.
### Why
- "None of the strategies is working" - live testing confirmed the camera cannot stream both feeds cleanly through source switching. Time-sliced is the reliable configuration within the hardware limit: IR priority, periodic visible. The experimental strategies (rapid switch, dual handle, dual component) stay available for measuring the camera's real limits.
### Notes
- Verify on camera: time-sliced should show smooth IR (~9 FPS during the IR phase) with visible updating every ~2.6 s. Check the "Payload:" line in Dual Component mode for evidence of a combined IR+visible frame (the only mechanism that could beat time-slicing).
### Files Changed
- halcon_camera_diagnosis.py
- CHANGELOG.md

## 2026-08-15 09:00

### What changed
- Rebuilt `halcon_camera_diagnosis.py` as an experimental acquisition-strategy tester. Added four selectable strategies: Baseline (single handle, IR_Data only, reproduces `halcon_roi_validation.py`), Dual Handle (two GigE connections: device string + camera IP, both streaming), Rapid Source Switching (single handle alternating IR_Data/VL_Data at a configurable hold interval, with per-direction switch-latency measurement), and Dual Component (single handle; probes payload-related HALCON parameters and the acquired frame's shape/channels to detect whether one frame carries both IR and visible). Added an automated experiment mode that sweeps rapid-switch hold intervals (1000, 500, 250, 100, 50, 25, 10 ms), runs each for 5 s, and reports IR FPS, visible FPS, frame counts, errors, and switch latencies in a results table in the GUI. Worker loop was refactored around a `BaseStrategy.step()` contract with a shared `_route_result()`; acquisition, processing and display FPS/latency stay measured separately.
### Why
- The TV46L has exactly one GigE stream channel (`DeviceStreamChannelCount=1`) and a camera-global `FLK_TI_StreamDataSourceSelector`, so visible lag was suspected to be a hard hardware limit. Instead of assuming that, the tool now experimentally tests every acquisition mechanism (dual connection, rapid switching at measured minimum intervals, combined payload/components) so the measured camera/HALCON behavior, not an assumption, determines the conclusion. ThermoView displays both feeds at full rate, so the mechanism must be found, not ruled out.
### Notes
- Requires a live camera to run the experiments. Watch the log and the "Run Switch Experiment" results. The Dual Component strategy reports payload probe evidence (e.g. `image_channels`, `PayloadSize`, frame shape) to decide whether a combined frame exists. If rapid switching shows a low stable minimum switch time, dual full-rate may be achievable via fast alternation; if not, that is the experimental answer.
### Files Changed
- halcon_camera_diagnosis.py
- CHANGELOG.md

## 2026-08-14 15:00

### What changed
- `halcon_camera_diagnosis.py`: rewrote visible acquisition so the visible feed works even though HALCON GigEVision2 can only open one stream per camera and the TV46L's `FLK_TI_StreamDataSourceSelector` is camera-global. The second handle is now opened by camera IP instead of the device string (which HALCON refused with error #5312). If the camera accepts the second connection (dual mode), both feeds stream concurrently; if not, the tool falls back to single-handle time-sliced visible sampling: it switches the shared stream to VL_Data every 4 s, grabs one visible frame, and switches back. Added `_dotted_ip()` (converts the integer IP from `[Device]GevDeviceIPAddress` to dotted form), `_verify_visible_stream()` (detects when the visible handle just echoes the IR source by comparing frame byte sizes and drops the handle), `_disable_visible()` and `close_visible()`. The IR ingest now detects a stream-source conflict (IR frame byte size suddenly changes) and disables the conflicting dual-stream.
### Why
- User test showed the visible feed was missing: opening a second handle with the same device string failed with HALCON error #5312 (device already in use). HALCON GigEVision2 opens only the first available stream channel per camera, so concurrent IR+VIS requires either a second IP connection or time-slicing the single stream.
### Notes
- Requires a live camera to verify which mode the TV46L enters. The IP second-connection may be refused by the camera, or the visible handle may echo the IR source (source selector is camera-global) - both cases fall back to time-sliced sampling, which costs roughly 1 s of IR FPS per 4 s cycle. Watch the log for "visible stream open ... failed" / "visible dual-stream unavailable" / "IR only (stream source conflict)".
### Files Changed
- halcon_camera_diagnosis.py
- CHANGELOG.md

## 2026-08-14 10:00

### What changed
- Fixed the disabled visible feed in `halcon_camera_diagnosis.py`. Stream switching now uses a clean `switch_stream()` (abort pending grab, select source, restart acquisition, drain stale frames) instead of switching `FLK_TI_StreamDataSourceSelector` mid-acquisition. Bit depth follows the stream: 16 for IR_Data, -1 (HALCON default) for VL_Data YUV422_8. Visible-grab errors are now logged at WARNING for the first 3 failures instead of DEBUG, so the real HALCON error is visible.
### Why
- The visible (VL_Data) stream was disabled after 5 consecutive grab failures. The old per-frame switch kept the IR bit depth (16) active on the 8-bit YUV visible stream and did not abort the pending IR grab, so HALCON rejected the visible grab.
### Notes
- Requires a live camera to verify the visible feed now streams. `num_buffers` still reports read-only on this camera; that warning is harmless.
### Files Changed
- halcon_camera_diagnosis.py
- CHANGELOG.md

## 2026-08-14 12:30

### What changed
- Rewrote IR/VIS acquisition in `halcon_camera_diagnosis.py`. Replaced the single framegrabber that switched streams (IR_Data / VL_Data) every loop iteration with two dedicated framegrabber handles (`_ir_fg`, `_vis_fg`), one locked to each stream. The loop now does non-blocking newest-frame grabs from both handles and a stall (no IR frame for 3 s) reopens both handles. Visible frames are now handled as RGB8 when HALCON delivers 3-channel data (640x480x3 = 921600 B/f) instead of being mis-decoded as packed YUYV; the YUYV decoder stays as a fallback for other builds.
### Why
- The old per-frame `switch_stream()` did abort + re-arm + GigE re-sync + drain on every iteration, which capped the whole loop at ~0.8 FPS (IR and VIS). The ROI validation tool never switches streams and runs smooth at the configured 9 FPS; the diagnosis tool now mirrors that for both feeds, so IR returns to 9 FPS and the visible feed runs at whatever the camera supplies.
### Notes
- Requires a live camera to verify both feeds now run at full rate. If the camera rejects a second GigE connection, the visible handle open degrades to IR-only (visible shows "N/A") instead of failing. Visible native rate may still be capped if `FLK_TI_ControlFeature_SetFrameRate` is a global camera control rather than IR-only.
### Files Changed
- halcon_camera_diagnosis.py
- CHANGELOG.md

## 2026-08-13 12:00

### What changed
- Added section `2A. Detailed Execution Flow (End-to-End)` to `docs/halcon_roi_validation_review.md`: step-by-step flow of `halcon_roi_validation.py` from process startup through worker init, acquisition loop, per-frame ROI processing, alarms, snapshots, position switching, NUC, focus, and shutdown — with line references.
### Why
- Requested a detailed runtime flow so developers can trace the code's execution without reading all 3525 lines.
### Notes
- Documentation only; no code changed. Line references point at current `halcon_roi_validation.py` line numbers.
### Files Changed
- docs/halcon_roi_validation_review.md
- CHANGELOG.md

## 2026-08-13 00:00

### What changed
- Added `docs/halcon_roi_validation_review.md`, a full code review of `halcon_roi_validation.py` covering purpose, architecture, threading model, every HALCON operator with location/why, DB access, alarm engine, snapshot worker, NUC/focus handling, recovery logic, display layer, startup flow, and degradation points.
### Why
- Requested documentation so future developers/agents can understand the entire 3525-line validation tool without reading it top to bottom.
### Notes
- Documentation only; no code changed. Cross-references `docs/ROI_Architecture.md`, `docs/GUI_Event_Flow.md`, `docs/halcon_operators.md`.
### Files Changed
- docs/halcon_roi_validation_review.md
- CHANGELOG.md

## 2026-08-12 11:30

### What changed
- Added `setup_env.ps1`, a one-click environment setup script for fresh PCs. It locates Python 3.10, installs the global packages from the new `requirements-global.txt` (HALCON interface, NumPy, OpenCV, PyQt5, harvesters, genicam), creates the project venv with `--system-site-packages` when missing, installs the dev packages from `requirements-dev.txt`, verifies with `tools/check_environment.py`, then activates the venv.
- Added `start_app.bat`, a double-click launcher that runs the setup once and then starts the application (`main.py`) with the venv python.
- Added `requirements-global.txt` with the pinned global packages (mvtec-halcon 24113, numpy 2.2.6, opencv-python 4.13.0.92, PyQt5 5.15.11, harvesters 1.4.3, genicam 1.5.1).
### Why
- New machines had no documented way to recreate the environment; users had to follow `docs/Development_Setup.md` manually.
### Notes
- HALCON runtime (24.11) must be installed on the machine before `mvtec-halcon` can be installed; the script warns about this. Global packages are installed into the global Python, never into the venv (project constraint). Verified end-to-end on this PC: `ALL CHECKS PASSED`, `import app.application` works. On a PC without Python 3.10 the script aborts with instructions.
### Files Changed
- setup_env.ps1
- start_app.bat
- requirements-global.txt
- CHANGELOG.md

## 2026-08-12 10:50

### What changed
- Fixed `RuntimeError: wrapped C/C++ object of type QThread has been deleted` in `halcon_roi_validation.py` when clicking Connect again after an initialization run finished.
- The finished init `QThread` was deleted via `deleteLater` but `self._init_thread` kept a stale Python reference, so the next `start_initialization()` call touched a destroyed object. Added `_on_init_thread_finished()` which resets `_init_thread`/`_init_worker` to `None` when the thread stops; `closeEvent()` is now safe too.
### Why
- Re-connecting after a failed GigE discovery (no cameras found) crashed the app.
### Notes
- Signal slot runs on the GUI thread (the `QThread` object lives there), so clearing the references is safe. Verify by clicking Connect twice in a row.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-11 18:20

### What changed
- Startup no longer blocks the GUI in `halcon_roi_validation.py`. SQL connect, camera/ROI-config loading and HALCON GigE discovery now run on a dedicated `StartupWorker` QThread started after `window.show()`. The window appears immediately, shows "Initializing..." status, and stays fully usable; completion or failure is reported through signals. SQL failure or HALCON discovery failure no longer freezes or crashes the GUI.
- Added per-camera POSITION support. Each camera owns its own `camera_positions`; ROI sets are now `Camera + Position -> ROIs` instead of `Camera -> ROIs`. New toolbar controls `Position: N` + `Next Position` operate on the selected camera only and wrap around its enabled positions. Changing one camera's position never touches the others.
- Position switch replaces only the active ROI regions for the selected camera (worker-side `request_position`/`_apply_position` inside the acquisition loop); no reconnect, no NUC, no acquisition restart. Alarm limits remain camera-specific and unchanged.
- `DatabaseRepository` added `load_camera_positions()` and an optional `position_id` filter on `load_rois()`; schema probes keep legacy databases (no `position_id` column / no `camera_positions` table) working with the old camera-wide ROI set.
### Why
- Slow SQL/HALCON startup previously froze the GUI. Positions let the pan/tilt system later move a camera between ROI sets without touching acquisition.
### Notes
- SQL schema requires two changes (see below) for position support; the code degrades gracefully without them. Camera acquisition, TV46LCamera, calibration and alarm logic untouched. Verified with `py_compile`, ruff (no new error classes vs baseline), and standalone smoke tests of the init flow, position wrap and per-camera independence. HALCON runtime and real cameras not available in the dev environment, so live validation is still required.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-11 14:45

### What changed
- Added `tests/diagnose_pipeline.py`, a standalone pipeline diagnostic for the TV46L GigE camera.
- Observes only: discovers/opens one camera, streams via the existing `TV46LCamera` (unchanged), then measures acquisition interval/jitter, per-frame checksum duplicate detection, minimal processing time, latest-frame-wins publication, acquisition-to-display latency, acquisition/processing/display backlogs, HALCON GigE packet counters, process RSS memory, and GC counts.
- Simple PyQt6 window shows the latest thermal frame plus live diagnostics; prints a diagnostic block every second and a final summary + evidence-based interpretation on Ctrl+C or `--duration N`.
- CLI: `--serial SN` selects a camera, `--duration SECONDS` auto-stops (0 = Ctrl+C). Frame ID/age reported as `unavailable` when HALCON exposes no such parameter.
### Why
- Locate where the progressive video lag/freeze originates in the TV46L pipeline without modifying production code or camera settings.
### Notes
- No production code or camera settings touched. During a 60 s test run the camera was already degraded (0.6 FPS, avg interval 1579 ms, jitter 1709 ms, lost packets 190->7046); processing (0.8 ms), display (31 ms avg latency) and memory (flat ~128 MB) were stable, 0 duplicate frames. Verified with `py_compile` + ruff (clean).
### Files Changed
- tests/diagnose_pipeline.py
- CHANGELOG.md

## 2026-08-11 12:55

### What changed
- Bottom status bar reworked in `halcon_roi_validation.py`: the left message now shows only `640 × 480 | Zoom | Active Alarms | Next NUC`; the right side shows the selected camera's five statistics only (`Acq FPS`, `Proc FPS`, `Disp FPS`, `Packet Loss/min`, `Total Packet Loss`).
- Duplicate status info removed: no more FPS/packet-loss/alarm-limit text in the left status message; alarm limit remains only in the top toolbar.
- Alarm terminal flooding removed: `_on_alarm_event` no longer emits `ALARM ACTIVE/CLEARED` lines; alarm state lives only in the common alarm table, alarm detection/evaluation unchanged.
- `Packet Loss/min` and `Total Packet Loss` now come from the HALCON GigE `[Stream]GevStreamLostPacketCount` counter. `Total` is the cumulative counter; `Per/min` is the change between consecutive samples over a rolling one-minute window. A backwards counter (reconnect / stream re-arm) resets the baseline instead of producing a false spike.
- Removed the old grab-timeout based packet-loss counter and its signal wiring.
### Why
- The status bar mixed camera-wide and per-camera data, duplicated values, and the event log was flooded with per-transition alarm messages while the authoritative alarm table already exists.
### Notes
- Uses actual HALCON stream counters only; packet loss is never derived from image tearing or GUI frame drops. Before a full minute of samples exists, `Packet Loss/min` reflects the elapsed interval only (not scaled to a synthetic full-minute value). Worker/acquisition/threading untouched; verified via `py_compile`, ruff (same error count as baseline, no new violations), and a standalone rolling-window logic test (counter reset + window expiry). Live hardware with 2+ cameras still needed for visual confirmation.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-11 10:25

### What changed
- Seeded the local `ThermalMonitor.dbo.cameras` table with the 4 known physical cameras (HB25100002/4/8, HB25080011 -> camera_number 1-4, model TV46L, enabled = 1, IP left NULL). Idempotent: existing serials are skipped.
### Why
- The cameras table was empty, so the SQL-driven connect correctly reported `Cameras loaded: 0` and no tiles were assigned even though 4 cameras were discovered. The app now loads `Cameras loaded: 4` and maps tiles by camera_number/serial.
### Notes
- Data-only change; schema untouched. `dbo.rois` and `dbo.alarm_settings` are still empty, so ROIs are absent and the global alarm default falls back to config.json (80.0 °C). ROIs can be loaded once rows are inserted.
### Files Changed
- halcon_roi_validation.py (unchanged this task)
- CHANGELOG.md

## 2026-08-11 10:15

### What changed
- Replaced JSON/config data sources in `halcon_roi_validation.py` with the `ThermalMonitor` SQL Server database (Part 2 of the DB migration; no other file touched).
- Cameras now come from `dbo.cameras`: enabled cameras only, ordered by `camera_number`, matched to discovered devices by serial number (IP as fallback). `camera_number` decides the 2x2 tile, so the fixed serial-to-tile behaviour is preserved and discovery order is never used. Disabled cameras (`enabled = 0`) are skipped.
- ROIs now load from `dbo.rois` joined through `rois.camera_id -> cameras.id`, only `enabled = 1`, keeping the existing `(y1, x1, y2, x2)` coordinate interpretation and all HALCON ROI math untouched. The `rois.json` loading path was removed; `rois.json` is no longer required.
- Default alarm configuration (`temperature_limit`, `enabled`, `use_max_temperature`) loads from `dbo.alarm_settings`. Each camera now has its own runtime alarm limit: a toolbar `Alarm Limit` spinbox edits the selected camera's limit live through the worker's new `set_alarm_limit()`. Because the current schema has no `camera_id` column, per-camera limits live in application memory only and are not persisted back to SQL (reported once as a known limitation).
- Settings with a clear `dbo.application_settings` equivalent now override `config.json` (mapping table `ConfigManager.CONFIG_TO_DB_KEY`); missing keys fall back to `config.json` and then built-in defaults.
- New `DatabaseRepository`/`DatabaseConfig` in the same file: isolated connection config at the top (Windows Integrated Security by default, env-var overridable), graceful failure when SQL is unreachable (clear log/event-log error, no crash, discovery-order fallback). Startup now logs `SQL connected`, `Cameras loaded: N`, `Disabled cameras skipped: N`, and `ROIs loaded for Camera N: N`.
### Why
- Move all camera/ROI/alarm configuration out of JSON files and into the existing SQL Server schema, preparing per-camera alarm configuration while the database is still global.
### Notes
- Schema untouched; all SQL access is read-only. Acquisition loop, threading, HALCON acquisition, calibration, temperature conversion, NUC, focus and packet handling unchanged. Verified via `py_compile`, ruff (F-severity), and an end-to-end smoke test against a throwaway copy of the schema (31 checks: connect, camera ordering/tile assignment, disabled skip, per-camera ROI load, alarm defaults, application-settings overrides, worker wiring, graceful DB-down). Live hardware is still required to re-confirm streaming.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 19:30

### What changed
- Added camera selection to the four-camera viewer. The user picks one camera by clicking anywhere inside its image; the selected panel gets a 3 px cyan border and its title shows the `| SELECTED` suffix (e.g. `Camera 2 | Connected | SELECTED`), while unselected panels keep `Camera 1 | Connected`. Only one camera may be selected; the default is Camera 1. Acquisition is untouched: every camera keeps its own framegrabber/worker/thread, ROI processing, alarm engine and auto-NUC timer regardless of selection.
### Why
- The app needs its final operating model where the operator focuses all tooling and readouts on one camera while the other three keep monitoring in the background.
### Notes
- Selection is a pure GUI/state refactor in `MainWindow`. One index (`self._selected_index`) is the single source of truth; every toolbar control, table, status readout and mouse view reads `self.cameras[_selected_index]`. A new `_select_camera()` applies the border via `CameraPanel.set_selected()` and calls `_refresh_selected_state()` so the ROI table, alarm table, mouse readout, status bar and NUC/focus/zoom state repopulate instantly from the just-selected camera. `CameraRuntime` now caches `latest_alarms` so switching selection never waits for a fresh alarm emit. Mouse temperature and stale alarm coloring now apply only to the selected camera; toolbar controls (focus, Manual NUC, Reload ROI) target the selected worker only, and focus/NUC/reload buttons enable only when the selected camera is connected. Alarm/ROI state is per-camera and never merged. Verify with live hardware that clicking any camera switches the border/title and that background cameras keep streaming, processing ROIs and raising alarms while another is selected.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 17:50

### What changed
- Fixed per-frame `AttributeError: 'NoneType' object has no attribute '_key'` crash in the four-camera viewer. Root cause: `rois.json` contained no ROIs (empty `[]`), so `_generate_halcon_regions()` returned early and left `_roi_regions` as `None`; the loop then called `ha.intensity(None, ...)` on every frame, which raised in `set_input_object`. The statistics block now checks `if self._roi_regions is not None` and emits an empty `ROIStatistics` list when no ROIs are loaded, so acquisition, display, alarms and GUI continue normally with zero ROIs. Batch loop and alarm evaluation are unchanged when ROIs exist.
### Why
- The app logged "Frame processing error" continuously and produced no working statistics whenever the ROI file contained no ROI entries.
### Notes
- Only `halcon_roi_validation.py` + `CHANGELOG.md` modified. Empty-ROI path emits `statistics=[]` (alarm engine no-ops, ROI table empty, no overlays). `py_compile` + `ruff` clean. Regression tests referenced the full 518 passed / 8 failed pre-existing baseline.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 17:42

### What changed
- Camera views now fill the 2x2 grid. The huge gaps and tiny images were caused by `HALCONDisplayWidget` using `QSizePolicy.Fixed` + `setFixedSize(640x480)` (zoom-derived), which overrode the panel's fit sizing and left the image smaller than its cell. The widget is now Expanding with no fixed size; the grid owns all space; on every resize the HALCON window is sized to the largest 4:3 rectangle that fits the widget and centered via a shared `_display_rect()`. This preserves the 640x480 aspect ratio with no stretch and no crop. Grid spacing reduced to 12 px, panel/toolbar margins tightened, and the grid stretch raised from 3 to 5 so the four cameras occupy almost the whole window. Mouse-to-image mapping now uses the actual displayed rectangle (letterbox margins ignored), so the temperature readout stays exact at any size.
- Cameras no longer time out/reconnect after Manual or Auto NUC. Root cause: while the camera internally performs NUC it deliberately produces no frames, but the grab loop treated every timeout as an acquisition failure and, after `CONSECUTIVE_FAIL_LIMIT`, closed and reopened the framegrabber, glitching all feeds. Now the worker tracks NUC state (`_nuc_active`, set in `_execute_nuc`): during NUC a grab timeout is expected and is handled by `_handle_nuc_wait_timeout`, which logs camera/serial/frame/grab-duration/timeout-count, waits at a throttled interval, and never counts it as a failure. Only if no frame arrives within the configurable NUC recovery window (`camera.grab_timeout_before_reconnect_seconds`, default 8 s) is the existing reconnect ladder used. After the first valid frame the worker emits the NUC completion log, discards exactly one frame (`_nuc_skip_next_frame`, in case it is unstable), then resumes normal acquisition. No framegrabber reopen, no reconnect, no ROI/calibration rebuild occurs on the NUC path.
- NUC timing moved into configuration (no hardcoding in the worker): keys `camera.nuc_duration_seconds` (2.5), `camera.nuc_grab_retry_interval_ms` (100) and `camera.grab_timeout_before_reconnect_seconds` (8) are declared in `ConfigManager.DEFAULT_CONFIG`, so they work out of the box and can later be overridden by adding them to `config.json`. `config.json` itself was not edited in this task.
### Why
- Four cameras embedded in one window and NUC stability for repeated Manual NUC operation (10 consecutive triggers without freezing unaffected cameras).
### Notes
- NUC command code path unchanged (same two REControlCmd writes + 0.05 s settle). The previous drain-loop of three `grab_image_async(.., 0)` after NUC was removed because it could itself see a timeout and confuse the loop; the throttled wait now handles recovery. Live hardware is required to confirm 10x Manual NUC behavior and that packet loss after NUC is reduced; offline pytest (518 passed, 8 failed) matches the documented pre-existing baseline (4 HALCON region-identity + 2 alarm-threshold + 2 pixel-convention tests). Only halcon_roi_validation.py + CHANGELOG.md modified.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 19:10

### What changed
- Fixed four-camera viewer cropping + wasted space. `HALCONDisplayWidget` previously resized its HALCON window to the zoom-derived 640x480 (`_display_size()`), overriding the fit size the panel had just applied, so the 640x480 window overflowed the smaller widget and left large black margins. Now the HALCON window always opens to the widget's actual size and `set_part` stays constant at the full 640x480 frame (0,0,479,639); only `set_window_extents` follows the widget. New `_sync_window_size()` is used by `resizeEvent`, `set_fit_size` and `set_zoom_index`. Result: every camera fills its 2x2 cell, scales uniformly, no crop, no stretch.
- Repaired mouse-to-image mapping in `HALCONDisplayWidget.mouseMoveEvent`, which used the zoom factor instead of the real widget->image scale, so the mouse temperature readout is accurate at any fit size.
- Fixed the 20-30s camera freeze (HALCON #5322 grab timeout). The acquisition loop previously caught every grab exception and retried `grab_image_async` forever on the same wedged framegrabber, logging "Processing error" repeatedly with no recovery. `run()` now isolates the grab behind its own `try`, classifies timeouts via `error_code == 5322` (`_is_grab_timeout`), and recovers with a ladder: transient timeouts are retried; `CONSECUTIVE_FAIL_LIMIT` (3) consecutive timeouts close and reopen only that camera's framegrabber (`_reassign_framegrabber`), re-arming the stream without touching calibration LUTs, ROI regions or the connection. A failed reopen escalates to the existing full re-init path. Only the affected camera recovers; the other three keep streaming.
- Added per-camera diagnostics: `_log_buffer_config()` logs num_buffers/socket/grab_timeout at start, and `_log_periodic_diag()` logs camera, frame number, thread id, reconnect count, grab timeout and processing time every 90 frames so processing-vs-111ms drift is visible before data loss.
- Added best-effort `num_buffers = 8` setting in `_configure_camera` so four simultaneous streams draining slower than line rate do not overflow the receiver buffer pool.
### Why
- Make the 4-camera viewer production-ready: full-frame display that fills the grid, and self-healing acquisition so no camera hangs or spams timeouts after ~30s.
### Notes
- Steady-state verification (10+ minutes, zero #5322) requires live hardware and camera wiring, which is not available in this environment; the recovery + diagnostics are the production-safe mechanism. No new Python files; only halcon_roi_validation.py + CHANGELOG.md touched. `config.json` was already modified in the working tree before this task and was left unchanged.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

### What changed
- Refactored `halcon_roi_validation.py` from a single camera to a four-camera 2x2 grid viewer. Added `CameraRuntime` (per-camera runtime state) and `CameraPanel` (title bar + fit-sized viewer per tile). `MainWindow` now manages `self._cameras[0..3]`; each camera owns its own `CameraWorker`, `QThread`, framegrabber, calibration, ROIs, display, and alarm/focus/NUC state. `_start_worker(runtime)` wires one worker+thread per camera; `_disconnect_all()` / `_shutdown_thread(runtime)` stop them independently.
- Removed auto-connect on startup. App now opens with "No Camera" in every panel and no acquisition thread running. Pressing Connect discovers cameras and opens up to four; Disconnect stops all four; Connect again rebuilds fresh workers (repeated Connect/Disconnect cycles work).
- Camera titles show "Camera N | Connected/Disconnected/No Camera". Each panel keeps 640x480 aspect via new `HALCONDisplayWidget.set_fit_size` (no stretching). Rainbow palette, ROI overlays, ROI labels, mouse temperature, alarm coloring unchanged per camera.
### Why
- Phase 1 of the four-camera architecture: establish independent per-camera pipelines in one window before adding Phase 2 features.
### Notes
- Processing pipeline unchanged (grab -> calibration -> ROI stats -> alarms -> display), just duplicated per camera. Focus/NUC/ROI-reload buttons currently act on the selected camera (default camera 1). ROI/alarm tables and status bar show camera 1 data. Selection logic deferred to Phase 2. No new Python files; only halcon_roi_validation.py + CHANGELOG.md touched.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 18:20

### What changed
- Added configurable default focus. `config.json` `focus` section gained `default_focus_mm` (1200). After a successful `initialize()`, the worker moves the lens to that exact position once, waits for it to settle, reads the final value once, then starts acquisition.
- Added configurable default focus. `config.json` `focus` section gained `default_focus_mm` (1200). After a successful `initialize()`, the worker moves the lens to that exact position once, waits for it to settle, reads the final value once, then releases the connection and starts acquisition.
- Added `_apply_default_focus` and `_wait_focus_stable` to `CameraWorker`. Target read from config, clamped to driver limits, never hardcoded.
### Why
- Every camera should start at a known focus immediately after connecting, with no manual stepping.
### Notes
- Failure to move focus logs "Default focus failed" / "Continuing with current focus position." and does NOT abort the connection. Runs once per successful connect only. Edit `default_focus_mm` to 1500 changes next-launch focus with zero Python changes. Manual + / - / ++ / -- logic untouched.
### Files Changed
- halcon_roi_validation.py
- config.json
- CHANGELOG.md
### What changed
- Focus UI in `halcon_roi_validation.py` expanded from two buttons (`+`/`-`) to four (`--`, `-`, `+`, `++`), all on one toolbar row with a `Focus` label and tooltips. Focus log simplified: one command now prints only the button label and the final focus distance (`Current Focus : xxxx mm`); `Target`/`Actual` lines removed.
- Config: `config.json` `focus` section now has `coarse_step_mm` and `fine_step_mm` (replaces `step_mm`). Worker `request_focus`/`_execute_focus` take a signed step in mm read from config each command; no step values hardcoded in Python.
### Why
- Coarse/fine stepping gives finer control; minimal log reduces noise. Steps remain config-driven for easy tuning without code edits.
### Notes
- Focus algorithm unchanged (read current, apply step, clamp, write, wait, read final). Only `halcon_roi_validation.py` and `config.json` touched. Needs real camera to confirm movement.
### Files Changed
- halcon_roi_validation.py
- config.json
- CHANGELOG.md

## 2026-08-07 17:50
### What changed
- Simplified `_execute_focus` in `halcon_roi_validation.py`. Removed all verification/tolerance/PASS/FAIL/SUCCESS logic and `wait_for_focus` poll. New flow: read current → read `focus.step_mm` from config → `target = current ± step` → clamp to limits → write `FLK_TI_ControlFeature_SetFocusDistanceMm` → wait ~200 ms → read back → print `Current`/`Target`/`Actual` → report `Focus completed`.
### Why
- Old logic rejected valid focus moves because the lens never hit the exact target mm, producing false FAILED.
### Notes
- "failed" now reported only on read/write exception. Increment source of truth is config.json `focus.step_mm`; no hardcoded 250/500/1000 in focus code. Only `halcon_roi_validation.py` changed. Needs real camera to confirm.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 17:45
### What changed
- Focus control in `halcon_roi_validation.py` reworked to match `tests/test_focus_control.py` +/- handling. Toolbar buttons renamed `Focus Near`/`Focus Far` to `Focus +`/`Focus -` (now `btn_focus_plus`/`btn_focus_minus`). `_execute_focus` drops near/far wording and the `wait_for_focus` poll path: reads current distance, applies configured `focus.step_mm` (plus/minus), clamps to `get_focus_limits()`, writes target, then reads back and reports SUCCESS/FAILED if actual is within 10 mm of target.
### Why
- Focus reported FAILED even though the motor moved, because `wait_for_focus` could not confirm the target within its short timeout. The simpler set-and-verify flow from the hardware test avoids that false negative.
### Notes
- Only `halcon_roi_validation.py` changed; other modules untouched. Verify focus step value in `config.json` (`focus.step_mm`). Needs real camera to confirm movement.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 17:30
### What changed
- Removed the temporary focus-parameter probe diagnostic from `camera/services/halcon_driver.py` (`FOCUS_PROBE_PARAMS`, `dump_focus_parameters`, unused `Callable` import) and its invocation from `CameraWorker.initialize` in `halcon_roi_validation.py`.
### Why
- Investigation complete; diagnostic no longer needed.
### Notes
- Focus implementation untouched. `py_compile` + `ruff` clean.
### Files Changed
- camera/services/halcon_driver.py
- halcon_roi_validation.py
- CHANGELOG.md
### Files Changed
- camera/services/halcon_driver.py
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 17:00
### What changed
- Reverted focus write parameter. The device rejects `FLK_TI_ControlFeature_TargetFocusDistanceMm` ("feature not supported" HALCON #5329). Production driver `tv46l_camera.py` writes only `FLK_TI_ControlFeature_SetFocusDistanceMm` via `driver.set_focus_distance()` with no extra control command. Restored that. Dropped the previously-invented `FLK_TI_ControlCommand_SetFocus` command and constants renamed to `FOCUS_READ_PARAM`/`FOCUS_WRITE_PARAM`; `execute_control_command()` removed. Prototype updated to log `Writing SetFocusDistanceMm = <target>` and no longer emits a fake "Executing" line.
### Why
- Hardware showed #5320 TargetFocusDistanceMm unsupported; the supported production path is a single `SetFocusDistanceMm` write + `wait_for_focus` poll.
### Notes
- `py_compile` + `ruff` pass. Movement now depends purely on the supported param; real camera needed to confirm Final increases/decreases.
### Files Changed
- camera/services/halcon_driver.py
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 16:45
### What changed
- Fixed circular import: `halcon_roi_validation.py` -> `HalconDriver` -> `camera.model_import` -> `tv46l_camera` -> back to `HalconDriver`. Moved the `from camera.models.camera_model import CameraModel` import in `camera/services/halcon_driver.py` behind a `TYPE_CHECKING` guard. The symbol is only used as a type hint, so it is never needed at runtime.
### Why
- App crashed at startup with `ImportError: cannot import name 'HalconDriver' from partially initialized module`.
### Notes
- `py_compile` + import smoke test (both modules load) pass. `ruff` still expected clean after this change.
### Files Changed
- camera/services/halcon_driver.py
- CHANGELOG.md

## 2026-08-07 16:30
### What changed
- Fixed TV46L focus: the driver previously wrote `FLK_TI_ControlFeature_SetFocusDistanceMm`, which the camera ignored (motor never moved). Now `HalconDriver.set_focus_distance()` writes `FLK_TI_ControlFeature_TargetFocusDistanceMm` and then executes the Fluke control command `FLK_TI_ControlCommand_SetFocus` (new `execute_control_command()`). Declared param constants `FOCUS_READ_PARAM`, `FOCUS_TARGET_PARAM`, `FOCUS_COMMAND_PARAM`.
- `HalconDriver.__init__` accepts an optional already-open `framegrabber` so the validation tool reuses its existing handle instead of opening a second one.
- `halcon_roi_validation.py` now delegates focus to the production `HalconDriver` (single focus implementation); removed its own inline HALCON focus code and the `_focus_scalar`/`_focus_get` helpers.
- Focus instrumentation logs once per command: Focus Near/Far, Current, Target, Writing <target param>, Executing <set-focus command>, Waiting, Final, then SUCCESS or FAILED + reason.
### Why
- Camera never moved (log showed Current 23368 / Target 22368 / Final 23368); prototype had a duplicate, ineffective focus implementation.
### Notes
- `py_compile` clean. Live camera required to confirm the `FLK_TI_ControlCommand_SetFocus` command name/value is accepted by hardware and that Final now changes.
### Files Changed
- camera/services/halcon_driver.py
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 16:00
### What changed
- Fixed reconnect after Disconnect in `halcon_roi_validation.py`. `_on_connect` only acted `if self._worker and not self._worker._connected`; after Disconnect `_shutdown_thread()` nulls the worker and thread, so Connect became a silent no-op. Now Connect tears down any stale worker then always creates a fresh one via `_discover_and_connect()`, producing a brand-new framegrabber each time (never reusing a handle). Connect -> Disconnect -> Connect works repeatedly.
- Focus Near/Far now log current, target and final focus distance once per command in `_execute_focus`. Reads the existing `FLK_TI_ControlFeature_CurrentFocusDistanceMm` parameter before and after the move; prints `Focus Near|Far`, `Current`, `Target`, `Final` (mm). On read failure prints `Current focus unavailable`.
### Why
- Reconnect button did nothing after disconnect; operators had to restart the app. Focus had no feedback of what position it landed on.
### Notes
- Verified `py_compile` clean. Live camera needed to confirm repeated reconnect and to observe actual focus log output on hardware. No GUI layout, ROI processing, or alarm system changed.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 15:30
### What changed
- Fixed `AlarmManager` API mismatch in `halcon_roi_validation.py`. `active_alarms` is a `@property`, but the worker called `self._alarm_manager.active_alarms()` (with parens) in `run()` at the set-diff check and the `alarms_changed.emit(...)` call, raising `TypeError: 'list' object is not callable` before the loop. Now calls use the property with no parens; single interface throughout.
- Frame-processing exceptions no longer disconnect/reconnect the camera. The old `except` block called `_handle_disconnect()`, which set `_connected=False`, so the loop's reconnect branch re-ran `initialize()` and recreated calibration/LUT/ROI regions/connection on every bad frame. Now an exception only logs, skips the frame, and continues; initialization happens once.
- Hardened shutdown order in `_shutdown_thread()` -> `worker.stop()` -> `thread.quit()` -> `thread.wait(5000)`; references are nulled only after the thread actually joins. If it cannot join within 5s a warning is logged and the QThread is NOT dropped, so it is never destroyed while still running. `closeEvent` now delegates to `_shutdown_thread`.
### Why
- Crash on startup (`'list' object is not callable`), repeated re-initialization churn, and `QThread: Destroyed while thread is still running` at exit.
### Notes
- Verified: no `.active_alarms()` call remains (only the `def` and `set_active_alarms()` remain). Headless stub test all-PASS incl. property read via `CameraWorker` + set-diff path. `ruff check` + `py_compile` clean. pytest 518 passed / 8 failed (same pre-existing baseline). Live camera needed to confirm no restart churn and clean exit on hardware.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 15:00
### What changed
- Part 2 GUI integration in `halcon_roi_validation.py` (acquisition/ROI/AlarmManager/HALCON pipeline untouched).
- Bottom section is now a horizontal pair: Alarm Table (left, ~28%) + ROI Statistics Table (right, ~72%). No popup/dock/tab; both live inside the existing main window. Alarm table has 3 columns only: ROI, Time (HH:MM:SS), Current Max (°C).
- Alarm table mirrors live alarms: inserts a row on activation, removes the row immediately on clear, and per frame updates only the "Current Max" cell while active (no full-table rebuild per frame, timestamp untouched).
- Worker now emits `alarms_changed` only when the active-alarm set changes, and `nuc_countdown` once per second. GUI updated via web: `_on_alarms_changed`/`_sync_alarm_table`/`_update_alarm_max_cells`/`_on_nuc_countdown`.
- ROI outlines and labels turn red while an ROI is in alarm, back to yellow on clear (color change only; no region rebuild, no flashing).
- Status bar now also shows `Active Alarms: N`, `Next NUC: <s>` (1/s), and `Alarm Limit: X °C` taken directly from `config.json`.
### Why
- Make active alarms visible at a glance: live table, red ROI, red text, and a count in the status bar, without touching the processing or alarm engine.
### Notes
- Verified offline with headless stubs: 25 checks pass (insert rows, no duplicate rows on repeat, timestamp fixed while active, per-cell Current Max update, immediate row removal on clear, re-alarm after clear, countdown, alarm limit from config, disabled-NUC dash, display active set). `ruff check` + `py_compile` clean. Full pytest 518 passed / 8 failed — same 8 pre-existing failures as baseline. Live FPS/screenshot verification still requires a connected TV46L.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 14:00
### What changed
- Added a configuration system to the HALCON ROI validation tool (`halcon_roi_validation.py` + new `config.json`). All tunables now come from `config.json` (camera FPS/reconnect, alarm limit, NUC interval, focus step, display palette/zoom). Loaded once at startup by `ConfigManager` and held in memory; the JSON file is never read inside the processing loop.
- Added `AlarmManager` (two-state engine per ROI: NORMAL <-> ACTIVE). Creates exactly one alarm when ROI Max > limit, stores the creation timestamp once, refreshes only `current_max` while active, clears when Max <= limit, and creates a fresh alarm (new timestamp) only after a clear. Alarm data: ROI name, timestamp, current max. Active alarms exposed via `active_alarms`.
- Pipeline now evaluates alarms straight from the existing `ROIStatistics` (grab -> calibration -> intensity -> min_max_gray -> evaluate AlarmManager). No recomputation, no extra HALCON call, no extra image pass.
- Automatic NUC: reads `nuc.interval_seconds` / `nuc.auto_enabled`, tracks `last_nuc_time`, and when the interval elapses runs the exact same `_execute_nuc()` used by the Manual NUC button. Manual NUC still works and also refreshes the timer.
- Focus step, reconnect delay, FPS, LUT palette, and default zoom now read from config instead of hardcoded values. Removed two pre-existing unused imports (`QHBoxLayout`, `QMessageBox`) so ruff passes.
### Why
- Part 1 of the configuration + alarm engine work: centralize all future-changeable values in `config.json`, and move alarm state logic into a single small class instead of scattering it through the GUI. Manual NUC code reused for auto-NUC to avoid duplication.
### Notes
- Verified with an offline stub test (config load, no duplicate alarms, constant timestamp while active, auto-clear, new alarm only after clear, auto-NUC interval) — all pass. `ruff check` and `py_compile` clean. Full pytest: 518 passed, 8 failed — same 8 pre-existing failures present on the clean baseline (unrelated `halcon.HRegion` API and alarm-pipeline tests). Requires a live TV46L to verify NUC and FPS on hardware.
### Files Changed
- halcon_roi_validation.py
- config.json
- CHANGELOG.md

## 2026-08-07 12:00
### What changed
- Improved HALCON ROI validation GUI display quality in `halcon_roi_validation.py` (display-only; no processing/camera/threading changes).
- Image no longer stretched to fill the widget. HALCON display widget now lives inside a `QScrollArea`; at 100% zoom one image pixel = one display pixel (640x480, none scaled).
- Added zoom (50/75/100/125/150/200/400%) by resizing the display window only; underlying frame stays 640x480. Ctrl+Mouse Wheel zooms, plain Mouse Wheel scrolls (QScrollArea), zoom center preserved.
- Added HALCON thermal palette via `ha.set_lut(window, "temperature")` (verified valid in HALCON 24.11); no OpenCV/NumPy colorization, display stays a HALCON image.
- ROI color changed to yellow `#EACE21` for visibility on the thermal palette; borders stay crisp (no anti-alias) because display is no longer scaled. Labels still use HALCON `disp_text` in image coordinates.
- Status bar now shows current zoom (e.g. `Zoom: 150%`).
### Why
- Previously the thermal image was scaled to fill the widget, making the image, ROI rectangles, and text blurry, and grayscale LUT looked non-thermal. Zoom needed for closer inspection.
### Notes
- Palette name `temperature` verified present in `HALCON-24.11` (valid list: temperature, rainbow, jet, color1, default; iron unavailable in this version). No extra HALCON stats or image copies added to runtime loop; zoom re-renders only the stored last frame on user zoom action.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 10:00
### What changed
- Fixed app-crash-on-exit (`QThread: Destroyed while thread is still running`) in `halcon_roi_validation.py`.
- Removed `CameraWorkerWrapper` entirely; was an unnecessary second QObject that blocked initiation of the loop. The worker now owns the acquisition loop directly (`initialized -> worker.run`).
- `run()` is guarded against re-entry (`if self._running: return`), checks `_running` each iteration and on shutdown, and after the loop runs `_cleanup()` (close framegrabber -> `_connected=False` -> emit `connected(False)`) then emits `finished`.
- `stop()` now only flips `_running=False`; it no longer closes the framegrabber / quits / waits / deletes. Those steps happen after `run()` returns, in the worker thread, so the framegrabber is never closed while a `grab_image_async` is in flight.
- Wiring: `worker.finished -> thread.quit`, `thread.finished -> worker.deleteLater + thread.deleteLater`. Shutdown uses new `_shutdown_thread()` helper (`quit()` + `wait(3000)`) from both `_on_disconnect` and `closeEvent`, and nulls the references afterwards.
- Removed unused `QWaitCondition` import and the dead `_worker_wrapper` attribute.
### Why
- Worker thread event loop was never actually running, so `thread.quit()` could not join it; the QThread was destroyed while `run()`'s infinite loop died still running. Removed the wrapper so the worker owns the loop and exits naturally on shutdown.
### Notes
- Focus/NUC unaffected (they are driven by direct attribute calls setting flags the loop reads under the mutex, not queued signals). Requires a real camera to verify clean USB/GigE disconnect and no hanging Python process.
- 5 pre-existing ruff warnings remain (unused `Optional/QHBoxLayout/QMessageBox`, two `except Exception as e`); unrelated to this change.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-07 09:00
### What changed
- Fixed Focus Near / Focus Far controls in `halcon_roi_validation.py`. `_execute_focus` used `float(ha.get_framegrabber_param(...))`, but HALCON returns an HTuple (list), raising `TypeError: float() argument must be... not 'list'`. Added `_focus_scalar()` unwrap + `_focus_get()` helper so reads return a real float before math. Reuses the same focus sequence as the existing camera/driver service (read current, compute target clamped to min/max, set distance, wait until within tolerance). No new focus algorithm.
- Hardened canonical focus source in `camera/services/halcon_driver.py`: `get_parameter()` now unwraps single-element HTuple/list via `_as_scalar()`, so `get_focus_distance()`/`get_focus_limits()` no longer feed a list into `float()`.
- Focus still runs in the worker thread: GUI disables both Focus buttons on press and re-enables via `focus_status` signal after movement completes; UI stays responsive.
- Removed noisy/debug logging per AGENTS rule: first-frame/calibration-output verification, "grabbing first frame", "HALCON window created", "ROI Table Rows", calibration/config step chatter, per-frame stall warning, reconnect chatter, FPS/time counters. Kept only: Camera discovered, Camera connected, Calibration loaded, Loaded N ROIs, Focus started, Focus completed, NUC started/completed, Camera disconnected, and critical errors.
### Why
- Focus buttons failed with TypeError; focus implementation was duplicated in the prototype instead of sharing the robust scalar handling. Logging flooded stdout/event log per-frame during debugging.
### Notes
- Prototype worker keeps its own framegrabber (existing design); the focus math matches `tv46l_camera.py`/`halcon_driver.py`. Hardware-only: focus movement requires a live test with the TV46L. Verified py_compile OK; ruff clean for changed code (6 pre-existing unused-import/except warnings remain).
### Files Changed
- camera/services/halcon_driver.py
- halcon_roi_validation.py
- CHANGELOG.md

## 2026-08-06 14:35
### What changed
- Applied MVTec batched-workflow optimization pass to the standalone ROI prototype (`halcon_roi_validation.py`). No production code touched.
- Overlay pipeline: `_overlay_rows()` cached, rebuilt only when dirty flag / storage `rev` / alarm set changes; `_build_overlay_pieces()` groups visible outlines by color, one `select_obj` per color group (was per-ROI select loop). `_mark_overlay_stale()` hooked into create/apply-edit/visibility/color/delete/duplicate/clear/load.
- ROI labels: per-frame `cv2.putText` loop (84.6 ms @50, 3.9 s @2000) replaced by worker-thread renderer with `_label_signature()` caching + `cv2.copyTo` alpha compose; labels redraw only on geometry/stats change. Main-thread label cost @2000: ~15 ms burst, ~1 ms idle.
- Statistics decoupled from display: `STATS_INTERVAL_MS=200` throttles stats/label refresh to ~5 Hz while display runs at full FPS.
- Internal per-stage profiler on live + benchmark paths (`_last_timing`: calibration, display_prep, himage, stats, alarm, label, overlay, display convert/image/overlay/flush). Benchmark now reports `stats_peak_ms`, `stats_rect1_ms`, `label_main_ms`, `verify_ms`.
- `GroupedROIStorage.rev` monotonic counter auto-invalidates overlay cache on any storage mutation.
### Why
- Apply the MVTec 12 principles (regions created once, batch stats per shape type, never rebuild during streaming, cached overlays, labels only on stats change, display FPS independent of stats FPS, internal profiler, minimal numpy/HALCON/Qt copies) so ROI count scales without frame drops.
### Notes
- Verified: ruff clean, py_compile OK, offscreen smokes pass, real-window display (HAL disp 8-15 ms), live camera drive test (3 cams discovered, real stats, throttled cadence, worker labels). Benchmark @2000 ROIs: 32.6 fps offscreen, 30.7 ms total; full 111 ms (9 FPS) budget with real display ~45 ms worst case.
- Known limitation: label worker joins on window close with 1 s timeout; snapshot builds label rows on the main thread.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md
- docs/benchmarks/ROI_MVTec_Optimization_Report.md (new)

## 2026-08-06 13:22
### What changed
- Bug-fix / usability pass on the standalone ROI prototype (`halcon_roi_validation.py`). No architecture changes, production ROI engine untouched.
- Fixed the editing bridge: `_drawing_geometry()` read `get_drawing_object_params` results as a list-of-lists and returned HALCON column names (`column1`/`column`) that `update_geometry` silently filtered out. Drawing-object moves therefore never reached the geometry arrays, so RegionCache, statistics, table and overlay stayed stale at the old position. The bridge now unpacks the flat value list and maps to the storage keys (`col1`/`col`).
- Overlay no longer displays the filled statistics regions: it shows 1 px `boundary()` outline contours taken from the cached regions (same source of truth). Outline contours are generated inside `RegionCache._rebuild` (cached outlines, no per-frame boundary cost). Hidden ROIs and the ROI being edited (rendered by its drawing object) are skipped. Benchmark FPS at 2000 ROIs: 5.4 -> 15.4.
- Selected ROI renders yellow (drawing object), others green by default (stored colour), alarms red. Colour editor kept and now applies the colour to the live drawing object immediately (verified HALCON supports per-object drawing-object colours).
- ROI labels (name + Min/Avg/Max) drawn into the display frame each statistics refresh (cv2), anchored at the ROI's top-left; they follow the geometry and disappear when the ROI is hidden/deleted. Labels are not drawn on the benchmark path.
- Added Focus - / Focus + / Manual NUC toolbar buttons wired to `TV46LCamera.focus_near()/focus_far()/manual_nuc()`; enabled on connect, disabled on disconnect; Auto Focus button permanently disabled (TV46L has no autofocus command).
- Event log is now a 160 px multi-line history (was a single line). Mouse/zoom info moved to the main-window status bar with a continuous Frame counter.
### Why
- Prototype's grouped-ROI editing workflow did not follow drawing-object edits (stale geometry/stats/overlay) and displayed filled statistics regions instead of outlines; usability items from the bug-fix request.
### Notes
- Verified: ruff clean, py_compile OK, offscreen smoke tests pass, real-display end-to-end drag test passes (arrays -> cache -> stats -> overlay -> table), live camera test passes (3 cams discovered, real calibrated statistics, buttons enabled/disabled correctly). Report: docs/ROI_Prototype_Bugfix_Report.md.
### Files Changed
- halcon_roi_validation.py
- CHANGELOG.md
- docs/ROI_Prototype_Bugfix_Report.md (new)

### What changed
- Processed the session learning extraction: applied the 3 suggested skill updates and staged 5 instincts for continuous-learning-v2.
- `.agents/skills/pyqt6-ui-development-rules/SKILL.md`: new Iron Laws — a slot must never emit the signal it is connected to (unbounded recursion / 0xC0000409); a printed traceback in passing `-s` pytest output is a hidden defect (PyQt swallows slot exceptions). Added matching anti-pattern row.
- `.agents/skills/python-performance-optimization/SKILL.md`: new Benchmark Methodology section (dated backups of report/raw data, record ambient CPU, in-process metrics over external samplers, verify process identity, regression-gate every change).
- `.agents/skills/pytest-coverage/SKILL.md`: new Stale-Test Classification section (prove pre-existence via worktree, classify by cause, fix tests not production code, document in Known_Issues.md).
- `.opencode/learnings/instincts-2026-08-06.json`: 5 session-extraction instincts in /instinct-import format.
### Why
- Persist lessons from the Phase 6 verification session (signal re-emission crash, benchmark baseline preservation, stale-test handling) so future sessions apply them automatically.
### Notes
- No production code changed. continuous-learning-v2 CLI not installed on this machine (no instinct-cli.py found); artifact staged for `/instinct-import`.
### Files Changed
- .agents/skills/pyqt6-ui-development-rules/SKILL.md
- .agents/skills/python-performance-optimization/SKILL.md
- .agents/skills/pytest-coverage/SKILL.md
- .opencode/learnings/instincts-2026-08-06.json (new)
- CHANGELOG.md

## 2026-08-06 12:24
### What changed
- Refactored `halcon_roi_validation.py` into a standalone ROI Calibration & Performance Prototype demonstrating MVTec's batched ROI architecture (per requirements list from ROI_Architecture.md): grouped type-array ROI storage, cached HALCON regions with dirty-flag rebuild, one batch statistics call per type (no reduce_domain), separated pipeline stages, PyQt5 GUI (toolbar, ROI table, selected-ROI form, processing info panel, thermal view with mouse temperature read-out), and a benchmark (50-2000 ROIs, CSV export, numpy cross-check).
- No production code touched: `roi_engine/*`, `roi/*`, `gui/calibration`, `gui/observer` are not imported by the prototype; only `camera/*`, `calibration/*`, `configuration/settings.py` are reused.
- Fixed a benchmark self-check bug: the numpy reference used banker's rounding while HALCON rasterizes rectangles with round-half-away-from-zero, causing ~700-unit stat errors at grid counts where ROI edges sat on x.5 coordinates. Benchmark grid is now quantized to integer pixel bounds; verification is pixel-exact (~0.001 float32 noise) at every count.
### Why
- Validate the batched ROI processing concept (grouped storage, dirty region cache, batch intensity/min_max_gray/area_center, 150 ms polled drawing-object editing because HALCON rejects Python callbacks) before porting it into the production ROI engine.
### Notes
- Verified headless: 31/31 smoke checks pass (storage, hit tests, cache rebuild counts, stats vs numpy, alarms, all five shapes); GUI instantiates offscreen; benchmark runs at 50/100/250/500/1000/2000 ROIs (~108/94/66/39/24/18 FPS) with exact numpy verification and one region rebuild per type per benchmark run.
- Known limitations documented in the module docstring: single-threaded pipeline, polled editing, one active drawing object at a time, calibration fallback to raw counts.
### Files Changed
- halcon_roi_validation.py (rewrite)
- CHANGELOG.md

## 2026-08-06 12:20
### What changed
- Removed the per-frame `logger.debug("Processing frame...")` call and the now-unused `logger` import from `ProcessingPipeline.process()` in `processing/pipeline/processing_pipeline.py`; production hot path no longer emits logging per frame.
- Phase 6 verification: re-ran the ROI benchmark (100/500/1000/1600) under reduced background load (closed Teams/Widgets/SearchHost; sampled CPU 20-80%, avg ~50%). New medians 26.3/78.3/156.4/242.4 ms vs baseline 25.2/93.0/215.7/297.3 ms — 500/1000/1600 improved 16-28% (load variance; no code changes to roi_engine). 100 ROI within noise. Budget status unchanged: 100/500 within the 111 ms (9 FPS) frame budget, 1000/1600 exceed it.
- Ran 900 s ROI soak (500 ROIs, synthetic): 14,205 frames, 0 exceptions, 0 HALCON errors, RSS stable 79-83 MB, memory slope 21.8 MB/h (limit 100). Dual-validation/position-switch/roi-editing/high-count/error-recovery all PASS. Camera_switch SKIPPED - no hardware connected.
- Static logging/code review: no per-frame, no benchmark-time, no debug logging remains in production code (camera/, processing/, roi_engine/, observation/, gui/). Diagnostic [DIAG] prints remain only in the legacy diagnostic camera driver used by manual test tools; production camera path (`camera/services/tv46l_camera.py`) is print-free. Removed temp artifacts (err/out.txt, bench/soak stdout captures, stray reports_test/reports_x).
- Added verification deliverables: reports/System_Verification_Report.md, Performance_Summary.md, Regression_Summary.md, Production_Readiness_Assessment.md, Go_NoGo_Recommendation.md; docs/Known_Issues.md; and docs/ROI_Production_Validation.md (manual GUI checklist previously referenced by the harness but missing).
### Why
- Phase 6 verification: logging hygiene + performance/memory evidence from the validation harness; confirmed architecture limits before any optimization.
### Notes
- Camera hardware unavailable during verification (GigE discovery scan returned no boards). Camera connect/disconnect/reconnect, streaming, calibration all deemed Not Executed.
### Files Changed
- processing/pipeline/processing_pipeline.py
- docs/benchmarks/ROI_Benchmark_Report.md
- docs/Known_Issues.md (new)
- docs/ROI_Production_Validation.md (new)
- reports/System_Verification_Report.md, Performance_Summary.md, Regression_Summary.md, Production_Readiness_Assessment.md, Go_NoGo_Recommendation.md (new)
- CHANGELOG.md

## 2026-08-06 10:15
### What changed
- Fixed an infinite-signal-loop bug in `gui/roi/roi_workspace.py`: the four `_on_*_changed` handlers (`_on_alarm_changed`, `_on_appearance_changed`, `_on_recording_changed`, `_on_renamed`) re-emitted the exact signal they are connected to on the same bus, causing unbounded recursion (RecursionError in pytest, native stack-overflow crash 0xC0000409 when running outside pytest).
- Handlers now only do their own work (alarm registration / dirty tracking); they no longer re-emit the incoming signal.
### Why
- Phase 6 validation harness crashed with 0xC0000409 on `--scenario roi_editing`; root-cause bisection isolated the re-emission. Widgets that need to react (e.g. list row refresh in `CalibrationWindow`, which connects directly to the bus) are already notified by the original emitter, so the re-emit was redundant.
### Notes
- Full suite: 518 passed, 8 failed — identical to pre-fix baseline (4 pixel-convention + 2 HRegion API in test_roi_phase2.py, 2 alarm-threshold in test_processing_pipeline.py). All 14 harness tests pass with no RecursionError in `-s` output.
- Validation scenarios: soak/dual_validation/position_switch/roi_editing/high_count/error_recovery all PASS; camera_switch SKIPPED (no camera hardware).
### Files Changed
- gui/roi/roi_workspace.py
- CHANGELOG.md

## 2026-08-04 16:10
### What changed
- Fixed a Phase 4 data-flow bug: the ROI property panel never wrote config edits back, so enabled/visible/alarm/recording/name toggles never reached the immutable engine store. Added `ROIWorkspace.update_configuration(config)` (replaces the stored config + `mark_dirty` store reload) and `ROIPropertyPanel.config_updated` (emits replaced configs from all edit handlers); `CalibrationWindow` wires the two.
- Added the production validation harness `tests/validation/` (CLI `python -m tests.validation`): soak, dual validation (1000+ frames), position switch, camera switch, ROI editing matrix, high ROI counts (up to 1600), error recovery; cv2 charts, JSON/CSV/Markdown reports, PASS/FAIL/SKIPPED verdicts.
- 14 harness tests in `tests/test_validation_harness.py`, including regression tests pinning the config write-back path.
### Why
- Validation scenarios (hide/disable/delete) exposed that appearance edits never reached the engine; narrow fix so the engine store reloads on every edit, without touching engine/store internals.
### Notes
- Synthetic scene contains per-frame noise (~0.05 °C), so stale-cache checks use a 1.0 °C tolerance.
- `ha.info_framegrabber("GigEVision2", "info_boards")` returns `(_info, boards)` (2-tuple); `camera.models` must be imported before `camera.services.tv46l_camera` (circular import); `CameraManager` has no `clear()`.
- Harness tests: 14/14 pass (short synthetic runs). Camera-mode scenarios (soak/camera_switch) still require hardware.
### Files Changed
- gui/roi/roi_workspace.py
- gui/roi/roi_property_panel.py
- gui/calibration/calibration_window.py
- tests/validation/ (new: __init__.py, metrics.py, charts.py, report.py, frame_source.py, camera_bootstrap.py, harness.py, scenarios.py, __main__.py)
- tests/test_validation_harness.py (new)
- CHANGELOG.md

## 2026-08-04 14:30
### What changed
- Integrated the production ROI engine into the Calibration Window (Phase 3, pilot). Added `roi_engine/integration.py`: `ROIEngineManager`, a backward-compatible facade over `ROIEngine`/`ROIEnginePool` with the same API as the legacy `RuntimeROIManagerImpl` (load, add_configuration, unload, get_active, mark_dirty, rebuild_dirty_regions, process_frame, ...).
- `gui/roi/roi_workspace.py` now creates one `ROIEngineManager` per camera (pooled engine) instead of `RuntimeROIManagerImpl`; the workspace config dict is passed as a config provider so edits/deletes reload the store snapshot. `_on_delete_roi` pops the config before `mark_dirty`.
- Added `Settings.ROI_ENGINE_DUAL_VALIDATION` (default False): when on, the legacy manager runs in parallel per frame and mismatches (min/max/mean/std/area/hotspot/valid) log one warning per ROI until they recover. Hotspot positions may differ by a few pixels on max plateaus (engine = first max pixel, legacy = plateau center) — tolerated up to 16 px.
- Fixed (vs legacy): geometry edits now reach statistics immediately; legacy kept the pre-edit geometry in its RuntimeROI objects.
- Added `tests/test_roi_engine_integration.py` (17 tests) and `docs/ROI_Engine_Integration_Report.md` (summary, architecture, validation, regression, go/no-go).
### Why
- Pilot rollout of the batched engine behind the Calibration Window without changing GUI behavior.
### Notes
- Full suite: 504 passed, 8 failed — the 8 are the same pre-existing legacy/HALCON-24.11 failures (verified earlier via git stash); no new failures. Ruff clean on all touched files.
- `Settings` is slots=True: read the new flag from a `Settings()` instance — class-level access returns the member descriptor (truthy).
### Files Changed
- roi_engine/integration.py (new)
- roi_engine/__init__.py
- gui/roi/roi_workspace.py
- configuration/settings.py
- tests/test_roi_engine_integration.py (new)
- docs/ROI_Engine_Integration_Report.md (new)
- CHANGELOG.md

## 2026-08-04 13:30
### What changed
- Cleaned `tests/conftest.py`: removed the parallel-build stub machinery (`_ensure_roi_engine_modules`, `_TypeStore`, `_ROIStore`, `_attach_geometry`, `build_test_store`); only shared helpers `make_config` and `synthetic_image` remain.
- Rewired `tests/test_region_cache.py` and `tests/test_statistics_batch.py` onto the real store: `build_store("cam_1", "pos_1", configs, generation=...)` and per-shape iteration via `store_for(shape)` / `ALL_SHAPES` (16 call sites fixed).
- Added `tests/test_roi_store.py` (11 tests): store immutability, enabled_indices, per-type arrays, memory_bytes, multi-camera independence, generation.
- Added `docs/ROI_Architecture.md` (mermaid diagrams: architecture, data flow, class relationships; old-vs-new table; scalability analysis; go/no-go recommendation).
### Why
- The roi_engine store package is committed, so the test suites no longer need stubs; tests must exercise the production store.
### Notes
- roi_engine suites: 38/38 pass; ruff clean on all touched files. Full suite: 487 passed, 8 failed — the 8 are PRE-EXISTING legacy failures (test_processing_pipeline alarm-active, test_roi_phase2 HALCON-area/`halcon.HRegion`), verified by stashing this work and re-running: identical failures on the committed baseline (HALCON 24.11 rasterization). Not caused by roi_engine.
- Benchmark caveat (from report): timings taken under ~100% external CPU load; batched engine ~2x slower than clean-machine probes; ratios/scaling representative.
### Files Changed
- tests/conftest.py
- tests/test_region_cache.py
- tests/test_statistics_batch.py
- tests/test_roi_store.py (new)
- docs/ROI_Architecture.md (new)
- CHANGELOG.md

## 2026-08-04 13:00
### What changed
- Added `tests/benchmark_roi_pipeline.py`: CLI benchmark of the batched `roi_engine` pipeline vs the legacy per-ROI path. Flags: `--counts`, `--frames`, `--no-legacy`, `--json out.json`, `--report`.- Mixed-shape synthetic geometry (50/20/10/10/10 % Rectangle1/Circle/Ellipse/Rectangle2/Polygon) on a deterministic non-overlapping 480x640 grid (seed 42); correctness spot-check vs legacy `extract_statistics` (1e-6, NaN-safe); per-frame allocation via tracemalloc; budget line 9 FPS = 111 ms.
- Benchmark report generated at `docs/benchmarks/ROI_Benchmark_Report.md` + raw results `ROI_Benchmark_raw_results.json`.
- Results (median per frame, machine under ~100% external CPU load): 50 ROIs 8.3 ms (legacy 31.6 ms), 100: 13.5 (44.5), 250: 22.9 (82.3), 500: 32.6 (146.3), 1000: 87.7 (337.2), 1600: 96.7 ms (428.3 ms); speedup 3.3-4.5x, sub-linear scaling (11.6x time for 32x ROIs).
### Why
- Quantify the batched engine's scalability and prove correctness against the legacy path before production rollout.
### Notes
- Spurious `KeyboardInterrupt` inside HALCON C calls (Windows parallel-operator abort) occurs in bursts; the benchmark retries interrupted frames up to 3x (timing covers only the successful attempt).
- Absolute timings are inflated by sustained 100% CPU contention (PyCharm/Chrome); report methodology documents the caveat. Legacy per-ROI ~0.27-0.63 ms/ROI matches the expected ballpark; batched engine ~2x slower than clean-machine probes at high counts.
- `docs/benchmarks/` did not exist; report writer creates it.
### Files Changed
- tests/benchmark_roi_pipeline.py (new)
- docs/benchmarks/ROI_Benchmark_Report.md (new)
- docs/benchmarks/ROI_Benchmark_raw_results.json (new)
- CHANGELOG.md

## 2026-08-03 17:00
### What changed
- Upgraded the global HALCON Python interface to match the installed runtime: `mvtec-halcon` 24112.0.0 → 24113.0.0 (global Python only; venv and HALCON runtime untouched).
- The `Wrong interface package version` warning no longer appears on `import halcon`.
- Updated `docs/DevelopmentEnvironment.md` (interface version, mismatch section replaced with resolution note).
### Why
- Interface/runtime mismatch: "Compatibility is not guaranteed and crashes etc. are possible."
### Notes
- Runtime verified unchanged at 24.11.3.0. `tools/check_environment.py`: all checks PASS, exit 0, clean stderr.
### Files Changed
- docs/DevelopmentEnvironment.md
- CHANGELOG.md

## 2026-08-03 18:10
### What changed
- Added the production ROI engine facade `roi_engine/engine.py`: per-camera `ROIEngine` (load_position → immutable store snapshot with bumped generation, process_frame with cache rebuild + HALCON statistics + never-crash exception safety, invalidate, get_runtime_statistics legacy view, memory_bytes, clear) and `ROIEnginePool` (camera_id → engine registry).
- Added `tests/test_roi_engine.py` (11 tests): batch processing, statistic values, multi-camera independence, pool lifecycle, guards, generation rebuild, invalidate, runtime-statistics compatibility, legacy JSON repository round-trip, clear().
### Why
- Public facade of the new type-array ROI engine (parallel build); backward compatible with `roi.runtime.RuntimeROIStatistics` and legacy JSON persistence.
### Notes
- The store package modules (build_store, ROIStore, type stores) were implemented in this session because the parallel store agent had not delivered after ~30 min; they follow the same documented contract and can be overwritten by the parallel implementation.
- Verified: ruff clean, `pytest tests/test_roi_engine.py` 11/11 pass, `from roi_engine import ROIEngine, ROIEnginePool` OK.
### Files Changed
- roi_engine/engine.py (new)
- roi_engine/store/factory.py (new)
- roi_engine/store/roi_store.py (new)
- roi_engine/store/rectangle1_store.py (new)
- roi_engine/store/rectangle2_store.py (new)
- roi_engine/store/circle_store.py (new)
- roi_engine/store/ellipse_store.py (new)
- roi_engine/store/polygon_store.py (new)
- tests/test_roi_engine.py (new)
- CHANGELOG.md

## 2026-08-03 16:30
### What changed
- Repaired the development environment (no project code changed):
  - Fixed corrupted venv-local pip (missing `pip-*.dist-info`): removed the broken `pip` folder and reinstalled (now pip 26.2 in the venv).
  - Installed `debugpy==1.8.21` into the venv — VS Code previously used the extension-bundled debugger, which crashed with `KeyboardInterrupt` inside pydevd tracing during the NumPy import at startup.
  - Added `.vscode/launch.json` + `.vscode/settings.json` pinning the venv interpreter.
  - Added `tools/check_environment.py` (interpreter, versions, PASS/FAIL for halcon/numpy/cv2/PyQt5/PyQt6/debugpy/pytest/ruff).
  - Added `requirements-dev.txt` (venv-local packages only) and `docs/Development_Setup.md` + `docs/DevelopmentEnvironment.md` (audit report).
- Verified: `check_environment.py` all PASS; app launches under `python -m debugpy --listen` and survives startup (previously crashed on the numpy import).
### Why
- Development environment was unhealthy: broken pip, no local debugpy, unstable VS Code debugging, undocumented dependencies.
### Notes
- Known remaining issue (documented): global `mvtec-halcon` 24112 vs installed HALCON runtime 24.11.3 — emits a version-mismatch warning. Recommended fix: `pip install --upgrade mvtec-halcon==24113` (global Python, outside the venv).
- Project constraint preserved: venv keeps `include-system-site-packages = true`; HALCON stays global-only.
### Files Changed
- .vscode/launch.json (new)
- .vscode/settings.json (new)
- tools/check_environment.py (new)
- requirements-dev.txt (new)
- docs/Development_Setup.md (new)
- docs/DevelopmentEnvironment.md (new)
- CHANGELOG.md

## 2026-08-03 10:30
### What changed
- Fixed `AttributeError: 'NoneType' object has no attribute 'style'` crash in `ROIPropertyPanel` (`gui/roi/roi_property_panel.py`).
- `_on_color_changed` and `_on_line_width_changed` built `replace(self._current_config.style, ...)` before the `_appearance_config` None-guard ran, so changing color/line width while no ROI is selected (or during clear/reset) crashed.
- Added the same `_current_roi_id is None or _current_config is None` early-return guard used by the alarm/recording handlers.
### Why
- GUI crash on startup/reset path when the appearance controls changed value with no ROI selected.
### Notes
- Verified: ruff clean, module imports. Other appearance handlers were already safe because they pass plain values into `_appearance_config`.
### Files Changed
- gui/roi/roi_property_panel.py
- CHANGELOG.md

## 2026-08-03 09:00
### What changed
- Camera detail window now opens ONLY by double-clicking a camera tile in the Observation window.
- Wired `ObserverWindow.camera_detail_requested` → `Application.open_camera_detail` (guarded via a WeakSet so the singleton observation window is wired once). Previously the signal was emitted but never connected, so tile double-click did nothing.
- Removed the only other entry point: the hidden "Camera Detail (Dev)" menu item / Ctrl+D shortcut in `MainWindow` (`camera_detail_dev_requested` signal, `_on_detail_dev`, `_menu_detail_dev`) and the Application's `DEV_CAMERA_ID` / `_on_camera_detail_dev_requested`.
- Fixed 2 window-architecture tests that created windows but never called `show()`, so `isVisible()` asserts were wrong (these tests got un-skipped once HALCON import worked).
### Why
- Requirement: the detailed camera window should be reachable only from an observation tile double-click, never from the main window.
### Notes
- `tests/test_window_architecture.py`: 28 passed (incl. new `test_observation_tile_double_click_opens_detail`). Full suite: 401 passed; remaining failures are all HALCON license error #2021 (environment, being fixed on the HALCON side) — none related to this change.
### Files Changed
- gui/main_window.py
- app/application.py
- tests/test_window_architecture.py
- CHANGELOG.md

## 2026-08-03 00:00
### What changed
- Made the HALCON `set_system("clip_region", "false")` call in `roi/geometry_to_hregion.py` non-fatal. It previously ran at module import time, so any HALCON failure (e.g. license error #2021) crashed the entire `roi` import and blocked opening the calibration window.
- The call is now deferred to a guarded `_configure_clip_region()` helper invoked lazily on first conversion; failures are logged and retried on the next conversion instead of breaking imports.
### Why
- Import-time HALCON calls make the whole app brittle: one HALCON-side error took down the calibration window and every module that imports `roi`.
### Notes
- Verified `import roi` and `import gui.calibration.calibration_window` pass with the current HALCON error active (it is now logged as a warning, not fatal).
### Files Changed
- roi/geometry_to_hregion.py
- CHANGELOG.md

## 2026-08-02 19:45
### What changed
- Added `WindowRegistry` (`app/window_registry.py`): single owner of all top-level windows with `WindowID` keys, `(id, instance_key)` addressing (one camera-detail window per camera), open/reuse/show/raise semantics, `on_open`/`on_close` lifecycle hooks, and auto-forget on external close via `destroyed` (`Qt.WA_DeleteOnClose`).
- Refactored `Application` to own all windows through the registry and centralize navigation (`open_main/open_calibration/open_observation/open_camera_detail/close_camera_detail/close_all_windows`). Window modules are now imported lazily so startup never depends on the ROI/HALCON stack.
- No-camera development mode: all windows open without cameras. Placeholders in `ThermalView` and `CameraTile`; `CalibrationWindow` gets a "No Camera Connected" combo entry and disabled-but-visible ROI toolbar; `CameraDetailWindow` polls silently for unknown cameras; hidden View menu item "Camera Detail (Dev)" (Ctrl+D) opens `dev_cam_1`.
- `MainWindow` emits `cameras_disconnected(list)` and `camera_detail_dev_requested()`; calibration/observation navigation is always enabled.
- Added `tests/test_window_architecture.py` (15 passing) and `docs/Window_Architecture.md`.
### Why
- Centralize window lifecycle (create/show/close/track) in one place, make every window openable without hardware for development, and prevent windows from constructing each other.
### Notes
- HALCON license error #2021 (system clock set back) blocks `gui.roi` import on this machine; the 13 ROI-dependent tests are skipped with a clear reason until the clock/license is fixed. The same error breaks pre-existing suite files (test_alarm, test_roi_*) — not caused by this change. Verify on a healthy machine.
- Registry teardown bug fixed: destroyed-handler captures the windows dict + key, not `self` (GC clears `__dict__` first).
- Application tests use `QT_QPA_PLATFORM=offscreen`.
### Files Changed
- app/window_registry.py (new)
- app/application.py
- gui/main_window.py, gui/roi/thermal_view.py, gui/widgets/camera_tile.py
- gui/calibration/calibration_window.py, gui/observer/observer_window.py, gui/camera_detail_window.py
- tests/test_window_architecture.py (new), docs/Window_Architecture.md (new), CHANGELOG.md

## 2026-08-02 18:30
### What changed
- Dead code cleanup: removed 30 unused files (~347 lines) and 9 empty placeholder packages (`alarms/`, `core/`, `database/`, `recorder/`, `camera/workers/`, `camera/configuration/`, `camera/discovery/`, `processing/overlays/`, `processing/statistics/`).
- Removed unused imports flagged by ruff F401 across 5 files, and a commented-out dead line in `app/application_controller.py`.
- Added `docs/DELETION_LOG.md` documenting every removal with verification notes.
### Why
- Reduce codebase clutter and maintenance surface; remove technical debt left from earlier development iterations (empty placeholders, superseded stubs, and an unused DB-backed camera-config module).
### Notes
- All deletions were verified to have zero references (AST import analysis + full grep across `.py`/YAML/JSON). Tests: 79 passed, 2 pre-existing failures unchanged. HALCON license error (#2021) blocks GUI/ROI test collection in dev environment.
- `previous_camera_connection/` and the legacy `camera/tv46l_camera.py` were deliberately KEPT (archived reference / in-progress migration).
### Files Changed
- 30 files deleted (see `docs/DELETION_LOG.md`)
- camera/services/tv46l_camera.py, camera/tv46l_camera.py, configuration/settings.py, halcon_roi_validation.py, processing/roi_processor.py (unused imports)
- app/application_controller.py (removed commented-out line)
- docs/DELETION_LOG.md (new)

## 2026-08-02 14:30
### What changed
- Enforced strict window hierarchy: Main → {Calibration, Observation}, Observation → Camera Detail only.
- Removed `MainWindow.camera_detail_requested` signal, camera-table double-click handler, and its wiring in `Application`.
- `ObserverWindow` now emits `camera_detail_requested(camera_id)` on tile double-click instead of constructing `CameraDetailWindow` directly; `Application` owns all detail windows (single tracked lifecycle, reuse, shutdown cleanup).
### Why
- Detailed View was reachable from the Main Window (camera table double-click), violating the intended navigation flow; also had two divergent detail-window lifecycles (Application-tracked vs. untracked ObserverWindow instances, which `shutdown()` could not close).
### Notes
- `Application` is now the sole window manager: create/destroy/show/raise/track for all four windows.
- No GUI window instantiates another GUI window; verify by grepping for window constructors inside `gui/`.
- HALCON license expired in dev environment (error #2021, system clock) — GUI tests requiring `gui.roi` cannot run locally.
### Files Changed
- gui/main_window.py
- gui/observer/observer_window.py
- app/application.py

## 2026-07-29
### What changed
- Created standalone HALCON ROI validation tool (`halcon_roi_validation.py`).
- Exercises every drawing object: Rectangle1, Rectangle2, Circle, Ellipse, Polygon/XLD.
- Registers callbacks for on_attach, on_detach, on_drag, on_resize, on_select.

## 2026-07-29 (later)
### What changed
- Fixed `_numpy_to_halcon()` to use `gen_image1`/`gen_image3` with `ctypes.data` pointers (was silently failing with `ha.disp_obj(numpy_array)`).
- Changed window mode `"buffer"` → `"visible"`, added `flush_buffer()` after `disp_obj`.
- Added inline diagnostics every 30 frames (raw dtype/shape/stats, temperature min/max/mean, display range).
- Added `set_part()` to scale displayed image to correct dimensions (was stretched to fill window).
- Added key handler: press 'S' to save current raw/display/temperature frames to `frame_debug/`.
- Suppressed verbose per-frame `numpy->HImage` log.
- Fixed `_log_direct()` to also print to stdout so diagnostics appear on CLI.
### Why
- HALCON `disp_obj` rejects numpy arrays — needed `gen_image3` for 3-channel images and `gen_image1` for grayscale.
- Diagnostics help compare pipeline against the working app frame-by-frame.
### Notes
- Working app's `ThermalView.display_image()` also silently fails with numpy arrays (caught by `except Exception: pass`).
- BGR→RGB conversion in `_numpy_to_halcon` correctly feeds `gen_image3` channel order.
### Files Changed
- halcon_roi_validation.py

## 2026-07-29 (FPS fix)
### What changed
- Added frame-number dedup in `_poll_frame()`: skip the entire calibration pipeline + HALCON display when `frame.frame_number` hasn't changed.
- Added `_last_frame_number` attribute to track already-seen frames.
### Why
- Timer fires at 30 Hz but camera sends at ~9 Hz. Each tick was re-processing and re-displaying the same frame — wasting CPU and spamming `clear_window` + `disp_obj` + `set_part` + `flush_buffer` at 30 Hz.
- HALCON window ops compete with GigE acquisition for internal GPU/network resources; throttling display to match camera rate prevents perceived packet loss.
### Notes
- Without dedup the display pipeline ran 3× per frame unnecessarily.
### Files Changed
- halcon_roi_validation.py
- Validates get_drawing_object_params(), get_drawing_object_iconic(), set_drawing_object_params().
- Appearance controls for color, line width, marker size.
- Reuses production camera code (CameraDiscovery, TV46LCamera, CalibrationManager).
- Live parameter display updates continuously during drag/resize.
- Live event log for every HALCON callback invocation.
### Why
- Need independent HALCON API verification before continuing ROI subsystem.
- Eliminate HALCON itself as a source of bugs in the ROI pipeline.
### Files Changed
- halcon_roi_validation.py

## 2026-07-25 00:30
### What changed
- Removed duplicate Calibration/Observation buttons from toolbar (kept only bottom navigation buttons).
- Renamed "Quick Actions" toolbar to "Tools" row with only Settings/Diagnostics/Logs (all stubs, disabled).
- Connected bottom Calibration/Observation buttons to click handlers (`_on_calibration`/`_on_observation`).
- Fixed button state logic: both buttons disabled when no cameras connected, enabled when >=1 connected.
- Auto-refresh after connect/disconnect: `_poll_status()` called immediately after connection change so badges/indicators update without waiting for the 2s poll timer.
- Selection preservation in `_refresh_table`: re-highlights the previously selected row after refresh.
- Removed stale `_rebuild_row_map` from old remove_camera path (now uses seen-set cleanup).
### Why
- Bottom navigation buttons were decorative — never connected to any signal, so Calibration/Observation windows never opened.
- Duplicate navigation (toolbar + bottom) was confusing.
- Indicator badges showed stale values until the next poll timer tick.
- Selection was lost after any refresh operation.
### Notes
- Pre-existing LSP errors (PyQt5 type resolution) unchanged.
- Application.py window management unchanged (already had proper single-instance + bring-to-front logic).
### Files Changed
- gui/main_window.py (utility bar, bottom button wiring, button states, selection preservation, auto-refresh)

## 2026-07-24 23:55
### What changed
- Rewrote table management in MainWindow to fix "3 empty rows" bug.
- `add_camera`: now temporarily disables `setSortingEnabled(False)` during row insertion to prevent sorting from creating phantom rows; uses local `_make_item` helper for cleaner item creation.
- `_refresh_table`: now tracks `seen` set and calls `remove_camera` for stale cameras no longer in the controller (prevents orphan rows).
- Removed all `[DIAG]` diagnostic prints from `main_window.py` and `application.py`.
### Why
- With sorting enabled, `insertRow` + `setItem` could behave unpredictably — sorting would reorder rows before items were fully set, leaving some rows empty. Disabling sorting during the insert/set window ensures items are written to the correct internal row.
- Stale camera cleanup prevents orphan rows from accumulating if cameras disappear.
### Notes
- Pre-existing LSP errors (PyQt5 dynamic type resolution) unchanged.
### Files Changed
- gui/main_window.py (add_camera: sorted→unsorted→resorted; _refresh_table: stale cleanup; _poll_status: removed diagnostics)
- app/application.py (removed diagnostic print block)

## 2026-07-24 23:45
### What changed
- Complete MainWindow rewrite into professional Control Center layout.
- **Header**: Top row with "Thermal Monitoring System" title + project info (left) and live system badges (HALCON/PLC/Cameras/Streaming/Recording) in top-right corner.
- **Toolbar**: Unicode-icon buttons (Discover/Connect/Disconnect/Refresh) with enabled/disabled state logic. Camera counter showing "Discovered: N | Connected: M / 8 | Streaming: K".
- **Quick Actions**: Second toolbar row with Calibration, Observation, Settings, Diagnostics, Logs buttons.
- **Camera Table**: Selection checkbox column (COL_CHECK), 40px row height, centered headers, auto-sized columns, connection state colors (green/red/orange/gray). Select All checkbox + Clear/Connect Selected/Disconnect Selected buttons below table.
- **Details Panel**: Fixed-height panel below table showing selected camera info (Name, Serial, IP, Model, Position, Firmware, Status, FPS). Updates on row selection.
- **Navigation**: Centered equal-width Calibration/Observation buttons (180×42px), enabled only when a camera is selected/has cameras.
- **Status Bar**: Minimal — "Ready" message, project label, version, live clock (HH:MM:SS updated every 1s).
- **Button states**: Calibration disabled until a camera row is selected. Observation disabled when no cameras registered. Quick action stubs (Settings/Diagnostics/Logs) disabled by default.
- **Clock timer**: New 1-second QTimer for status bar clock display.
- Removed: top-right Calibration/Observation toolbar buttons (duplicate navigation), system indicators from status bar (moved to header), unused styles.
### Why
- The Main Window needed to resemble a professional industrial control center rather than a development utility.
- Duplicate navigation (toolbar + bottom buttons) was confusing. Kept bottom navigation.
- System indicators are more visible in the header than the status bar.
- Details panel avoids opening a separate dialog for basic per-camera info.
- Button state management improves usability and prevents invalid operations.
### Notes
- No backend code modified. Same signals (`calibration_requested`, `observation_requested`, `camera_detail_requested`, `discover_requested`) preserved.
- Public API (`add_camera`, `remove_camera`, `update_camera_status`) unchanged.
- All pre-existing LSP errors are PyQt5 false positives.
### Files Changed
- gui/main_window.py (full rewrite)

## 2026-07-24 23:30
### What changed
- Fixed double crash on Discover/Connect: `_discover_and_register_cameras` now wraps each camera in a per-board try/except (instead of one try around the entire loop) and skips already-registered cameras via `get_camera() != None` check. `_refresh_table` made defensive against missing table items. `_on_discover` simplified — signal emission is fire-and-forget with no try/except wrapper.
### Why
- The single try/except around the HALCON enumeration loop meant the first camera that already existed caused the whole function to abort, leaving remaining cameras unregistered and the table out of sync. Subsequent `_refresh_table()` would then crash on `None` items.
- The "connect not working" was cascade — discovery failed, leaving zero cameras to connect.
### Notes
- No backend code touched. Discovery is now fully idempotent: clicking Discover multiple times is safe.
### Files Changed
- app/application.py (_discover_and_register_cameras: per-camera error handling, skip existing)
- gui/main_window.py (_refresh_table: defensive None checks, _on_discover: simplified)

## 2026-07-24 23:15
### What changed
- Fixed discover button crash: replaced `self._controller.camera_manager.discover()` (no such method) with signal-based architecture — MainWindow emits `discover_requested`, Application handles it via `_on_discover_requested -> _discover_and_register_cameras()`. Added `discover_requested = pyqtSignal()` to MainWindow.
### Why
- Discover button called a nonexistent method (`CameraManager.discover`), raising `AttributeError` every time. No cameras could ever be discovered.
### Notes
- `connect_all` / `disconnect_all` were correct (call controller methods) — the "connect not working" was a side effect of discovery failing first, leaving zero cameras to connect.
### Files Changed
- gui/main_window.py (added discover_requested signal, fixed _on_discover)
- app/application.py (wired discover_requested signal)

## 2026-07-24 23:00
### What changed
- Phase 2 - Layout refinements: professional industrial polish across all windows.
- CameraControlPanel rewritten with 5 QGroupBox sections (Camera, Position, PTZ, Focus, NUC) — camera info, position combo with Prev/Next/Go To/Home, directional PTZ pad (↑ ←HOME→ ↓), focus Near/Far + Fine +/- controls with monospace distance readout, and Execute NUC button.
- CalibrationWindow: thermal/visible viewers wrapped in fixed 644×488 panels with consistent objectName="panel" styling; right ROI panel set to 30% width via stretch factor 7:3 splitter ratio.
- ObservationWindow: fixed 8-tile grid (4×2, never reordered) with pre-created CameraTiles; cameras assigned by index to first empty slot; double-click opens CameraDetailWindow; tile.clear_camera() preserves grid layout on disconnect.
- MainWindow: selection column with checkable items; row height increased to 36px; checkbox reflects connection state.
- CameraDetailWindow: increased content margins (16,16,16,16) and spacing (12); thermal/visible viewers and bottom sections wrapped in QFrame panels.
### Why
- The Phase 1 three-window architecture needed professional spacing, consistent panel styling, and proper layout proportions.
- Fixed 640×480 viewer size in CalibrationWindow ensures consistent display area.
- Fixed 8-tile grid simplifies observation mode with predictable layout.
- Selection column with checkboxes aligns with industrial table conventions.
### Notes
- All false-positive LSP errors (PyQt5 dynamic typing) are pre-existing and harmless.
- No backend code touched.
### Files Changed
- gui/widgets/camera_control_panel.py (rewrite: group-box sections, PTZ pad, focus fine, NUC)
- gui/calibration/calibration_window.py (fixed 640×480 viewers, 30% ROI splitter)
- gui/observer/observer_window.py (rewrite: fixed 8-tile grid, slot-based assignment)
- gui/main_window.py (selection column, 36px row height, checkable items)
- gui/camera_detail_window.py (increased margins/spacing, panel wrapping)
- CHANGELOG.md (updated)

## 2026-07-24 22:00
### What changed
- Complete GUI 2.0 redesign (Phase 1 - Layout & User Experience).
- Main Window rewritten as Control Center with camera discovery table, system status indicators, Menu Bar, Toolbar, and navigation buttons.
- Calibration Window rewritten as Engineering Mode with left camera controls panel, dual thermal/visible synchronized viewers, right ROI workspace panel with collapsible property inspector.
- Observation Window rewritten as Operator Mode with camera tile grid (up to 8 cameras), active alarm table, and minimal controls.
- Camera Detail Window created as a new standalone widget for per-camera inspection.
- Centralized theme system (gui/theme.py) with professional light industrial palette: #F4F5F7 background, #FFFFFF panels, #1976D2 accent.
- ROIPropertyPanel rewritten from flat scroll form to collapsible sections (General, Geometry, Appearance, Alarm, Recording, Metadata) like Visual Studio Property Inspector.
- CameraControlPanel refactored for compact left-panel placement in calibration window.
- Application bootstrap updated to manage lazy-loaded Calibration, Observation, and Camera Detail windows.
### Why
- The original MainWindow mixed camera viewing with ROI editing in a single window, creating a cluttered experience.
- The three-window architecture separates concerns: Main Window (control center), Calibration (engineering), Observation (operator).
- The collapsible property inspector replaces the large scrolling form that was difficult to navigate.
- The centralized theme ensures consistent styling across all windows.
### Notes
- All existing backend code is untouched (Camera, HALCON, ROI, Alarm, Processing, etc.).
- All 421 existing tests pass; 8 pre-existing backend failures unchanged.
- Icon files in assets/icons/ are unused placeholder (.gitkeep only) — text/unicode-based indicators used instead.
- ruff lint check passes with zero errors.
### Files Changed
- gui/theme.py (new)
- gui/main_window.py (rewrite)
- gui/widgets/camera_control_panel.py (refactor)
- gui/roi/roi_property_panel.py (rewrite - collapsible sections)
- gui/calibration/calibration_window.py (rewrite from placeholder)
- gui/observer/observer_window.py (rewrite from placeholder)
- gui/camera_detail_window.py (new)
- app/application.py (update)

## 2026-07-24 18:00
### What changed
- **Fixed calibration never initialized**: `CameraFactory.create_camera()` only called `calibration_manager.initialize()` if `camera_model.calibration_file` was set — but it was always `None` because we never set it during discovery. The method now always calls `initialize()` inside a try/except, matching the pattern in the working `camera_viewer.py`.
### Why
- Without initialization, the lookup table (LUT) was never built. `raw_to_display()` raised `RuntimeError("Lookup table has not been generated.")` on every frame, which was silently caught by `_process_frame()`, resulting in blank camera tiles.
### Notes
- `CalibrationManager.initialize()` takes no arguments (reads `settings.CALIBRATION_FILE` internally), but the old factory code passed `camera_model.calibration_file` — that would have caused `TypeError` if the guard were ever True.
### Files Changed
- camera/factory/camera_factory.py

## 2026-07-24 18:30
### What changed
- **Complete camera pipeline parity audit**: Compared old working implementation (commit 0f3fb5b `tv46l_camera.py`, `previous_camera_connection/live_camera.py`) against new architecture (`HalconDriver` + `AcquisitionEngine` + `CameraFactory` + `Application`). Fixed two critical `open_framegrabber()` parameter mismatches.
### Why
- The previous registration + calibration fixes were insufficient — cameras were detected (discovery worked) but no feed appeared due to silent `open_framegrabber()` failure.
### Notes
- **FieldType**: old code uses `"progressive"` (position 8), new code used `"default"`.
- **Device**: old code passes device identifier string (e.g. `"2c19:0001a6e0xxxx"`), new code was passing IP address. HALCON expects the device identifier from `info_framegrabber()` output for GigE Vision.
- `for_each_camera()` wrapper catches all exceptions silently, so connection failure is logged but invisible in GUI.
- Pre-existing LSP type errors (`HHandle|None`) are harmless.
### Files Changed
- camera/services/halcon_driver.py (open_framegrabber FieldType + Device params)

## 2026-07-24 17:30
### What changed
- **Fixed camera discovery + registration bootstrap**: Added HALCON-based `ha.info_framegrabber()` discovery to `Application.initialize()`. Discovered cameras are now registered with `CameraManager` and `MainWindow` via `CameraFactory`.
- **Fixed `HalconDriver.open_framegrabber()` parameter order**: IP address was passed as CameraType (param 13) instead of Device (param 14). Changed `CameraType` to `"default"`, `Device` to IP address, added missing `LineIn=-1`.
### Why
- Application never discovered cameras: `CameraDiscovery.discover()` was a stub ("will be added later"). `CameraManager` was always empty. `connect_all()` and `start_all()` were no-ops. Poll timer ran on empty list.
- Even if cameras were registered, the wrong `open_framegrabber` parameter mapping would fail to open the correct camera.
### Notes
- Fix restores equivalent behavior from the working `camera_viewer.py` which uses the same `ha.info_framegrabber("GigEVision2", "info_boards")` pattern and passes device/ip as the Device parameter.
- Previously applied fixes in `HalconDriver` (`grab_frame()`, `grab_image_start()`) are now reachable because cameras are actually connected.
### Files Changed
- app/application.py (initialize + _discover_and_register_cameras)
- camera/services/halcon_driver.py (open_framegrabber parameter order)

## 2026-07-24 17:00
### What changed
- **Fixed broken camera acquisition pipeline**: Added `grab_frame()` method to `HalconDriver` and added `grab_image_start()` call at end of `connect()`.
### Why
- `AcquisitionEngine._acquisition_loop()` called `self._driver.grab_frame()` which didn't exist on `HalconDriver`, causing `AttributeError` on every loop iteration. Frames were never produced.
- `grab_image_start()` was never called, so HALCON never entered continuous acquisition mode.
- Both of these omissions happened when the camera services layer was split from the monolithic `TV46LCamera` into `HalconDriver` + `AcquisitionEngine`. The `grab_frame()` method was accidentally not ported.
### Notes
- Regression introduced during services-layer refactoring (Phase 7/8 ROI integration).
- Pre-existing LSP type errors on `_framegrabber` (typed as `None | ...`) are harmless and unrelated.
### Files Changed
- camera/services/halcon_driver.py (connect + grab_frame)

## 2026-07-24 16:30
### What changed
- **Fixed HALCON API compatibility**: Replaced `ha.HRegion.gen_*()` and `ha.HImage()` class-based API calls with standalone functions (`ha.gen_rectangle1()`, `ha.gen_circle()`, `ha.gen_ellipse()`, `ha.gen_region_polygon_filled()`, `ha.himage_from_numpy_array()`). The HALCON Python module at this site does not expose `HRegion` or `HImage` classes — only module-level functions.
### Why
- `geometry_to_hregion.py` used `ha.HRegion.gen_rectangle1(...)` which raised `AttributeError: module 'halcon' has no attribute 'HRegion'` at runtime. Same for `ha.HImage()` in `statistics.py`.
- Direct inspection of `dir(halcon)` confirmed no `HRegion`/`HImage` exports; all region/image creation is via standalone functions returning `ha.HObject`.
### Notes
- Type annotations changed from `ha.HRegion`/`ha.HImage` to `ha.HObject` which IS accessible.
- `_numpy_to_himage` simplified from two-step (`HImage()` + `.gen_image1()`) to single `ha.himage_from_numpy_array()` call.
- LSP type-checking false positives remain for HALCON operator return types (incomplete PEP 484 stubs).
### Files Changed
- roi/geometry_to_hregion.py (6 callsites + type hints)
- roi/statistics.py (type hints + _numpy_to_himage body)
- tests/test_roi_phase2.py (3 callsites)

## 2026-07-24
### What changed
- **ROI Subsystem Phase 1 (Foundation — revision 2)**: Addressed review feedback across all modules.
- **`roi/acquisition_state.py`** (new): `AcquisitionState` dataclass (camera_id, pan, tilt, zoom, focus) replaces raw `position_id` in ROIConfiguration. Frozen, hashable. Future-proof for multi-axis acquisition.
- **`roi/geometry.py`** (rewrite): `ROIGeometry` is now a proper ABC with abstract `shape`, `validate()`, `bounding_box()`. All five concrete types implement self-validation (raise ValueError on invalid params) and compute axis-aligned bounding boxes. `PolygonROI` now stores `points: tuple[tuple[float, float], ...]` instead of separate rows/cols.
- **`roi/runtime_cache.py`** (new): `RuntimeROICache` — isolates HALCON HRegion storage from `RuntimeROI`. Holds region, area, bounding_box, dirty flag, last_generation. Prevents HALCON types from leaking into the generic model. Future cache additions (reduced image, contour, mask) add here without touching RuntimeROI.
- **`roi/runtime.py`** (rewrite): `RuntimeROIStatistics` now includes `valid`, `processing_time_ms`, `frame_id`, `alarm_active`, `alarm_since`, `last_updated`. `RuntimeROI` replaces raw `_cached_region` field with `cache: RuntimeROICache` for clean separation of concerns.
- **`roi/configuration.py`** (rewrite): Uses `AcquisitionState` instead of `position_id`. Added explicit boundary documentation: lists what must never be added (cached_region, statistics, drawing_object, runtime_state, etc.).
- **`roi/geometry_to_hregion.py`** (new): Dedicated conversion layer — one responsibility: `ROIGeometry → HRegion`. Each shape type has its own private `_gen_*` function. HALCON import confined to this module. Raises `NotImplementedError` until HALCON is available.
- **`roi/interfaces.py`** (rewrite): `ROIManager.load/unload_position` → `load/unload_state(acquisition_state)`. `RuntimeROIManager` now includes `get_active()`, `mark_dirty()`, `rebuild_dirty_regions()`, `refresh_statistics()`. `ROIRepository.load_all()` takes `AcquisitionState`.
- **`roi/__init__.py`**: Updated exports for new modules (AcquisitionState, RuntimeROICache, geometry_to_hregion, BoundingBox).
### Why
- Position ID alone is insufficient for systems where zoom/focus/lens affect ROI validity.
- Self-validating geometry prevents invalid data from entering the system at the boundary.
- Tuple of (row,col) pairs eliminates row/col length mismatch bugs and simplifies iteration/serialization.
- HALCON HRegion storage needs a dedicated container so RuntimeROI doesn't leak HALCON types.
- Runtime statistics were missing fields that other parts of the system will need (frame_id, timing, alarm state).
- A dedicated conversion layer keeps HALCON code isolated, following project convention.
- Missing interface methods (get_active, mark_dirty, rebuild_dirty, refresh_statistics) would force downstream code to work around the gaps.
### Notes
- 12 files now in `roi/` (3 new, 6 rewritten, 3 unchanged).
- Full runtime verification passes: geometry validation, bounding boxes, polygon storage, AcquisitionState equality, RuntimeROI/Cache integration.
- All geometry types are frozen dataclasses with slots. Lint (ruff) passes cleanly.
- Geometry classes are frozen (immutable) dataclasses with slots.
- RuntimeROI declares `_cached_region: object` as placeholder for future HALCON HRegion.
- Lint (ruff) passes cleanly. All imports verified at runtime.
- Parameter Browser with three categories: Read Only, Read/Write, Write Only (auto-discovered via HALCON APIs + known registry).
- Manual Test Box with Read/Write/Execute for ad-hoc parameter testing.
- Quick Test mode — set `TEST_PARAMETER` constant at the top to auto-test any single parameter on startup.
- Parameter Inspector showing name, value, HALCON/Python type, access, timestamps, error info.
- Parameter Scanner that iterates all parameters, classifies them, exports to CSV/JSON.
- History table with timestamped log of all operations.
- Live refresh (off/500ms/1s/2s/5s) for the selected parameter.
- Connect/Disconnect/Reconnect with device discovery via `info_framegrabber`.
- Standalone — no imports from production code, no modifications to existing system.
### Why
- Reverse-engineering tool to discover undocumented TV46L features.
- Safe experimentation without risk to production monitoring.
- Build a complete capability database over time via the Parameter Scanner.
### Files Changed
- tests/halcon_parameter_explorer.py (new)

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

## 2026-07-24 16:55
### What changed
- Fixed `DrawingObjectFactory.attach_to_window` argument order: swapped `draw_obj` and `window_handle` to match HALCON's `attach_drawing_object_to_window(window_handle, draw_handle)` signature.
- Fixed `DrawingObjectFactory.set_callback` to catch `Exception` (not `TypeError`) when setting Python callables — the actual exception is `halcon.ffi.HTupleConversionError`, which is not a subclass of `TypeError`.
- Added `check_callable(callback)` guard before calling `set_drawing_object_callback` to gracefully skip unsupported callback types.
- Added class-scoped `halcon_window` fixture in tests using `ha.open_window(..., "buffer", "")` to provide a valid window handle for HALCON-dependent tests.
- Fixed unused import lint warnings across editor package and tests (10 removals via `ruff --fix`).
### Why
- All `TestROIEditorManagerWithHalcon` tests failed because window handle `123` was invalid; they now use a real buffer window from `ha.open_window`.
- Callback tests failed with `HTupleConversionError` because the Python HALCON binding doesn't accept `Callable` as callback — only `int`/`Sequence[int]` for HLibProCall.
- `attach_drawing_object_to_window` had the correct C API signature but arguments were swapped in our Python code.
### Notes
- Buffer windows created via `ha.open_window` work headlessly and accept drawing object attachment.
- HALCON type-stub LSP errors (HHandle vs object, callable vs MaybeSequence[int]) remain as pre-existing false positives.
### Files Changed
- roi/editor/drawing_object_factory.py (swapped attach args, fixed callback exception type)
- tests/test_roi_editor.py (added halcon_window fixture, switched 123 -> self.window, removed unused imports)

## 2026-07-24 17:30
### What changed
- Implemented `alarm/` package — standalone, deterministic alarm engine with no HALCON or GUI dependencies:
  - `conditions.py` — Strategy pattern for alarm conditions (HIGH, LOW, RANGE) via `ConditionEvaluator` ABC with registry (`get_evaluator`, `register_evaluator`). Each evaluator handles NaN values, hysteresis (trigger vs clear thresholds), and selects the appropriate statistic (max for HIGH, min for LOW, mean for RANGE).
  - `state_machine.py` — `AlarmState` enum (NORMAL → PENDING → ACTIVE → ACKNOWLEDGED → CLEARED) and `AlarmStateMachine` with frame-timestamp-based delay timing, `is_valid_transition()` validation, `acknowledge()`, `force_clear()`, and `reset()`.
  - `events.py` — Immutable `AlarmEvent` dataclass (`frozen=True, slots=True`) with `AlarmEventKind` (ACTIVATED, CLEARED, ACKNOWLEDGED, RESET).
  - `evaluator.py` — `AlarmEvaluator` (pure function, no side effects) evaluates one ROI using `RuntimeROIStatistics` + `ROIAlarmSettings` + `AlarmStateMachine`.
  - `history.py` — `AlarmHistory` with per-ROI and global event querying, `clear()`.
  - `manager.py` — `AlarmManager` with per-ROI state machines, `evaluate()`, `evaluate_all()`, `acknowledge()`, `reset()`, `register()`, `unregister()`, `clear_all()`, `on_event` callback, thread-safe via `threading.Lock`.
  - `interfaces.py` — `ConditionEvaluator` ABC (strategy), `AlarmEventHandler` protocol.
  - `__init__.py` — Public API exports.
- Created `tests/test_alarm.py` — 104 tests covering all state transitions, hysteresis, delay, acknowledge, reset, disabled alarms, invalid stats, NaN values, multiple ROI independence, event generation, history, edge cases, and custom evaluator registration.
### Why
- The existing `processing/alarm_processor.py` used old types (`ROIResult`, `AlarmThreshold`), lacked PENDING state, hysteresis, acknowledgement, history, and used `time.monotonic()` (non-deterministic).
- Phase 5 requires a clean, testable, deterministic alarm engine that consumes `RuntimeROIStatistics` and `ROIAlarmSettings` (the new Layer 2 types).
### Notes
- Delay timing uses frame timestamps (not wall clock) for deterministic testing.
- Evaluator registry is extensible — future conditions (DELTA, RATE, HOTSPOT) can be added via `register_evaluator`.
- No HALCON, GUI, persistence, or recording dependencies.
- Thread safety via per-method `Lock` in `AlarmManager`.
### Files Changed
- alarm/__init__.py (new)
- alarm/conditions.py (new)
- alarm/events.py (new)
- alarm/evaluator.py (new)
- alarm/history.py (new)
- alarm/interfaces.py (new)
- alarm/manager.py (new)
- alarm/result.py (new)
- alarm/state_machine.py (new)
- tests/test_alarm.py (new)

## 2026-07-24 17:30
### What changed
- **Phase 6 (Persistence) enhancements**: Added `Project` data model with `CameraReference`, `ProjectRepository` for project-level CRUD, forward-compatible schema handling (warns instead of raises for future versions, preserves unknown fields through round-trip), and enhanced ROI value validation (hex color format, alarm condition enum values, geometry bounds).
- **Forward compatibility**: `validate_schema_version` now logs a warning for future schema versions instead of raising `SchemaVersionError`. Unknown top-level fields are extracted during read, stored, and re-injected during write.
- **Value validation**: New `validate_roi_values()` function validates hex color format (`#RRGGBB`), alarm condition enum membership, and geometry field constraints (positive numbers, rectangle row2>row1/col2>col1, positive circle radius, positive ellipse radii).
- **Example**: Added `config/roi/project.json.example` with sample project/camera hierarchy.
### Why
- Spec requires a project-level entry point for multi-camera deployments (per `ROI_Design_Decisions.md` and `ROI_Subsystem_Plan_Part2.md`).
- Forward compatibility is critical for long-lived installations where schema version may be updated by different application versions.
- Value validation catches common configuration errors early, before they propagate to the GUI or HALCON layer.
### Notes
- Existing `JSONROIRepository` unchanged; `ProjectRepository` is a separate class alongside it.
- `_extra_fields` stored by file path in `JSONROIRepository._extra_fields`; fallback to disk read on cache miss.
- 30 new tests: project serialization (6), project repository (11), forward compatibility (4), value validation (9).
- Total persistence tests: 75 (all passing).
### Files Changed
- roi/persistence/project.py (new)
- roi/persistence/schema.py (modified — forward-compat, validation)
- roi/persistence/serializer.py (modified — project serialization, helpers)
- roi/persistence/repository.py (modified — extra fields, ProjectRepository)
- roi/persistence/__init__.py (modified — exports)
- tests/test_roi_persistence.py (modified — 30 new tests)
- config/roi/project.json.example (new)

## 2026-07-24 15:20
### What changed
- **Phase 7 (GUI Integration)**: Wired ROI subsystem into MainWindow. Added right-side ROI panel with toolbar, list, and property panel. Connected signal bus to workspace, selection manager, and dirty tracker.
- **`gui/main_window.py`** (modified): Added `_init_roi()` to create signal bus, selection manager, dirty tracker, editor manager, repository, and workspace. Modified layout to a horizontal splitter: camera tiles (left) + ROI panel (right). Added `_build_roi_panel()` creating the ROI toolbar, list widget, and property panel. Added `_connect_roi_signals()` wiring toolbar→signal bus, list→signal bus, property panel→signal bus, and signal bus→widget updates. Camera tile click now loads ROI state for the selected camera.
- **`gui/roi/roi_workspace.py`** (modified): `_on_edit_start()` now catches editor errors gracefully (logging a warning) so ROI creation works even when no HALCON window is available. Removed unused imports (`ROIManager`, `ROICommand`).
- **`gui/roi/roi_list_widget.py`** (modified): Removed unused `ROIAlarmCondition` import.
- **`gui/roi/roi_property_panel.py`** (modified): Removed unused imports (`QHBoxLayout`, `QPushButton`, `ROIAlarmSettings`, `ROIRecordingSettings`, `ROIStyle`).
- **`tests/test_roi_gui.py`** (fixed): Multi-arg signal tests now use lambdas to capture both arguments. Workspace tests pass without real HALCON window (editor failure handled gracefully). Removed unused `pytest` import.
### Why
- Complete the GUI integration for Phase 7 — users can now create, view, select, and edit ROIs through the main application window with full dirty tracking and save support.
- The workspace no longer crashes on editor failure, enabling ROI creation in test environments and when HALCON windows aren't available.
### Notes
- Editor manager uses `window_handle=0` as placeholder; real HALCON windows from ThermalView can be wired later.
- Signal bus wiring follows the architecture: toolbar/list/property → signal bus → workspace → signal bus → widget updates.
- Save button is disabled until dirty state is set (via toolbar.set_dirty).
### Files Changed
- gui/main_window.py
- gui/roi/roi_workspace.py
- gui/roi/roi_list_widget.py
- gui/roi/roi_property_panel.py
- tests/test_roi_gui.py

## 2026-07-24
### What changed
- **Phase 8 (System Integration)**: Wired ROI processing into the frame loop. All cameras now have per-camera `RuntimeROIManagerImpl` instances. Alarm evaluation runs on every frame. Statistics and alarm state signals update the ROI list widget.
### Files Changed
- gui/roi/roi_workspace.py — Added per-camera `_runtime_managers: dict[str, RuntimeROIManagerImpl]`, `_alarm_manager`, `_active_camera_id`, `process_frame()` method. All `_runtime_manager` references replaced with active camera lookups. Alarm registration on create/duplicate/load_state; unregistration on delete. Added `add_configuration()` to runtime manager (incremental ROI add without clearing existing ROIs).
- gui/main_window.py — `_process_frame()` now gets temperature image and calls `workspace.process_frame()`. Added `_on_roi_statistics_updated()` and `_on_roi_alarm_state_changed()` handlers wired to signal bus.
- gui/roi/roi_property_panel.py — Added `is_current_roi()` method.
- roi/runtime_manager.py — Added `add_configuration()` method for incremental ROI addition without `unload()`.
- docs/ROI_Runtime_Flow.md — New architecture documentation.
- tests/test_roi_integration.py — 26 integration tests covering frame processing, alarm triggering, signal emission, multi-camera independence, alarm registration lifecycle, edge cases (empty/nan temps, camera switch, edit-then-process).
### Why
- Complete the integration of all ROI subsystem components (ROIWorkspace, RuntimeROIManagerImpl, AlarmManager) into the live frame processing pipeline.
- Per-camera managers enable independent ROI processing for all cameras simultaneously.
- Signal-based GUI updates ensure thread safety.
### Notes
- 342 tests pass (6 pre-existing HALCON failures unchanged).
- Zero regressions across all ROI GUI, persistence, alarm, editor, phase2, and integration tests.

## 2026-08-03 19:05
### What changed
- Verified and fixed the roi_engine batch pipeline (masks.py, region_cache.py, statistics_engine.py) plus two HALCON-backed test suites (tests/test_region_cache.py, tests/test_statistics_batch.py): 16/16 tests pass, ruff clean.
- Corrected the rotated-rectangle mask: HALCON gen_rectangle2 puts length1 along the (-sin phi, cos phi) axis (verified at phi=0: 21x61 region), so the mask is now a polygon fill of the four corners in perimeter order (l1,l2), (l1,-l2), (-l1,-l2), (-l1,l2); the previous order emitted a bow-tie (area 1867 vs 3672).
- Ellipse mask uses 2x2 supersampling (max 2.4% area deviation), polygon mask 4x4; hotspot search now dilates the mask by one pixel (8-connectivity) and discards pixels hotter than the HALCON maximum, guaranteeing the hotspot pixel carries the exact region maximum.
- Legacy reference comparisons required plain Python floats (legacy HALCON calls reject numpy.float64).
### Why
- Task-spec rect2 convention was wrong; approximate masks dropped boundary pixels HALCON includes, which broke hotspot-exactness for corner maxima.
### Notes
- HALCON rect2 rasterization == gen_region_polygon_filled of its corners (1081 vs 1083 px). Probe scripts (temp) deleted; store subclasses from the parallel agent are still pending (conftest falls back to direct file loading).
### Files Changed
- roi_engine/masks.py
- roi_engine/statistics_engine.py
- tests/test_region_cache.py
- tests/test_statistics_batch.py
