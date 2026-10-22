import math
from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPaintEvent, QPainter, QPen, QTransform
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtWidgets import QWidget


class BubblePreview(QSvgWidget):
    tailMoved = pyqtSignal(QPointF)
    tailStartMoved = pyqtSignal(QPointF)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setToolTip(
            "Drag the blue tail end to point at the speaker. "
            "In Advanced mode, drag the green start along the bubble edge.")
        self.tip: Optional[QPointF] = None
        self.tail_start: Optional[QPointF] = None
        self.drag_start = False
        self.dragging = False
        self.drag_view_box: Optional[QRectF] = None
        self.view_box: QRectF = QRectF()
        self.svg_box = QRectF()
        self.background = QImage()
        self.canvas_rect = QRectF()
        self.bubble_transform = QTransform()

    def setContext(self, image: Optional[QImage] = None,
                   canvas_rect: Optional[QRectF] = None,
                   transform: Optional[QTransform] = None) -> None:
        self.background = QImage() if image is None else image
        self.canvas_rect = QRectF() if canvas_rect is None else QRectF(canvas_rect)
        self.bubble_transform = QTransform() if transform is None else QTransform(transform)
        self.update()

    def setBubble(self, svg: str, view_box: QRectF, tip: Optional[QPointF],
                  tail_start: Optional[QPointF] = None) -> None:
        if self.dragging and (tip is None or (self.drag_start and tail_start is None)):
            self.dragging = False
            self.drag_view_box = None
            self.unsetCursor()
        self.svg_box = QRectF(view_box)
        if self.dragging and self.drag_view_box is not None:
            self.view_box = QRectF(self.drag_view_box)
        else:
            self.view_box = QRectF(self.bubble_transform.mapRect(view_box))
            if not self.background.isNull():
                width, height = self.view_box.width(), self.view_box.height()
                self.view_box.adjust(-width / 2, -height / 2, width / 2, height / 2)
        self.tip = tip
        self.tail_start = tail_start
        self.load(svg.encode("utf-8"))
        self.update()

    def viewport(self, view_box: QRectF) -> QRectF:
        scale = min(self.width() / view_box.width(),
                    self.height() / view_box.height())
        return QRectF((self.width() - view_box.width() * scale) / 2,
                      (self.height() - view_box.height() * scale) / 2,
                      view_box.width() * scale, view_box.height() * scale)

    def toWidget(self, point: QPointF, view_box: QRectF) -> QPointF:
        viewport = self.viewport(view_box)
        scale = viewport.width() / view_box.width()
        world_point = self.bubble_transform.map(point)
        return viewport.topLeft() + (world_point - view_box.topLeft()) * scale

    def toBubble(self, point: QPointF, view_box: QRectF) -> QPointF:
        viewport = self.viewport(view_box)
        scale = viewport.width() / view_box.width()
        world_point = view_box.topLeft() + (point - viewport.topLeft()) / scale
        inverse, invertible = self.bubble_transform.inverted()
        if not invertible:
            raise ValueError("Cannot drag a tail through a singular preview transform")
        return inverse.map(world_point)

    def paintEvent(self, event: Optional[QPaintEvent]) -> None:
        # Use the same letterboxed viewport for drawing and hit testing.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.view_box.isEmpty():
            return
        viewport = self.viewport(self.view_box)
        painter.save()
        painter.setClipRect(viewport)
        painter.fillRect(viewport, self.palette().base())
        painter.translate(viewport.topLeft())
        scale = viewport.width() / self.view_box.width()
        painter.scale(scale, scale)
        painter.translate(-self.view_box.left(), -self.view_box.top())
        if not self.background.isNull():
            painter.drawImage(self.canvas_rect, self.background)
        painter.setWorldTransform(self.bubble_transform, True)
        renderer = self.renderer()
        if renderer is None:
            raise RuntimeError("The preview SVG renderer is unavailable")
        renderer.render(painter, self.svg_box)
        painter.restore()
        for point, color in ((self.tail_start, "#2e7d32"), (self.tip, "#1565c0")):
            if point is not None:
                painter.setPen(QPen(QColor(color), 2))
                painter.setBrush(QColor("#ffffff"))
                painter.drawEllipse(self.toWidget(point, self.view_box), 6, 6)

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self.tip is not None:
            handles = [(self.tip, False)]
            if self.tail_start is not None:
                handles.append((self.tail_start, True))
            distances: List[Tuple[float, bool]] = []
            for point, start in handles:
                handle = self.toWidget(point, self.view_box)
                distances.append((math.hypot(event.pos().x() - handle.x(),
                                             event.pos().y() - handle.y()), start))
            distance, start = min(distances)
            if distance <= 14:
                self.dragging = True
                self.drag_start = start
                self.drag_view_box = QRectF(self.view_box)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if self.dragging and self.drag_view_box is not None:
            self._emit_drag(self.toBubble(QPointF(event.pos()), self.drag_view_box))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, a0: Optional[QMouseEvent]) -> None:
        event = a0
        if event is None:
            return
        if (self.dragging and self.drag_view_box is not None
                and event.button() == Qt.MouseButton.LeftButton):
            point = self.toBubble(QPointF(event.pos()), self.drag_view_box)
            self.dragging = False
            self.drag_view_box = None
            self.unsetCursor()
            self._emit_drag(point)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _emit_drag(self, point: QPointF) -> None:
        if self.drag_start:
            self.tailStartMoved.emit(point)
        else:
            self.tailMoved.emit(point)
