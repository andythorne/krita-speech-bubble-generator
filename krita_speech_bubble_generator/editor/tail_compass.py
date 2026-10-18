"""Eight tail-angle presets, independent of tail length and dragging."""

import math
from typing import Callable, Dict, Optional, Tuple

from PyQt5.QtCore import QLineF, QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtGui import QPaintEvent, QPainter, QPen
from PyQt5.QtWidgets import (
    QGridLayout, QLabel, QSizePolicy, QToolButton, QWidget,
)


DIRECTIONS: Tuple[Tuple[str, str, int, int], ...] = (
    ("N", "North", 0, 1),
    ("NE", "North-east", 0, 2),
    ("E", "East", 1, 2),
    ("SE", "South-east", 2, 2),
    ("S", "South", 2, 1),
    ("SW", "South-west", 2, 0),
    ("W", "West", 1, 0),
    ("NW", "North-west", 0, 0),
)


class _ArrowButton(QToolButton):
    def __init__(self, angle: float, parent: QWidget) -> None:
        super().__init__(parent)
        self._angle = angle
        self.setCheckable(True)
        self.setFixedSize(28, 28)

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        super().paintEvent(a0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().buttonText().color(), 1.8))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(math.degrees(self._angle))
        painter.drawLine(QLineF(-7, 0, 7, 0))
        painter.drawLine(QLineF(2, -5, 7, 0))
        painter.drawLine(QLineF(2, 5, 7, 0))


class TailCompass(QWidget):
    angle_selected = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Tail position")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.buttons: Dict[str, QToolButton] = {}
        self._angles: Dict[str, float] = {}
        for direction, label, row, column in DIRECTIONS:
            angle = math.atan2(row - 1, column - 1)
            button = _ArrowButton(angle, self)
            button.setAccessibleName("Tail position: " + label)
            button.setToolTip("Position tail to the " + label.lower() + ".")
            button.clicked.connect(self._direction_clicked(angle))
            self.buttons[direction] = button
            self._angles[direction] = angle
            layout.addWidget(button, row, column)
        center = QLabel(self)
        center.setFixedSize(28, 28)
        center.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        center.setToolTip("Drag the preview tail handle for other angles.")
        layout.addWidget(center, 1, 1)

    def _direction_clicked(self, angle: float) -> Callable[[bool], None]:
        def clicked(checked: bool) -> None:
            self.set_angle(angle)
            self.angle_selected.emit(angle)
        return clicked

    def set_angle(self, angle: float) -> None:
        for direction, button in self.buttons.items():
            difference = angle - self._angles[direction]
            distance = math.atan2(math.sin(difference), math.cos(difference))
            blocker = QSignalBlocker(button)
            button.setChecked(math.isclose(distance, 0.0, rel_tol=0.0, abs_tol=1e-9))
            del blocker
