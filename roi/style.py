"""
style.py

ROI display style for the Thermal Monitoring System.

Defines how an ROI is rendered in the GUI.

This class contains ONLY display configuration data.
No HALCON, no GUI code, no processing logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ROIStyle:
    """
    Display style configuration for one ROI.

    Controls how the ROI outline and label appear in the
    camera view.

    Responsibilities
    ----------------
    - Store visual display parameters.
    - Provide defaults for the most common style.

    Must never:
    - Contain HALCON Drawing Object references.
    - Contain GUI widget references.
    - Control ROI geometry.
    - Control alarm or recording behavior.
    - Reference any window or display handle.
    """

    color: str = "#FFFF00"

    selected_color: str = "#00FF00"

    alarm_color: str = "#FF0000"

    line_width: int = 2

    label_visible: bool = True

    label_size: int = 10
