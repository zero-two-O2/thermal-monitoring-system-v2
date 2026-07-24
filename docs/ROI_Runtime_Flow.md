# ROI Runtime Processing Flow (Phase 8)

## Overview

Phase 8 integrates the ROI subsystem into the camera frame processing pipeline. Every frame from every camera flows through ROI processing and alarm evaluation simultaneously with display rendering.

## Architecture

```
Frame Poll (QTimer, ~30ms)
  │
  ├─ context.camera.get_frame()           ← raw 16-bit frame
  │
  └─ _process_frame(raw, context)
       │
       ├─ cal.raw_to_display(raw)         ← display pipeline
       ├─ cal.apply_colormap(display)     → rgb for tile
       │
       └─ cal.raw_to_temperature(raw)     ← ROI pipeline
            │
            └─ ROIWorkspace.process_frame(camera_id, temp, frame_id)
                 │
                 ├─ RuntimeROIManagerImpl (per camera)
                 │    ├─ rebuild_dirty_regions()
                 │    ├─ process_frame() → list[RuntimeROIStatistics]
                 │    └─ get_active() → iter RuntimeROI
                 │
                 ├─ emit roi_statistics_updated(camera_id)
                 │    └─ ROIListWidget.update_temperature(roi_id, temp)
                 │
                 └─ AlarmManager.evaluate_all(stats_dict, frame_id)
                      │
                      └─ emit roi_alarm_state_changed(roi_id, AlarmResult)
                           ├─ ROIListWidget.update_alarm_state(roi_id, state)
                           └─ ROIPropertyPanel.load_roi(config)  (if selected)
```

## Key Components

| Component | File | Role |
|---|---|---|
| `ROIWorkspace` | `gui/roi/roi_workspace.py` | Integration hub: holds per-camera runtime managers, alarm manager, coordinates create/delete/edit/process |
| `RuntimeROIManagerImpl` | `roi/runtime_manager.py` | Per-camera runtime cache: manages HRegion cache, geometry rebuild, statistics extraction |
| `AlarmManager` | `alarm/manager.py` | Evaluates statistics against alarm thresholds, manages state machines, fires events |
| `MainWindow` | `gui/main_window.py` | Frame polling loop, signal wiring, widget updates |

## Data Flow

### Per-Camera Runtime Managers

Each `camera_id` gets its own `RuntimeROIManagerImpl` instance in `ROIWorkspace._runtime_managers`. When `load_state(acquisition_state)` is called (camera selection), the active camera's manager is populated with ROIs from persistence.

- `workspace.active_camera_id` tracks the displayed camera
- `workspace.get_runtime_manager(camera_id)` returns the manager for any camera
- `workspace.runtime_manager` property returns the active camera's manager
- `workspace.unload_camera(camera_id)` cleans up a camera's manager

### Processing Pipeline

`ROIWorkspace.process_frame(camera_id, temp, frame_id)`:

1. Gets or creates the runtime manager for `camera_id`
2. Calls `manager.process_frame(temperature_image, frame_id)`:
   - Rebuilds dirty HRegions
   - Extracts statistics (min, max, mean, stddev, hotspot) for each active ROI
   - Returns `list[RuntimeROIStatistics]`
3. If camera is the active (displayed) camera, emits `roi_statistics_updated`
4. Collects valid statistics into `dict[roi_id, RuntimeROIStatistics]`
5. Calls `alarm_manager.evaluate_all(stats_dict, frame_id)`:
   - Evaluates each ROI's statistics against its alarm settings
   - Returns `list[AlarmResult]`
6. For each alarm result, emits `roi_alarm_state_changed(roi_id, alarm_result)`

### GUI Signal Wiring

```
roi_statistics_updated(camera_id)
  → MainWindow._on_roi_statistics_updated(camera_id)
    → iter mgr.get_active() for active camera
    → ROIListWidget.update_temperature(roi_id, max_temp)

roi_alarm_state_changed(roi_id, AlarmResult)
  → MainWindow._on_roi_alarm_state_changed(roi_id, alarm_result)
    → ROIListWidget.update_alarm_state(roi_id, state_name)
    → ROIPropertyPanel.load_roi(config)  (if this ROI is selected)
```

## Alarm Integration

- **Registration**: `_on_create_roi`, `_on_duplicate_roi`, `load_state` call `alarm_manager.register(roi_id, alarm_settings)`
- **Update**: `_on_alarm_changed` re-registers the ROI's alarm settings
- **Unregistration**: `_on_delete_roi` calls `alarm_manager.unregister(roi_id)`
- **Evaluation**: `process_frame` calls `alarm_manager.evaluate_all(stats, frame_id)`

## Thread Safety

- Processing runs in the GUI thread (QTimer poll), but uses thread-safe `AlarmManager` (internal lock)
- Signal emissions are thread-safe (Qt signals)
- `RuntimeROIManagerImpl` is not thread-safe — called only from GUI thread

## Error Handling

- `process_frame` is guarded by MainWindow's `try/except` in `_poll_frames`
- Individual ROI failures produce `valid=False` statistics — other ROIs continue processing
- Missing alarm registrations are silently skipped by `evaluate_all`
