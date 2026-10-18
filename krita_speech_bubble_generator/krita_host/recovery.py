"""Explicit recovery of generated groups detached from their saved layer."""

import re
from typing import List, NamedTuple, Tuple
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QByteArray, QRectF, QUuid
from PyQt5.QtGui import QTransform
from PyQt5.QtSvg import QSvgRenderer

from ..bubbles.settings import (
    ANNOTATION_PREFIX, SHAPE_NAME, SavedBubble, TransformValues, decode_record, transform_values,
)
from ..editor.contracts import GatewayError
from .contracts import Document


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


def detached_group(svg: str, name: str, require_text: bool = True) -> DetachedGroup:
    groups = [element for element in parse_svg(svg)
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


def has_detached_records(document: Document) -> bool:
    for key in document.annotationTypes():
        match = re.fullmatch(re.escape(ANNOTATION_PREFIX) + r"(\{[^{}]+\})(?:-.+)?", key)
        if match is not None:
            layer_id = QUuid(match[1])
            if not layer_id.isNull() and document.nodeByUniqueID(layer_id) is None:
                return True
    return False


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
