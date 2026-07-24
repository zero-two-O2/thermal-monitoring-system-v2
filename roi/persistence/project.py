from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class CameraReference:
    camera_id: str
    name: str = ""
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Project:
    name: str
    description: str = ""
    author: str = ""
    application_version: str = "1.0.0"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    cameras: list[CameraReference] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
