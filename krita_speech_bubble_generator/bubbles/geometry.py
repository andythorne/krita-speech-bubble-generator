import math
import random
from typing import Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QFont, QFontMetricsF, QPainterPath, QPainterPathStroker, QPolygonF, QTransform,
)

from .text_runs import TextRun, styled_font


MIN_NODES = 8
MAX_NODES = 64
MIN_THOUGHT_BLOBS = 1
MAX_THOUGHT_BLOBS = 10


def filled_path_centroid(path: QPainterPath) -> Optional[QPointF]:
    """Find the center of filled area, accounting for holes and overlaps."""
    scale = 8.0
    polygons = QTransform().scale(scale, scale).map(path).simplified().toSubpathPolygons()
    contours: List[Tuple[QPolygonF, float, QPointF, QRectF]] = []
    for polygon in polygons:
        twice_area = polygon_x = polygon_y = 0.0
        for index in range(len(polygon) - 1):
            start, end = polygon[index], polygon[index + 1]
            cross = start.x() * end.y() - end.x() * start.y()
            twice_area += cross
            polygon_x += (start.x() + end.x()) * cross
            polygon_y += (start.y() + end.y()) * cross
        if abs(twice_area) > 1e-9:
            contours.append((polygon, abs(twice_area),
                             QPointF(polygon_x / (3 * twice_area),
                                     polygon_y / (3 * twice_area)),
                             polygon.boundingRect()))
    weight = moment_x = moment_y = 0.0
    for polygon, area, centroid, bounds in contours:
        # Qt's simplified paths use odd-even fill, not consistent contour winding.
        depth = sum(
            1 for parent, parent_area, _, parent_bounds in contours
            if parent_area > area and parent_bounds.contains(bounds)
            and parent.containsPoint(polygon[0], Qt.FillRule.OddEvenFill))
        area_weight = area if depth % 2 == 0 else -area
        weight += area_weight
        moment_x += area_weight * centroid.x()
        moment_y += area_weight * centroid.y()
    if weight == 0:
        return None
    return QPointF(moment_x / weight / scale, moment_y / weight / scale)


def validate_nodes(nodes: Optional[int]) -> None:
    if nodes is not None and (type(nodes) is not int or not MIN_NODES <= nodes <= MAX_NODES):
        raise ValueError("Invalid node count")


def ellipse_transform(rect: QRectF) -> QTransform:
    center = rect.center()
    return QTransform().translate(center.x(), center.y()).scale(
        rect.width() / 2, rect.height() / 2)


def oval_curve_control(squareness: int) -> float:
    circle = 4 * (math.sqrt(2) - 1) / 3
    return circle + (1 - circle) * squareness / 100


def oval_path(rect: QRectF, squareness: int = 0) -> QPainterPath:
    path = QPainterPath()
    if squareness == 0:
        path.addEllipse(rect)
        return path
    control = oval_curve_control(squareness)
    path.moveTo(1, 0)
    path.cubicTo(1, control, control, 1, 0, 1)
    path.cubicTo(-control, 1, -1, control, -1, 0)
    path.cubicTo(-1, -control, -control, -1, 0, -1)
    path.cubicTo(control, -1, 1, -control, 1, 0)
    path.closeSubpath()
    return ellipse_transform(rect).map(path)


def squared_ellipse_point(point: QPointF, squareness: int) -> QPointF:
    """Reshape a contour point, retaining its angle and radial variation."""
    if squareness == 0 or point.isNull():
        return point
    x, y = abs(point.x()), abs(point.y())
    control = oval_curve_control(squareness)
    low, high = 0.0, 1.0
    curve_x, curve_y = 1.0, 0.0
    for _ in range(32):
        t = (low + high) / 2
        u = 1 - t
        curve_x = u ** 3 + 3 * u * u * t + 3 * u * t * t * control
        curve_y = 3 * u * u * t * control + 3 * u * t * t + t ** 3
        if curve_y * x < curve_x * y:
            low = t
        else:
            high = t
    return point * math.hypot(curve_x, curve_y)


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


def tail_anchor(path: QPainterPath, center: QPointF, direction: QPointF) -> QPointF:
    """Intersect the center-to-pointer axis with the bubble body."""
    return outline_anchor(path, center, direction)


def tail_tip(path: QPainterPath, center: QPointF, angle: float,
             length: float) -> QPointF:
    direction = QPointF(math.cos(angle), math.sin(angle))
    return tail_anchor(path, center, direction) + direction * length


def bubble_path(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                style: str, font_size: float, thought_size: int = 100,
                irregularity: int = 0, seed: int = 0, curve: int = 0,
                curve_direction: str = "Up", thought_blobs: int = 3,
                outline_width: float = 0) -> QPainterPath:
    """Compose a direct outline and tail through the selected type's policy."""
    from .registry import resolve_bubble
    from .types import TailParameters

    return resolve_bubble(style).compose_tail(
        body, center, tip,
        TailParameters(font_size, thought_size, irregularity, seed, curve, curve_direction,
                       thought_blobs=thought_blobs, outline_width=outline_width))


def _tail_geometry(body: QPainterPath, center: QPointF,
                   tip: Optional[QPointF],
                   anchor: Optional[QPointF] = None
                   ) -> Optional[Tuple[QPointF, QPointF, float]]:
    if tip is None or body.contains(tip):
        return None
    offset = tip - (center if anchor is None else anchor)
    distance = math.hypot(offset.x(), offset.y())
    if distance < 1e-6:
        return None
    direction = offset / distance
    if anchor is None:
        anchor = tail_anchor(body, center, direction)
    length = math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y())
    if length < 1e-6:
        return None
    return direction, anchor, length


def _tail_bend(direction: QPointF, length: float, curve: int,
               curve_direction: str) -> QPointF:
    sign = -1 if curve_direction == "Up" else 1
    return QPointF(-direction.y(), direction.x()) * (length * curve / 100 * sign)


def _thought_start(body: QPainterPath, centerline: QPainterPath, radius: float,
                   clearance: float, start: float, end: float) -> Optional[float]:
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * (radius + clearance))
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    obstacle = body.united(stroker.createStroke(body))
    if obstacle.contains(centerline.pointAtPercent(centerline.percentAtLength(end))):
        return None
    if not obstacle.contains(centerline.pointAtPercent(centerline.percentAtLength(start))):
        return start
    for _ in range(24):
        middle = (start + end) / 2
        if obstacle.contains(centerline.pointAtPercent(centerline.percentAtLength(middle))):
            start = middle
        else:
            end = middle
    return end


def thought_trail(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                  font_size: float, thought_size: int = 100,
                  irregularity: int = 0, seed: int = 0, curve: int = 0,
                  curve_direction: str = "Up",
                  anchor: Optional[QPointF] = None, thought_blobs: int = 3,
                  outline_width: float = 0) -> QPainterPath:
    if type(thought_blobs) is not int or not MIN_THOUGHT_BLOBS <= thought_blobs <= MAX_THOUGHT_BLOBS:
        raise ValueError("Invalid thought blob count")
    geometry = _tail_geometry(body, center, tip, anchor)
    if geometry is None or tip is None:
        return QPainterPath(body)
    direction, anchor, length = geometry
    result = QPainterPath(body)
    generator = random.Random("thought-trail-{}".format(seed))
    amount = irregularity / 100
    bend = _tail_bend(direction, length, curve, curve_direction)
    centerline = QPainterPath(anchor)
    centerline.cubicTo(anchor + direction * (length / 3) + bend * (2 / 3),
                       tip - direction * (length / 3), tip)
    path_length = centerline.length()
    intervals = max(1, thought_blobs - 1)
    spacing_scale = min(1.0, 2 / intervals)
    blobs: List[Tuple[float, float, float]] = []
    for index in range(thought_blobs):
        scale = 1 - 0.6 * index / intervals
        radius = min(font_size * 0.32, length * 0.13) * thought_size / 100 * scale
        radius *= spacing_scale
        # Retain legacy size/rotation draws while replacing random placement.
        generator.uniform(-0.04, 0.04)
        generator.uniform(-0.65, 0.65)
        radius_x = radius * (1 + generator.uniform(-0.35, 0.6) * amount)
        radius_y = radius * (1 + generator.uniform(-0.35, 0.6) * amount)
        rotation = generator.uniform(-65, 65) * amount
        blobs.append((radius_x, radius_y, rotation))
    radii = [max(radius_x, radius_y) for radius_x, radius_y, _ in blobs]
    outline = min(outline_width, path_length / (2 * thought_blobs + 1))
    available = path_length - (thought_blobs + 0.5) * outline
    minimum_gap = min(0.5, available / (2 * (thought_blobs + 1)))
    diameter_sum = 2 * sum(radii)
    fit = min(1.0, (available - (thought_blobs + 1) * minimum_gap) / diameter_sum)
    gap = 0.0
    start = None
    for _ in range(32):
        gap = (path_length - (thought_blobs + 0.5) * outline
               - diameter_sum * fit) / (thought_blobs + 1)
        first = radii[0] * fit + outline + gap
        remaining = (diameter_sum - radii[0]) * fit + (thought_blobs - 0.5) * outline
        end = path_length - remaining - thought_blobs * minimum_gap
        start = _thought_start(body, centerline, radii[0] * fit, outline + minimum_gap,
                               first, end)
        if start is not None:
            gap = (path_length - start - remaining) / thought_blobs
            if gap >= minimum_gap - 1e-8:
                break
        start = None
        fit *= 0.5
        outline *= 0.5
        minimum_gap *= 0.5
    if start is None:
        raise ValueError("The thought tail cannot fit outside its bubble body")
    distance = start
    for index, (radius_x, radius_y, rotation) in enumerate(blobs):
        if index:
            distance += (radii[index - 1] + radii[index]) * fit + outline + gap
        blob_center = centerline.pointAtPercent(centerline.percentAtLength(distance))
        dot = ellipse_path(blob_center, radius_x * fit, radius_y * fit, rotation)
        result = result.united(dot)
    return result


def speech_tail(body: QPainterPath, center: QPointF, tip: Optional[QPointF],
                font_size: float, curve: int = 0,
                curve_direction: str = "Up",
                anchor: Optional[QPointF] = None) -> QPainterPath:
    advanced = anchor is not None
    geometry = _tail_geometry(body, center, tip, anchor)
    if geometry is None or tip is None:
        return QPainterPath(body)
    direction, anchor, length = geometry
    base_direction = direction
    if advanced:
        radial = anchor - center
        base_direction = radial / math.hypot(radial.x(), radial.y())
    perpendicular = QPointF(-base_direction.y(), base_direction.x())
    left = outline_anchor(body, center, perpendicular) - center
    right = outline_anchor(body, center, -perpendicular) - center
    inside_radius = min(math.hypot(left.x(), left.y()), math.hypot(right.x(), right.y()))
    half_width = min(font_size * 0.4, inside_radius * 0.5)
    tail = QPainterPath()
    # Keep the inset base centered on the body-to-tip axis, even for curved tails.
    tail.moveTo(center + perpendicular * half_width)
    tail.lineTo(anchor + perpendicular * half_width)
    if curve:
        # Ease the bend out before the tip instead of curling back into a hook.
        control_start = anchor + direction * (length / 3) + _tail_bend(
            direction, length, curve, curve_direction) * (2 / 3)
        control_end = tip - direction * (length / 3)
        tail.cubicTo(control_start + perpendicular * (half_width * 2 / 3),
                     control_end + perpendicular * (half_width / 3), tip)
        tail.cubicTo(control_end - perpendicular * (half_width / 3),
                     control_start - perpendicular * (half_width * 2 / 3),
                     anchor - perpendicular * half_width)
    else:
        tail.lineTo(tip)
        tail.lineTo(anchor - perpendicular * half_width)
    tail.lineTo(center - perpendicular * half_width)
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
               font_family: str, font_size: float, baseline_offset: float,
               fill: str, stroke: str, stroke_width: float, text_color: str,
               view_box: QRectF,
               runs: Optional[List[List[TextRun]]] = None,
               line_origins: Optional[List[float]] = None) -> str:
    text: List[str] = []
    baseline = text_rect.top() + baseline_offset
    for index, line in enumerate(lines):
        content = escape(line)
        anchor = "middle"
        x = text_rect.center().x()
        if line_origins is not None:
            x += line_origins[index]
            anchor = "start"
        if runs is not None and any(run.bold or run.italic for run in runs[index]):
            widths: List[float] = []
            font = QFont(font_family)
            font.setPixelSize(round(font_size))
            for run in runs[index]:
                widths.append(QFontMetricsF(styled_font(font, run)).horizontalAdvance(run.text))
            if line_origins is None:
                x -= sum(widths) / 2
            anchor = "start"
            spans: List[str] = []
            offset = x
            for run, width in zip(runs[index], widths):
                spans.append(
                    '<tspan x="{}" font-weight="{}" font-style="{}">{}</tspan>'.format(
                        offset, "bold" if run.bold else "normal",
                        "italic" if run.italic else "normal", escape(run.text)))
                offset += width
            content = "".join(spans)
        text.append(
            '<text x="{}" y="{}" font-family={} font-size="{}" '
            'fill="{}" text-anchor="{}" xml:space="preserve">{}</text>'.format(
                x, baseline, quoteattr(font_family),
                font_size, text_color, anchor, content))
        baseline += font_size
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
