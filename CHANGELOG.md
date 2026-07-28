## 2026-07-27 20:00
### What changed
- Fixed missing live camera feed in Calibration and Observation windows.
- Two root causes identified and fixed:
  1. Acquisition thread was never started after camera connection (AcquisitionEngine.start() never called by MainWindow connect handlers).
  2. ThermalView.display_image() received numpy RGB arrays but tried to pass them to ha.disp_obj() which expects HALCON HImage objects. Also window handle was never created.
- Changes:
  - `gui/main_window.py`: Added `self._controller.start_all()` after `connect_all()` in `_on_connect()`, and `self._controller.start_camera(cid)` after `connect_camera(cid)` in `_on_connect_selected()`.
  - `gui/roi/thermal_view.py`: Added QPixmap-based display path via `_display_numpy()` for numpy arrays, with proper BGR→RGB conversion and scaled rendering. HALCON display path preserved for HObject inputs. Placeholder/feed state management using stacked QLabel.
- Verified: Same single acquisition thread feeds both Calibration and Observation windows. No second camera instance created.
- Added temporary debug logging at each pipeline stage for verification.
### Why
- Cameras were discovered and connected but no frame data reached the GUI, making Calibration and Observation windows non-functional.
### Notes
- Debug logging can be removed after verification — look for `print("[Acquisition]`, `print("[Camera]`, `print("[Calibration]`, `print("[Observation]"` markers.
- Temporary logging added in: acquisition_engine.py, tv46l_camera.py, calibration_window.py, observer_window.py.
### Files Changed
- gui/main_window.py
- gui/roi/thermal_view.py
- gui/calibration/calibration_window.py (debug logging only)
- gui/observer/observer_window.py (debug logging only)
- camera/services/acquisition_engine.py (debug logging only)
- camera/services/tv46l_camera.py (debug logging only)

## 2026-07-25 02:00
### What changed
- Created Settings window (`gui/settings_window.py`): QListWidget navigation (10 categories) + QStackedWidget pages. Categories: General, Appearance, Project, Cameras, ROI Defaults, Alarm Defaults, Recording, Logging, Network, Advanced. Each page has realistic placeholder controls (combos, spinboxes, checkboxes, line edits). Apply button per page.
- Created Diagnostics window (`gui/diagnostics_window.py`): System group (Python/Qt/HALCON version + platform info), Camera Diagnostics table (7-col table with name/connection/FPS/latency/age/dropped/status, polled every 2s from controller), Recent Log Output area. Uses `ApplicationController` for live camera data.
- Created Event Log window (`gui/log_window.py`): `LogWindow` singleton with `LogWindow.log(message, severity, source)` class method for global access. Toolbar with search input, severity filter (All/INFO/WARNING/ERROR), Auto Scroll checkbox, Clear, Export to CSV. Table columns: Timestamp, Severity (color-coded), Source, Message. Max 10k entries.
- Removed "Tools" label + separator from utilities toolbar — now just Settings/Diagnostics/Logs buttons directly.
- Added Event Log entry in View menu.
- Wired all 3 buttons in MainWindow (`_on_settings`, `_on_diagnostics`, `_on_logs`): lazy instance creation, single-instance enforcement, bring-to-front, cleanup on close.
- Added logging integration to all GUI actions: Application Start, Discover, Connect, Disconnect, Refresh, Connect Selected, Disconnect Selected, Open Calibration, Open Observation, Open Settings, Open Diagnostics, Open Logs. Errors logged as ERROR severity.
- Added `shutdown_utility_windows()` method to MainWindow, called from `closeEvent` and from Application.shutdown.
### Why
- The Settings, Diagnostics, and Logs buttons were disabled stubs — no actual windows existed.
- Event logging is essential for commissioning and debugging. The `LogWindow.log()` class method allows future integration with Camera Manager, Alarm Engine, ROI Manager, etc. without redesign.
- The singleton pattern on LogWindow ensures one-instance and global accessibility.
### Notes
- Pre-existing LSP errors (PyQt5 type resolution) unchanged.
- No backend code modified. No HALCON, camera manager, ROI, alarm, persistence, or processing pipeline changes.
- Settings window is structural — most controls are placeholders with TODO comments for QSettings integration.
- Diagnostics window uses live controller data but FPS/latency/age/dropped columns show "N/A" until per-camera frame metrics are exposed.
### Files Changed
- gui/settings_window.py (new)
- gui/diagnostics_window.py (new)
- gui/log_window.py (new)
- gui/main_window.py (utilities bar, window management, logging, menu entry)
- app/application.py (shutdown integration)

## 2026-07-25 01:00
### What changed
- Fixed invisible text bugs in Main Window: section label color `COLOR_BACKGROUND` → `COLOR_TEXT_PRIMARY`, detail value color `#F4F5F7` → `COLOR_TEXT_PRIMARY`, checkbox color `COLOR_SELECTION` → `COLOR_TEXT_PRIMARY`, clock/field label colors use theme constants.
- Wrapped Camera Management section (table + actions bar) in a white card (`QFrame#panel`) with rounded border.
- Wrapped Navigation section in a white card (`QFrame#panel`) — no more isolated buttons on background.
- Details panel already had `objectName="panel"` — confirmed properly styled as white card.
- Removed horizontal separator (`sep2`) between details and navigation (cards provide their own visual separation via borders + spacing).
- No hardcoded `black` or `#000000` values remain in main_window.py.
### Why
- Section labels were invisible (white-on-light-gray) due to wrong color constant usage.
- Widgets placed directly on window background created large dark areas when theme was applied.
- Card-based layout gives professional appearance with consistent white-on-light-gray hierarchy.
### Notes
- Pre-existing LSP errors (PyQt5 type resolution) unchanged.
- No backend code, no functional logic, no signal wiring changed.
### Files Changed
- gui/main_window.py (card wrapping, color constant fixes, hardcoded hex removal)

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
