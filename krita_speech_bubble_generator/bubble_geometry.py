import math
import random
from xml.sax.saxutils import escape, quoteattr

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QTransform


STYLES = ("Oval", "Rounded", "Square", "Thought", "Shouting")
SHOUTING_SHAPES = ("Balanced", "Angular", "Punchy", "Expressive")
MIN_NODES = 8
MAX_NODES = 64


def ellipse_path(center, radius_x, radius_y, angle=0):
    path = QPainterPath()
    path.addEllipse(QPointF(), radius_x, radius_y)
    transform = QTransform().translate(center.x(), center.y()).rotate(angle)
    return transform.map(path)


def body_path(rect, style, corner_radius=None, irregularity=50, seed=0,
              shouting_shape="Balanced", nodes=None):
    if nodes is not None and (type(nodes) is not int or not MIN_NODES <= nodes <= MAX_NODES):
        raise ValueError("Invalid node count")
    path = QPainterPath()
    center = rect.center()
    ellipse = QTransform().translate(center.x(), center.y()).scale(
        rect.width() / 2, rect.height() / 2)
    if style == "Square":
        path.addRect(rect)
    elif style == "Oval":
        path.addEllipse(rect)
    elif style == "Rounded":
        radius = min(rect.width(), rect.height()) / 2
        if corner_radius is not None:
            radius = min(radius, corner_radius)
        path.addRoundedRect(rect, radius, radius)
    elif style == "Thought":
        path.addEllipse(rect)
        generator = random.Random(seed)
        amount = irregularity / 100
        count = 16 if nodes is None else nodes
        lobe_scale = 16 / count
        # Overlapping lobes give the cloud a single, seam-free outline.
        for i in range(count):
            angle = 2 * math.pi / count * (i + generator.uniform(-0.28, 0.28) * amount)
            distance = 0.86 + generator.uniform(-0.07, 0.07) * amount
            distance = 1 - (1 - distance) * lobe_scale
            radius_x = 0.24 * lobe_scale * (1 + generator.uniform(-0.35, 0.5) * amount)
            radius_y = 0.30 * lobe_scale * (1 + generator.uniform(-0.35, 0.5) * amount)
            rotation = generator.uniform(-55, 55) * amount
            lobe = ellipse_path(
                QPointF(distance * math.cos(angle), distance * math.sin(angle)),
                radius_x, radius_y, rotation)
            path = path.united(ellipse.map(lobe))
    elif style == "Shouting":
        if shouting_shape not in SHOUTING_SHAPES:
            raise ValueError("Unknown shouting shape: " + str(shouting_shape))
        generator = random.Random(seed)
        amount = irregularity / 100
        count = nodes if nodes is not None else (18 if shouting_shape == "Punchy" else 24)
        spacing = 0.45 if shouting_shape == "Expressive" else 0.35
        height = 0.16 if shouting_shape == "Punchy" else 0.25
        height_variation = 0.035 if shouting_shape == "Expressive" else 0.025
        # Broad sectors at low counts need less jitter to keep shoulders outside the text ellipse.
        tip_fraction = 0.6 if shouting_shape == "Expressive" else 0.5
        safe_sector = math.acos(1.03 / (1 + height - height_variation)) / tip_fraction
        sector = 2 * math.pi / count
        spacing = min(spacing, (safe_sector - sector) / (safe_sector + sector))
        widths = [1 + generator.uniform(-spacing, spacing) * amount for _ in range(count)]
        step = 2 * math.pi / sum(widths)
        angle = generator.uniform(0, 2 * math.pi) * amount
        boundaries = [angle]
        for width in widths:
            boundaries.append(boundaries[-1] + width * step)
        tips = []
        for i in range(count):
            angle = (boundaries[i] + boundaries[i + 1]) / 2
            if shouting_shape == "Expressive":
                angle += (boundaries[i + 1] - boundaries[i]) * generator.uniform(
                    -0.1, 0.1) * amount
            radius = 1 + height + generator.uniform(-height_variation, height_variation) * amount
            tips.append((angle, QPointF(radius * math.cos(angle), radius * math.sin(angle))))
        path.moveTo(ellipse.map(tips[0][1]))
        for i, (angle, _) in enumerate(tips):
            next_angle, next_tip = tips[(i + 1) % len(tips)]
            if i == len(tips) - 1:
                next_angle += 2 * math.pi
            middle = boundaries[i + 1]
            radius = 1.02 + generator.uniform(-0.01, 0.01) * amount
            valley = QPointF(radius * math.cos(middle), radius * math.sin(middle))
            if shouting_shape == "Angular":
                path.lineTo(ellipse.map(valley))
                path.lineTo(ellipse.map(next_tip))
                continue
            tangent = QPointF(-math.sin(middle), math.cos(middle))
            # Keep the valley smooth and its controls inside adjacent angular sectors.
            shoulder = 0.95 if shouting_shape == "Punchy" else 0.9
            reach = math.tan(min(middle - angle, next_angle - middle)) * radius * shoulder
            path.quadTo(ellipse.map(valley - tangent * reach), ellipse.map(valley))
            path.quadTo(ellipse.map(valley + tangent * reach), ellipse.map(next_tip))
        path.closeSubpath()
    else:
        raise ValueError("Unknown bubble style: " + style)
    return path


def outline_anchor(path, center, direction):
    """Intersect a ray with the actual outline, including cloud lobes/spikes."""
    distances = []
    polygon = path.toFillPolygon()
    for start, end in zip(polygon, polygon[1:]):
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


def tail_tip(path, center, angle, length):
    direction = QPointF(math.cos(angle), math.sin(angle))
    return outline_anchor(path, center, direction) + direction * length


def bubble_path(body, center, tip, style, font_size, thought_size=100,
                irregularity=0, seed=0):
    if tip is None or body.contains(tip):
        return QPainterPath(body)
    offset = tip - center
    distance = math.hypot(offset.x(), offset.y())
    if distance < 1e-9:
        return QPainterPath(body)
    direction = offset / distance
    anchor = outline_anchor(body, center, direction)
    length = math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y())
    if length < 1e-6:
        return QPainterPath(body)
    if style == "Thought":
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


def path_data(path):
    commands = []
    start = None
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


def bubble_svg(path, lines, text_rect, font_family, font_size, cap_height,
               fill, stroke, stroke_width, text_color, view_box):
    text = []
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
