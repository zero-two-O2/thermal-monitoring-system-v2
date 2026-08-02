# Code Deletion Log

## [2026-08-02] Dead Code Cleanup Session

Branch: `refactor/dead-code-cleanup`

### Analysis Tools Used
- `ruff` F401/F841/F811 (unused imports, local vars, redefinitions)
- AST-based reachability analysis (Python `ast` module)
- Full-codebase grep for every candidate symbol (Python + YAML/JSON)
- Manual verification of `__init__.py` re-exports and test references

### Unused Imports Removed (ruff F401, auto-fixed)
- `camera/services/tv46l_camera.py` - `pathlib.Path`, `typing.Optional`
- `camera/tv46l_camera.py` - `sys`, `numpy as np`
- `configuration/settings.py` - `dataclasses.field`
- `halcon_roi_validation.py` - `time`, `pathlib.Path`, `PyQt5.QtWidgets.QCheckBox`
- `processing/roi_processor.py` - `processing.models.roi_models.AlarmCondition`

### Empty Placeholder Files Deleted (0 bytes, zero references)
These files contained no code and were never imported anywhere in the project (verified via AST import analysis across all `.py` files):

- `alarms/alarm_engine.py` - empty placeholder
- `alarms/__init__.py` - empty placeholder (whole package unused)
- `app/launcher.py` - empty placeholder
- `camera/workers/camera_worker.py` - empty placeholder
- `camera/workers/__init__.py` - empty placeholder (whole package unused)
- `core/constants.py`, `core/enums.py`, `core/exceptions.py`, `core/system_manager.py`, `core/__init__.py` - empty placeholders (whole package unused)
- `database/database_manager.py`, `database/database_models.py`, `database/__init__.py` - empty placeholders (whole package unused)
- `gui/widgets/thermal_view.py` - empty placeholder (real implementation is `gui/roi/thermal_view.py`)
- `processing/overlays/overlay_renderer.py`, `processing/overlays/__init__.py` - empty placeholders (whole package unused)
- `processing/roi_manager.py` - empty placeholder
- `processing/statistics/roi_statistics.py`, `processing/statistics/__init__.py` - empty placeholders (whole package unused)
- `recorder/recorder_engine.py`, `recorder/__init__.py` - empty placeholders (whole package unused)
- `utilities/helpers.py` - empty placeholder

### Dead Modules With Content Deleted (zero references)
- `camera/configuration/camera_configuration.py` + `camera_configuration_service.py` - Only imported each other; never used by app or tests. Also depended on empty `database` package (deleted).
- `camera/discovery/camera_discovery.py` + `__init__.py` - Stub implementation ("will be added later"); never imported. Real discovery is at `camera/camera_discovery.py`.
- `processing/models/image_models.py` - `ThermalImage`, `VisibleImage`, `TemperatureMatrix` dataclasses never referenced anywhere.

### Dead Code Removed In-Place
- `app/application_controller.py` line 441 - commented-out dead `return context.processing_pipeline.process(...)`

### Empty Directories Removed
- `alarms/`, `core/`, `database/`, `recorder/`, `camera/workers/`, `processing/overlays/`, `processing/statistics/`, `camera/configuration/`, `camera/discovery/`

### Remaining (manual review needed - NOT deleted)
- `previous_camera_connection/` - 28 tracked files, an older standalone implementation referenced in CHANGELOG history; not imported by current code but intentionally archived for reference. Verify with team before removal.
- `camera/tv46l_camera.py` (legacy monolithic, 1027 lines) vs `camera/services/tv46l_camera.py` (new architecture) - Both actively imported; appears to be an in-progress architectural migration. Do NOT consolidate without confirming migration status.
- `test_camera.py`, `test_tv46l_camera.py` (root-level scripts) - Standalone test scripts; may still be used manually for hardware tests.
- `camera/camera_discovery.py` vs removed `camera/discovery/` stub - only the active `camera/camera_discovery.py` was kept.

### Impact
- Files deleted: 30 (22 placeholder/empty, 3 dead modules with content, 5 modified for import cleanup)
- Lines of code removed: ~347 (excluding empty files)
- Dead packages removed: 9 directories

### Testing
- `ruff check` passes (all F401 clean; 4 pre-existing F541/E731 style issues remain in untouched code)
- All `.py` files compile via `py_compile`
- Test suite: 79 passed / 2 failed (`test_processing_pipeline.py::test_high_alarm_pipeline`, `test_multiple_alarm_pipeline`) - both failures are PRE-EXISTING and identical to the baseline before cleanup
- HALCON-dependent tests cannot run in dev environment due to license/system-clock error (#2021) - pre-existing, unrelated to cleanup
- Main application modules import successfully (except those blocked by the HALCON license environment issue)

### Notes
- No public API was removed - all deleted symbols were internal with zero references.
- HALCON license expired in dev environment (error #2021, system clock) blocks GUI/ROI test collection locally.
