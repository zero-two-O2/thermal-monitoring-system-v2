from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)


class ROIToolbar(QFrame):
    create_roi_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    save_requested = pyqtSignal()

    SHAPES = ["rectangle1", "rectangle2", "circle", "ellipse", "polygon"]
    SHAPE_LABELS = {
        "rectangle1": "Rect",
        "rectangle2": "Rot. Rect",
        "circle": "Circle",
        "ellipse": "Ellipse",
        "polygon": "Polygon",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("roiToolbar")
        self.setFrameShape(QFrame.StyledPanel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        title = QLabel("ROI Tools")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        for shape in self.SHAPES:
            btn = QPushButton(self.SHAPE_LABELS.get(shape, shape))
            btn.setToolTip(f"Create {shape.replace('_', ' ')} ROI")
            btn.clicked.connect(lambda checked, s=shape: self._on_create(s))
            layout.addWidget(btn)

        layout.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #555555;")
        layout.addWidget(sep)
        layout.addSpacing(8)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip("Delete selected ROI")
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(""))
        layout.addWidget(self._delete_btn)

        self._duplicate_btn = QPushButton("Duplicate")
        self._duplicate_btn.setToolTip("Duplicate selected ROI")
        self._duplicate_btn.clicked.connect(lambda: self.duplicate_requested.emit(""))
        layout.addWidget(self._duplicate_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setToolTip("Edit selected ROI")
        layout.addWidget(self._edit_btn)

        layout.addSpacing(8)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #555555;")
        layout.addWidget(sep2)
        layout.addSpacing(8)

        self._save_btn = QPushButton("Save")
        self._save_btn.setToolTip("Save all ROI configurations")
        self._save_btn.clicked.connect(self.save_requested.emit)
        layout.addWidget(self._save_btn)
        self._save_btn.setEnabled(False)

        layout.addStretch()

    def set_dirty(self, dirty: bool) -> None:
        self._save_btn.setEnabled(dirty)
        if dirty:
            self._save_btn.setStyleSheet("font-weight: bold;")
        else:
            self._save_btn.setStyleSheet("")

    def _on_create(self, shape: str) -> None:
        self.create_roi_requested.emit(shape)
