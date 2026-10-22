"""Explicit, ordered built-ins and their composition boundary."""

from collections import OrderedDict
from typing import Iterable, Mapping, Protocol, TypeVar

from .types import (
    BubbleType, OvalBubble, RoundedBubble, ShoutingBubble, SquareBubble, ThoughtBubble,
    SharpBubble,
)
from .shapes import BubbleShape, OvalShape, SquareShape, TracingShape
from .shouting_algorithms import (
    AngularShouting, BalancedShouting, ExpressiveShouting, PunchyShouting,
    ShoutingAlgorithm,
)


class Identified(Protocol):
    identifier: str


Implementation = TypeVar("Implementation", bound=Identified)


def build_registry(
        implementations: Iterable[Implementation]) -> OrderedDict[str, Implementation]:
    """Index implementations in declaration order, rejecting ambiguous identifiers."""
    registry: OrderedDict[str, Implementation] = OrderedDict()
    for implementation in implementations:
        identifier = implementation.identifier
        if identifier in registry:
            raise ValueError("Duplicate registry identifier: " + identifier)
        registry[identifier] = implementation
    return registry


SHOUTING_ALGORITHMS: OrderedDict[str, ShoutingAlgorithm] = build_registry((
    BalancedShouting(), AngularShouting(), PunchyShouting(), ExpressiveShouting(),
))
BUBBLE_TYPES: OrderedDict[str, BubbleType] = build_registry((
    OvalBubble(), RoundedBubble(), SquareBubble(), ThoughtBubble(),
    ShoutingBubble(SHOUTING_ALGORITHMS["Balanced"]),
))
SHAPES: OrderedDict[str, BubbleShape] = build_registry((
    OvalShape(), SquareShape(), TracingShape(),
))
BUBBLE_STYLES: OrderedDict[str, BubbleType] = build_registry((
    SharpBubble(), RoundedBubble(), ThoughtBubble(),
    ShoutingBubble(SHOUTING_ALGORITHMS["Balanced"]),
))


def _resolve(registry: Mapping[str, Implementation], key: object,
             description: str) -> Implementation:
    if not isinstance(key, str):
        raise ValueError("Unknown {}: {}".format(description, key))
    try:
        return registry[key]
    except (KeyError, TypeError):
        raise ValueError("Unknown {}: {}".format(description, key)) from None


def resolve_bubble(style: object, shout_shape: object = "Balanced",
                   shape: object = None) -> BubbleType:
    registry = {**BUBBLE_TYPES, **BUBBLE_STYLES} if shape is None else BUBBLE_STYLES
    bubble = _resolve(registry, style, "bubble style")
    if bubble.capabilities.shouting:
        bubble = bubble.with_algorithm(
            _resolve(SHOUTING_ALGORITHMS, shout_shape, "shouting shape"))
    return bubble if shape is None else bubble.with_shape(_resolve(SHAPES, shape, "bubble shape"))
