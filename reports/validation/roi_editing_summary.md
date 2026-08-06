# ROI Engine — ROI Editing Matrix

Scenario: `roi_editing`
Generated: 2026-08-06T10:51:33

Drives every edit operation through the same signal bus the calibration window uses and checks the engine reacts on the next frame (statistics track moved geometry; disabled ROIs leave processing; visibility stays GUI-only).

## Verdict

**PASS** — failed operations: none.

## Operations

| op | ok | note |
| --- | --- | --- |
| create | True | id=roi_53bc61ac |
| move_off_spot | True | max 47.52 -> 22.21 |
| move_onto_spot | True | max=91.44 |
| resize | True | max=94.75 |
| rename | True |  |
| duplicate | True | id=roi_ce3be557 |
| hide | True | visible=False processed=True |
| show | True | visible=True |
| disable | True | enabled=False processed=False |
| enable | True | enabled=True max=94.79 |
| delete | True |  |
