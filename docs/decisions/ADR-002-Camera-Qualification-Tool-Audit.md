# ADR-002: Camera Qualification Tool Engineering Review

## Status

Accepted

## Date

2026-07-22

## Summary

The Camera Qualification Tool (`tests/camera_viewer.py`) underwent a comprehensive
engineering audit. The tool is structurally sound but contained several defects
that produced false qualification results, primarily caused by a bug in the
camera driver and by timing collection that sampled at 1 Hz instead of
per-frame. Both issues have been corrected.

## Strengths (unchanged)

- **StageStats** is a correct online statistics accumulator (min, max, total,
  total_sq, count, sliding-window percentile). The math is sound for the value
  ranges encountered (< 1000 ms, squares < 1e6, float64 mantissa ~15 digits).
- **FrameRecord dataclass** correctly captures the full pipeline timeline for a
  single frame (grab through paint). The field set is complete.
- **QualificationMonitor** is a clean passive observer that never modifies
  camera state.
- **HealthEvaluator** is a straightforward threshold-based live evaluation
  suitable for the real-time UI.
- **TimingMonitor** correctly separates each pipeline stage into its own
  StageStats instance, enabling independent live monitoring.
- **GraphManager / GraphWidget** render scrolling time-series data without
  introducing latency or data loss.
- **ThermalWidget** correctly separates UI concerns from measurement logic.
- **Panel classes** (AcquisitionPanel, ProcessingPanel, SystemPanel,
  HealthPanel, TimingTable) correctly reflect live state to the user.

## Problems Found

### P1 — Camera `is_alive()` always returns False (HIGH severity)

**Location:** `camera/tv46l_camera.py:69, 381, 640-649`

**Description:** The field `_last_frame_time` is initialized to `0.0` in
`__init__` but is never updated in `_grab_loop()`. The `is_alive()` method
checks `time.time() - self._last_frame_time < 2.0`, which is always `False`
(first check: `0.0 == 0` returns `False`; after init diff is always > 2 s).

**Impact:** Every consumer of `is_alive()` sees a permanently-dead camera.
The live health panel showed WARNING (after the prior fix changed FAIL to
WARNING), and the QualificationSession accumulated `record_not_alive` events
on every 1-second poll, eventually reaching FAIL threshold after 50 seconds
of runtime — even with frames flowing perfectly. This is the root cause of
false Camera FAIL in the qualification report.

**Fix applied:** Added `self._last_frame_time = time.time()` inside the
successful-grab block of `_grab_loop()`, under the same `self._lock` that
guards `_frame_counter` and `_latest_frame`.

**Code change:** `camera/tv46l_camera.py` line 381.

---

### P2 — Timing samples collected at 1 Hz instead of per-frame (HIGH severity)

**Location:** `_update_diagnostics()`, `ThermalWidget`

**Description:** The 1-second `_update_diagnostics` timer read the latest
paint timing from `ThermalWidget.paint_duration` / `paint_total_latency`,
which only stores the most recent paint event. At 30 FPS, this discards 29
out of every 30 samples (~97 % loss). The `QualificationSession` received
only 1 paint/total-latency sample per second, producing a statistically
impoverished report.

**Impact:** Timing subsystem qualification was based on ~60 samples per
minute instead of ~1800. The 95th percentile computed from 60 samples has
wide confidence intervals, increasing the risk of both false PASS and false
FAIL.

**Fix applied:**
- Added a `_paint_events: deque[EmittedEvent]` queue to `ThermalWidget`.
- Each `paintEvent()` now appends `(paint_duration_ms, total_latency_ms,
  update_delay_ms)` to the queue.
- `_update_diagnostics()` calls `drain_paint_events()` and records *every*
  accumulated event into `_timing`, `_graph_manager`, and `_session`.
- Added `EmittedEvent` type alias for clarity.

**Code change:** `tests/camera_viewer.py`, `ThermalWidget` class and
`_update_diagnostics()`.

---

### P3 — Camera subsystem mixed unrelated concepts (MEDIUM severity)

**Location:** `QualificationSession`

**Description:** The "Camera" subsystem in the qualification report conflated
connection state, thread state, frame arrival, and timeouts into a single
PASS/WARNING/FAIL. A disconnected camera (FAIL) and a running camera with
brief frame gaps (WARNING) produced the same "Camera" line item in the
report, making failures unactionable.

**Impact:** An engineer reading the report could not tell whether the camera
failed to connect, the acquisition thread stopped, or frames were merely
arriving slowly.

**Fix applied:** Split "Camera" into three independent subsystems in the
session report:
- `camera_connection`: PASS if always connected, FAIL if disconnected or never
  connected. Based purely on `connected` property and `_camera_disconnected`
  flag.
- `acquisition_thread`: PASS if thread always running, WARNING if stopped
  early, FAIL if never started.
- `frame_acquisition`: frames arriving, timeouts, FPS stability (renamed from
  "acquisition" to clarify scope).
- `transport`: GigE Vision packet statistics (lost packets, resend packets).

**Code change:** `QualificationSession` class, `generate_report()` method.

---

### P4 — Duplicate end-to-end latency calculation (MEDIUM severity)

**Location:** `_update_diagnostics()` (removed)

**Description:** Two different total latency calculations existed in
`_update_diagnostics`:
1. `w.paint_finish_time - latest.grab_start` (FrameRecord.grab_start +
   widget paint_finish — could mix frames)
2. `tw.paint_finish_time - tw._grab_start_time` (both from ThermalWidget —
   always same frame)

Both updated `self._timing.total`, causing each paint event to be double-
counted in the statistics.

**Impact:** Total latency statistics were inflated by 2x (every sample
counted twice). The `_timing.total.count` was double the true number of
paint events.

**Fix applied:** Removed calculation (1). All total latency now comes from
`ThermalWidget.paint_total_latency`, which is computed in `paintEvent` from
a single frame's `(paint_finish_time - _grab_start_time)`.

---

### P5 — Per-stage timings not recorded in session (MEDIUM severity)

**Location:** `QualificationSession`

**Description:** The session recorded total latency and paint duration, but
not the intermediate pipeline stages (acquire, numpy, publish, gui_delay,
display, colormap, qimage, pixmap). While the live `_timing` (TimingMonitor)
received every per-frame sample, the session report had no access to these
distributions.

**Impact:** If a future qualification criterion needed to distinguish
"slow camera acquisition" from "slow colormap conversion", the session
data would not support it.

**Fix applied:**
- Added `_per_stage: dict[str, list[float]]` to `QualificationSession`.
- Added `record_per_stage(stage, value_ms)` method.
- Called from `_poll_frame` for every frame, alongside the existing
  `_timing.update_all()`.

---

### P6 — FrameRecord paint timestamps populated at 1 Hz (LOW severity)

**Location:** `_update_diagnostics()`

**Description:** `FrameRecord.paint_start` and `paint_finish` fields were
updated inside the 1-second diagnostics timer, writing the latest widget
timestamps to the most recent `FrameRecord`. They were never written from
the actual paint event.

**Impact:** The FrameRecord history (500 records) only had paint timestamps
for the last record, and only from the most recent paint, not the frame's
own paint.

**Fix (partial):** The paint-timestamp assignment now happens inside the
paint-event drain loop, so it runs once per diagnostics cycle. Full
per-frame correlation would require plumbing the frame sequence number
through the paint event — a larger change that would add complexity without
improving report correctness.

**Left for future work:** Per-frame paint-timestamp correlation.

---

### P7 — Live health evaluation `_update_console` duplicated overall logic (LOW severity)

**Location:** `_update_console()`

**Description:** The console health computation manually iterated status
values to find `FAIL`/`WARNING` — duplicating `HealthEvaluator.overall()`.

**Fix applied:** Replaced inline logic with `HealthEvaluator.overall(statuses)`.

---

### P8 — `QualificationEngine` class is essentially dead code (LOW severity)

**Location:** `QualificationEngine` class

**Description:** `QualificationEngine` was the original threshold-based
evaluator. It is still instantiated in `MainWindow.__init__` but no longer
used by `_show_qualification_report()` (which now uses `QualificationSession`).
The `_qualification` attribute is only referenced for type hint purposes in
the import section.

**Impact:** None on correctness. Minor code bloat (~50 lines).

**Recommendation:** Remove `QualificationEngine` and its instantiation in a
future cleanup. Left unchanged to minimise diff scope.

---

### P9 — `QualificationMonitor._camera_was_connected` field unused (LOW severity)

**Location:** `QualificationMonitor.__init__()` (already removed in prior edit)

**Description:** This field was never read. It was removed in the Phase 1
refactoring.

---

### P10 — Console health display uses live values, not session data (informational)

**Location:** `_update_console()`

**Description:** The console output (`[CAMQUAL] ... Health:PASS`) uses the
live `_evaluate_health()` which reads current `_timing` latest values. This
is appropriate for a live diagnostic tool — the console is a real-time
status indicator, not a qualification report.

**Assessment:** Not a bug. The session-based report serves the qualification
purpose; the console serves the live-monitoring purpose. They are expected
to differ.

---

## Code Changes

| File | Change |
|---|---|
| `camera/tv46l_camera.py:381` | Added `self._last_frame_time = time.time()` in `_grab_loop()` |
| `tests/camera_viewer.py` | Added `EmittedEvent` type alias |
| `tests/camera_viewer.py` | Added paint event queue (`_paint_events`) to `ThermalWidget` |
| `tests/camera_viewer.py` | Paint event emission in `ThermalWidget.paintEvent()` |
| `tests/camera_viewer.py` | Added `ThermalWidget.drain_paint_events()` |
| `tests/camera_viewer.py` | `_update_diagnostics()` now drains all paint events |
| `tests/camera_viewer.py` | Duplicate total latency calculation removed |
| `tests/camera_viewer.py` | `QualificationSession`: split Camera into 4 subsystems |
| `tests/camera_viewer.py` | `QualificationSession`: added `_per_stage` timing collection |
| `tests/camera_viewer.py` | `QualificationSession`: replaced `record_disconnect`/`record_not_alive` with `record_camera_state` |
| `tests/camera_viewer.py` | `_poll_frame`: per-stage timings recorded into session |
| `tests/camera_viewer.py` | `_check_camera_state()`: uses `record_camera_state()` |
| `tests/camera_viewer.py` | `_update_console()`: uses `HealthEvaluator.overall()` |
| `tests/camera_viewer.py` | `_show_qualification_report()`: uses `QualificationSession` |

## Remaining Work

1. **Per-frame paint-timestamp correlation in FrameRecord** — Currently,
   `FrameRecord.paint_start` / `paint_finish` are populated from the latest
   paint event, not the originating frame. To fix, the paint event would need
   to carry the frame sequence number, and `_update_diagnostics` would need
   to locate the matching FrameRecord. Not done because it adds complexity
   and the paint timestamps are not used in the qualification report.

2. **Remove dead `QualificationEngine` class** — Not done to minimise diff
   scope. Safe to remove in a future cleanup.

3. **`_timeout_counter` race condition in `tv46l_camera.py`** — The counter
   is incremented outside the lock. Concurrent reads from the GUI thread may
   see stale values. Not fixed because it would require a lock refactor
   across the driver, which is outside the qualification tool scope.

4. **`get_stream_statistics()` lock-free reads in `tv46l_camera.py`** —
   `frame_counter` and `timeout_counter` are read without holding the lock.
   Same reasoning as above.

5. **StageStats `stddev` population vs sample formula** — The current
   code computes population stddev (divides by n). For large sample counts
   (> 30) the difference from sample stddev (divides by n-1) is negligible
   (< 2 %). The values are small (< 1000), so catastrophic cancellation is
   not a practical concern. Not fixed.

## Verification

- Both files pass `ast.parse` syntax check.
- Every stale reference (`record_disconnect`, `record_not_alive`,
  `_check_camera_health`, etc.) has been removed.
- All new evaluator methods (`evaluate_camera_connection`,
  `evaluate_acquisition_thread`, `evaluate_frame_acquisition`,
  `evaluate_transport`) are present and used in `generate_report`.
- Paint event queue is created, populated in `paintEvent`, drained in
  `_update_diagnostics`.
- Per-stage timing is recorded per-frame in `_poll_frame`.
