# ROI Engine — Position Switching

Scenario: `position_switch`
Generated: 2026-08-06T10:51:32

Switches through positions 0/1/2/199 repeatedly and verifies the store generation counter advances, the active ROI count matches, and returning to the start position reproduces identical statistics (no stale cache).

## Verdict

**PASS** — errors: none; stale cache: False.

## Details

- Cycles: 100
- Switches: 500
- Sequence: (0, 1, 2, 199, 0)
- ROIs/position: 8

## Generation counter

- Final generation: 501

## Memory slope (tail 50%)

- 5.984 MB/h (delta 0.008 MB)
