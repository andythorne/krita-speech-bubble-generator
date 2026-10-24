"""Explicit recovery of generated groups detached from their saved layer."""

import re
from typing import List, NamedTuple, Optional, Tuple
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QByteArray, QRectF, QUuid
from PyQt5.QtGui import QTransform
from PyQt5.QtSvg import QSvgRenderer

from ..bubbles.settings import (
    ANNOTATION_PREFIX, SHAPE_NAME, BubbleSettings, SavedBubble, SettingsError,
    TransformValues, decode_record, encode_record, transform_values,
)
from ..editor.contracts import GatewayError
from .contracts import Document, Shape


SETTINGS_NAME = "rsbg-settings-"


def group_settings(shape: Shape) -> Optional[BubbleSettings]:
    names = [child.name() for child in shape.children()
             if child.name().startswith(SETTINGS_NAME)]
    if not names:
        return None
    if len(names) != 1:
        raise SettingsError("The bubble contains multiple embedded settings records.")
    match = re.fullmatch(re.escape(SETTINGS_NAME) + r"([0-9a-f]+)-end\d*", names[0])
    if match is None:
        raise SettingsError("The bubble's embedded settings record is invalid.")
    try:
        data = bytes.fromhex(match[1])
    except ValueError as error:
        raise SettingsError("The bubble's embedded settings record is invalid.") from error
    return decode_record(data).settings


def store_group_settings(shape: Shape, settings: BubbleSettings) -> None:
    children = shape.children()
    if children:
        # Krita preserves shape names through clipboard SVG, but discards arbitrary
        # SVG metadata. An existing child's name carries data without extra artwork.
        carrier = next((child for child in children
                        if child.name().startswith(SETTINGS_NAME)), children[0])
        name = SETTINGS_NAME + encode_record(settings, QTransform()).hex() + "-end"
        if carrier.name() != name:
            carrier.setName(name)


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def generated_name(name: str) -> bool:
    return (name == SHAPE_NAME or name.startswith(SHAPE_NAME + "-")
            or re.fullmatch(re.escape(SHAPE_NAME) + r"\d+", name) is not None)


def stable_name(name: str) -> bool:
    return re.fullmatch(re.escape(SHAPE_NAME) + r"-[0-9a-f]{32}", name) is not None


def parse_svg(svg: str) -> ET.Element:
    try:
        return ET.fromstring(svg)
    except ET.ParseError as error:
        raise GatewayError("Cannot read the bubble SVG: " + str(error)) from error


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


class Outline(NamedTuple):
    bounds: Tuple[float, float, float, float]
    transform: TransformValues

    def rect(self) -> QRectF:
        return QRectF(*self.bounds)

    def matrix(self) -> QTransform:
        return QTransform(*self.transform)


def read_outline(element: ET.Element) -> Outline:
    # Isolate geometry from stroke, styles, IDs and unrelated SVG resources.
    root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg")
    group = ET.SubElement(root, "g", transform=element.get("transform", ""))
    ET.SubElement(group, "path", id="outline", d=element.get("d", ""))
    renderer = QSvgRenderer(QByteArray(ET.tostring(root)))
    bounds = renderer.boundsOnElement("outline")
    transform = renderer.transformForElement("outline")
    if not renderer.isValid() or bounds.isEmpty() or not transform.isInvertible():
        raise GatewayError("The bubble outline has invalid geometry or placement.")
    return Outline((bounds.x(), bounds.y(), bounds.width(), bounds.height()),
                   transform_values(transform))


class DetachedGroup(NamedTuple):
    text: str
    outline: Outline

    def placement(self, generated_svg: str) -> QTransform:
        paths = [element for element in parse_svg(generated_svg).iter()
                 if tag(element) == "path"]
        if len(paths) != 1:
            raise GatewayError("The regenerated bubble must have one outline.")
        generated = read_outline(paths[0])
        inverse, invertible = generated.matrix().inverted()
        if not invertible:
            raise GatewayError("The regenerated bubble placement is not invertible.")
        old, new = self.outline.rect(), generated.rect()
        return (
            inverse * QTransform.fromTranslate(-new.left(), -new.top())
            * QTransform.fromScale(old.width() / new.width(), old.height() / new.height())
            * QTransform.fromTranslate(old.left(), old.top()) * self.outline.matrix()
        )


def detached_group(svg: str, name: str, require_text: bool = True,
                   fragment: bool = False) -> DetachedGroup:
    if fragment:
        # Shape.toSvg exports a fragment whose namespace declarations normally
        # belong to the enclosing layer SVG.
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
            'xmlns:krita="http://krita.org/namespaces/svg/krita" '
            'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd">'
            + svg + "</svg>")
    root = parse_svg(svg)
    groups = [element for element in ([root] if tag(root) == "g" else root)
              if tag(element) == "g" and element.get("id") == name]
    if len(groups) != 1:
        raise GatewayError("Cannot uniquely locate the selected bubble group in the layer SVG.")
    children = list(groups[0])
    paths = [element for element in children if tag(element) == "path"]
    texts = [element for element in children if tag(element) == "text"]
    if len(paths) != 1 or not texts or len(children) != len(texts) + 1:
        raise GatewayError("Recovery requires an intact bubble group with one outline and its text.")
    text = normalized_text(" ".join("".join(element.itertext()) for element in texts))
    if require_text and not text:
        raise GatewayError("A bubble without lettering cannot be matched to saved settings.")
    return DetachedGroup(text, read_outline(paths[0]))


def matching_records(document: Document, name: str, text: str) -> List[SavedBubble]:
    scoped: List[SavedBubble] = []
    unscoped: List[SavedBubble] = []
    pattern = re.escape(ANNOTATION_PREFIX) + r"(\{[^{}]+\})(?:-(.+))?"
    for key in document.annotationTypes():
        match = re.fullmatch(pattern, key)
        if match is None:
            continue
        layer_id = QUuid(match[1])
        if layer_id.isNull() or document.nodeByUniqueID(layer_id) is not None:
            continue
        saved_name = match[2] or SHAPE_NAME
        if saved_name != SHAPE_NAME and saved_name != name:
            continue
        record = decode_record(bytes(document.annotation(key)))
        if normalized_text(record.settings.text) == text:
            (scoped if saved_name == name and name != SHAPE_NAME else unscoped).append(record)
    return scoped or unscoped
