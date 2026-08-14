# halcon_roi_validation.py — Code Review

**File:** `halcon_roi_validation.py` (project root)
**Lines:** 3525
**Type:** Standalone GUI-based HALCON validation tool
**Target camera:** Fluke ThermoView TV46L (GigE Vision)
**Purpose:** Replicate the MVTec HDevelop processing architecture exactly, end to end, through a real GUI so the HALCON-based ROI pipeline can be validated against production hardware.

---

## 1. What the File Does

The file is a complete, self-contained desktop application. It:

1. Discovers TV46L cameras over GigE Vision using HALCON (`GigEVision2` framegrabber).
2. Loads camera, position, ROI, and alarm configuration from a Microsoft SQL Server database (`ThermalMonitor`, read-only).
3. Runs up to **4 cameras** in parallel, each in its own acquisition thread.
4. For each frame:
   - Grabs the raw 16-bit thermal image (`grab_image_async`).
   - Converts raw counts to temperature (`CalibrationManager.raw_to_temperature`).
   - Re-imports the temperature frame into HALCON and computes ROI statistics with `intensity` and `min_max_gray`.
   - Evaluates alarms against a per-ROI limit.
   - Emits the frame + statistics to the GUI for display, tables, and status readouts.
5. Supports live display with HALCON windows, ROI outlines, zoom, mouse-temperature readout, thermal palette LUT.
6. Supports manual and automatic NUC (Non-Uniformity Correction), focus moves, and per-camera position switching.
7. Saves **alarm snapshots** (normalized temperature frames rendered to PNG with overlays) on a dedicated background worker so acquisition is never blocked by disk I/O.
8. Handles network recovery: grab timeouts are filtered, and the framegrabber is closed/reopened after a run of consecutive failures.

---

## 2. Processing Workflow (per frame)

Exactly as stated in the module docstring:

```
grab_image_async()
  -> himage_as_numpy_array()          (raw 16-bit -> numpy)
  -> CalibrationManager.raw_to_temperature()
  -> himage_from_numpy_array(float32) (temperature -> HALCON image)
  -> intensity(regions, image)        (mean, deviation per ROI)
  -> min_max_gray(regions, image, 0)  (min, max, range per ROI)
  -> AlarmManager.evaluate(statistics)
  -> frame_ready.emit(temp, statistics, proc_ms)   -> GUI
```

This lives in `CameraWorker.run()` (`halcon_roi_validation.py:1442`).

---

## 2A. Detailed Execution Flow (End-to-End)

The complete runtime flow, from process start to shutdown. Every numbered step
is the parent of the indented steps below it.

### 2A.1 Process Startup (`main`, `:3492`)

1. `QApplication` created, Fusion style applied.
2. `DatabaseRepository` and `ConfigManager` are built (SQL **not** connected yet; the window appears immediately, `:3499`).
3. Dark Fusion palette applied per DESIGN.md (background `#1E1E1E`, panels `#252526`, borders `#3C3C3C`, `:3502`).
4. `MainWindow` built and shown, then `start_initialization()` launched (`:3517-3519`).

### 2A.2 MainWindow Construction (`MainWindow.__init__`, `:2330`)

1. Create 4 `CameraRuntime` objects (`CAMERA_COUNT`, `:2349`) — each is an empty per-camera state container.
2. Seed every camera with the default alarm limit (`:2354`).
3. Build the UI:
   - Toolbar: Connect/Disconnect, Focus (`-- - + ++`), Manual NUC, Alarm Limit spin + Apply, Position label + Next Position (`_create_toolbar`, `:2406`).
   - Camera area: fixed **2x2** grid of `CameraPanel` (title bar + `HALCONDisplayWidget`), mouse-temperature readout strip below (`:2490`, `:2522`).
   - Info panel: global alarm table (6 cols), ROI statistics table (6 cols), event log (`:2597`).
   - Status bar: left message; right permanent widgets for Acq/Proc/Disp FPS + Packet Loss/min + Total Packet Loss (`:2635`). 1 s `QTimer` drives display FPS (`:2668`).
4. Default selection = Camera 1 (`:2403`).

### 2A.3 Background Initialization (`start_initialization`, `:2873`; `StartupWorker.run`, `:2264`)

Runs on a dedicated QThread so SQL I/O and HALCON discovery never block the GUI.

1. `start_initialization` spawns `StartupWorker` (`:2887`). Button set to "Initializing..." and disabled.
2. `StartupWorker.run`:
   - Connect SQL (`_db.connect`, `:2266`); try installed ODBC drivers against each candidate server, 5 s per attempt (`:211-215`). Success -> `sql_connected`; failure -> `sql_failed`, degraded mode (`:2267-2273`).
   - Load configuration bundle **if SQL connected** (`:2282`): cameras (`load_cameras`), disabled count, per-camera positions (`_load_all_positions`), global alarm settings, per-camera alarm rows when the schema exposes `camera_id` (`:2282-2295`).
   - HALCON GigE discovery via `CameraDiscovery().discover()` (`:2300`). Failure -> `initialization_failed`, stop.
   - Emit `initialization_complete(discovered, bundle)` (`:2309`).

### 2A.4 Camera-to-Tile Assignment (`_on_initialization_complete`, `:2926` -> `_finish_connect`, `:2676`)

1. Bundle stored in `self._init_bundle` (GUI thread never runs SQL afterwards).
2. SQL available -> `_connect_from_database` (`:2698`):
   - Map discovered devices by **serial number**, IP only as fallback (`:2719`).
   - For each enabled `dbo.cameras` row: `tile = camera_number - 1`; skip tiles out of range / already assigned / camera not visible in discovery (`:2722-2746`).
   - Load that camera's positions; **prefer Position 1**, else first enabled position (`:2753`).
   - Load per-camera alarm defaults; call `_start_worker` (`:2765`).
3. SQL unavailable -> `_connect_from_discovery` (`:2771`): assign discovered cameras to tiles in discovery order, no DB id, no positions.
4. `_start_worker` (`:2794`):
   - Build `CameraWorker` with camera info, config, DB id, position id, alarm defaults, positions (`:2808`).
   - `moveToThread`, connect all signals (`frame_ready`, `error_occurred`, `alarms_changed`, `rois_changed`, `stream_stats`, ...), start thread; `thread.started -> worker.initialize`; `worker.initialized -> worker.run` (`:2861-2862`).

### 2A.5 Worker Initialization (`CameraWorker.initialize`, `:917`)

Runs once on the worker thread.

1. `open_framegrabber("GigEVision2", ..., device, ...)` (`:920`) — device identifier from discovery.
2. Wrap `HalconDriver` for focus/motor control (`:926`).
3. `_configure_camera` (`:974`): `set_framegrabber_param` — IR data source, `bits_per_channel=16`, packet-size negotiation, 1 MB socket, `num_buffers=8`, frame rate from config, disable automatic fine offsets (NUC).
4. `grab_image_start(-1)` then grab first frame (5 s) (`:936-938`).
5. `CalibrationManager.initialize()` — load temperature calibration (`:942`).
6. `_load_rois` (`:1014`): read `dbo.rois` (position-scoped when assigned, legacy camera-wide otherwise); empty set if SQL down — camera still starts.
7. `_generate_halcon_regions` (`:1061`): `gen_rectangle1` **once** from parallel `(rows1, cols1, rows2, cols2)` arrays, coordinate order `(y1, x1, y2, x2)`.
8. `_apply_default_focus` (`:1782`): one-time move to `focus.default_focus_mm`, clamped; failure non-fatal.
9. `connected = True`; arm one-time startup NUC (`:960`); emit `connected_signal(True)` then `initialized` -> `run()`.

### 2A.6 Acquisition Loop (`CameraWorker.run`, `:1442`)

Per iteration, in the worker thread:

1. **Not connected** -> `_attempt_reconnect` (`:1461`) + sleep `reconnect_seconds`; continue.
2. **Grab** `grab_image_async(framegrabber, GRAB_TIMEOUT_MS=500)` (`:1469`). Exceptions branch (`:1470`):
   - `_nuc_active` -> `_handle_nuc_wait_timeout` (`:1375`): timeout is expected during NUC, never counts as a failure; throttled retry; escalate to normal recovery after `grab_timeout_before_reconnect_seconds` (`:1396`).
   - `_is_grab_timeout` (`:1478`, error code 5322) -> `_handle_grab_timeout` (`:1412`): bump consecutive-failure counter, emit `packet_loss`; at `CONSECUTIVE_FAIL_LIMIT` (3) -> `_reassign_framegrabber` (`:1327`) closes/reopens **only this camera's** handle (calibration, LUT, regions untouched; other cameras unaffected) (`:1428-1436`).
   - Other grab errors -> log, sleep 50 ms, continue.
3. **Successful grab** resets the failure streak (`:1491`).
4. **Startup NUC**: if pending -> `_execute_nuc` once, `continue` (`:1498`). (One time only, `_startup_nuc_done`.)
5. **NUC recovery**: first valid frame after NUC sets `_nuc_skip_next_frame = True` (`:1511`); that one frame is discarded (`:1521`).
6. **Per-frame processing** (`:1527-1556`):
   - `himage_as_numpy_array` (raw 16-bit -> numpy) (`:1531`).
   - `raw_to_temperature` (`:1533`) — calibration conversion.
   - `himage_from_numpy_array(temp.astype(np.float32))` (`:1536`).
   - If regions exist: `intensity(regions, image)` -> mean/deviation; `min_max_gray(regions, image, 0)` -> min/max/range (`:1543`); build `ROIStatistics` per ROI name (`:1546`). Empty regions -> empty statistics list (no HALCON crash).
7. **Frame buffer**: append `FrameBufferEntry` to `deque(maxlen=30)` ring (`:1560-1569`).
8. **Alarm evaluation**: `AlarmManager.evaluate(statistics)` (`:1573`) — see 2A.8.
9. **Alarm change notification**: `alarms_changed` emitted only when the active-set changes (`:1577`).
10. **NUC countdown** throttled to 1/s (`:1583`).
11. **Emit to GUI**: `frame_ready.emit(temp_frame, statistics, proc_ms)` (`:1589`) — numpy array, thread-safe.
12. **Stream stats** ~1/s from HALCON GigE counters (`:1595`); Acq/Proc FPS derived from frame deltas.
13. **Command queue** under `_mutex` (`:1605`): manual NUC, auto-NUC due, focus step, position switch — all executed here on the worker thread, never on the GUI thread.
14. Periodic drift log every 90 frames (`:1624`).
15. Loop until `stop()` flips `_running`; then `_cleanup` (`:1638`): stop snapshot worker, `close_framegrabber`, emit `finished` -> thread quits.

### 2A.7 GUI Frame Path (`_on_frame_ready`, `:3118` -> `HALCONDisplayWidget._draw`, `:2092`)

1. Store `latest_temp`, `latest_statistics`, `processing_time_ms` on the `CameraRuntime` (`:3121-3123`).
2. `display_frame` -> `_draw` (`:2092`):
   - Normalize temperature to 8-bit (finite-only min/max; non-finite set to 0) (`:2103-2117`).
   - `himage_from_numpy_array(display)` (`:2120`), `set_part` full 640x480, `clear_window`, `disp_obj` — **palette applied by HALCON LUT at display time** (`set_lut`, `:2035`); raw temperature never modified.
   - For each ROI: `set_draw("margin")`, `disp_rectangle1` (yellow `#EACE21`, red `#FF0000` when that ROI is in alarm) + label `disp_text` (`:2132-2145`).
   - `flush_buffer` (`:2147`).
3. Selected camera only: ROI table updated (`_update_roi_table`, `:3253`) and status bar refreshed (`:3130`).

### 2A.8 Alarm Engine (`AlarmManager.evaluate`, `:746`)

Two-state per ROI: NORMAL <-> ACTIVE.

- `stat.maximum > limit` and not active -> create `Alarm` (timestamp frozen), call `_on_alarm_event` (NORMAL -> ALARM) (`:754-763`).
- Already active -> refresh `current_max`; timestamp never touched (`:764`).
- `stat.maximum <= limit` and active -> remove alarm, event CLEAR (`:766`).
- `_on_alarm_event` (`:1144`): **only** fires on NORMAL->ALARM. Pulls latest frame from ring buffer, builds `SnapshotRequest`, enqueues to `SnapshotWorker` subject to 2 s re-trigger suppression per `(camera, position, roi)` (`:1154-1164`).
- `alarms_changed` -> `_on_alarms_changed` (`:3348`) -> rebuild global alarm table (all cameras) + outline colors.

### 2A.9 Alarm Snapshot (`SnapshotWorker.run`, `:643` / `_save`, `:661`)

1. Bounded `deque(maxlen=30)`; consumer runs on its own QThread; queue full -> drop with warning (`:631`).
2. `_save`: normalize temperature to 8-bit, build grayscale `QImage`, draw header (camera, position, timestamp) + ROI rectangles/labels (active ROI red, others yellow) (`:688-693`).
3. Write `alarm_snapshots/Camera{n}_Position{p}_ROI{i}_{stamp}.png` (`:696-703`).

### 2A.10 Position Switch (`_on_next_position`, `:3195` -> `_apply_position`, `:1099`)

1. GUI picks next enabled position (wrapping) (`:3209`), calls `request_position(id)` (mutex-guarded flag).
2. Acquisition loop executes `_apply_position` (`:1619`): same position -> skip; otherwise load `dbo.rois` for `(camera, position)`, `_set_rois` -> regions regenerated (`:1124`).
3. Alarm state cleared (stale alarms must not survive the ROI swap) (`:1125`); `rois_changed` emitted -> panel title + ROI data updated (`:3222`). Camera and stream keep running.

### 2A.11 NUC (`_execute_nuc`, `:1666`)

1. Sets `_nuc_active=True` (grab timeouts during NUC are expected, not failures).
2. Issues `FLK_TI_ControlFeature_REControlCmd` = `RequestFineOffset` then `ExecuteFineOffset` (`:1687-1696`).
3. Camera stops producing frames; loop keeps waiting via `_handle_nuc_wait_timeout`; first valid frame resumes acquisition with one frame discarded.

### 2A.12 Focus Step (`_execute_focus`, `:1710`)

Signed step from config (`coarse_step_mm`/`fine_step_mm`); target = current + step, clamped to driver limits via `HalconDriver`, move applied, position read back and logged (`:1738-1750`). Failure logged, camera keeps running.

### 2A.13 Shutdown (`_disconnect_all`, `:2940` -> `_shutdown_thread`, `:3460`; `closeEvent`, `:3483`)

1. Per camera: `worker.stop()` (flip `_running`), `thread.quit()`, `thread.wait(5000)` (`:3470-3472`).
2. References nulled only after the thread has actually finished; a worker that does not exit in 5 s is kept alive rather than destroyed (`:3473-3477`).
3. Packet-loss baselines reset, alarm table cleared, buttons re-enabled.
4. `closeEvent` also quits the init thread (3 s wait) before accepting (`:3484-3489`).

---

## 3. Module / Layer Breakdown

Grain-of-truth layering (respects the project architecture `GUI -> Camera Layer -> HALCON`):

| Component | Location | Responsibility |
|---|---|---|
| `DatabaseConfig` / `DatabaseRepository` | `:150` / `:163` | Read-only SQL Server access (cameras, positions, ROIs, alarm + app settings) |
| `ConfigManager` | `:469` | Config precedence: SQL `application_settings` > `config.json` > built-in defaults |
| `CameraWorker` | `:787` | Acquisition + HALCON processing thread (one per camera) |
| `CameraRuntime` | `:432` | Per-camera runtime state container (worker, display, stats, position, alarms) |
| `AlarmManager` | `:707` | Two-state alarm engine (NORMAL -> ACTIVE -> NORMAL) |
| `SnapshotWorker` | `:616` | Background alarm-snapshot PNG writer (own thread + bounded queue) |
| `HALCONDisplayWidget` | `:1844` | HALCON window widget: display, ROI outlines, zoom, mouse position |
| `CameraPanel` | `:2170` | One 2x2 grid cell: title bar + fit-sized viewer |
| `StartupWorker` | `:2244` | Background init thread: SQL connect, config load, HALCON discovery |
| `MainWindow` | `:2327` | Main window: toolbar, 2x2 grid, info panel, status bar, wiring |
| `ROIData` / `CameraPosition` / `ROIStatistics` / `Alarm` / `FrameBufferEntry` / `SnapshotRequest` | model dataclasses | Data-only transfer objects |

---

## 4. Configuration

`ConfigManager` (`:469`) implements a strict precedence:

```
dbo.application_settings (SQL)  ->  config.json  ->  built-in defaults
```

- `config.json` is read exactly once at construction.
- `CONFIG_TO_DB_KEY` maps JSON paths to SQL keys (e.g. `camera.fps` -> `camera_fps`).
- SQL wins only when the mapped key actually exists in the table.
- SQL strings are coerced to the type of the fallback value (`_coerce_value`, `:563`).

Key defaults (`camera.fps` = 9 -> ~111 ms frame interval; this drives the grab timeout of 500 ms at `:114`).

Alarm limits have a validation range `0.0 .. 2000.0` (`MAX_ALARM_LIMIT` / `MIN_ALARM_LIMIT`, `:75`) matching the toolbar spin box.

---

## 5. Database Layer (`DatabaseRepository`, `:163`)

- Host/credentials come from environment variables with defaults (`:81-85`); Windows Integrated Security by default (no credentials in code).
- Driver and server candidates are tried until one works; per-attempt timeout of 5 s (`:215`) keeps a dead DB cheap to fail.
- **Read-only by design**: the schema is never modified; no tables or columns are created.
- Schema probes (`_detect_alarm_camera_column`, `_detect_rois_position_column`, `_detect_positions_table`) check which columns/tables exist so legacy schemas degrade gracefully.
- When SQL is unreachable the repository stays connected=False and exposes `last_error` so callers continue without crashing.

Key queries:
- `load_cameras` — enabled cameras ordered by `camera_number` (`:264`).
- `load_rois(camera_id, position_id)` — ROI definitions; filtered per position when the schema has `rois.position_id`, else camera-wide; falls back to legacy `position_id IS NULL` rows before the SQL migration (`:280`).
- `load_camera_positions` — enabled positions per camera (`:328`).
- `load_alarm_settings` — per-camera row via `camera_id` when the column exists, else the single global row (`:348`).

---

## 6. Threading Model

Every camera owns an independent worker thread; GUI never blocks acquisition.

| Thread | Owner | Work |
|---|---|---|
| GUI thread | Qt main loop | Display, tables, status bar, toolbar state |
| Worker thread x4 | `CameraWorker` (one per camera) | `grab_image_async`, conversion, HALCON ROI stats, alarms, stream stats |
| Snapshot thread x1 | `SnapshotWorker` | Serial PNG writing of alarm snapshots from a bounded `deque(maxlen=30)` |
| Init thread x1 | `StartupWorker` | SQL connect + HALCON discovery at startup |

- `CameraWorker` is a `QObject` moved to a `QThread`; `initialize()` runs on thread start, then `run()` loops until `stop()` (`:1835`) flips `_running`.
- Cleanup of the framegrabber happens in `run()` after the loop returns (`_cleanup`, `:1638`), never while a grab may be in flight.
- Worker -> GUI data crosses only via `pyqtSignal`; frames cross as numpy arrays (thread-safety note at `:1588`).
- GUI -> worker commands (`request_nuc`, `request_focus`, `request_position`, `set_alarm_limit`) are guarded by a `QMutex` and executed inside the acquisition loop (`:1605-1621`), so **all HALCON region work happens on the worker thread**, never the GUI thread.

---

## 7. HALCON Operators — Where, What, Why

| Operator                                | Location | Usage |
|---                                      |---|---|
| `open_framegrabber("GigEVision2", ...)` | `:920`, `:1344` | Open the GigE Vision framegrabber for a device. Generic open is followed by TV46L-specific parameter setup. |
| `set_framegrabber_param`                | `:976-1012` | TV46L acquisition config: IR data source, 16-bit, packet negotiation, receive socket size 1 MB, `num_buffers=8` (in-flight buffers so 4 streams don't overflow), frame rate, disable automatic fine offsets (NUC). Also used to trigger NUC (`:1687-1696`). |
| `get_framegrabber_param`                | `:1258`, `:1304` | Read GigE stream counters (`GevStreamLostPacketCount`, `Seen`, `Delivered`, `Resend`) for packet-loss statistics, and buffer params for diagnostics. |
| `grab_image_start` / `grab_image_async` | `:936-938`, `:1359-1360`, `:1469` | Continuous pre-grabbing (`-1`); `grab_image_async` with 500 ms timeout in the loop. Timeout error code 5322 handled specially. |
| `himage_as_numpy_array`                 | `:1531` | Raw HALCON image (16-bit) to numpy for the calibration conversion. |
| `himage_from_numpy_array`               | `:1536`, `:2120` | Numpy temperature (float32) -> HALCON image for statistics; 8-bit display -> HALCON image for display. |
| `gen_rectangle1`                        | `:1071` | Generate all ROI regions **once** from parallel (rows1, cols1, rows2, cols2) arrays, per `(y1, x1, y2, x2)` interpretation. |
| `intensity`                             | `:1543` | Region/image statistics: mean and deviation per ROI. |
| `min_max_gray`                          | `:1544` | Per-ROI min, max, range in temperature terms. |
| `open_window` / `set_window_extents` / `set_part` / `set_lut` / `set_draw` / `set_line_width` / `set_color` / `clear_window` / `disp_obj` / `disp_rectangle1` / `disp_text` / `flush_buffer`                            | display widget `HALCONDisplayWidget` | Full HALCON-native rendering: window sized to the 4:3 fit, `set_part` maps the full 640x480 image, thermal palette applied via HALCON LUT at display time (raw data unchanged), ROI outlines drawn as margin rectangles (ROI color `#EACE21`, alarm color `#FF0000`) with labels, then flushed. |
| `close_window` / `close_framegrabber`   | `:1996`, `:1654` | Clean teardown on resize / shutdown. |

Design rule honored: the palette is `ha.set_lut(window, palette)` — HALCON applies the palette **at display time**; the raw thermal data is never modified.

---

## 8. Camera Connection & Recovery

### Initialization (`initialize`, `:917`)
1. Open framegrabber -> wrap `HalconDriver` for focus control -> configure camera -> start grab -> grab first frame (5 s timeout).
2. Load calibration (`CalibrationManager.initialize()`).
3. Load ROIs from SQL and generate HALCON regions once.
4. Apply default focus exactly once (failure is non-fatal).
5. Arm one-time **startup NUC**, fired on the first valid frame of the loop.

### Grab-timeout recovery (`_handle_grab_timeout`, `:1412`)
- A transient timeout is logged + `packet_loss.emit()`.
- After `CONSECUTIVE_FAIL_LIMIT` (3) consecutive timeouts, the framegrabber is closed and reopened (`_reassign_framegrabber`, `:1327`). Calibration LUTs, ROI regions, connection state are deliberately untouched; only this camera's handle is replaced, so the other three keep streaming.

### NUC handling (`_nuc_active`)
- During NUC the camera produces no frames; timeouts are **expected**, not counted as failures (`_handle_nuc_wait_timeout`, `:1375`) until a configured recovery timeout (`grab_timeout_before_reconnect_seconds`) elapses, then the normal ladder is used.
- The first valid frame after NUC is discarded (`_nuc_skip_next_frame`) because it may be unstable.

### Timeout classification (`_is_grab_timeout`, `:1283`)
- Numeric check: `exc.error_code == 5322`. String fallback covers builds without the code.

---

## 9. Alarm System

`AlarmManager` (`:707`) implements a two-state engine:
- **NORMAL -> ACTIVE**: when `stat.maximum > limit`, one `Alarm` is created with a timestamp + `current_max`. Timestamp is never touched while active; only `current_max` refreshes.
- **ACTIVE -> NORMAL**: when temp drops to/under the limit the alarm is removed; a later re-cross creates a brand-new alarm with a new timestamp (`evaluate`, `:746`).
- `_on_alarm_event` (`:1144`) is intentionally silent for logging (no flood) and only used to trigger **alarm snapshots** on NORMAL->ALARM transitions, subject to a **2-second re-trigger suppression** per `(camera, position, roi)` and a shared frame ring buffer (`deque(maxlen=30)`).
- GUI notification only when the active-alarm set changes (`:1577`).
- `clear()` drops all alarms when the ROI set changes on a position switch (`:774`).
- The global alarm table mirrors alarms from **all** cameras; rows keyed by `(camera index, ROI name)` (`_sync_alarm_table`, `:3368`).

Notes in code: alarm limits are per-camera in memory; they are **not** written back to SQL (schema only has a single global default) — this limitation is reported once (`_report_per_camera_alarm_limitation`, `:3103`).

---

## 10. Alarm Snapshots

`SnapshotWorker` (`:616`):
- Bounded queue (`deque(maxlen=30)`) to drop overload instead of blocking the caller.
- `_save` (`:661`): normalizes temperature frame to 8-bit (finite-only min/max), renders as grayscale `QImage`, draws header text + ROI rectangles/labels with a painter, names file as `Camera{n}_Position{p}_ROI{i}_{timestamp}.png`, saves into `alarm_snapshots/`.
- Runs on its own QThread; `stop()` drains after pending requests.

---

## 11. Focus Control

- `_apply_default_focus` (`:1782`): one-time lens move to `focus.default_focus_mm` from config (clamped to driver limits, settled via `_wait_focus_stable`, `:1758`). Non-fatal failure.
- `_execute_focus` (`:1710`): signed step move from the coarse/fine config steps; reads back and logs final distance.
- Focus driver is `HalconDriver` from `camera/services/halcon_driver.py`.

---

## 12. Display Layer (`HALCONDisplayWidget`, `:1844`)

- Window sized to the largest **4:3 rectangle** that fits the widget (aspect 640:480) — no stretching, no cropping (`_compute_fit_rect`, `:1908`; `_display_rect`, `:1926`).
- Zoom levels 50%..400%; zoom > 100% is clamped to the fit (`:1935`). The underlying frame stays 640x480.
- Mouse temperature: maps widget pixel -> image pixel via the actual display rect so accuracy holds at any zoom (`mouseMoveEvent`, `:2061`); only the selected camera reports.
- Clicking selects the camera (`camera_clicked`).
- `_draw` (`:2092`): normalizes temp to 8-bit, displays via HALCON `disp_obj` with LUT, then draws ROI margins/labels; alarm ROIs turn red.
- Qt dark theme via `app.setPalette` in `main()` (`:3502`) matching DESIGN.md (#1E1E1E background, #252526 base, #3C3C3C borders/buttons).

---

## 13. Main Window & Layout (`MainWindow`, `:2327`)

- Toolbar: Connect / Disconnect, Focus step buttons (--, -, +, ++), Manual NUC, Alarm Limit spin + Apply, Position label + Next Position button.
- Camera area: fixed **2x2 grid** of `CameraPanel` (Expanding so resizing scales all four), with a mouse-temperature readout strip underneath.
- Info panel: common alarm table (6 cols), ROI statistics table (6 cols), event log.
- Status bar: left message = feed/zoom/alarms/NUC countdown; right permanent widgets = Acq/Proc/Disp FPS + Packet Loss/min + Total Packet Loss for the **selected** camera.
- Display FPS measured on the GUI side (1 s timer); Acq/Proc FPS and packet loss come from HALCON stream counters.

### Packet-loss accounting (`_update_packet_loss_min`, `:3296`)
- Keeps a rolling one-minute window of deltas between consecutive cumulative HALCON `GevStreamLostPacketCount` samples.
- Counter going backwards (reconnect/stream re-arm) resets the baseline instead of producing a false spike.
- Total Packet Loss = raw cumulative counter.

---

## 14. Startup Sequence (background, non-blocking)

`main()` (`:3492`):
1. Build DB repo + config (SQL not connected yet — window shows immediately).
2. Apply dark Fusion palette, build and show `MainWindow`.
3. `start_initialization()` (`:2873`): spawns `StartupWorker` thread that connects SQL, loads cameras/positions/ROI config/alarm settings, runs HALCON discovery, then emits `initialization_complete(discovered, bundle)`.
4. `_finish_connect` (`:2676`): with SQL -> `_connect_from_database` (match by serial, IP fallback, place on `camera_number` tile, prefer Position 1); without SQL -> `_connect_from_discovery` (discovery order fallback).
5. Each assigned tile starts a `CameraWorker` thread.

---

## 15. Graceful Degradation Points

The file is careful not to crash when subsystems fail:

- SQL down -> cameras still run with empty ROI sets / discovery-order fallback; logged with clear messages.
- Calibration not loaded -> first frame raises, connection reports error via signals.
- ROIs empty -> batch statistics skipped; empty statistics list emitted (would otherwise crash).
- HALCON LUT name invalid -> warning + default LUT.
- window/display errors -> logged, not fatal.
- Snapshot worker init failure -> snapshots simply disabled.
- Worker thread not exiting in 5 s -> kept alive instead of destroying a running QThread (`_shutdown_thread`, `:3460`).
- Bad alarm limit input -> rejected and logged, spin rebound.

---

## 16. Naming / Standards Compliance

- Dataclasses used for models (`ROIData`, `CameraPosition`, `ROIStatistics`, `Alarm`, `FrameBufferEntry`, `SnapshotRequest`), data-only.
- Logging via `logger` everywhere; no `print()`.
- Type hints on public functions/methods; constants in UPPER_CASE; private members prefixed `_`.
- Comments explain WHY (recovery rationale, NUC behavior, schema probes), not obvious code.
- Constants for timeouts/ranges (no magic numbers): `GRAB_TIMEOUT_MS`, `CONSECUTIVE_FAIL_LIMIT`, `MAX_ALARM_LIMIT`, etc.

---

## 17. Notable Observations

1. **Two-state alarm engine** intentionally avoids alarm ringing/re-timestamp on every frame — only on state transitions.
2. **Startup NUC** is executed exactly once after the first valid frame and never repeated on reconnect (`_startup_nuc_pending`/`_done`).
3. **Frame ring buffer** (`deque(maxlen=30)`, ~2 s at 9 FPS) decouples snapshot requests from live processing.
4. **HALCON regions generated once**; re-generated only when ROIs change (position switch) — never per frame.
5. `_connect_from_database` re-reads cameras if the bundle is empty as a safety net, but the bundle path is preferred to keep SQL off the GUI thread.
6. Packet-loss percentage (`packet_loss_percent`) is only reported when `seen > 0` (`percentage_available`), avoiding a divide-by-zero / misleading value.

---

## 18. Verification Status

This document is a code review only. Live verification (camera connect, frame processing, alarm triggers) requires TV46L hardware + HALCON runtime + SQL Server. Static checks recommended before running: `ruff`, `mypy`, application import test.

---

*Generated for the development team. Cross-reference with `docs/ROI_Architecture.md`, `docs/GUI_Event_Flow.md`, and `docs/halcon_operators.md`.*