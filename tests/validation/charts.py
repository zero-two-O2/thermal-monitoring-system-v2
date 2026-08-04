"""
charts.py

Minimal line-chart rendering using only numpy + OpenCV.

matplotlib and Pillow are not available in this environment, so reports
embed charts generated with cv2. Each chart is a PNG with axes, a
polyline, and min/max annotations.
"""

from __future__ import annotations

import numpy as np
import cv2

WIDTH = 960
HEIGHT = 360
MARGIN_L = 60
MARGIN_R = 20
MARGIN_T = 24
MARGIN_B = 34
BG = (30, 30, 30)
GRID = (60, 60, 60)
LINE = (220, 140, 60)
TEXT = (220, 220, 220)


def _plot_area():
    """Return the pixel rectangle (x0, y0, x1, y1) used for the plot."""
    return (
        MARGIN_L,
        MARGIN_T,
        WIDTH - MARGIN_R,
        HEIGHT - MARGIN_B,
    )


def _scale(points: list[float], y_min: float, y_max: float) -> list[tuple[int, int]]:
    """Map (x-index, value) pairs into pixel coordinates."""
    x0, y0, x1, y1 = _plot_area()
    n = max(1, len(points) - 1)
    span = y_max - y_min
    span = span if span > 0.0 else 1.0
    out = []
    for i, v in enumerate(points):
        px = int(x0 + (i / n) * (x1 - x0))
        py = int(y1 - (v - y_min) / span * (y1 - y0))
        out.append((px, py))
    return out


def line_chart(
    path: str,
    values: list[float],
    title: str,
    ylabel: str,
    xlabel: str = "elapsed seconds",
) -> None:
    """Render a line chart of `values` to `path` as PNG.

    Pure-Python/cv2 renderer; matplotlib unavailable in this environment.
    """
    if not values:
        raise ValueError("line_chart requires at least one value")

    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    canvas = np.full((HEIGHT, WIDTH, 3), BG, dtype=np.uint8)
    x0, y0, x1, y1 = _plot_area()
    cv2.rectangle(canvas, (x0, y0), (x1, y1), GRID, 1)

    v_min = float(min(values))
    v_max = float(max(values))
    span = v_max - v_min
    if span > 0.0:
        step = span / 4.0
        for k in range(5):
            gy = int(y1 - (k / 4.0) * (y1 - y0))
            cv2.line(canvas, (x0, gy), (x1, gy), GRID, 1)
            val = v_min + step * k
            label = f"{val:.2f}"
            (tw, th), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
            )
            cv2.putText(
                canvas, label, (x0 - tw - 6, gy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, TEXT, 1, cv2.LINE_AA,
            )

    pts = _scale(values, v_min, v_max)
    for a, b in zip(pts, pts[1:]):
        cv2.line(canvas, a, b, LINE, 1, cv2.LINE_AA)
    for p in pts:
        cv2.circle(canvas, p, 1, LINE, -1)

    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.putText(
        canvas, title, ((WIDTH - tw) // 2, 16),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT, 1, cv2.LINE_AA,
    )
    (tw, _), _ = cv2.getTextSize(ylabel, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.putText(
        canvas, ylabel, (8, (HEIGHT + tw) // 2),
        cv2.FONT_HERSHEY_SIMPLEX, 0.45, TEXT, 1, cv2.LINE_AA,
    )
    (tw, _), _ = cv2.getTextSize(xlabel, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.putText(
        canvas, xlabel, ((WIDTH - tw) // 2, HEIGHT - 8),
        cv2.FONT_HERSHEY_SIMPLEX, 0.45, TEXT, 1, cv2.LINE_AA,
    )

    cv2.imwrite(path, canvas)


def memory_graph(path: str, samples_mb: list[float]) -> None:
    """Render a process memory graph (MB) with a start/end annotation."""
    line_chart(path, samples_mb, "Process Memory (RSS, MB)", "MB")


def fps_graph(path: str, fps_samples: list[float]) -> None:
    """Render an FPS-over-time graph."""
    line_chart(path, fps_samples, "Frames Per Second", "FPS")
