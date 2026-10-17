import math
import random
from typing import Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QTransform


MIN_NODES = 8
MAX_NODES = 64


def validate_nodes(nodes: Optional[int]) -> None:
    if nodes is not None and (type(nodes) is not int or not MIN_NODES <= nodes <= MAX_NODES):
        raise ValueError("Invalid node count")


def ellipse_transform(rect: QRectF) -> QTransform:
    center = rect.center()
    return QTransform().translate(center.x(), center.y()).scale(
        rect.width() / 2, rect.height() / 2)


def ellipse_path(center: QPointF, radius_x: float, radius_y: float,
                 angle: float = 0) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(), radius_x, radius_y)
    transform = QTransform().translate(center.x(), center.y()).rotate(angle)
    return transform.map(path)


def body_path(rect: QRectF, style: str, corner_radius: Optional[float] = None,
              irregularity: int = 50, seed: int = 0,
              shouting_shape: str = "Balanced",
              nodes: Optional[int] = None) -> QPainterPath:
    """Construct an outline directly, using the same policies as the renderer."""
    from .registry import resolve_bubble
    from .types import BodyParameters

    parameters = BodyParameters(corner_radius, irregularity, seed, nodes)
    return resolve_bubble(style, shouting_shape).body_path(rect, parameters)


def outline_anchor(path: QPainterPath, center: QPointF, direction: QPointF) -> QPointF:
    """Intersect a ray with the actual outline, including cloud lobes/spikes."""
    distances: List[float] = []
    polygon = path.toFillPolygon()
    for i in range(len(polygon) - 1):
        start, end = polygon[i], polygon[i + 1]
        edge = end - start
        offset = start - center
        cross = direction.x() * edge.y() - direction.y() * edge.x()
        if abs(cross) < 1e-9:
            continue
        distance = (offset.x() * edge.y() - offset.y() * edge.x()) / cross
        fraction = (offset.x() * direction.y() - offset.y() * direction.x()) / cross
        if distance >= 0 and 0 <= fraction <= 1:
            distances.append(distance)
    if not distances:
        raise ValueError("The tail ray does not intersect the bubble outline")
    return center + direction * max(distances)


def tail_tip(path: QPainterPath, center: QPointF, angle: float,
             length: float) -> QPointF:
    direction = QPointF(math.cos(angle), math.sin(angle))
    return outline_anchor(path, center, direction) + direction * length


def bubble_path(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                style: str, font_size: float, thought_size: int = 100,
                irregularity: int = 0, seed: int = 0) -> QPainterPath:
    """Compose a direct outline and tail through the selected type's policy."""
    from .registry import resolve_bubble
    from .types import TailParameters

    return resolve_bubble(style).compose_tail(
        body, center, tip, TailParameters(font_size, thought_size, irregularity, seed))


def _tail_geometry(body: QPainterPath, center: QPointF,
                   tip: Optional[QPointF]) -> Optional[Tuple[QPointF, QPointF, float]]:
    if tip is None or body.contains(tip):
        return None
    offset = tip - center
    distance = math.hypot(offset.x(), offset.y())
    if distance < 1e-9:
        return None
    direction = offset / distance
    anchor = outline_anchor(body, center, direction)
    length = math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y())
    if length < 1e-6:
        return None
    return direction, anchor, length


def thought_trail(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                  font_size: float, thought_size: int = 100,
                  irregularity: int = 0, seed: int = 0) -> QPainterPath:
    geometry = _tail_geometry(body, center, tip)
    if geometry is None or tip is None:
        return QPainterPath(body)
    direction, anchor, length = geometry
    result = QPainterPath(body)
    generator = random.Random("thought-trail-{}".format(seed))
    amount = irregularity / 100
    perpendicular = QPointF(-direction.y(), direction.x())
    for fraction, scale in ((0.25, 1), (0.58, 0.7), (0.87, 0.4)):
        radius = min(font_size * 0.32, length * 0.13) * thought_size / 100 * scale
        fraction += generator.uniform(-0.04, 0.04) * amount
        blob_center = anchor + (tip - anchor) * fraction + perpendicular * (
            radius * generator.uniform(-0.65, 0.65) * amount)
        radius_x = radius * (1 + generator.uniform(-0.35, 0.6) * amount)
        radius_y = radius * (1 + generator.uniform(-0.35, 0.6) * amount)
        rotation = generator.uniform(-65, 65) * amount
        dot = ellipse_path(blob_center, radius_x, radius_y, rotation)
        result = result.united(dot)
    return result


def speech_tail(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                font_size: float) -> QPainterPath:
    geometry = _tail_geometry(body, center, tip)
    if geometry is None or tip is None:
        return QPainterPath(body)
    direction, anchor, length = geometry
    perpendicular = QPointF(-direction.y(), direction.x())
    left = outline_anchor(body, center, perpendicular) - center
    right = outline_anchor(body, center, -perpendicular) - center
    inside_radius = min(math.hypot(left.x(), left.y()), math.hypot(right.x(), right.y()))
    half_width = min(font_size * 0.65, length * 0.5, inside_radius * 0.5)
    tail = QPainterPath()
    # Start inside the body, not just behind the ray intersection: at shallow
    # angles a short, perpendicular triangle base can lie entirely outside it.
    tail.moveTo(center + perpendicular * half_width)
    tail.quadTo(anchor + perpendicular * half_width, tip)
    tail.quadTo(anchor - perpendicular * half_width, center - perpendicular * half_width)
    tail.closeSubpath()
    return body.united(tail)


def path_data(path: QPainterPath) -> str:
    commands: List[str] = []
    start: Optional[QPointF] = None
    i = 0
    while i < path.elementCount():
        element = path.elementAt(i)
        if element.isMoveTo():
            start = QPointF(element.x, element.y)
            commands.append("M{} {}".format(element.x, element.y))
        elif element.isLineTo():
            if QPointF(element.x, element.y) == start:
                commands.append("Z")
            else:
                commands.append("L{} {}".format(element.x, element.y))
        elif element.isCurveTo():
            control = path.elementAt(i + 1)
            end = path.elementAt(i + 2)
            commands.append("C{} {} {} {} {} {}".format(
                element.x, element.y, control.x, control.y, end.x, end.y))
            if QPointF(end.x, end.y) == start:
                commands.append("Z")
            i += 2
        i += 1
    return " ".join(commands)


def bubble_svg(path: QPainterPath, lines: Iterable[str], text_rect: QRectF,
               font_family: str, font_size: float, cap_height: float,
               fill: str, stroke: str, stroke_width: float, text_color: str,
               view_box: QRectF) -> str:
    text: List[str] = []
    baseline = text_rect.top() + cap_height
    for line in lines:
        text.append(
            '<text x="{}" y="{}" font-family={} font-size="{}" '
            'fill="{}" text-anchor="middle">{}</text>'.format(
                text_rect.center().x(), baseline, quoteattr(font_family),
                font_size, text_color, escape(line)))
        baseline += font_size * 1.3
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        'viewBox="{x} {y} {w} {h}">'
        '<g id="rsbg-bubble"><path d="{path}" fill="{fill}" fill-rule="evenodd" '
        'stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round"/>'
        '{text}</g></svg>'
    ).format(
        x=view_box.x(), y=view_box.y(), w=view_box.width(), h=view_box.height(),
        path=path_data(path), fill=fill, stroke=stroke, width=stroke_width,
        text="".join(text))
