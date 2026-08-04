"""
tests.validation entry point.

Usage:
    python -m tests.validation --scenario soak --camera cam_HB25100002 --duration-s 1800
    python -m tests.validation --scenario dual_validation --frames 1000
    python -m tests.validation --scenario all            # everything (short form)

Each scenario writes its reports under --out (default reports/validation).
See docs/ROI_Production_Validation.md for the test matrix.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow running as `python -m tests.validation` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.validation import __version__  # noqa: E402
from tests.validation.scenarios import (  # noqa: E402
    run_camera_switch,
    run_dual_validation,
    run_error_recovery,
    run_high_count,
    run_position_switch,
    run_roi_editing,
    run_soak,
)

SCENARIOS: dict[str, Any] = {
    "soak": run_soak,
    "dual_validation": run_dual_validation,
    "position_switch": run_position_switch,
    "camera_switch": run_camera_switch,
    "roi_editing": run_roi_editing,
    "high_count": run_high_count,
    "error_recovery": run_error_recovery,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tests.validation",
        description="ROI Engine production validation harness (Phase 4).",
    )
    parser.add_argument(
        "--scenario",
        choices=[*SCENARIOS, "all"],
        default="all",
        help="Scenario to run (default: all short scenarios)",
    )
    parser.add_argument(
        "--camera",
        default="cam_harness",
        help=(
            "Rig camera id (cam_<serial>) for camera mode; "
            "'sim' forces synthetic frames (default: cam_harness, "
            "falls back to synthetic when unavailable)"
        ),
    )
    parser.add_argument(
        "--out",
        default="reports/validation",
        help="Directory for report artifacts (default: reports/validation)",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=300.0,
        help="Soak duration in seconds (camera recipe: 1800 for 30 min)",
    )
    parser.add_argument(
        "--warmup-s",
        type=float,
        default=30.0,
        help="Soak warmup excluded from FPS statistics (capped at 20%% of run)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=1000,
        help="Frames for dual validation (minimum 1000)",
    )
    parser.add_argument(
        "--rois",
        type=int,
        default=1600,
        help="Max ROIs (soak/high_count/dual_validation)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=100,
        help="Position-switch cycles (5 switches per cycle)",
    )
    return parser


def _run_one(name: str, fn: Any, args: argparse.Namespace) -> dict[str, Any]:
    print(f"=== scenario: {name} ===")
    result = fn(args)
    print(json.dumps(result, indent=2, default=str))
    print(f"=== {name} verdict: {result.get('verdict', '?')} ===")
    return result


def main() -> int:
    """Run the requested scenario(s) and print the summary."""
    args = _build_parser().parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: dict[str, Any] = {"generated": datetime.now().isoformat(timespec="seconds")}
    for name in names:
        try:
            results[name] = _run_one(name, SCENARIOS[name], args)
        except Exception as exc:
            results[name] = {"verdict": "ERROR", "error": str(exc)}
            import traceback

            traceback.print_exc()

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    print(f"Summary written to {summary_path}")

    failures = [
        name for name, res in results.items()
        if name != "generated"
        and res.get("verdict") not in ("PASS", "SKIPPED")
    ]
    skipped = [
        name for name, res in results.items()
        if name != "generated" and res.get("verdict") == "SKIPPED"
    ]
    if skipped:
        print(f"SKIPPED (no camera): {', '.join(skipped)}")
    print(
        f"Final: {'ALL PASS' if not failures else 'FAILED: ' + ', '.join(failures)}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
