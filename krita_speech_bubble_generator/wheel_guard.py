from PyQt5.QtCore import QEvent, QObject, QPointF
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication


class WheelGuard(QObject):
    def __init__(self, scroll, parent):
        super().__init__(parent)
        self.scroll = scroll

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return False
        viewport = self.scroll.viewport()
        forwarded = QWheelEvent(
            QPointF(viewport.mapFromGlobal(event.globalPos())),
            QPointF(event.globalPos()), event.pixelDelta(), event.angleDelta(),
            event.buttons(), event.modifiers(), event.phase(), event.inverted(),
            event.source())
        QApplication.sendEvent(viewport, forwarded)
        event.accept()
        return True
