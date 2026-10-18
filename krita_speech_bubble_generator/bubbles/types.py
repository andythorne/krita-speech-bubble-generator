"""Bubble-specific enclosure, outline, and tail policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import random
from typing import Optional, TYPE_CHECKING

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from .geometry import (
    ellipse_path, ellipse_transform, speech_tail, thought_trail, validate_nodes,
)
from .shouting_algorithms import ShoutingAlgorithm

if TYPE_CHECKING:
    from .settings import BubbleSettings


@dataclass(frozen=True)
class BubbleCapabilities:
    thought: bool = False
    shouting: bool = False


@dataclass(frozen=True)
class BodyParameters:
    corner_radius: Optional[float] = None
    irregularity: int = 50
    seed: int = 0
    nodes: Optional[int] = None

    def __post_init__(self) -> None:
        validate_nodes(self.nodes)


@dataclass(frozen=True)
class TailParameters:
    font_size: float
    thought_size: int = 100
    irregularity: int = 0
    seed: int = 0


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
        return BodyParameters()

    def enclosure_padding(self, settings: BubbleSettings) -> float:
        return settings.font_size * (0.5 + settings.padding / 100) + settings.outline / 2

    @abstractmethod
    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        """Build this type's body without a tail."""

    def compose_tail(self, body: QPainterPath, center: QPointF,
                     tip: Optional[QPointF], parameters: TailParameters) -> QPainterPath:
        return speech_tail(body, center, tip, parameters.font_size)

    def with_algorithm(self, algorithm: ShoutingAlgorithm) -> BubbleType:
        return self


class OvalBubble(BubbleType):
    identifier = label = "Oval"

    def enclosure_padding(self, settings: BubbleSettings) -> float:
        return settings.font_size * settings.padding / 100

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        padded = _rectangular_enclosure(width, height, padding)
        ratio = min(2, padded.width() / padded.height())
        # Fit all four text-box corners, without letting short text flatten the oval.
        body_width = math.hypot(padded.width(), ratio * padded.height())
        return QRectF(0, 0, body_width, body_width / ratio)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(rect)
        return path


class RoundedBubble(BubbleType):
    identifier = label = "Rounded"

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _rectangular_enclosure(width, height, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        padding = self.enclosure_padding(settings)
        return BodyParameters(corner_radius=min(settings.font_size * 3, padding))

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        radius = min(rect.width(), rect.height()) / 2
        if parameters.corner_radius is not None:
            radius = min(radius, parameters.corner_radius)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path


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
    capabilities = BubbleCapabilities(thought=True)

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _elliptical_enclosure(width, height, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return BodyParameters(irregularity=settings.thought_irregularity,
                              seed=settings.thought_seed, nodes=settings.thought_nodes)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(rect)
        ellipse = ellipse_transform(rect)
        generator = random.Random(parameters.seed)
        amount = parameters.irregularity / 100
        count = 16 if parameters.nodes is None else parameters.nodes
        lobe_scale = 16 / count
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
        return path

    def compose_tail(self, body: QPainterPath, center: QPointF,
                     tip: Optional[QPointF], parameters: TailParameters) -> QPainterPath:
        return thought_trail(body, center, tip, parameters.font_size,
                             parameters.thought_size, parameters.irregularity,
                             parameters.seed)


class ShoutingBubble(BubbleType):
    identifier = label = "Shouting"
    capabilities = BubbleCapabilities(shouting=True)

    def __init__(self, algorithm: ShoutingAlgorithm) -> None:
        self.algorithm = algorithm

    def body_rect(self, width: float, height: float, padding: float) -> QRectF:
        return _elliptical_enclosure(width, height, padding)

    def body_parameters(self, settings: BubbleSettings) -> BodyParameters:
        return BodyParameters(irregularity=settings.shout_irregularity,
                              seed=settings.shout_seed, nodes=settings.shout_nodes)

    def body_path(self, rect: QRectF,
                  parameters: BodyParameters = BodyParameters()) -> QPainterPath:
        outline = self.algorithm.outline(
            parameters.nodes, parameters.irregularity, parameters.seed)
        return outline.to_path(ellipse_transform(rect))

    def with_algorithm(self, algorithm: ShoutingAlgorithm) -> ShoutingBubble:
        return ShoutingBubble(algorithm)
