"""
recording_settings.py

ROI recording configuration for the Thermal Monitoring System.

Defines recording behavior triggered by this ROI.

This class contains ONLY recording configuration data.
No recording logic, no HALCON, no GUI code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ROIRecordingSettings:
    """
    Recording behavior for one ROI.

    Controls whether alarm events or manual triggers from
    this ROI start a recording session.

    Responsibilities
    ----------------
    - Store recording enable flag.
    - Store pre-trigger and post-trigger durations.
    - Store image and video save preferences.

    Must never:
    - Control the recorder directly.
    - Reference ROI geometry or statistics.
    - Contain HALCON or GUI code.
    """

    enabled: bool = False

    duration_seconds: int = 20

    pre_trigger_seconds: int = 0

    post_trigger_seconds: int = 20

    save_images: bool = False

    save_video: bool = True
