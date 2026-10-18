"""Conservative recovery of the original plugin's outline-and-text SVG layers."""

from dataclasses import dataclass
import math
import re
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QTransform

from ..bubbles.settings import BubbleSettings, SettingsError, settings_from_dict


_NUMBER = r"[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(r"[MLCQZ]|" + _NUMBER)
_UNSUPPORTED = (
    "Select a vector layer containing just one old bubble outline and its text. "
    "Grouped bubbles, multiple bubbles and layers with other artwork cannot be imported."
)


@dataclass(frozen=True)
class LegacyBubble:
    settings: BubbleSettings
    body: QRectF
    transform: QTransform
    shape_count: int
    tip: Optional[QPointF] = None

    def placement(self, generated: QRectF) -> QTransform:
        """Map the regenerated body onto the old body in document points."""
        return (
            QTransform.fromTranslate(-generated.center().x(), -generated.center().y())
            * QTransform.fromScale(self.body.width() / generated.width(),
                                   self.body.height() / generated.height())
            * QTransform.fromTranslate(self.body.center().x(), self.body.center().y())
            * self.transform
        )


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _attributes(element: ET.Element) -> Dict[str, str]:
    values = dict(element.attrib)
    for declaration in values.get("style", "").split(";"):
        key, separator, value = declaration.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _number(value: str) -> float:
    if re.fullmatch(_NUMBER, value.strip()) is None:
        raise SettingsError("Unsupported number in the old bubble SVG.")
    result = float(value)
    if not math.isfinite(result):
        raise SettingsError("Invalid number in the old bubble SVG.")
    return result


def _transform(element: ET.Element) -> QTransform:
    value = element.get("transform", "").strip()
    if not value:
        return QTransform()
    match = re.fullmatch(r"(matrix|translate)\s*\(([^()]*)\)", value)
    if match is None:
        raise SettingsError("Unsupported transform in the old bubble SVG.")
    numbers = [_number(part) for part in re.split(r"[\s,]+", match[2].strip())]
    if match[1] == "matrix" and len(numbers) == 6:
        transform = QTransform(*numbers)
    elif match[1] == "translate" and len(numbers) in (1, 2):
        transform = QTransform.fromTranslate(
            numbers[0], numbers[1] if len(numbers) == 2 else 0)
    else:
        raise SettingsError("Unsupported transform in the old bubble SVG.")
    if not transform.isInvertible():
        raise SettingsError("The old bubble transform is not invertible.")
    return transform


def _outline(data: str) -> Tuple[QPainterPath, List[Tuple[str, QPointF]], bool]:
    """Read only the absolute path commands emitted by the old plugin/Krita."""
    if _TOKEN.sub("", data).strip(" ,\t\r\n"):
        raise SettingsError("Unsupported path in the old bubble SVG.")
    tokens = _TOKEN.findall(data)
    if not tokens or tokens[0] != "M" or tokens[-1] != "Z":
        raise SettingsError(_UNSUPPORTED)
    path = QPainterPath()
    vertices: List[Tuple[str, QPointF]] = []
    curved = False
    index = 0
    command = ""
    while index < len(tokens):
        if tokens[index] in ("M", "L", "C", "Q", "Z"):
            command = tokens[index]
            index += 1
        if command == "Z":
            if index != len(tokens):
                raise SettingsError(_UNSUPPORTED)
            path.closeSubpath()
            break
        count = {"M": 2, "L": 2, "C": 6, "Q": 4}.get(command, 0)
        if not count or index + count > len(tokens):
            raise SettingsError("Invalid path in the old bubble SVG.")
        values = [_number(token) for token in tokens[index:index + count]]
        index += count
        point = QPointF(values[-2], values[-1])
        if command == "M":
            if vertices:
                raise SettingsError(_UNSUPPORTED)
            path.moveTo(point)
        elif command == "L":
            path.lineTo(point)
        elif command == "C":
            path.cubicTo(values[0], values[1], values[2], values[3], values[4], values[5])
            curved = True
        else:
            path.quadTo(values[0], values[1], values[2], values[3])
            curved = True
        vertices.append((command, point))
        if command == "M":
            command = "L"
    if len(vertices) < 5 or path.boundingRect().isEmpty():
        raise SettingsError(_UNSUPPORTED)
    return path, vertices, curved


def read_legacy_bubble(svg: str) -> LegacyBubble:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise SettingsError("Cannot read the old bubble SVG: " + str(error)) from error
    if _tag(root) != "svg" or root.get("transform"):
        raise SettingsError(_UNSUPPORTED)
    shapes = [child for child in root if _tag(child) != "defs"]
    if (not shapes or _tag(shapes[0]) != "path" or len(shapes) < 2
            or any(_tag(child) != "text" for child in shapes[1:])):
        raise SettingsError(_UNSUPPORTED)
    outline = shapes[0]
    if list(outline):
        raise SettingsError(_UNSUPPORTED)
    attributes = _attributes(outline)
    if attributes.get("stroke-linejoin") != "round":
        raise SettingsError("The outline does not match an original-plugin bubble.")
    path, vertices, curved = _outline(attributes.get("d", ""))
    transform = _transform(outline)
    inverse, _ = transform.inverted()
    text_shapes = shapes[1:]
    text_attributes = [_attributes(element) for element in text_shapes]
    first = text_attributes[0]
    font_size = first.get("font-size", "")
    size = _number(font_size[:-2] if font_size.endswith(("px", "pt")) else font_size)
    if not size.is_integer():
        raise SettingsError("The old bubble has an unsupported font size.")
    family = first.get("font-family", "").strip("'\"")
    if not family:
        raise SettingsError("The old bubble has no recoverable font.")
    anchors: List[QPointF] = []
    lines: List[str] = []
    for element, values in zip(text_shapes, text_attributes):
        if (values.get("text-anchor") != "middle"
                or values.get("font-size") != first.get("font-size")
                or values.get("font-family") != first.get("font-family")
                or values.get("fill", "#000000") != first.get("fill", "#000000")
                or any(_tag(child) != "tspan" for child in element.iter()
                       if child is not element)):
            raise SettingsError("The text does not match an original-plugin bubble.")
        relative = _transform(element) * inverse
        if any(abs(actual - expected) > 1e-5 for actual, expected in (
                (relative.m11(), 1), (relative.m12(), 0),
                (relative.m21(), 0), (relative.m22(), 1))):
            raise SettingsError("The old bubble text and outline have different transforms.")
        anchors.append(relative.map(QPointF(_number(values.get("x", "")),
                                            _number(values.get("y", "")))))
        lines.append("".join(element.itertext()))
    if any(abs(point.x() - anchors[0].x()) > 0.5 for point in anchors):
        raise SettingsError("The old bubble text lines are not aligned.")
    if any(anchors[i].y() <= anchors[i - 1].y() for i in range(1, len(anchors))):
        raise SettingsError("The old bubble text lines are not in reading order.")

    # A curved upstream outline has exactly two straight edges meeting at its tip.
    straight = [index for index, (command, _) in enumerate(vertices) if command == "L"]
    tip = None
    if curved and straight:
        if len(straight) != 2 or straight[1] != straight[0] + 1:
            raise SettingsError("The old bubble tail cannot be recovered safely.")
        tip_index = straight[0]
        tip = vertices[tip_index][1]
        body_points = [point for index, (_, point) in enumerate(vertices)
                       if index != tip_index]
        body = QRectF(
            QPointF(min(point.x() for point in body_points),
                    min(point.y() for point in body_points)),
            QPointF(max(point.x() for point in body_points),
                    max(point.y() for point in body_points)))
    else:
        body = path.boundingRect()
    if body.isEmpty() or any(not body.adjusted(-1, -1, 1, 1).contains(point)
                             for point in anchors):
        raise SettingsError("The old bubble text is outside its outline.")
    length = 0
    angle = math.pi / 4
    if tip is not None:
        x = min(0, tip.x() - body.left()) + max(0, tip.x() - body.right())
        y = min(0, tip.y() - body.top()) + max(0, tip.y() - body.bottom())
        if not x and not y:
            raise SettingsError("The old bubble tail tip is inside its body.")
        angle = math.atan2(tip.y() - body.center().y(), tip.x() - body.center().x())
        # Keep the box extension here; import fits the original tip to the new body.
        length = round(math.hypot(x, y))
    values = BubbleSettings().to_dict()
    values.update(
        text=" ".join(" ".join(lines).split()),
        font=family, font_size=int(size), fill=attributes.get("fill", "#000000"),
        stroke=attributes.get("stroke", "#000000"),
        text_color=first.get("fill", "#000000"),
        outline=round(_number(attributes.get("stroke-width", "1"))),
        autocenter=True, line_length=0, padding=0, tail_angle=angle,
        tail_length=min(length, int(size) * 10))
    return LegacyBubble(settings_from_dict(values), body, transform, len(shapes), tip)
