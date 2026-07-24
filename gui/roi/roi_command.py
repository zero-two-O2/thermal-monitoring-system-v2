from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ROICommand:
    execute: Callable[[], Any]
    undo: Callable[[], Any] | None = None
    description: str = ""
    _executed: bool = field(default=False, init=False, repr=False)

    def run(self) -> Any:
        result = self.execute()
        self._executed = True
        return result
