# ROI Engine — High ROI Count

Scenario: `high_count`
Generated: 2026-08-06T10:51:45

Runs 100/250/500/1000/1600 ROIs against synthetic frames. Target: 9 FPS sustained in camera mode with responsive GUI.

## Verdict

**PASS** — failed steps: none.

## Mode

- Synthetic frames
- Target: 9 FPS

## Per step

| rois | frames | elapsed_s | fps | engine_memory_mb | gui_ok |
| --- | --- | --- | --- | --- | --- |
| 100 | 30 | 0.75 | 39.998 | 0.09 | True |
| 250 | 30 | 0.856 | 35.034 | 0.112 | True |
| 500 | 30 | 1.567 | 19.147 | 0.144 | True |
| 1000 | 30 | 2.65 | 11.319 | 0.217 | True |
| 1600 | 30 | 3.884 | 7.723 | 0.299 | True |

## Note

Cursor temperature and editing responsiveness are manual GUI checks listed in docs/ROI_Production_Validation.md.
