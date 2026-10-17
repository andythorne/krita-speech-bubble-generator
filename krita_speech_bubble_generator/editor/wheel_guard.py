from typing import Optional

from PyQt5.QtCore import QEvent, QObject, QPointF
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication, QScrollArea


class WheelGuard(QObject):
    def __init__(self, scroll: QScrollArea, parent: Optional[QObject]) -> None:
        super().__init__(parent)
        self.scroll = scroll

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        event = a1
        if not isinstance(event, QWheelEvent) or event.type() != QEvent.Type.Wheel:
            return False
        viewport = self.scroll.viewport()
        if viewport is None:
            return False
        forwarded = QWheelEvent(
            QPointF(viewport.mapFromGlobal(event.globalPos())),
            QPointF(event.globalPos()), event.pixelDelta(), event.angleDelta(),
            event.buttons(), event.modifiers(), event.phase(), event.inverted(),
            event.source())
        QApplication.sendEvent(viewport, forwarded)
        event.accept()
        return True
