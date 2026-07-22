"""
focus_test.py

GUI tool to test TV46L motorized focus in real time.

MIT licensed (see AGENTS.md).

Sources consulted:
    Halcon_Parameters.md    (focus param names and range values)
    diagnose_focus.py       (root-cause investigation patterns)
    test_focus_control.py   (basic interactive CLI flow)
    camera_viewer.py        (PyQt6 GUI rendering pattern)
    tv46l_camera.py (lines 815–860)   (focus API implementation)
    halcon_driver.py        (low-level param get/set)

Hardware focus parameters (from Halcon_Parameters.md):
    FLK_TI_ControlFeature_SetFocusDistanceMm       (set)
    FLK_TI_ControlFeature_CurrentFocusDistanceMm   (get)
    FLK_TI_ControlFeature_FocusDistanceMm_Min      (150 mm)
    FLK_TI_ControlFeature_FocusDistanceMm_Max      (1 000 000 mm)

Usage:
    python -m tests.focus_test --device <device_id> --serial <sn> --ip <ip>

    or for discovery-based first camera:
    python -m tests.focus_test

Keyboard:
    F5        Refresh all readings
    Up        Step +25 mm
    Down      Step -25 mm
    PgUp      Step +250 mm
    PgDn      Step -250 mm
    Home      Focus to MIN
    End       Focus to MAX
    Q         Quit

Halcon_Parameters reference (focus):
    - FLK_TI_ControlFeature_SetFocusDistanceMm — write focus
    - FLK_TI_ControlFeature_CurrentFocusDistanceMm — read current
    - Range: [150 .. 1 000 000] mm

Common failure modes: writing to SetFocusDistanceMm succeeds silently
but CurrentFocusDistanceMm never changes → lens may be jammed, firmware
may reject value silently, or SetFocusDistanceMm is read-only on this
firmware variant.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from camera.camera_discovery import CameraDiscovery
from camera.camera_info import CameraInfo
from camera.tv46l_camera import TV46LCamera
from configuration.settings import Settings


# ==========================================================
# Constants
# ==========================================================
_PARAM_SET_FOCUS = "FLK_TI_ControlFeature_SetFocusDistanceMm"
_PARAM_CUR_FOCUS = "FLK_TI_ControlFeature_CurrentFocusDistanceMm"
_PARAM_FOCUS_MIN = "FLK_TI_ControlFeature_FocusDistanceMm_Min"
_PARAM_FOCUS_MAX = "FLK_TI_ControlFeature_FocusDistanceMm_Max"


# ==========================================================
# Helpers
# ==========================================================

def normalize_8(image: np.ndarray) -> np.ndarray:
    image = image.astype(np.float32)
    mn, mx = float(image.min()), float(image.max())
    if mx > mn:
        image = (image - mn) / (mx - mn) * 255.0
    else:
        image.fill(0)
    return image.astype(np.uint8)


def ndarray_to_pixmap(arr: np.ndarray) -> QPixmap | None:
    if arr is None or arr.size == 0:
        return None
    if arr.ndim == 2:
        h, w = arr.shape
        colored = cv2.applyColorMap(arr, cv2.COLORMAP_INFERNO)
        rgb = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
    else:
        h, w = arr.shape[:2]
        rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)

    if rgb.flags.c_contiguous:
        data = rgb.data
    else:
        data = rgb.tobytes()
    qimg = QImage(data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def round_mm(val: Any) -> float | Any:
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return val


# ==========================================================
# FocusTestDialog
# ==========================================================

class FocusTestDialog(QWidget):
    """
    Real-time PyQt6 GUI for TV46L focus testing.
    """

    @staticmethod
    def _scalar(val):
        if isinstance(val, (list, tuple)) and len(val) == 1:
            return val[0] if val else None
        return val

    def __init__(self, device: str, serial: str, model: str,
                 vendor: str, ip: str) -> None:
        super().__init__()

        self._camera: TV46LCamera | None = None
        self._connected = False
        self._focus_min = 150.0
        self._focus_max = 1000000.0

        self._device = device
        self._serial = serial
        self._model = model
        self._vendor = vendor
        self._ip = ip

        self._build_ui()
        self._connect_timers()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(
            f"Focus Test - {self._model}  SN={self._serial}"
        )
        self.resize(1200, 800)

        root = QVBoxLayout(self)

        # top row: image + info
        top = QHBoxLayout()

        self._image_label = QLabel("(no frame)")
        self._image_label.setFixedSize(640, 480)
        self._image_label.setFrameStyle(QFrame.Shape.Box)
        top.addWidget(self._image_label)

        # info group
        info_group = QGroupBox("Camera Info")
        info_layout = QGridLayout(info_group)
        info_layout.addWidget(QLabel("Model:"),  0, 0)
        info_layout.addWidget(QLabel(self._model), 0, 1)
        info_layout.addWidget(QLabel("Serial:"),  1, 0)
        info_layout.addWidget(QLabel(self._serial), 1, 1)
        info_layout.addWidget(QLabel("IP:"),      2, 0)
        info_layout.addWidget(QLabel(self._ip),   2, 1)
        self._lbl_fps = QLabel("FPS: ---")
        info_layout.addWidget(self._lbl_fps, 3, 0, 1, 2)
        self._lbl_temp = QLabel("Temp: ---")
        info_layout.addWidget(self._lbl_temp, 4, 0, 1, 2)
        info_layout.setRowStretch(5, 1)
        top.addWidget(info_group)

        root.addLayout(top)

        # focus group
        focus_group = QGroupBox("Focus Control")
        fgl = QGridLayout(focus_group)

        fgl.addWidget(QLabel("Current (mm):"), 0, 0)
        self._lbl_current = QLabel("---")
        self._lbl_current.setStyleSheet("font-weight: bold;")
        fgl.addWidget(self._lbl_current, 0, 1)

        fgl.addWidget(QLabel("Limits (mm):"), 1, 0)
        self._lbl_limits = QLabel("---")
        fgl.addWidget(self._lbl_limits, 1, 1)

        fgl.addWidget(QLabel("Target  (mm):"), 2, 0)
        self._lbl_target = QLabel("---")
        fgl.addWidget(self._lbl_target, 2, 1)

        fgl.addWidget(QLabel("Focus busy:"), 3, 0)
        self._lbl_busy = QLabel("---")
        fgl.addWidget(self._lbl_busy, 3, 1)

        fgl.addWidget(QLabel("Settle status:"), 4, 0)
        self._lbl_settle = QLabel("---")
        fgl.addWidget(self._lbl_settle, 4, 1)

        # target spin
        fgl.addWidget(QLabel("Manual target:"), 5, 0)
        target_row = QHBoxLayout()
        self._spin_target = QSpinBox()
        self._spin_target.setRange(int(self._focus_min),
                                   int(self._focus_max))
        self._spin_target.setValue(int(self._focus_min))
        self._spin_target.setSingleStep(10)
        self._spin_target.setSuffix(" mm")
        target_row.addWidget(self._spin_target)
        self._btn_target = QPushButton("GO")
        self._btn_target.clicked.connect(
            lambda: self.move_to(float(self._spin_target.value()))
        )
        target_row.addWidget(self._btn_target)
        fgl.addLayout(target_row, 5, 1)

        # slider
        fgl.addWidget(QLabel("Slider proportional:"), 6, 0)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(1000)
        self._slider.setValue(0)
        self._slider.sliderReleased.connect(self._on_slider)
        fgl.addWidget(self._slider, 6, 1)

        root.addWidget(focus_group)

        # log area
        log_group = QGroupBox("Diagnostics Log")
        log_layout = QVBoxLayout(log_group)
        self._lbl_log = QLabel("(idle)")
        self._lbl_log.setWordWrap(True)
        log_layout.addWidget(self._lbl_log)
        root.addWidget(log_group)

        # buttons row
        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh (F5)")
        refresh_btn.clicked.connect(self.read_all)
        buttons.addWidget(refresh_btn)

        for text, step in [
            ("Focus MIN", None),
            ("Focus MAX", None),
            ("+25 mm", 25), ("-25 mm", -25),
            ("+250 mm", 250), ("-250 mm", -250),
            ("+1000 mm", 1000), ("-1000 mm", -1000),
        ]:
            btn = QPushButton(text)
            if step is None:
                is_max = text == "Focus MAX"
                btn.clicked.connect(
                    lambda _ignored, m=is_max: self.move_to(
                        self._focus_max if m else self._focus_min
                    )
                )
            else:
                btn.clicked.connect(
                    lambda _ignored, s=step: self.step_focus(s)
                )
            buttons.addWidget(btn)

        self._chk_update = QCheckBox("Live focus read")
        self._chk_update.setChecked(True)
        buttons.addWidget(self._chk_update)
        buttons.addStretch()
        root.addLayout(buttons)

    # ---------------------------------------------------------
    # Timers
    # ---------------------------------------------------------

    def _connect_timers(self) -> None:
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._update_frame)
        self._frame_timer.start(33)

        self._focus_timer = QTimer(self)
        self._focus_timer.timeout.connect(self._read_focus_loop)
        self._focus_timer.start(300)

    # ---------------------------------------------------------
    # Camera lifecycle
    # ---------------------------------------------------------

    def connect_camera(self) -> bool:
        """Open camera, start acquisition, read limits."""
        info = CameraInfo(
            device=self._device,
            serial=self._serial,
            model=self._model,
            vendor=self._vendor,
            ip=self._ip,
        )
        try:
            self._camera = TV46LCamera(info, Settings())
            self._camera.connect()
            self._camera.start()
            ok = self._camera.wait_for_first_frame(15)
            if not ok:
                self._log("FAIL: No frame within 15 s",
                          is_error=True)
                return False
            self._connected = True
            try:
                self._focus_min = float(
                    self._scalar(
                        self._camera.get_parameter(_PARAM_FOCUS_MIN)
                    )
                )
                self._focus_max = float(
                    self._scalar(
                        self._camera.get_parameter(_PARAM_FOCUS_MAX)
                    )
                )
            except Exception as exc:
                self._log(f"Cannot read focus limits: {exc}")
                # fallback from Halcon_Parameters.md
            self._lbl_limits.setText(
                f"{self._focus_min:g}  –  {self._focus_max:g}"
            )
            self._spin_target.setRange(int(self._focus_min),
                                       int(self._focus_max))

            self._log("Camera ready.")
            self.read_all()
            return True
        except Exception as exc:
            self._log(f"Camera FAIL: {exc}", is_error=True)
            return False

    def disconnect_camera(self) -> None:
        if self._camera is not None:
            try:
                self._camera.disconnect()
            except Exception:
                pass
        self._connected = False

    # ---------------------------------------------------------
    # Live video
    # ---------------------------------------------------------

    def _update_frame(self) -> None:
        if not self._connected or self._camera is None:
            return
        frame = self._camera.get_latest_frame()
        if frame is None:
            return
        raw = normalize_8(frame.image)
        pm = ndarray_to_pixmap(raw)
        if pm is not None:
            pm = pm.scaled(
                self._image_label.width(),
                self._image_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self._image_label.setPixmap(pm)
        self._lbl_fps.setText(f"FPS: {self._camera.get_fps()}")

    # ---------------------------------------------------------
    # Focus reads
    # ---------------------------------------------------------

    def _read_focus_loop(self) -> None:
        if not self._connected or self._camera is None:
            return
        if not self._chk_update.isChecked():
            return
        self.read_all()

    def read_all(self) -> None:
        if not self._connected or self._camera is None:
            return
        self._read_focus()
        self._read_temp()

    def _read_focus(self) -> None:
        if self._camera is None:
            return
        try:
            cur = round_mm(
                self._camera.get_parameter(_PARAM_CUR_FOCUS)
            )
            self._lbl_current.setText(f"{cur} mm")
        except Exception as exc:
            self._lbl_current.setText(f"FAIL: {exc}")

    def _read_temp(self) -> None:
        if self._camera is None:
            return
        try:
            t = self._camera.device_temperature()
            ct = self._camera.critical_temperature()
            self._lbl_temp.setText(
                f"Temp: {t:.1f} °C  (critical: {ct:.0f} °C)"
            )
        except Exception as exc:
            self._lbl_temp.setText(f"Temp: FAIL ({exc})")

    # ---------------------------------------------------------
    # Focus actions
    # ---------------------------------------------------------

    def move_to(self, target: float) -> None:
        """Write focus, measure timing, poll settle."""
        if self._camera is None:
            return
        target = float(np.clip(target, self._focus_min, self._focus_max))
        self._lbl_target.setText(f"{target:g} mm")
        self._lbl_settle.setText("sending...")

        t0 = time.perf_counter()
        try:
            self._camera.set_parameter(_PARAM_SET_FOCUS, target)
            elapsed = time.perf_counter() - t0
            self._lbl_settle.setText(
                f"wrote in {elapsed*1000:.1f} ms"
            )
            self._log(
                f"set_focus_distance({target:g}) "
                f"done in {elapsed*1000:.1f} ms"
            )
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            self._lbl_settle.setText("ERROR")
            self._log(
                f"set_focus_distance({target:g}) FAILED "
                f"in {elapsed*1000:.1f} ms: {exc}",
                is_error=True,
            )
            return

        # poll settle
        settled = False
        final_dist = None
        t0 = time.perf_counter()
        try:
            settled = self._camera.wait_for_focus(
                target, tolerance_mm=10, timeout=2.0
            )
            final_dist = round_mm(
                self._camera.get_parameter(_PARAM_CUR_FOCUS)
            )
        except Exception as exc:
            self._log(f"wait_for_focus threw: {exc}")

        settle_ms = (time.perf_counter() - t0) * 1000
        if settled:
            self._lbl_settle.setText(
                f"settled in {settle_ms:.0f} ms"
            )
        else:
            self._lbl_settle.setText(
                f"UNSETTLED after {settle_ms:.0f} ms (target={target:g}, "
                f"actual={final_dist})"
            )

        try:
            self._lbl_busy.setText(
                f"{self._camera.focus_busy()}"
            )
        except Exception as exc:
            self._lbl_busy.setText(f"ERROR: {exc}")

        self._read_focus()

    def step_focus(self, delta: float) -> None:
        if self._camera is None:
            return
        try:
            cur = float(
                self._camera.get_parameter(_PARAM_CUR_FOCUS)
            )
        except Exception as exc:
            self._log(
                f"Cannot step {delta:+g} mm: read current failed: "
                f"{exc}",
                is_error=True,
            )
            return
        self.move_to(cur + delta)

    def move_to_min(self) -> None:
        self.move_to(self._focus_min)

    def move_to_max(self) -> None:
        self.move_to(self._focus_max)

    def _on_slider(self) -> None:
        ratio = self._slider.value() / 1000.0
        target = self._focus_min + ratio * (
            self._focus_max - self._focus_min
        )
        self.move_to(target)

    # ---------------------------------------------------------
    # Logging
    # ---------------------------------------------------------

    def _log(self, msg: str, is_error: bool = False) -> None:
        ts = time.strftime("%H:%M:%S")
        prefix = "ERR" if is_error else "INF"
        self._lbl_log.setText(f"[{ts}]  {prefix}  {msg}")

    # ---------------------------------------------------------
    # Keyboard
    # ---------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        if k == Qt.Key.Key_Q or k == Qt.Key.Key_Escape:
            self.disconnect_camera()
            self.close()
        elif k == Qt.Key.Key_F5:
            self.read_all()
        elif k == Qt.Key.Key_Up:
            self.step_focus(25)
        elif k == Qt.Key.Key_Down:
            self.step_focus(-25)
        elif k == Qt.Key.Key_PageUp:
            self.step_focus(250)
        elif k == Qt.Key.Key_PageDown:
            self.step_focus(-250)
        elif k == Qt.Key.Key_Home:
            self.move_to_min()
        elif k == Qt.Key.Key_End:
            self.move_to_max()
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self.disconnect_camera()
        super().closeEvent(event)


# ==========================================================
# Main
# ==========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TV46L focus diagnostic GUI tool"
    )
    parser.add_argument("--device", help="GigEVision device string")
    parser.add_argument("--serial", help="Camera serial number")
    parser.add_argument("--model", help="Camera model string")
    parser.add_argument("--ip", help="Camera IP address")
    parser.add_argument("--vendor", default="Fluke Process Instruments",
                        help="Camera vendor")
    args = parser.parse_args()

    if args.device and args.serial and args.model and args.ip:
        device, serial = args.device, args.serial
        model, ip = args.model, args.ip
        vendor = args.vendor
    else:
        # discover first camera
        print("Discovering cameras...")
        discovery = CameraDiscovery()
        cameras = discovery.discover()
        if not cameras:
            print("No cameras discovered. Provide --device, --serial, "
                  "--model, --ip explicitly.")
            sys.exit(1)
        cam = cameras[0]
        device, serial = cam.device, cam.serial
        model, ip = cam.model, cam.ip
        vendor = cam.vendor
        print(f"Found {model}  SN={serial}  IP={ip}")

    app = QApplication(sys.argv)
    dialog = FocusTestDialog(
        device=device, serial=serial, model=model,
        vendor=vendor, ip=ip,
    )
    dialog.show()

    if not dialog.connect_camera():
        print("Camera connection FAILED. See GUI log.")
        QTimer.singleShot(0, dialog.close)
    else:
        print("Camera ready. GUI visible.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
