"""
Minimal HALCON + PyQt6 display test.
Tests HALCON window embedding without camera/acquisition.
"""

import sys
import halcon as ha
import numpy as np
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QTimer


class MinimalHALCONWidget(QWidget):
    """Minimal widget with embedded HALCON window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window_handle = None
        self._image_width = 640
        self._image_height = 480
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

    def create_window(self):
        """Create HALCON window embedded in this widget."""
        print(f"Widget size: {self.width()}x{self.height()}", flush=True)
        print(f"Widget geometry: {self.geometry()}", flush=True)
        print(f"Widget visible: {self.isVisible()}", flush=True)
        print(f"Widget winId: {int(self.winId())}", flush=True)

        if self._window_handle is None:
            try:
                self._window_handle = ha.open_window(
                    0, 0, self.width(), self.height(),
                    int(self.winId()), "buffer", ""
                )
                ha.set_part(self._window_handle, 0, 0, self._image_height - 1, self._image_width - 1)
                print(f"HALCON window created: handle={self._window_handle}", flush=True)
            except Exception as e:
                print(f"Failed to create HALCON window: {e}", flush=True)
                import traceback
                traceback.print_exc()

    def display_test_image(self):
        """Display a generated test image."""
        if self._window_handle is None:
            self.create_window()
        if self._window_handle is None:
            print("No window handle", flush=True)
            return

        try:
            # Create test image using numpy then convert to HALCON
            print("Creating test image...", flush=True)
            test_numpy = np.zeros((self._image_height, self._image_width), dtype=np.uint8)
            # Draw a white rectangle
            test_numpy[100:300, 100:500] = 255
            test_image = ha.himage_from_numpy_array(test_numpy)
            
            print("Calling clear_window...", flush=True)
            ha.clear_window(self._window_handle)
            
            print("Calling disp_obj...", flush=True)
            ha.disp_obj(test_image, self._window_handle)
            print("disp_obj completed", flush=True)
            
            print("Calling flush_buffer...", flush=True)
            ha.flush_buffer(self._window_handle)
            print("flush_buffer completed", flush=True)
            
            # Also try dump_window to verify content
            try:
                print("Calling dump_window...", flush=True)
                dumped = ha.dump_window(self._window_handle)
                ha.write_image(dumped, "png", 0, "test_dump")
                print("dump_window saved to test_dump.png", flush=True)
            except Exception as e:
                print(f"dump_window failed: {e}", flush=True)
                
        except Exception as e:
            print(f"Display error: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._window_handle:
            try:
                ha.set_window_extents(self._window_handle, 0, 0, self.width(), self.height())
                ha.set_part(self._window_handle, 0, 0, self._image_height - 1, self._image_width - 1)
                print(f"Window resized to: {self.width()}x{self.height()}", flush=True)
            except Exception as e:
                print(f"Resize error: {e}", flush=True)

    def closeEvent(self, event):
        if self._window_handle:
            try:
                ha.close_window(self._window_handle)
            except Exception:
                pass
        super().closeEvent(event)


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minimal HALCON Display Test")
        self.resize(800, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.halcon_widget = MinimalHALCONWidget()
        layout.addWidget(self.halcon_widget, stretch=1)

        self.btn_test = QPushButton("Display Test Image")
        self.btn_test.clicked.connect(self.halcon_widget.display_test_image)
        layout.addWidget(self.btn_test)

        self.status_label = QLabel("Click button to display test image")
        layout.addWidget(self.status_label)

        # Force widget to be shown and laid out before creating HALCON window
        QTimer.singleShot(100, self.on_ready)

    def on_ready(self):
        print("=== Window ready, creating HALCON window ===", flush=True)
        self.halcon_widget.create_window()
        self.status_label.setText("HALCON window created. Running auto-test...")
        # Auto-run test after window creation
        QTimer.singleShot(500, self.run_auto_test)

    def run_auto_test(self):
        print("=== Running auto test ===", flush=True)
        self.halcon_widget.display_test_image()
        self.status_label.setText("Test image displayed. Check test_dump.png")


def main():
    app = QApplication(sys.argv)
    
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()