# GUI Event Flow

> **Phase 7 — ROI GUI Integration**
>
> Defines every signal path between GUI widgets and the ROI subsystem.
>
> Widgets never call managers directly. Widgets emit signals. The signal bus relays to managers. Managers own behavior. Widgets own presentation.

---

# Legend

```
Widget ──emit──► SignalBus ──relay──► Manager
Widget ──emit──► SignalBus ──relay──► Widget (synchronization)

Manager ──emit──► SignalBus ──relay──► Widget (refresh)

            ┌──── SignalBus ────┐
            │   (QObject with   │
            │   pyqtSignals)    │
            └───────────────────┘
```

All communication flows **through** the signal bus. No widget-to-widget or widget-to-manager direct coupling.

---

# Signals

## Signal Bus (declarative)

```python
class ROISignalBus(QObject):
    # Selection
    roi_selected = pyqtSignal(str)           # roi_id
    roi_deselected = pyqtSignal(str)         # roi_id
    selection_cleared = pyqtSignal()

    # Lifecycle
    roi_created = pyqtSignal(str)            # roi_id
    roi_deleted = pyqtSignal(str)            # roi_id
    roi_duplicated = pyqtSignal(str, str)    # new_id, original_id

    # Editing
    editing_started = pyqtSignal(str)        # roi_id
    editing_finished = pyqtSignal(str)       # roi_id

    # Property changes (specific)
    roi_geometry_changed = pyqtSignal(str)   # roi_id
    roi_alarm_changed = pyqtSignal(str)      # roi_id
    roi_visibility_changed = pyqtSignal(str) # roi_id
    roi_appearance_changed = pyqtSignal(str) # roi_id
    roi_recording_changed = pyqtSignal(str)  # roi_id
    roi_metadata_changed = pyqtSignal(str)   # roi_id
    roi_renamed = pyqtSignal(str)            # roi_id

    # Camera/Position
    camera_changed = pyqtSignal(str)         # camera_id
    position_changed = pyqtSignal(str, str)  # camera_id, position_id

    # Dirty state
    dirty_state_changed = pyqtSignal(bool)

    # Runtime updates (from processing pipeline)
    roi_statistics_updated = pyqtSignal(str) # roi_id
    roi_alarm_state_changed = pyqtSignal(str, object)  # roi_id, AlarmState
```

---

# Event Flows

## 1. User Clicks ROI in List

```
User clicks ROI row
    │
    ▼
ROIListWidget
    │  emits: selection_changed(roi_id)
    ▼
ROISignalBus.roi_selected
    │
    ├──► ROISelectionManager.select(roi_id)
    │       └── sets current_selection = roi_id
    │
    ├──► ROIPropertyPanel.load_roi(roi_id)
    │       └── reads from ROIManager.get_configuration(roi_id)
    │       └── populates all tabs (read-only until edit mode)
    │
    ├──► ThermalView.highlight_roi(roi_id)
    │       └── disp_region(region) with selection color
    │       └── (does NOT create Drawing Object)
    │
    └──► MainWindow status bar update
```

## 2. User Creates ROI

```
User clicks "Create Rectangle1" tool
    │
    ▼
ROIToolbar
    │  emits: create_roi_requested(shape_type)
    ▼
ROISignalBus.create_roi_requested    (handled by ROIWorkspace)
    │
    ▼
ROIWorkspace._on_create_roi(shape_type)
    │
    ├──► ROIManager.create_roi(shape_type, acquisition_state)
    │       ├── generates new roi_id
    │       ├── creates ROIConfiguration with default geometry/settings
    │       └── returns config
    │
    ├──► DrawingObjectManager.open_editor(config)
    │       ├── DrawingObjectFactory.create_drawing_object(geometry)
    │       ├── set_appearance(style)
    │       ├── attach_drawing_object_to_window(window_handle, draw_obj)
    │       └── set_drawing_object_callback(draw_obj, "on_drag", ...)
    │
    ├──► RuntimeROIManager.load([config])
    │       └── creates RuntimeROI (INACTIVE, dirty=True)
    │
    ├──► DirtyTracker.mark_created(roi_id)
    │
    └──► ROISignalBus.roi_created(roi_id)
            │
            ├──► ROIListWidget.add_row(roi_id)
            ├──► ROIPropertyPanel.load_roi(roi_id)
            └──► DirtyTracker updates UI (save button enabled)
```

## 3. User Drags ROI (Drawing Object Callback)

```
User drags/resizes Drawing Object
    │
    ▼
HALCON fires on_drag / on_resize callback
    │
    ▼
DrawingObjectManager callback (lightweight)
    │  reads: get_drawing_object_params(draw_obj, param_names)
    │  updates: local geometry copy
    │  emits: geometry_edited(roi_id, new_geometry)
    ▼
ROIWorkspace._on_geometry_edited(roi_id, new_geometry)
    │
    ├──► ROIManager.update_geometry(roi_id, new_geometry)
    │       └── stores in ROIConfiguration
    │
    ├──► RuntimeROIManager.mark_dirty(roi_id)
    │       └── cached HRegion marked for rebuild
    │
    ├──► DirtyTracker.mark_modified(roi_id, ROIDirtyType.GEOMETRY)
    │
    └──► ROISignalBus.roi_geometry_changed(roi_id)
            │
            ├──► ROIListWidget.update_row(roi_id)
            │       └── (shape column may change)
            ├──► ROIPropertyPanel.refresh_geometry(roi_id)
            ├──► ThermalView.redraw_highlight(roi_id)
            └──► RuntimeROIManager.rebuild_dirty_regions()
                    └── regenerates cached HRegion
```

## 4. User Edits Threshold in Property Panel

```
User changes threshold value
    │
    ▼
ROIPropertyPanel (alarm tab)
    │  emits: alarm_changed(roi_id, alarm_settings)
    ▼
ROISignalBus.roi_alarm_changed
    │
    ├──► ROIManager.update_alarm(roi_id, alarm_settings)
    │       └── stores in ROIConfiguration
    │
    ├──► DirtyTracker.mark_modified(roi_id, ROIDirtyType.ALARM)
    │
    └──► ROIPropertyPanel.refresh_alarm(roi_id)
            └── (confirms new value was applied)
```

## 5. User Renames ROI

```
User edits name field in property panel
    │
    ▼
ROIPropertyPanel (general tab)
    │  emits: rename_requested(roi_id, new_name)
    ▼
ROIWorkspace._on_rename(roi_id, new_name)
    │
    ├──► ROIManager.rename_roi(roi_id, new_name)
    │
    ├──► DirtyTracker.mark_modified(roi_id, ROIDirtyType.CONFIGURATION)
    │
    └──► ROISignalBus.roi_renamed(roi_id)
            │
            └──► ROIListWidget.update_row(roi_id)
```

## 6. User Deletes ROI

```
User clicks Delete (or presses Delete key)
    │
    ▼
ROIListWidget / ROIToolbar
    │  emits: delete_requested(roi_id)
    ▼
ROIWorkspace._on_delete_roi(roi_id)
    │
    ├──► DrawingObjectManager.close_editor(roi_id)
    │       └── detach + clear_drawing_object
    │
    ├──► ROIManager.remove_roi(roi_id)
    │
    ├──► RuntimeROIManager.unload()  # for this ROI
    │       └── release HALCON region resources
    │
    ├──► ROISelectionManager.clear_selection()
    │
    ├──► DirtyTracker.mark_deleted(roi_id)
    │
    └──► ROISignalBus.roi_deleted(roi_id)
            │
            ├──► ROIListWidget.remove_row(roi_id)
            ├──► ROIPropertyPanel.clear()
            └──► ThermalView.remove_highlight(roi_id)
```

## 7. User Duplicates ROI

```
User clicks Duplicate
    │
    ▼
ROIToolbar / context menu
    │  emits: duplicate_requested(roi_id)
    ▼
ROIWorkspace._on_duplicate_roi(roi_id)
    │
    ├──► ROIManager.duplicate_roi(roi_id)
    │       ├── deep-copies ROIConfiguration
    │       ├── generates new roi_id
    │       └── returns new config
    │
    ├──► RuntimeROIManager.load([new_config])
    │
    ├──► DirtyTracker.mark_created(new_roi_id)
    │
    └──► ROISignalBus.roi_duplicated(new_id, original_id)
            │
            ├──► ROIListWidget.add_row(new_id)
            └──► ROISelectionManager.select(new_id)
```

## 8. User Switches Camera

```
User clicks different camera tile / selects from list
    │
    ▼
MainWindow / CameraTile
    │  emits: camera_changed(camera_id)
    ▼
ROISignalBus.camera_changed
    │
    ├──► DrawingObjectManager.close_all()
    │       └── detach + clear every Drawing Object
    │
    ├──► ROISelectionManager.clear_selection()
    │
    ├──► ROIWorkspace._switch_camera(camera_id)
    │       ├── ROIManager.load_state(new_acquisition_state)
    │       ├── RuntimeROIManager.load(configurations)
    │       └── DirtyTracker.set_baseline(configurations)
    │
    └──► ROISignalBus.position_changed(camera_id, position_id)
            │
            ├──► ROIListWidget.rebuild(configurations)
            ├──► ROIPropertyPanel.clear()
            └──► ThermalView.clear_overlays()
```

## 9. User Switches Position

```
Operator changes position (PTZ preset, dropdown, etc.)
    │
    ▼
CameraControlPanel / position selector
    │  emits: position_changed(camera_id, position_id)
    ▼
ROISignalBus.position_changed
    │
    └──► (same flow as camera switch, but camera_id stays same)
            ├──► DrawingObjectManager.close_all()
            ├──► ROISelectionManager.clear_selection()
            ├──► ROIManager.load_state(new_acquisition_state)
            ├──► RuntimeROIManager.load(configurations)
            ├──► DirtyTracker.set_baseline(configurations)
            ├──► ROIListWidget.rebuild(configurations)
            ├──► ROIPropertyPanel.clear()
            └──► ThermalView.clear_overlays()
```

## 10. User Enters Edit Mode (Double-Click ROI)

```
User double-clicks ROI in list OR presses Enter with ROI selected
    │
    ▼
ROIListWidget
    │  emits: edit_requested(roi_id)
    ▼
ROIWorkspace._on_edit_start(roi_id)
    │
    ├──► DrawingObjectManager.open_editor(config)
    │       ├── create_drawing_object(geometry)
    │       ├── set_appearance(style)
    │       ├── attach_drawing_object_to_window(window, draw_obj)
    │       ├── set_callback(draw_obj, "on_drag", callback)
    │       ├── set_callback(draw_obj, "on_resize", callback)
    │       └── set_callback(draw_obj, "on_select", callback)
    │
    └──► ROISignalBus.editing_started(roi_id)
            │
            └──► ROIPropertyPanel.enable_editing(roi_id)
```

## 11. User Finishes Editing (Clicks elsewhere / presses Escape)

```
User presses Escape / clicks off ROI / selects different tool
    │
    ▼
ROIWorkspace / keyboard handler
    │  emit: edit_finish_requested(roi_id)
    ▼
ROIWorkspace._on_edit_finish(roi_id)
    │
    ├──► DrawingObjectManager.close_editor(roi_id)
    │       ├── read_geometry()  (final read)
    │       ├── detach_drawing_object_from_window(window, draw_obj)
    │       └── clear_drawing_object(draw_obj)
    │
    ├──► ROIManager.update_geometry(roi_id, final_geometry)
    │
    ├──► RuntimeROIManager.mark_dirty(roi_id)
    ├──► RuntimeROIManager.rebuild_dirty_regions()
    │
    ├──► DirtyTracker.mark_modified(roi_id, ROIDirtyType.GEOMETRY)
    │
    └──► ROISignalBus.editing_finished(roi_id)
            │
            ├──► ROIListWidget.update_row(roi_id)
            ├──► ROIPropertyPanel.refresh_geometry(roi_id)
            └──► ThermalView.redraw_highlight(roi_id)
                    └── (uses cached HRegion, NOT Drawing Object)
```

## 12. Pipeline Updates ROI Statistics

```
Processing Pipeline (background thread)
    │
    ▼
ROIProcessor.process_frame()
    │
    ▼
RuntimeROIManager.refresh_statistics(roi_id, stats)
    │
    ▼
AlarmManager.evaluate(roi_id, stats)
    │
    ▼
ROIWorkspace receives update (via callback/event)
    │  emit: roi_statistics_updated(roi_id)
    │  emit: roi_alarm_state_changed(roi_id, alarm_state)
    ▼
ROISignalBus
    ├──► ROIListWidget.update_alarm_state(roi_id, alarm_state)
    ├──► ROIListWidget.update_temperature(roi_id, stats.mean)
    └──► ThermalView.update_alarm_highlight(roi_id, alarm_state)
```

## 13. User Saves

```
User clicks Save button
    │
    ▼
ROIToolbar
    │  emits: save_requested()
    ▼
ROIWorkspace._on_save()
    │
    ├──► DrawingObjectManager.close_all()
    │       └── (ensure clean state before saving)
    │
    ├──► ROIManager.save_all()
    │       └── delegates to JSONROIRepository
    │
    └──► DirtyTracker.reset()
            │
            └──► ROISignalBus.dirty_state_changed(False)
```

---

# Architecture Summary

```
                         ┌──────────────────────┐
                         │    MainWindow        │
                         │  (layout container)  │
                         └───────┬──────────────┘
                                 │ owns
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
     ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
     │  ROIWorkspace │  │ ROIListWidget │  │  ThermalView  │
     │  (coordinator)│  │  (model/view) │  │ (HALCON win)  │
     └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
             │                  │                   │
             ▼                  ▼                   ▼
     ┌─────────────────────────────────────────────────────┐
     │                   ROISignalBus                      │
     │          (all communication flows through)          │
     └────┬────────┬────────┬────────┬────────┬────────┬───┘
          │        │        │        │        │        │
          ▼        ▼        ▼        ▼        ▼        ▼
    ┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐┌────────┐
    │  ROI   ││Drawing ││Runtime ││ Alarm  ││  ROI   ││ Dirty  │
    │Manager ││Object  ││ROI     ││Manager ││Selection││Tracker│
    │        ││Manager ││Manager ││        ││Manager ││        │
    └────────┘└────────┘└────────┘└────────┘└────────┘└────────┘
```

# Key Rules

1. **Widgets emit signals.** They never call managers directly.
2. **Managers own behavior.** They never reference widgets.
3. **Signal bus relays.** It has no business logic — only signal definitions.
4. **Workspace coordinates.** `ROIWorkspace` connects signal bus to managers. It is thin — it translates signals into manager calls and back.
5. **Drawing Objects are temporary.** They exist only between `editing_started` and `editing_finished`. Never outside that window.
6. **Property Panel is read-only until edit mode.** It displays data but only emits change signals when the user finishes editing (on focus lost or Enter).
7. **Selection is centralized.** `ROISelectionManager` is the single source of truth for what is selected.
8. **Dirty state is typed.** `ROIDirtyType` distinguishes GEOMETRY, ALARM, APPEARANCE, RECORDING, METADATA, CONFIGURATION.
9. **Every edit is a command.** Even without undo, `CreateROICommand`, `RenameROICommand`, etc. wrap each operation.
10. **GUI thread only.** All signals and slots execute on the Qt event loop. Pipeline updates arrive via queued signals from background threads.

---

*End of GUI_Event_Flow.md*
