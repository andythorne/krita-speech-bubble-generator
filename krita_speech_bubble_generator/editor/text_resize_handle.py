from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMouseEvent, QPaintEvent, QPainter
from PyQt5.QtWidgets import QTextEdit, QWidget


class TextResizeHandle(QWidget):
    def __init__(self, editor: QTextEdit) -> None:
        super().__init__(editor.parentWidget())
        self.editor = editor
        self.start_y: Optional[int] = None
        self.start_height = editor.height()
        self.setFixedHeight(12)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag up or down to resize the speech text box.")
        self.setAccessibleName("Resize speech text box")
        editor.setFixedHeight(110)

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().mid().color())
        center = self.width() // 2
        painter.drawLine(center - 18, 4, center + 18, 4)
        painter.drawLine(center - 18, 7, center + 18, 7)

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_y = event.globalY()
            self.start_height = self.editor.height()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if self.start_y is not None:
            height = self.start_height + event.globalY() - self.start_y
            self.editor.setFixedHeight(max(70, min(1000, height)))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self.start_y is not None:
            self.mouseMoveEvent(event)
            self.start_y = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
