# Window Architecture

## Goal

Every window in the application is owned and navigated by exactly one object:
the `Application` (via the `WindowRegistry`).

No window constructs, shows, closes, or tracks another window. Windows only
emit **requests** (Qt signals). `Application` translates requests into
registry operations.

```
MainWindow ──signals──► Application ──open/close──► WindowRegistry ──create──► Windows
                                                          │
                                                          └── destroyed ──forget──►
```

## Window Hierarchy

```
Main
 ├── Calibration
 ├── Observation
 │    └── Camera Detail  (one per camera)
 └── (dev) Camera Detail (hidden View menu item, Ctrl+D)
```

Navigation is strictly hierarchical and centralized:

- `MainWindow` emits `calibration_requested`, `observation_requested`,
  `camera_detail_dev_requested` and `cameras_disconnected(list)`.
- `ObserverWindow` emits `camera_detail_requested(camera_id)`.
- No window emits a signal that requests a sibling or parent window.

## WindowRegistry (`app/window_registry.py`)

Single-owner registry of all top-level windows.

- **WindowID** enum: `MAIN`, `CALIBRATION`, `OBSERVATION`, `CAMERA_DETAIL`.
- **Keys**: `(WindowID, instance_key)`. `instance_key` is `None` for
  single-instance windows and the camera id for `CAMERA_DETAIL` (one detail
  window per camera).
- **register(id, factory, on_open, on_close)**: `factory` creates the window,
  `on_open`/`on_close` hooks run after creation / before close
  (polling lifecycle, list refresh, wiring).
- **open(...)**: creates the window if missing, otherwise reuses the existing
  instance (show / raise / activate). Creating a camera-detail window
  requires `camera_id` and `camera_name` factory arguments.
- **close / close_all**: run `on_close` and destroy windows.
- **External close safety**: windows use `Qt.WA_DeleteOnClose`. When the user
  closes a window through the title bar, the `destroyed` signal fires and the
  registry forgets the entry automatically (no stale instance).
- **get / is_open / instances / iter_windows**: read-only queries.
- Registering or opening an unregistered id raises `ValueError`.

## Application (`app/application.py`)

- Owns: `QApplication`, `ApplicationController`, `WindowRegistry`.
- Navigation facade: `open_main()`, `open_calibration()`, `open_observation()`,
  `open_camera_detail(camera_id)`, `close_camera_detail(camera_id)`,
  `close_all_windows()`.
- Window modules are imported lazily inside factories, so starting the
  application never depends on optional modules (e.g. the ROI/HALCON stack).
- `initialize()` runs camera discovery; `shutdown()` closes all windows and
  shuts down the controller.
- Dev mode: `DEV_CAMERA_ID = "dev_cam_1"`. The hidden View menu item
  "Camera Detail (Dev)" (Ctrl+D) opens a camera-detail window without a
  connected camera — useful when no hardware is available.

## Lifecycle / Polling

Polling is bound to the window lifecycle through registry hooks:

| Window          | on_open                                  | on_close        |
|-----------------|------------------------------------------|-----------------|
| MAIN            | wire navigation signals (idempotent)     | —               |
| CALIBRATION     | refresh_camera_list + start_polling      | stop_polling    |
| OBSERVATION     | populate tiles + start_polling           | stop_polling    |
| CAMERA_DETAIL   | start_polling                            | stop_polling    |

Closing a window therefore always stops its polling; reopening creates a
fresh, correctly initialized window.

## No-Camera (Development) Mode

The system must be fully navigable without connected cameras:

- All windows open normally; navigation is never disabled.
- Camera-dependent controls are disabled, not hidden.
- Placeholder text ("No Camera Connected") is shown in thermal views and
  camera tiles.
- `CalibrationWindow` shows a "No Camera Connected" combo entry (no camera
  selected) and disables the ROI toolbar.
- `CameraDetailWindow` polls silently when the camera is not registered.
- Disconnecting cameras closes the corresponding detail windows.

## Extending

To add a new window:

1. Add a `WindowID` member in `app/window_registry.py`.
2. Register it in `Application._register_windows()` with factory + hooks.
3. Add a navigation method on `Application`.
4. Emit a request signal from the requesting window; never construct the
   target window directly.

## Testing

`tests/test_window_architecture.py` covers registry semantics, no-camera mode
and centralized navigation (Qt offscreen). Tests that construct ROI-dependent
windows are skipped when `gui.roi` cannot be imported (e.g. missing/expired
HALCON license); on a healthy machine they run normally.
