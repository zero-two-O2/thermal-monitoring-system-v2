"""
report.py

Persist validation results: raw metrics as JSON, per-second samples as CSV,
charts as PNG, and a human-readable Markdown summary.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.validation import charts
from tests.validation.metrics import Metrics, MetricsAnalyzer


class ValidationReport:
    """Collects scenario results and writes the deliverable files."""

    def __init__(self, out_dir: str | os.PathLike[str], scenario: str) -> None:
        """Create a report targeting `out_dir` for `scenario`."""
        self._out = Path(out_dir)
        self._out.mkdir(parents=True, exist_ok=True)
        self._scenario = scenario
        self._results: dict[str, Any] = {}

    @property
    def out_dir(self) -> Path:
        """Directory where the report files are written."""
        return self._out

    def record(self, section: str, data: Any) -> None:
        """Store a result section (replaces previous value)."""
        self._results[section] = data

    def write_metrics(self, metrics: Metrics) -> Path:
        """Write metrics JSON + CSV; returns the JSON path."""
        analyzer = MetricsAnalyzer(metrics)
        payload = {
            "scenario": self._scenario,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(metrics.duration_s(), 3),
            "counts": analyzer.counts(),
            "fps": analyzer.fps_stats(),
            "pipeline_ms": analyzer.pipeline_stats(),
            "memory": {
                "slope_mb_per_hour": analyzer.memory_slope()["mb_per_hour"],
                "delta_mb": analyzer.memory_slope()["mb_total"],
                "range": analyzer.memory_range(),
            },
        }
        json_path = self._out / f"{self._scenario}_metrics.json"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        csv_path = self._out / f"{self._scenario}_intervals.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "t", "fps", "rss_mb", "cpu_percent",
                    "active_rois", "engine_memory_mb", "store_memory_mb",
                ]
            )
            for s in metrics.intervals:
                writer.writerow(
                    [
                        round(s.t, 3), round(s.fps, 3), round(s.rss_mb, 3),
                        round(s.cpu_percent, 3), s.active_rois,
                        round(s.engine_memory_mb, 3), round(s.store_memory_mb, 3),
                    ]
                )
        return json_path

    def write_charts(self, metrics: Metrics) -> list[Path]:
        """Write PNG charts for memory and FPS; returns created paths."""
        memory = [s.rss_mb for s in metrics.intervals]
        fps = [s.fps for s in metrics.intervals]
        paths = []
        if memory:
            p = self._out / f"{self._scenario}_memory.png"
            charts.memory_graph(str(p), memory)
            paths.append(p)
        if fps:
            p = self._out / f"{self._scenario}_fps.png"
            charts.fps_graph(str(p), fps)
            paths.append(p)
        return paths

    def write_markdown(
        self, title: str, intro: str, sections: list[tuple[str, str]]
    ) -> Path:
        """Write the Markdown summary for this scenario run."""
        md = self._out / f"{self._scenario}_summary.md"
        lines = [
            f"# {title}",
            "",
            f"Scenario: `{self._scenario}`",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            intro.strip(),
            "",
        ]
        for heading, body in sections:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(body.strip())
            lines.append("")
        md.write_text("\n".join(lines), encoding="utf-8")
        return md

    def to_json(self) -> dict[str, Any]:
        """The accumulated result sections (used by the final report)."""
        return dict(self._results)
