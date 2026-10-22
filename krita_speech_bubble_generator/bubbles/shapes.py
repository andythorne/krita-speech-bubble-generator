"""Shape-owned enclosure geometry, independent of outline decoration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
from typing import List, NamedTuple, Sequence, TYPE_CHECKING, Tuple

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from .geometry import (
    ellipse_transform, oval_curve_control, oval_path, squared_ellipse_point, tail_anchor,
)

if TYPE_CHECKING:
    from .settings import BubbleSettings


def convex_hull(points: Sequence[QPointF]) -> List[QPointF]:
    coordinates = sorted({(point.x(), point.y()) for point in points})
    if len(coordinates) < 3:
        return [QPointF(x, y) for x, y in coordinates]

    def cross(a: Tuple[float, float], b: Tuple[float, float],
              c: Tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower: List[Tuple[float, float]] = []
    upper: List[Tuple[float, float]] = []
    for chain, values in ((lower, coordinates), (upper, coordinates[::-1])):
        for point in values:
            while len(chain) > 1 and cross(chain[-2], chain[-1], point) <= 0:
                chain.pop()
            chain.append(point)
    return [QPointF(x, y) for x, y in lower[:-1] + upper[:-1]]


def polygon_path(points: Sequence[QPointF]) -> QPainterPath:
    path = QPainterPath()
    if points:
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
    return path


def project_contour(contour: QPainterPath, point: QPointF) -> QPointF:
    rect = contour.boundingRect()
    center = rect.center()
    distance = math.hypot(point.x(), point.y())
    if distance < 1e-9:
        return center
    direction = QPointF(point.x() * rect.width(), point.y() * rect.height())
    length = math.hypot(direction.x(), direction.y())
    anchor = tail_anchor(contour, center, direction / length)
    return center + (anchor - center) * distance


def subdivide(points: Sequence[QPointF], iterations: int = 3) -> List[QPointF]:
    result = list(points)
    for _ in range(iterations):
        midpoints = [(point + result[(index + 1) % len(result)]) / 2
                     for index, point in enumerate(result)]
        updated: List[QPointF] = []
        for index, point in enumerate(result):
            median = (midpoints[index - 1] + midpoints[index]) / 2
            updated.extend(((point + median) / 2, midpoints[index]))
        result = updated
    return result


def smooth_enclosing(path: QPainterPath) -> QPainterPath:
    """Subdivision rounds angles; grow back to contain the requested enclosure."""
    if any(path.elementAt(index).isCurveTo()
           for index in range(path.elementCount())):
        return path
    polygon = path.toFillPolygon()
    points = [polygon[index] for index in range(len(polygon) - 1)]
    if len(points) < 3:
        return path
    center = path.boundingRect().center()
    rounded = subdivide(points)
    # Homothetic expansion preserves convexity and the subdivision profile.
    scale = 1.0
    for _ in range(80):
        result = polygon_path([center + (point - center) * scale for point in rounded])
        if all(result.contains(center + (point - center) * 0.999999)
               for point in points):
            return result
        scale *= 1.025
    return path


@dataclass(frozen=True)
class ShapeCapabilities:
    squareness: bool = False


class ShapeLayout(NamedTuple):
    body_rect: QRectF
    text_rect: QRectF
    contour: QPainterPath


class BubbleShape(ABC):
    identifier: str
    label: str
    capabilities = ShapeCapabilities()

    def padding(self, settings: BubbleSettings) -> Tuple[float, float]:
        vertical = settings.oval_vertical_padding if settings.oval_custom else settings.padding
        return (2 * (settings.font_size * settings.padding / 100 + settings.outline / 2),
                settings.font_size * vertical / 100 + settings.outline / 2)

    @abstractmethod
    def contour(self, bounds: QRectF, lines: Sequence[QRectF],
                settings: BubbleSettings) -> QPainterPath:
        """Enclose centered measured lettering and shape-owned padding."""

    def layout(self, bounds: QRectF, lines: Sequence[QRectF],
               settings: BubbleSettings) -> ShapeLayout:
        contour = self.contour(bounds, lines, settings)
        box = contour.boundingRect()
        contour.translate(-box.left(), -box.top())
        text_rect = bounds.translated(-box.left(), -box.top())
        return ShapeLayout(QRectF(0, 0, box.width(), box.height()), text_rect, contour)

    def project(self, contour: QPainterPath, point: QPointF,
                settings: BubbleSettings) -> QPointF:
        """Project normalized decoration coordinates onto this shape's contour."""
        return project_contour(contour, point)

    def rounded_contour(self, contour: QPainterPath, radius: float) -> QPainterPath:
        if any(contour.elementAt(index).isCurveTo()
               for index in range(contour.elementCount())):
            return contour
        return smooth_enclosing(contour)


class OvalShape(BubbleShape):
    identifier = label = "Oval"
    capabilities = ShapeCapabilities(squareness=True)

    def project(self, contour: QPainterPath, point: QPointF,
                settings: BubbleSettings) -> QPointF:
        squareness = settings.oval_squareness if settings.oval_custom else 0
        return ellipse_transform(contour.boundingRect()).map(
            squared_ellipse_point(point, squareness))

    def contour(self, bounds: QRectF, lines: Sequence[QRectF],
                settings: BubbleSettings) -> QPainterPath:
        horizontal, vertical = self.padding(settings)
        squareness = settings.oval_squareness if settings.oval_custom else 0
        if not settings.oval_custom:
            padded_width = max(1, bounds.width() + 2 * horizontal)
            padded_height = max(1, bounds.height() + 2 * vertical)
            ratio = min(2, padded_width / padded_height)
            width = math.hypot(padded_width, ratio * padded_height)
            height = width / ratio
            return oval_path(QRectF(-width / 2, -height / 2, width, height))
        corner = 0.5 + 0.375 * oval_curve_control(squareness)
        width = max(1, (bounds.width() + 2 * horizontal) / corner)
        height = max(1, (bounds.height() + 2 * vertical) / corner)
        return oval_path(QRectF(-width / 2, -height / 2, width, height), squareness)


class SquareShape(BubbleShape):
    identifier = label = "Square"

    def rounded_contour(self, contour: QPainterPath, radius: float) -> QPainterPath:
        rect = contour.boundingRect()
        radius = min(radius, min(rect.width(), rect.height()) * 0.2)
        # Enclose the padded rectangle's corners, retaining long straight edges.
        extra = radius * (1 - 1 / math.sqrt(2))
        rect.adjust(-extra, -extra, extra, extra)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def contour(self, bounds: QRectF, lines: Sequence[QRectF],
                settings: BubbleSettings) -> QPainterPath:
        horizontal, vertical = self.padding(settings)
        rect = bounds.adjusted(-horizontal, -vertical, horizontal, vertical)
        rect.setWidth(max(1, rect.width()))
        rect.setHeight(max(1, rect.height()))
        path = QPainterPath()
        path.addRect(rect)
        return path


class TracingShape(BubbleShape):
    identifier = label = "Tracing"

    def contour(self, bounds: QRectF, lines: Sequence[QRectF],
                settings: BubbleSettings) -> QPainterPath:
        horizontal, vertical = self.padding(settings)
        corners: List[QPointF] = []
        padded: List[QPointF] = []
        for line in lines:
            safe = QRectF(line)
            if safe.width() < 1:
                safe.adjust(-0.5, 0, 0.5, 0)
            if safe.height() < 1:
                safe.adjust(0, -0.5, 0, 0.5)
            corners.extend((safe.topLeft(), safe.topRight(), safe.bottomRight(), safe.bottomLeft()))
            safe.adjust(-horizontal, -vertical, horizontal, vertical)
            padded.extend((safe.topLeft(), safe.topRight(), safe.bottomRight(), safe.bottomLeft()))
        hull = convex_hull(corners)
        # Polygon area centroid, not the mean of unevenly spaced hull vertices.
        area = moment_x = moment_y = 0.0
        for index, point in enumerate(hull):
            other = hull[(index + 1) % len(hull)]
            cross = point.x() * other.y() - other.x() * point.y()
            area += cross
            moment_x += (point.x() + other.x()) * cross
            moment_y += (point.y() + other.y()) * cross
        center = (QPointF(moment_x / (3 * area), moment_y / (3 * area))
                  if abs(area) > 1e-9 else bounds.center())
        supports: List[Tuple[QPointF, float]] = []
        for index, point in enumerate(hull):
            edge = hull[(index + 1) % len(hull)] - point
            normal = QPointF(edge.y(), -edge.x()) / math.hypot(edge.x(), edge.y())
            if (point.x() - center.x()) * normal.x() + (
                    point.y() - center.y()) * normal.y() < 0:
                normal = -normal
            support = (normal.x() * point.x() + normal.y() * point.y()
                       + horizontal * abs(normal.x()) + vertical * abs(normal.y()))
            supports.append((normal, support))
        # Move vertices to the intersections of outward-offset supporting edges.
        # This protects both padding axes even at shallow text-hull corners.
        displaced: List[QPointF] = []
        for index, (normal, support) in enumerate(supports):
            previous, previous_support = supports[index - 1]
            determinant = previous.x() * normal.y() - normal.x() * previous.y()
            if abs(determinant) < 1e-9:
                return polygon_path(convex_hull(padded))
            displaced.append(QPointF(
                (previous_support * normal.y() - support * previous.y()) / determinant,
                (previous.x() * support - normal.x() * previous_support) / determinant))
        return polygon_path(displaced)
