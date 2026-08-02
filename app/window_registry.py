"""
window_registry.py

Central window registry and navigation.

The Application is the single owner of every window.
Windows never construct or manipulate other windows.
All window transitions happen through the registry.

Future windows (Settings, Diagnostics, Logs, ROI Database,
Recipe Manager, System Health) are added by registering a
factory - no navigation logic changes.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Iterator

from PyQt5.QtWidgets import QWidget

from utilities import logger


class WindowID(Enum):
    """Unique identifiers for every window type."""

    MAIN = "main"
    CALIBRATION = "calibration"
    OBSERVATION = "observation"
    CAMERA_DETAIL = "camera_detail"


Factory = Callable[..., QWidget]
LifecycleHook = Callable[[QWidget], None]


def _is_valid(window: QWidget) -> bool:
    """Return True if the wrapped C++ object still exists."""
    try:
        window.isVisible()
        return True
    except RuntimeError:
        return False


class WindowRegistry:
    """
    Single owner of every window in the application.

    Singleton windows (MAIN, CALIBRATION, OBSERVATION) are keyed
    by WindowID only. Instance windows (CAMERA_DETAIL) are keyed
    by (WindowID, instance_key) so each camera has exactly one
    detail window.

    Lifecycle:
        open()  -> create (if needed) -> show -> raise -> activate
        close() -> lifecycle hook -> close -> destroy -> forget
    """

    def __init__(self) -> None:
        self._factories: dict[WindowID, Factory] = {}
        self._on_open: dict[WindowID, LifecycleHook] = {}
        self._on_close: dict[WindowID, LifecycleHook] = {}
        self._windows: dict[tuple[WindowID, str | None], QWidget] = {}

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------

    def register(
        self,
        window_id: WindowID,
        factory: Factory,
        on_open: LifecycleHook | None = None,
        on_close: LifecycleHook | None = None,
    ) -> None:
        """
        Register a window factory.

        on_open is called after the window is shown.
        on_close is called before the window is closed.
        """
        if window_id in self._factories:
            raise ValueError(f"Window already registered: {window_id}")
        self._factories[window_id] = factory
        self._on_open[window_id] = on_open
        self._on_close[window_id] = on_close

    def is_registered(self, window_id: WindowID) -> bool:
        return window_id in self._factories

    # ---------------------------------------------------------
    # Lookup
    # ---------------------------------------------------------

    @staticmethod
    def _key(window_id: WindowID, instance_key: str | None) -> tuple[WindowID, str | None]:
        return (window_id, instance_key)

    def get(self, window_id: WindowID, instance_key: str | None = None) -> QWidget | None:
        """Return the window if it exists and is still alive."""
        window = self._windows.get(self._key(window_id, instance_key))
        if window is None:
            return None
        if not _is_valid(window):
            self._forget(window_id, instance_key)
            return None
        return window

    def is_open(self, window_id: WindowID, instance_key: str | None = None) -> bool:
        return self.get(window_id, instance_key) is not None

    def instances(self, window_id: WindowID) -> list[QWidget]:
        """Return every live window of a given type."""
        result = []
        for (wid, _key), window in list(self._windows.items()):
            if wid == window_id and _is_valid(window):
                result.append(window)
        return result

    def iter_windows(self) -> Iterator[QWidget]:
        """Iterate over every live window."""
        for (wid, _key), window in list(self._windows.items()):
            if _is_valid(window):
                yield window

    # ---------------------------------------------------------
    # Navigation
    # ---------------------------------------------------------

    def open(
        self,
        window_id: WindowID,
        instance_key: str | None = None,
        **factory_kwargs,
    ) -> QWidget:
        """
        Open a window.

        Creates the window if it does not exist, then shows,
        raises and activates it. Reopening focuses the existing
        window.
        """
        window = self.get(window_id, instance_key)
        if window is None:
            window = self._create(window_id, instance_key, **factory_kwargs)

        window.show()
        window.raise_()
        window.activateWindow()

        hook = self._on_open.get(window_id)
        if hook is not None:
            self._call_hook(hook, window)
        return window

    def close(self, window_id: WindowID, instance_key: str | None = None) -> None:
        """
        Close a window and forget it.

        Safe to call for windows that are not open.
        """
        window = self._windows.pop(self._key(window_id, instance_key), None)
        if window is None or not _is_valid(window):
            return

        hook = self._on_close.get(window_id)
        if hook is not None:
            self._call_hook(hook, window)

        try:
            window.close()
        except RuntimeError:
            pass

    def close_all(self) -> None:
        """Close and forget every window."""
        for window_id, _key in list(self._windows):
            self.close(window_id, _key)

    # ---------------------------------------------------------
    # Internal
    # ---------------------------------------------------------

    def _create(
        self,
        window_id: WindowID,
        instance_key: str | None,
        **factory_kwargs,
    ) -> QWidget:
        factory = self._factories.get(window_id)
        if factory is None:
            raise ValueError(f"No factory registered for window: {window_id}")
        try:
            window = factory(**factory_kwargs)
        except TypeError:
            logger.exception(f"Window factory rejected arguments for {window_id}")
            raise

        key = self._key(window_id, instance_key)
        self._windows[key] = window

        # The handler captures the dict directly: during teardown GC
        # the registry's own attributes may already be cleared while
        # the destroyed signal still fires.
        def _on_destroyed(
            *_args,
            windows=self._windows,
            registry_key=key,
        ) -> None:
            windows.pop(registry_key, None)

        window.destroyed.connect(_on_destroyed)
        return window

    def _forget(self, window_id: WindowID, instance_key: str | None) -> None:
        self._windows.pop(self._key(window_id, instance_key), None)

    @staticmethod
    def _call_hook(hook: LifecycleHook, window: QWidget) -> None:
        try:
            hook(window)
        except RuntimeError:
            # Window may already be destroyed (e.g. user closed it).
            pass
