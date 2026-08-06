# ROI Engine — Dual Validation (engine vs legacy)

Scenario: `dual_validation`
Generated: 2026-08-06T10:51:18

Runs the legacy manager in parallel with the engine for 1000 frames and compares statistics at 1e-6 tolerance (hotspot within 16 px). Mismatches are logged once per ROI per kind until recovery.

## Verdict

**PASS** — zero mismatches.

## Details

- Frames: 1000
- ROIs: 1600
- Tolerance: 1e-6

## Mismatch summary

- Warnings: 0
- Affected ROIs: 0
- Per-ROI fields: none

## Note

The dual-validation flag `ROI_ENGINE_DUAL_VALIDATION` remains OFF by default; this run does not change production behavior.
