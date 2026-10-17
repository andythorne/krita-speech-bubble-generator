from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget


class TextResizeHandle(QWidget):
    def __init__(self, editor):
        super().__init__(editor.parentWidget())
        self.editor = editor
        self.start_y = None
        self.setFixedHeight(12)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag up or down to resize the speech text box.")
        self.setAccessibleName("Resize speech text box")
        editor.setFixedHeight(110)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().mid().color())
        center = self.width() // 2
        painter.drawLine(center - 18, 4, center + 18, 4)
        painter.drawLine(center - 18, 7, center + 18, 7)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_y = event.globalY()
            self.start_height = self.editor.height()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start_y is not None:
            height = self.start_height + event.globalY() - self.start_y
            self.editor.setFixedHeight(max(70, min(1000, height)))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_y is not None:
            self.mouseMoveEvent(event)
            self.start_y = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
