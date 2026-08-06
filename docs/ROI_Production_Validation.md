# ROI Production Validation — Test Matrix

The automated harness (`python -m tests.validation`) covers the measurable parts of ROI
engine production validation. This document is the operator checklist for the parts of the
matrix that require a live camera or a human operator.

## Automated scenarios (harness)

Run any with `python -m tests.validation --scenario <name>`.

| Scenario | What it verifies | Pass condition |
|---|---|---|
| `soak` | Long-duration stability + memory leaks | 1000+ frames; memory slope < 100 MB/h; 0 exceptions/HALCON errors |
| `dual_validation` | Engine vs legacy statistics | 1e-6 tolerance on all fields, hotspot ≤ 16 px |
| `position_switch` | Repeated position switching | No stale cache; store generation advances; stats reproduce |
| `camera_switch` | Camera switching, engine pool reuse | Memory stable; engine reused; correct stats after return |
| `roi_editing` | Full edit matrix (create/delete/duplicate/move/hide/show/enable/rename/alarm) | Edit reaches engine on next frame; disabled ROIs leave processing; visibility is GUI-only |
| `high_count` | 100/250/500/1000/1600 ROIs | Statistics valid; statistics-handler time small; GUI unblocked |
| `error_recovery` | Disconnect/reconnect/reload robustness | Statistics recover without corrupted store |

## Manual operator checklist (camera mode, Object 7)

The harness measures the statistics-handler time, but these GUI behaviors require a human
operator with a connected camera:

1. **Cursor temperature**
   - Mouse over the live image in the Observer window.
   - The temperature readout under/at the cursor must update within one frame (~100 ms) and
     match the displayed color scale at that point.
   - Tolerance: ±1 °C in flat regions; region edges may blend over a few pixels.
2. **Editing responsiveness**
   - In the Calibration window with 500+ configured ROIs, create, move, and delete a ROI.
   - The ROI outline must track the mouse without perceptible lag (> 30 FPS feel), and the
     ROI must not leave stale artifacts on the next rendered frames.
   - Enable/disable and show/hide toggles must take effect on the next processed frame.
3. **Alarm feedback (if alarms are configured)**
   - Crossing an alarm threshold must outline the ROI in red within one frame and show the
     alarm in the alarm list.
4. **Recording indicator** — the record button and status-bar state must reflect the actual
   recording state (image/video) without blocking the acquisition thread.
5. **Palette / overlay changes** — switching the thermal palette or toggling ROI overlays must
   never modify the raw thermal data and must redraw instantly.

## Acceptance gate

A scenario is green only if its PASS verdict is reported. Manual items are green only when an
operator confirms them with a connected TV46L camera. Hardware-less runs mark camera-only
items as Not Executed and do not claim success.