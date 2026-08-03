"""
Window architecture tests.

Verifies the WindowRegistry, centralized navigation, window
lifecycle and the no-camera (development) mode.

Runs Qt offscreen - no display required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _process(qapp: QApplication) -> None:
    qapp.processEvents()
    # WA_DeleteOnClose schedules deletion via DeferredDelete events.
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


try:
    import gui.roi  # noqa: F401

    _HALCON_AVAILABLE = True
    _HALCON_REASON = ""
except Exception as exc:
    _HALCON_AVAILABLE = False
    _HALCON_REASON = f"gui.roi import failed: {exc}"

requires_halcon = pytest.mark.skipif(
    not _HALCON_AVAILABLE,
    reason=_HALCON_REASON,
)


def _make_registry():
    from app.window_registry import WindowRegistry, WindowID

    def _make_window(text: str):
        from PyQt5.QtCore import Qt

        window = QLabel(text)
        # Real application windows use WA_DeleteOnClose, so a close()
        # destroys the window and the registry forgets it.
        window.setAttribute(Qt.WA_DeleteOnClose)
        return window

    registry = WindowRegistry()
    registry.register(
        WindowID.MAIN,
        lambda: _make_window("main"),
    )
    registry.register(
        WindowID.CALIBRATION,
        lambda: _make_window("calibration"),
        on_open=lambda w: setattr(w, "_opened", True),
        on_close=lambda w: setattr(w, "_closed", True),
    )
    registry.register(
        WindowID.CAMERA_DETAIL,
        lambda camera_id, camera_name: _make_window(f"{camera_id}:{camera_name}"),
    )
    return registry, WindowID


# ==============================================================
# WindowRegistry
# ==============================================================


class TestWindowRegistry:
    def test_register_and_open_creates_window(self, qapp):
        registry, WindowID = _make_registry()
        window = registry.open(WindowID.MAIN)
        assert window is not None
        assert registry.is_open(WindowID.MAIN)
        assert registry.get(WindowID.MAIN) is window
        window.close()

    def test_open_reuses_existing_window(self, qapp):
        registry, WindowID = _make_registry()
        first = registry.open(WindowID.MAIN)
        second = registry.open(WindowID.MAIN)
        assert first is second
        registry.close_all()

    def test_open_calls_on_open_hook(self, qapp):
        registry, WindowID = _make_registry()
        window = registry.open(WindowID.CALIBRATION)
        assert getattr(window, "_opened", False) is True
        registry.close_all()

    def test_close_calls_on_close_hook_and_forgets(self, qapp):
        registry, WindowID = _make_registry()
        window = registry.open(WindowID.CALIBRATION)
        registry.close(WindowID.CALIBRATION)
        assert getattr(window, "_closed", False) is True
        assert not registry.is_open(WindowID.CALIBRATION)

    def test_close_unopened_window_is_safe(self, qapp):
        registry, WindowID = _make_registry()
        registry.close(WindowID.CALIBRATION)

    def test_close_all_closes_everything(self, qapp):
        registry, WindowID = _make_registry()
        registry.open(WindowID.MAIN)
        registry.open(WindowID.CALIBRATION)
        registry.close_all()
        assert not registry.is_open(WindowID.MAIN)
        assert not registry.is_open(WindowID.CALIBRATION)

    def test_external_close_forgets_window(self, qapp):
        registry, WindowID = _make_registry()
        window = registry.open(WindowID.CALIBRATION)
        window.close()  # WA_DeleteOnClose-style destruction
        _process(qapp)
        assert not registry.is_open(WindowID.CALIBRATION)

    def test_camera_detail_one_window_per_camera(self, qapp):
        registry, WindowID = _make_registry()
        a1 = registry.open(WindowID.CAMERA_DETAIL, instance_key="cam_1",
                           camera_id="cam_1", camera_name="A")
        a2 = registry.open(WindowID.CAMERA_DETAIL, instance_key="cam_1",
                           camera_id="cam_1", camera_name="A")
        b1 = registry.open(WindowID.CAMERA_DETAIL, instance_key="cam_2",
                           camera_id="cam_2", camera_name="B")
        assert a1 is a2
        assert b1 is not a1
        assert len(registry.instances(WindowID.CAMERA_DETAIL)) == 2
        registry.close_all()

    def test_close_camera_detail_by_key(self, qapp):
        registry, WindowID = _make_registry()
        registry.open(WindowID.CAMERA_DETAIL, instance_key="cam_1",
                      camera_id="cam_1", camera_name="A")
        registry.close(WindowID.CAMERA_DETAIL, instance_key="cam_1")
        assert not registry.is_open(WindowID.CAMERA_DETAIL, instance_key="cam_1")

    def test_unregistered_window_raises(self, qapp):
        from app.window_registry import WindowRegistry, WindowID

        registry = WindowRegistry()
        with pytest.raises(ValueError):
            registry.open(WindowID.MAIN)

    def test_duplicate_registration_raises(self, qapp):
        from app.window_registry import WindowRegistry, WindowID

        registry = WindowRegistry()
        registry.register(WindowID.MAIN, lambda: QLabel("main"))
        with pytest.raises(ValueError):
            registry.register(WindowID.MAIN, lambda: QLabel("main"))


# ==============================================================
# No-Camera Mode (development)
# ==============================================================


class TestNoCameraMode:
    def test_main_window_opens_without_cameras(self, qapp):
        from app.application_controller import ApplicationController
        from gui.main_window import MainWindow

        window = MainWindow(ApplicationController())
        assert window.isVisible() is False
        # Navigation buttons must be enabled without any camera.
        assert window._calibration_btn.isEnabled()
        assert window._observation_btn.isEnabled()
        assert window._menu_calibration.isEnabled()
        assert window._menu_observation.isEnabled()
        window.close()

    def test_main_window_emits_navigation_signals(self, qapp):
        from app.application_controller import ApplicationController
        from gui.main_window import MainWindow

        window = MainWindow(ApplicationController())
        received: list[str] = []
        window.calibration_requested.connect(lambda: received.append("cal"))
        window.observation_requested.connect(lambda: received.append("obs"))
        window._on_calibration()
        window._on_observation()
        assert received == ["cal", "obs"]
        window.close()

    @requires_halcon
    def test_calibration_window_opens_without_cameras(self, qapp):
        from app.application_controller import ApplicationController
        from gui.calibration.calibration_window import CalibrationWindow

        window = CalibrationWindow(ApplicationController())
        window.show()
        window.refresh_camera_list()
        # Camera selector remains visible with a placeholder entry.
        assert window._camera_combo.count() == 1
        assert window._camera_combo.itemText(0) == "No Camera Connected"
        assert window._camera_combo.itemData(0) is None
        # Camera-dependent controls are disabled, not hidden.
        assert window._roi_toolbar.isEnabled() is False
        assert window._roi_toolbar.isVisible()
        # Placeholders are displayed.
        assert window._thermal_view._placeholder.isVisible()
        assert window._visible_view._placeholder.isVisible()
        window.close()

    @requires_halcon
    def test_calibration_window_no_camera_selection(self, qapp):
        from app.application_controller import ApplicationController
        from gui.calibration.calibration_window import CalibrationWindow

        window = CalibrationWindow(ApplicationController())
        window.refresh_camera_list()
        window._on_camera_selected(0)  # placeholder entry
        assert window._selected_camera_id is None
        assert window._roi_toolbar.isEnabled() is False
        window.close()

    def test_observation_window_opens_without_cameras(self, qapp):
        from app.application_controller import ApplicationController
        from gui.observer.observer_window import ObserverWindow

        window = ObserverWindow(ApplicationController())
        # All 8 tiles exist and show the placeholder.
        assert len(window._tiles) == 8
        for tile in window._tiles:
            assert "No Camera Connected" in tile._image_label.text()
        window.close()

    @requires_halcon
    def test_camera_detail_window_opens_without_camera(self, qapp):
        from app.application_controller import ApplicationController
        from gui.camera_detail_window import CameraDetailWindow

        window = CameraDetailWindow("dev_cam_1", "dev_cam_1", ApplicationController())
        window.show()
        assert window.isVisible()
        assert window._thermal_view._placeholder.isVisible()
        # Polling without a registered camera must not crash.
        window._poll()
        window.close()

    @requires_halcon
    def test_thermal_view_placeholder_text(self, qapp):
        from gui.roi.thermal_view import PLACEHOLDER_TEXT, ThermalView

        view = ThermalView()
        assert "No Camera Connected" in PLACEHOLDER_TEXT
        assert "Connect a camera from" in PLACEHOLDER_TEXT
        assert view._placeholder.text() == PLACEHOLDER_TEXT
        view.close()


# ==============================================================
# Application Navigation
# ==============================================================


class TestApplicationNavigation:
    def _make_application(self, qapp):
        from app.application import Application

        application = Application()
        return application

    def test_application_opens_main(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        assert application.window is not None
        assert application.registry.is_open(WindowID.MAIN)
        application.shutdown()

    @requires_halcon
    def test_open_calibration_and_observation(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.open_calibration()
        application.open_observation()
        assert application.registry.is_open(WindowID.CALIBRATION)
        assert application.registry.is_open(WindowID.OBSERVATION)
        application.shutdown()

    @requires_halcon
    def test_navigation_signals_open_windows(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.window.calibration_requested.emit()
        application.window.observation_requested.emit()
        assert application.registry.is_open(WindowID.CALIBRATION)
        assert application.registry.is_open(WindowID.OBSERVATION)
        application.shutdown()

    @requires_halcon
    def test_open_camera_detail_unregistered(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.open_camera_detail("dev_cam_1")
        assert application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="dev_cam_1"
        )
        application.shutdown()

    @requires_halcon
    def test_open_camera_detail_reuses_existing(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        first = application.registry.open(
            WindowID.CAMERA_DETAIL,
            instance_key="cam_a",
            camera_id="cam_a",
            camera_name="A",
        )
        application.open_camera_detail("cam_a")
        assert application.registry.get(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        ) is first
        application.shutdown()

    @requires_halcon
    def test_observation_tile_double_click_opens_detail(self, qapp):
        from camera.factory.camera_factory import CameraFactory
        from camera.models.camera_model import CameraModel
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        context = CameraFactory().create_camera(
            CameraModel(camera_id="cam_a", camera_name="Camera A")
        )
        application.controller.add_camera(context)
        application.open_observation()
        observation = application.registry.get(WindowID.OBSERVATION)
        slot = observation._slot_map["cam_a"]
        observation._tiles[slot].double_clicked.emit("cam_a")
        assert application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        )
        application.shutdown()

    @requires_halcon
    def test_cameras_disconnected_closes_details(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.open_camera_detail("cam_a")
        application.open_camera_detail("cam_b")
        assert len(application.registry.instances(WindowID.CAMERA_DETAIL)) == 2

        application.window.cameras_disconnected.emit(["cam_a"])
        assert not application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        )
        assert application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="cam_b"
        )
        application.shutdown()

    @requires_halcon
    def test_shutdown_closes_all_windows(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.open_calibration()
        application.open_observation()
        application.open_camera_detail("cam_a")
        application.shutdown()
        assert not application.registry.is_open(WindowID.CALIBRATION)
        assert not application.registry.is_open(WindowID.OBSERVATION)
        assert not application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        )

    @requires_halcon
    def test_window_external_close_removes_from_registry(self, qapp):
        from app.window_registry import WindowID

        application = self._make_application(qapp)
        application.open_camera_detail("cam_a")
        window = application.registry.get(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        )
        window.close()
        _process(qapp)
        assert not application.registry.is_open(
            WindowID.CAMERA_DETAIL, instance_key="cam_a"
        )
        application.shutdown()

    @requires_halcon
    def test_calibration_never_opens_observation(self, qapp):
        # Structural rule: CalibrationWindow has no signal that
        # requests another window.
        from gui.calibration.calibration_window import CalibrationWindow

        signals = [s for s in dir(CalibrationWindow) if s.endswith("requested")]
        assert signals == []
