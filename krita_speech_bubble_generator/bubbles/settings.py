"""Editable values and the version-1 saved-bubble format."""

from dataclasses import dataclass, fields, replace
import json
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union, cast

from PyQt5.QtGui import QColor, QTransform

from .geometry import MAX_NODES, MIN_NODES, MAX_THOUGHT_BLOBS, MIN_THOUGHT_BLOBS
from .registry import BUBBLE_STYLES, SHAPES, SHOUTING_ALGORITHMS


ANNOTATION_PREFIX = "rsbg-bubble-"
SHAPE_NAME = "rsbg-bubble"
TransformValues = Tuple[float, float, float, float, float, float]
SettingValue = Union[str, int, float, bool, None, List[Dict[str, Union[int, bool]]]]


class SettingsError(ValueError):
    """A saved record cannot safely be used by the editor."""


@dataclass(frozen=True)
class TextStyle:
    """A styled text run using end-exclusive Python string indices."""

    start: int
    end: int
    bold: bool = False
    italic: bool = False


@dataclass(frozen=True)
class BubbleSettings:
    style: str = "Sharp"
    shape: str = "Oval"
    wrapping: str = "Standard"
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
    tail_enabled: bool = True
    tail_advanced: bool = False
    tail_start_angle: Optional[float] = None
    tail_end_x: Optional[float] = None
    tail_end_y: Optional[float] = None
    lock_tail: bool = True
    tail_curve: int = 0
    tail_curve_direction: str = "Up"
    thought_size: int = 100
    thought_blobs: int = 3
    shout_irregularity: int = 50
    shout_shape: str = "Balanced"
    shout_nodes: int = 10
    shout_seed: int = 0
    thought_irregularity: int = 50
    thought_nodes: int = 10
    thought_seed: int = 0
    text_styles: Tuple[TextStyle, ...] = ()

    def __post_init__(self) -> None:
        # Also accept the original unambiguous names at the Python API boundary.
        if self.style in ("Oval", "Square", "Round"):
            shape, style = LEGACY_APPEARANCE[self.style]
            object.__setattr__(self, "shape", shape)
            object.__setattr__(self, "style", style)

    def with_style_from(self, source: "BubbleSettings") -> "BubbleSettings":
        """Copy appearance/layout, keeping target dialogue, emphasis and tail placement."""
        return replace(self, **{name: getattr(source, name) for name in STYLE_FIELDS})

    def to_dict(self) -> Dict[str, SettingValue]:
        return {
            "version": 1,
            "style": self.style,
            "shape": self.shape,
            "wrapping": self.wrapping,
            "text": self.text,
            "text_styles": [
                {"start": run.start, "end": run.end,
                 "bold": run.bold, "italic": run.italic}
                for run in self.text_styles
            ],
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
            "tail_enabled": self.tail_enabled,
            "tail_advanced": self.tail_advanced,
            "tail_start_angle": self.tail_start_angle,
            "tail_end_x": self.tail_end_x,
            "tail_end_y": self.tail_end_y,
            "lock_tail": self.lock_tail,
            "tail_curve": self.tail_curve,
            "tail_curve_direction": self.tail_curve_direction,
            "thought_size": self.thought_size,
            "thought_blobs": self.thought_blobs,
            "shout_irregularity": self.shout_irregularity,
            "shout_shape": self.shout_shape,
            "shout_nodes": self.shout_nodes,
            "shout_seed": self.shout_seed,
            "thought_irregularity": self.thought_irregularity,
            "thought_nodes": self.thought_nodes,
            "thought_seed": self.thought_seed,
        }


STYLE_FIELDS = (
    "style", "shape", "wrapping",
    "font", "font_size", "text_color", "fill", "stroke", "outline",
    "padding", "oval_custom", "oval_vertical_padding", "oval_squareness",
    "autocenter", "optical_center", "line_length",
    "tail_curve", "tail_curve_direction", "thought_size", "thought_blobs",
    "shout_shape", "shout_nodes", "shout_irregularity", "shout_seed",
    "thought_nodes", "thought_irregularity", "thought_seed",
)


@dataclass(frozen=True)
class SavedBubble:
    settings: BubbleSettings
    baseline: TransformValues
    layer_id: str = ""


LEGACY_APPEARANCE = {
    "Oval": ("Oval", "Sharp"), "Square": ("Square", "Sharp"),
    "Round": ("Square", "Rounded"), "Rounded": ("Square", "Rounded"),
    "Thought": ("Oval", "Thought"), "Shouting": ("Oval", "Shouting"),
}

# Fresh editor defaults and old records deliberately have different semantics.
LEGACY_DEFAULTS: Dict[str, SettingValue] = {
    "text_styles": [],
    "shape": "Oval",
    "wrapping": "Standard",
    "lock_tail": True,
    "tail_enabled": True,
    "tail_advanced": False,
    "tail_start_angle": None,
    "tail_end_x": None,
    "tail_end_y": None,
    "tail_curve": 0,
    "tail_curve_direction": "Up",
    "thought_size": 100,
    "thought_blobs": 3,
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
    "tail_length": (0, 990),
    "tail_curve": (0, 100),
    "thought_size": (25, 400),
    "thought_blobs": (MIN_THOUGHT_BLOBS, MAX_THOUGHT_BLOBS),
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


def _text_styles(value: object, text: str) -> Tuple[TextStyle, ...]:
    if not isinstance(value, (list, tuple)):
        raise SettingsError("Invalid text_styles")
    runs: List[TextStyle] = []
    previous_end = 0
    for item in cast(Sequence[object], value):
        if not isinstance(item, Mapping):
            raise SettingsError("Invalid text_styles run")
        values = cast(Mapping[object, object], item)
        start = _integer(values.get("start"), "text_styles start",
                         previous_end, len(text) - 1)
        end = _integer(values.get("end"), "text_styles end", start + 1, len(text))
        bold = _boolean(values.get("bold"), "text_styles bold")
        italic = _boolean(values.get("italic"), "text_styles italic")
        if not bold and not italic:
            raise SettingsError("Invalid text_styles: run has no style")
        runs.append(TextStyle(start, end, bold, italic))
        previous_end = end
    return tuple(runs)


def settings_from_dict(data: object, legacy: bool = False) -> BubbleSettings:
    """Build editable values; persisted data must use the legacy codec path."""
    values = dict(_settings_mapping(data))
    if "shape" not in values:
        old_style = values.get("style")
        if isinstance(old_style, str) and old_style in LEGACY_APPEARANCE:
            values["shape"], values["style"] = LEGACY_APPEARANCE[old_style]
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
        values.get("style"), BUBBLE_STYLES, "Unsupported bubble format")
    shape = _registry_identifier(values.get("shape"), SHAPES, "Invalid bubble shape")
    wrapping = _string(values.get("wrapping"), "wrapping")
    if wrapping not in ("Standard", "Diamond"):
        raise SettingsError("Invalid wrapping")
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
    autocenter = _boolean(values["autocenter"], "text alignment")
    lock_tail = _boolean(values["lock_tail"], "tail length lock")
    tail_angle = _number(values["tail_angle"], "Invalid tail angle")
    tail_points = {
        key: None if values[key] is None else _number(values[key], "Invalid " + key)
        for key in ("tail_start_angle", "tail_end_x", "tail_end_y")}
    if (tail_points["tail_end_x"] is None) != (tail_points["tail_end_y"] is None):
        raise SettingsError("Tail end coordinates must be provided together")
    return BubbleSettings(
        style=style,
        shape=shape,
        wrapping=wrapping,
        text=strings["text"],
        text_styles=_text_styles(values["text_styles"], strings["text"]),
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
        tail_length=integers["tail_length"],
        tail_angle=tail_angle,
        tail_enabled=_boolean(values["tail_enabled"], "tail enabled"),
        tail_advanced=_boolean(values["tail_advanced"], "advanced tail"),
        tail_start_angle=tail_points["tail_start_angle"],
        tail_end_x=tail_points["tail_end_x"],
        tail_end_y=tail_points["tail_end_y"],
        lock_tail=lock_tail,
        tail_curve=integers["tail_curve"],
        tail_curve_direction=tail_curve_direction,
        thought_size=integers["thought_size"],
        thought_blobs=integers["thought_blobs"],
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
    normalized: Dict[str, object] = {**settings.to_dict(), "baseline": list(baseline)}
    if "layer_id" in values:
        normalized["layer_id"] = _string(values["layer_id"], "bubble layer identity")
    return normalized


def decode_record(data: bytes) -> SavedBubble:
    try:
        values: object = json.loads(bytes(data).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError) as error:
        raise SettingsError(str(error)) from error
    normalized = validate_settings(values)
    return SavedBubble(
        settings_from_dict(normalized, legacy=True),
        _baseline_values(normalized["baseline"]),
        _string(normalized.get("layer_id", ""), "bubble layer identity"))


def encode_record(settings: BubbleSettings,
                  baseline: Union[TransformValues, QTransform],
                  layer_id: str = "") -> bytes:
    values = validate_settings({**settings.to_dict(),
                                "baseline": _baseline_values(baseline),
                                **({"layer_id": layer_id} if layer_id else {})})
    return json.dumps(values, allow_nan=False).encode("utf-8")
