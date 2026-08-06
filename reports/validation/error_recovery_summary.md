# ROI Engine — Error Recovery

Scenario: `error_recovery`
Generated: 2026-08-06T10:51:46

Exercises camera disconnect/reconnect (camera mode) or engine recreation (synthetic mode), position reload, and verifies statistics recover without crashes or a corrupted store.

## Verdict

**PASS** — errors: none.

## Mode

Synthetic

## Events

| event | ok |
| --- | --- |
| baseline | True |
| engine_recreated | True |
| position_reload | True |
| statistics_recovered | True |
