"""Seeded, normalized shouting contours and their interchangeable policies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import random
from typing import Callable, List, NamedTuple, Optional, Tuple, Union

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QPainterPath, QTransform

from .geometry import validate_nodes


OutlineSegment = Union[Tuple[QPointF], Tuple[QPointF, QPointF]]
OutlineSegments = Tuple[OutlineSegment, ...]
ValleyTracer = Callable[
    [float, float, float, float, QPointF, QPointF, float], OutlineSegments]


class ShoutingOutline(NamedTuple):
    start: QPointF
    segments: OutlineSegments

    def to_path(self, transform: Optional[QTransform] = None) -> QPainterPath:
        """Map the normalized commands before Qt converts quadratics to cubics."""
        transform = QTransform() if transform is None else transform
        path = QPainterPath()
        start, segments = self
        path.moveTo(transform.map(start))
        for segment in segments:
            if len(segment) == 1:
                path.lineTo(transform.map(segment[0]))
            else:
                path.quadTo(transform.map(segment[0]), transform.map(segment[1]))
        path.closeSubpath()
        return path


class ShoutingAlgorithm(ABC):
    identifier: str
    label: str
    legacy_nodes: int = 24

    @abstractmethod
    def outline(self, nodes: Optional[int] = None, irregularity: int = 50,
                seed: int = 0) -> ShoutingOutline:
        """Return closed contour commands in a unit ellipse's coordinates."""


def _linear_valley(angle: float, next_angle: float, middle: float, radius: float,
                   valley: QPointF, next_tip: QPointF, shoulder: float) -> OutlineSegments:
    return ((valley,), (next_tip,))


def _curved_valley(angle: float, next_angle: float, middle: float, radius: float,
                   valley: QPointF, next_tip: QPointF, shoulder: float) -> OutlineSegments:
    tangent = QPointF(-math.sin(middle), math.cos(middle))
    reach = math.tan(min(middle - angle, next_angle - middle)) * radius * shoulder
    return ((valley - tangent * reach, valley),
            (valley + tangent * reach, next_tip))


@dataclass(frozen=True)
class _SpikePolicy:
    spacing: float
    height: float
    height_variation: float
    tip_fraction: float
    lean: float
    shoulder: float
    trace: ValleyTracer


def _spiked_outline(nodes: int, irregularity: int, seed: int,
                    policy: _SpikePolicy) -> ShoutingOutline:
    validate_nodes(nodes)
    generator = random.Random(seed)
    amount = irregularity / 100
    safe_sector = math.acos(
        1.03 / (1 + policy.height - policy.height_variation)) / policy.tip_fraction
    sector = 2 * math.pi / nodes
    spacing = min(policy.spacing, (safe_sector - sector) / (safe_sector + sector))
    widths = [1 + generator.uniform(-spacing, spacing) * amount for _ in range(nodes)]
    step = 2 * math.pi / sum(widths)
    angle = generator.uniform(0, 2 * math.pi) * amount
    boundaries = [angle]
    for width in widths:
        boundaries.append(boundaries[-1] + width * step)
    tips: List[Tuple[float, QPointF]] = []
    for i in range(nodes):
        angle = (boundaries[i] + boundaries[i + 1]) / 2
        if policy.lean:
            angle += (boundaries[i + 1] - boundaries[i]) * generator.uniform(
                -policy.lean, policy.lean) * amount
        radius = 1 + policy.height + generator.uniform(
            -policy.height_variation, policy.height_variation) * amount
        tips.append((angle, QPointF(radius * math.cos(angle), radius * math.sin(angle))))
    segments: List[OutlineSegment] = []
    for i, (angle, _) in enumerate(tips):
        next_angle, next_tip = tips[(i + 1) % len(tips)]
        if i == len(tips) - 1:
            next_angle += 2 * math.pi
        middle = boundaries[i + 1]
        radius = 1.02 + generator.uniform(-0.01, 0.01) * amount
        valley = QPointF(radius * math.cos(middle), radius * math.sin(middle))
        segments.extend(policy.trace(
            angle, next_angle, middle, radius, valley, next_tip, policy.shoulder))
    return ShoutingOutline(tips[0][1], tuple(segments))


class BalancedShouting(ShoutingAlgorithm):
    identifier = label = "Balanced"
    _policy = _SpikePolicy(0.35, 0.25, 0.025, 0.5, 0, 0.9, _curved_valley)

    def outline(self, nodes: Optional[int] = None, irregularity: int = 50,
                seed: int = 0) -> ShoutingOutline:
        return _spiked_outline(
            self.legacy_nodes if nodes is None else nodes, irregularity, seed, self._policy)


class AngularShouting(ShoutingAlgorithm):
    identifier = label = "Angular"
    _policy = _SpikePolicy(0.35, 0.25, 0.025, 0.5, 0, 0.9, _linear_valley)

    def outline(self, nodes: Optional[int] = None, irregularity: int = 50,
                seed: int = 0) -> ShoutingOutline:
        return _spiked_outline(
            self.legacy_nodes if nodes is None else nodes, irregularity, seed, self._policy)


class PunchyShouting(ShoutingAlgorithm):
    identifier = label = "Punchy"
    legacy_nodes = 18
    _policy = _SpikePolicy(0.35, 0.16, 0.025, 0.5, 0, 0.95, _curved_valley)

    def outline(self, nodes: Optional[int] = None, irregularity: int = 50,
                seed: int = 0) -> ShoutingOutline:
        return _spiked_outline(
            self.legacy_nodes if nodes is None else nodes, irregularity, seed, self._policy)


class ExpressiveShouting(ShoutingAlgorithm):
    identifier = label = "Expressive"
    _policy = _SpikePolicy(0.45, 0.25, 0.035, 0.6, 0.1, 0.9, _curved_valley)

    def outline(self, nodes: Optional[int] = None, irregularity: int = 50,
                seed: int = 0) -> ShoutingOutline:
        return _spiked_outline(
            self.legacy_nodes if nodes is None else nodes, irregularity, seed, self._policy)
