"""Editable values and the version-1 saved-bubble format."""

from dataclasses import dataclass, fields
import json
import math
from typing import Dict, Mapping, Sequence, Tuple, Union, cast

from PyQt5.QtGui import QColor, QTransform

from .geometry import MAX_NODES, MIN_NODES
from .registry import BUBBLE_TYPES, SHOUTING_ALGORITHMS


ANNOTATION_PREFIX = "rsbg-bubble-"
SHAPE_NAME = "rsbg-bubble"
TransformValues = Tuple[float, float, float, float, float, float]
SettingValue = Union[str, int, float, bool]


class SettingsError(ValueError):
    """A saved record cannot safely be used by the editor."""


@dataclass(frozen=True)
class BubbleSettings:
    style: str = "Oval"
    text: str = "Krita speech bubble generator!"
    font: str = "Segoe Print"
    font_size: int = 14
    fill: str = "#ffffff"
    stroke: str = "#000000"
    text_color: str = "#000000"
    outline: int = 3
    padding: int = 150
    oval_custom: bool = False
    oval_vertical_padding: int = 150
    oval_squareness: int = 0
    autocenter: bool = True
    optical_center: bool = False
    line_length: int = 0
    tail_length: int = 0
    tail_angle: float = math.pi / 4
    lock_tail: bool = True
    tail_curve: int = 0
    tail_curve_direction: str = "Up"
    thought_size: int = 100
    shout_irregularity: int = 50
    shout_shape: str = "Balanced"
    shout_nodes: int = 24
    shout_seed: int = 0
    thought_irregularity: int = 50
    thought_nodes: int = 16
    thought_seed: int = 0

    def to_dict(self) -> Dict[str, SettingValue]:
        return {
            "version": 1,
            "style": self.style,
            "text": self.text,
            "font": self.font,
            "font_size": self.font_size,
            "fill": self.fill,
            "stroke": self.stroke,
            "text_color": self.text_color,
            "outline": self.outline,
            "padding": self.padding,
            "oval_custom": self.oval_custom,
            "oval_vertical_padding": self.oval_vertical_padding,
            "oval_squareness": self.oval_squareness,
            "autocenter": self.autocenter,
            "optical_center": self.optical_center,
            "line_length": self.line_length,
            "tail_length": self.tail_length,
            "tail_angle": self.tail_angle,
            "lock_tail": self.lock_tail,
            "tail_curve": self.tail_curve,
            "tail_curve_direction": self.tail_curve_direction,
            "thought_size": self.thought_size,
            "shout_irregularity": self.shout_irregularity,
            "shout_shape": self.shout_shape,
            "shout_nodes": self.shout_nodes,
            "shout_seed": self.shout_seed,
            "thought_irregularity": self.thought_irregularity,
            "thought_nodes": self.thought_nodes,
            "thought_seed": self.thought_seed,
        }


@dataclass(frozen=True)
class SavedBubble:
    settings: BubbleSettings
    baseline: TransformValues


# Fresh editor defaults and old records deliberately have different semantics.
LEGACY_DEFAULTS: Dict[str, SettingValue] = {
    "lock_tail": True,
    "tail_curve": 0,
    "tail_curve_direction": "Up",
    "thought_size": 100,
    "shout_irregularity": 0,
    "shout_seed": 0,
    "shout_shape": "Balanced",
    "thought_irregularity": 0,
    "thought_nodes": 16,
    "thought_seed": 0,
    "padding": 150,
    "oval_custom": False,
    "oval_vertical_padding": 150,
    "oval_squareness": 0,
    "optical_center": False,
}
INTEGER_RANGES: Dict[str, Tuple[int, int]] = {
    "font_size": (1, 99),
    "outline": (0, 50),
    "padding": (0, 300),
    "oval_vertical_padding": (0, 300),
    "oval_squareness": (0, 100),
    "line_length": (0, 100),
    "tail_curve": (0, 100),
    "thought_size": (25, 400),
    "shout_nodes": (MIN_NODES, MAX_NODES),
    "thought_nodes": (MIN_NODES, MAX_NODES),
    "shout_irregularity": (0, 100),
    "shout_seed": (0, 2 ** 31 - 1),
    "thought_irregularity": (0, 100),
    "thought_seed": (0, 2 ** 31 - 1),
}


def _registry_identifier(value: object, registry: Mapping[str, object],
                         message: str) -> str:
    if not isinstance(value, str) or value not in registry:
        raise SettingsError(message)
    return value


def _number(value: object, message: str) -> Union[int, float]:
    if type(value) is not int and type(value) is not float:
        raise SettingsError(message)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise SettingsError(message)
    return value


def _string(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise SettingsError("Invalid " + key)
    return value


def _integer(value: object, key: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SettingsError("Invalid " + key)
    return value


def _boolean(value: object, message: str) -> bool:
    if type(value) is not bool:
        raise SettingsError("Invalid " + message)
    return value


def _settings_mapping(data: object) -> Mapping[object, object]:
    if not isinstance(data, Mapping):
        raise SettingsError("Invalid bubble settings")
    return cast(Mapping[object, object], data)


def settings_from_dict(data: object, legacy: bool = False) -> BubbleSettings:
    """Build editable values; persisted data must use the legacy codec path."""
    values = dict(_settings_mapping(data))
    if legacy:
        if values.get("style") == "Round":
            values["style"] = "Rounded"
        for key, default in LEGACY_DEFAULTS.items():
            values.setdefault(key, default)
    else:
        for key, default in BubbleSettings().to_dict().items():
            values.setdefault(key, default)

    if type(values.get("version")) is not int or values["version"] != 1:
        raise SettingsError("Unsupported bubble format")
    style = _registry_identifier(
        values.get("style"), BUBBLE_TYPES, "Unsupported bubble format")
    shout_shape = _registry_identifier(
        values.get("shout_shape"), SHOUTING_ALGORITHMS, "Invalid shouting shape")
    tail_curve_direction = _string(values.get("tail_curve_direction"), "tail curve direction")
    if tail_curve_direction not in ("Up", "Down"):
        raise SettingsError("Invalid tail curve direction")
    if legacy:
        values.setdefault(
            "shout_nodes", SHOUTING_ALGORITHMS[shout_shape].legacy_nodes)

    for field in fields(BubbleSettings):
        if field.name not in values:
            raise SettingsError("Missing " + field.name)
    strings = {key: _string(values[key], key)
               for key in ("text", "font", "fill", "stroke", "text_color")}
    for key in ("fill", "stroke", "text_color"):
        if not QColor(strings[key]).isValid():
            raise SettingsError("Invalid " + key)
    integers = {key: _integer(values[key], key, minimum, maximum)
                for key, (minimum, maximum) in INTEGER_RANGES.items()}
    tail_length = _integer(
        values["tail_length"], "tail_length", 0, integers["font_size"] * 10)
    autocenter = _boolean(values["autocenter"], "text alignment")
    lock_tail = _boolean(values["lock_tail"], "tail length lock")
    tail_angle = _number(values["tail_angle"], "Invalid tail angle")
    return BubbleSettings(
        style=style,
        text=strings["text"],
        font=strings["font"],
        font_size=integers["font_size"],
        fill=strings["fill"],
        stroke=strings["stroke"],
        text_color=strings["text_color"],
        outline=integers["outline"],
        padding=integers["padding"],
        oval_custom=_boolean(values["oval_custom"], "oval customisation"),
        oval_vertical_padding=integers["oval_vertical_padding"],
        oval_squareness=integers["oval_squareness"],
        autocenter=autocenter,
        optical_center=_boolean(values["optical_center"], "optical centering"),
        line_length=integers["line_length"],
        tail_length=tail_length,
        tail_angle=tail_angle,
        lock_tail=lock_tail,
        tail_curve=integers["tail_curve"],
        tail_curve_direction=tail_curve_direction,
        thought_size=integers["thought_size"],
        shout_irregularity=integers["shout_irregularity"],
        shout_shape=shout_shape,
        shout_nodes=integers["shout_nodes"],
        shout_seed=integers["shout_seed"],
        thought_irregularity=integers["thought_irregularity"],
        thought_nodes=integers["thought_nodes"],
        thought_seed=integers["thought_seed"],
    )


def transform_values(transform: QTransform) -> TransformValues:
    return (transform.m11(), transform.m12(), transform.m21(),
            transform.m22(), transform.dx(), transform.dy())


def _baseline_values(value: object) -> TransformValues:
    if isinstance(value, QTransform):
        value = transform_values(value)
    if not isinstance(value, (list, tuple)):
        raise SettingsError("Invalid bubble transform")
    components = cast(Sequence[object], value)
    if len(components) != 6:
        raise SettingsError("Invalid bubble transform")
    numbers = tuple(_number(component, "Invalid bubble transform")
                    for component in components)
    if not QTransform(*numbers).isInvertible():
        raise SettingsError("Invalid bubble transform")
    return (numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], numbers[5])


def validate_settings(data: object) -> Dict[str, object]:
    """Normalize a saved-format mapping without mutating the caller's data."""
    values = _settings_mapping(data)
    settings = settings_from_dict(values, legacy=True)
    baseline = _baseline_values(values.get("baseline"))
    return {**settings.to_dict(), "baseline": list(baseline)}


def decode_record(data: bytes) -> SavedBubble:
    try:
        values: object = json.loads(bytes(data).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError) as error:
        raise SettingsError(str(error)) from error
    normalized = validate_settings(values)
    return SavedBubble(
        settings_from_dict(normalized, legacy=True),
        _baseline_values(normalized["baseline"]))


def encode_record(settings: BubbleSettings,
                  baseline: Union[TransformValues, QTransform]) -> bytes:
    values = validate_settings({**settings.to_dict(),
                                "baseline": _baseline_values(baseline)})
    return json.dumps(values, allow_nan=False).encode("utf-8")
