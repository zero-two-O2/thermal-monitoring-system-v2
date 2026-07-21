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
