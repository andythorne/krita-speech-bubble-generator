"""Bubble-specific enclosure, outline, and tail policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
import math
import random
from typing import Callable, Iterable, Optional, Sequence, TYPE_CHECKING, Tuple

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from .geometry import (
    ellipse_path, ellipse_transform, oval_curve_control, oval_path, speech_tail,
    squared_ellipse_point, thought_trail, validate_nodes,
)
from .shouting_algorithms import ShoutingAlgorithm
from .shapes import BubbleShape, project_contour, smooth_enclosing

if TYPE_CHECKING:
    from .settings import BubbleSettings


@dataclass(frozen=True)
class BubbleCapabilities:
    thought: bool = False
    shouting: bool = False
    custom_enclosure: bool = False


@dataclass(frozen=True)
class BodyParameters:
    corner_radius: Optional[float] = None
    irregularity: int = 50
    seed: int = 0
    nodes: Optional[int] = None
    squareness: int = 0

    def __post_init__(self) -> None:
        validate_nodes(self.nodes)


@dataclass(frozen=True)
class TailParameters:
    font_size: float
    thought_size: int = 100
    irregularity: int = 0
    seed: int = 0
    curve: int = 0
    curve_direction: str = "Up"
    anchor: Optional[QPointF] = None
    thought_blobs: int = 3
    outline_width: float = 0


def _thought_lobes(
        parameters: BodyParameters) -> Iterable[Tuple[QPointF, float, float, float]]:
    generator = random.Random(parameters.seed)
    amount = parameters.irregularity / 100
    count = 16 if parameters.nodes is None else parameters.nodes
    scale = 16 / count
    for index in range(count):
        angle = 2 * math.pi / count * (index + generator.uniform(-0.28, 0.28) * amount)
        distance = 0.86 + generator.uniform(-0.07, 0.07) * amount
        distance = 1 - (1 - distance) * scale
        radius_x = 0.24 * scale * (1 + generator.uniform(-0.35, 0.5) * amount)
        radius_y = 0.30 * scale * (1 + generator.uniform(-0.35, 0.5) * amount)
        rotation = generator.uniform(-55, 55) * amount
        yield (QPointF(distance * math.cos(angle), distance * math.sin(angle)),
               radius_x, radius_y, rotation)


def _rectangular_enclosure(width: float, height: float, padding: float) -> QRectF:
    return QRectF(0, 0, max(1, width + 4 * padding), max(1, height + 2 * padding))


def _elliptical_enclosure(width: float, height: float, padding: float) -> QRectF:
    return QRectF(0, 0, max(1, (width + 4 * padding) * math.sqrt(2)),
                  max(1, (height + 2 * padding) * math.sqrt(2)))


class BubbleType(ABC):
    identifier: str
    label: str
    capabilities = BubbleCapabilities()

    @abstractmethod
    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        """Enclose the measured text and padding with a stable body origin."""

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return BodyParameters(
            squareness=settings.oval_squareness
            if self.capabilities.custom_enclosure and settings.oval_custom else 0)

    def enclosure_padding(self, settings: BubbleSettings) -> float:
        return settings.font_size * settings.padding / 100 + settings.outline / 2

    def enclose_text(self, width: float, height: float,
                     settings: BubbleSettings) -> QRectF:
        if self.capabilities.custom_enclosure and settings.oval_custom:
            horizontal = self.enclosure_padding(settings)
            vertical = (settings.font_size * settings.oval_vertical_padding / 100
                        + settings.outline / 2)
            # Each quarter-curve's midpoint fits a padded text-box corner.
            corner = 0.5 + 0.375 * oval_curve_control(settings.oval_squareness)
            return QRectF(0, 0, max(1, (width + 4 * horizontal) / corner),
                          max(1, (height + 2 * vertical) / corner))
        return self.body_rect(width, height, self.enclosure_padding(settings))

    @abstractmethod
    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        """Build this type's body without a tail."""

    def compose_tail(self, body: QPainterPath, center: QPointF,
                     tip: Optional[QPointF], parameters: TailParameters) -> QPainterPath:
        return speech_tail(body, center, tip, parameters.font_size,
                           parameters.curve, parameters.curve_direction, parameters.anchor)

    def with_algorithm(self, algorithm: ShoutingAlgorithm) -> BubbleType:
        return self

    def with_shape(self, shape: BubbleShape) -> BubbleType:
        return ComposedBubble(self, shape)

    def layout_body(self, bounds: QRectF, lines: Sequence[QRectF],
                    settings: BubbleSettings) -> Tuple[QRectF, QRectF, QPainterPath]:
        rect = self.enclose_text(bounds.width(), bounds.height(), settings)
        text = QRectF((rect.width() - bounds.width()) / 2,
                      (rect.height() - bounds.height()) / 2,
                      bounds.width(), bounds.height())
        return rect, text, self.body_path(rect, self.body_parameters(settings))

    def decorate(self, contour: QPainterPath, parameters: BodyParameters,
                 project: Optional[Callable[[QPointF], QPointF]] = None) -> QPainterPath:
        return contour

    def decorate_shape(self, contour: QPainterPath, parameters: BodyParameters,
                       shape: BubbleShape, settings: BubbleSettings) -> QPainterPath:
        return self.decorate(
            contour, parameters, lambda point: shape.project(contour, point, settings))


class ComposedBubble(BubbleType):
    """One composition adapter, not a subclass for each shape/style pair."""

    def __init__(self, style: BubbleType, shape: BubbleShape) -> None:
        self.style = style
        self.shape = shape
        self.identifier = style.identifier
        self.label = style.label
        self.capabilities = style.capabilities

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return self.style.body_rect(width, height, padding)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        return self.style.body_path(rect, parameters)

    def layout_body(self, bounds: QRectF, lines: Sequence[QRectF],
                    settings: BubbleSettings) -> Tuple[QRectF, QRectF, QPainterPath]:
        rect, text_rect, contour = self.shape.layout(bounds, lines, settings)
        body = self.style.decorate_shape(
            contour, self.style.body_parameters(settings), self.shape, settings)
        # Decoration may extend the body, but never changes the lettering origin.
        return rect, text_rect, body

    def compose_tail(self, body: QPainterPath, center: QPointF,
                     tip: Optional[QPointF], parameters: TailParameters) -> QPainterPath:
        return self.style.compose_tail(body, center, tip, parameters)


class SharpBubble(BubbleType):
    identifier = label = "Sharp"

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _rectangular_enclosure(width, height, padding)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        path = QPainterPath()
        path.addRect(rect)
        return path


class OvalBubble(BubbleType):
    identifier = label = "Oval"
    capabilities = BubbleCapabilities(custom_enclosure=True)

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        padded = _rectangular_enclosure(width, height, padding)
        ratio = min(2, padded.width() / padded.height())
        # Fit all four text-box corners, without letting short text flatten the oval.
        body_width = math.hypot(padded.width(), ratio * padded.height())
        return QRectF(0, 0, body_width, body_width / ratio)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        return oval_path(rect, parameters.squareness)


class RoundedBubble(BubbleType):
    identifier = label = "Rounded"

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _rectangular_enclosure(width, height, padding)

    def _corner_radius(self, settings: BubbleSettings) -> float:
        return min(settings.font_size * 3,
                   settings.font_size * 0.5 + self.enclosure_padding(settings))

    def enclose_text(self, width: float, height: float,
                     settings: BubbleSettings) -> QRectF:
        padding = self.enclosure_padding(settings)
        radius = self._corner_radius(settings)
        horizontal = max(0, radius - 2 * padding)
        vertical = max(0, radius - padding)
        inner_radius = max(0, radius - settings.outline / 2)
        extra = 0.0
        if horizontal ** 2 + vertical ** 2 > inner_radius ** 2:
            # Fit text corners inside the rounded outline's inner edge.
            extra = (horizontal + vertical - math.sqrt(
                2 * inner_radius ** 2 - (horizontal - vertical) ** 2)) / 2
        return self.body_rect(width + 2 * extra, height + 2 * extra, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return BodyParameters(corner_radius=self._corner_radius(settings))

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        radius = min(rect.width(), rect.height()) / 2
        if parameters.corner_radius is not None:
            radius = min(radius, parameters.corner_radius)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def decorate(self, contour: QPainterPath, parameters: BodyParameters,
                 project: Optional[Callable[[QPointF], QPointF]] = None) -> QPainterPath:
        if any(contour.elementAt(index).isCurveTo()
               for index in range(contour.elementCount())):
            return contour
        return smooth_enclosing(contour)

    def decorate_shape(self, contour: QPainterPath, parameters: BodyParameters,
                       shape: BubbleShape, settings: BubbleSettings) -> QPainterPath:
        return shape.rounded_contour(
            contour, self._corner_radius(settings)
            if parameters.corner_radius is None else parameters.corner_radius)


class SquareBubble(BubbleType):
    identifier = label = "Square"

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _rectangular_enclosure(width, height, padding)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        path = QPainterPath()
        path.addRect(rect)
        return path


class ThoughtBubble(BubbleType):
    identifier = label = "Thought"
    capabilities = BubbleCapabilities(thought=True, custom_enclosure=True)

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _elliptical_enclosure(width, height, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return replace(super().body_parameters(settings),
                       irregularity=settings.thought_irregularity,
                       seed=settings.thought_seed, nodes=settings.thought_nodes)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        path = oval_path(rect, parameters.squareness)
        ellipse = ellipse_transform(rect)
        for center, radius_x, radius_y, rotation in _thought_lobes(parameters):
            lobe = ellipse_path(
                squared_ellipse_point(center, parameters.squareness),
                radius_x, radius_y, rotation)
            path = path.united(ellipse.map(lobe))
        return path

    def compose_tail(self, body: QPainterPath, center: QPointF,
                     tip: Optional[QPointF], parameters: TailParameters) -> QPainterPath:
        return thought_trail(body, center, tip, parameters.font_size,
                             parameters.thought_size, parameters.irregularity,
                             parameters.seed, parameters.curve,
                             parameters.curve_direction, parameters.anchor,
                             thought_blobs=parameters.thought_blobs,
                             outline_width=parameters.outline_width)

    def decorate(self, contour: QPainterPath, parameters: BodyParameters,
                 project: Optional[Callable[[QPointF], QPointF]] = None) -> QPainterPath:
        path = QPainterPath(contour)
        projection: Callable[[QPointF], QPointF] = (
            project or (lambda point: project_contour(contour, point)))
        rect = contour.boundingRect()
        for normalized, radius_x, radius_y, rotation in _thought_lobes(parameters):
            center = projection(normalized)
            lobe = ellipse_path(QPointF(), radius_x, radius_y, rotation)
            transform = ellipse_transform(QRectF(
                center.x() - rect.width() / 2, center.y() - rect.height() / 2,
                rect.width(), rect.height()))
            path = path.united(transform.map(lobe))
        return path


class ShoutingBubble(BubbleType):
    identifier = label = "Shouting"
    capabilities = BubbleCapabilities(shouting=True, custom_enclosure=True)

    def __init__(self, algorithm: ShoutingAlgorithm) -> None:
        self.algorithm = algorithm

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _elliptical_enclosure(width, height, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return replace(super().body_parameters(settings),
                       irregularity=settings.shout_irregularity,
                       seed=settings.shout_seed, nodes=settings.shout_nodes)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        outline = self.algorithm.outline(
            parameters.nodes, parameters.irregularity, parameters.seed)
        return outline.to_path(ellipse_transform(rect), parameters.squareness)

    def with_algorithm(self, algorithm: ShoutingAlgorithm) -> ShoutingBubble:
        return ShoutingBubble(algorithm)

    def decorate(self, contour: QPainterPath, parameters: BodyParameters,
                 project: Optional[Callable[[QPointF], QPointF]] = None) -> QPainterPath:
        outline = self.algorithm.outline(parameters.nodes, parameters.irregularity, parameters.seed)
        start, segments = outline
        projection: Callable[[QPointF], QPointF] = (
            project or (lambda point: project_contour(contour, point)))
        path = QPainterPath()
        path.moveTo(projection(start))
        for segment in segments:
            if len(segment) == 1:
                path.lineTo(projection(segment[0]))
            else:
                path.quadTo(projection(segment[0]), projection(segment[1]))
        path.closeSubpath()
        return path if path.contains(contour) else contour.united(path)
