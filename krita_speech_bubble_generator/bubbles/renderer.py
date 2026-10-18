"""Host-independent text layout, bubble geometry, and SVG rendering."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Callable, List, NamedTuple, Optional, TYPE_CHECKING

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QFont, QFontMetricsF, QPainterPath

from .geometry import bubble_svg, filled_path_centroid, tail_anchor, tail_tip
from .registry import resolve_bubble
from .types import BubbleType, TailParameters

if TYPE_CHECKING:
    from .settings import BubbleSettings


class Geometry(NamedTuple):
    body_rect: QRectF
    text_rect: QRectF
    body: QPainterPath
    path: QPainterPath
    tip: Optional[QPointF]
    lines: List[str]
    metrics: QFontMetricsF


class RenderResult(NamedTuple):
    svg: str
    view_box: QRectF
    tip: Optional[QPointF]


def get_speech_lines(text: str, line_length: float,
                     measure: Callable[[str], float] = len) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if line_length <= 0:
            lines.append(paragraph)
            continue
        line = ""
        for word in paragraph.split():
            if line and measure(line + " " + word) > line_length:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        lines.append(line)
    return lines


def automatic_speech_lines(text: str) -> List[str]:
    threshold = max(1, int(math.sqrt(len(text)) * 1.8))
    result: List[str] = []
    for paragraph in text.split("\n"):
        paragraph_words = paragraph.split()
        words: List[str] = []
        count = 0
        for word in paragraph_words:
            words.append(word)
            count += len(word)
            # The original wraps after reaching the threshold, excluding spaces.
            if count >= threshold:
                result.append(" ".join(words))
                words = []
                count = 0
        if words or not paragraph_words:
            result.append(" ".join(words))
    return result


def _text_bounds(lines: List[str], metrics: QFontMetricsF, font: QFont,
                 size: int, optical_center: bool = False) -> QRectF:
    half_width = 0.0
    top = -metrics.capHeight()
    bottom = (len(lines) - 1) * size
    lettering = QPainterPath()
    lettering.setFillRule(Qt.FillRule.WindingFill)
    for index, line in enumerate(lines):
        advance = metrics.horizontalAdvance(line)
        # Shaped outlines preserve kerning, unlike tightBoundingRect's glyph sums.
        glyphs = QPainterPath()
        glyphs.addText(0, 0, font, line)
        ink = glyphs.boundingRect()
        half_width = max(half_width, advance / 2,
                         advance / 2 - ink.left(), ink.right() - advance / 2)
        top = min(top, index * size + ink.top())
        bottom = max(bottom, index * size + ink.bottom())
        if optical_center:
            glyphs.translate(-advance / 2, index * size)
            lettering.addPath(glyphs)
    if optical_center:
        centroid = filled_path_centroid(lettering)
        if centroid is not None:
            # Reserve enough room on both sides of the optical center for all ink.
            half_height = max(centroid.y() - top, bottom - centroid.y())
            top, bottom = centroid.y() - half_height, centroid.y() + half_height
    return QRectF(-half_width, top, half_width * 2, bottom - top)


class BubbleRenderer:
    def __init__(self, resolver: Callable[[str, str], BubbleType] = resolve_bubble) -> None:
        self._resolve = resolver

    def geometry(self, settings: BubbleSettings) -> Geometry:
        size = settings.font_size
        font = QFont(settings.font)
        if settings.autocenter:
            lines = automatic_speech_lines(settings.text)
        else:
            lines = get_speech_lines(settings.text, settings.line_length)
        font.setPixelSize(size)
        metrics = QFontMetricsF(font)
        bounds = _text_bounds(lines, metrics, font, size, settings.optical_center)
        bubble = self._resolve(settings.style, settings.shout_shape)
        width, height = bounds.width(), bounds.height()
        rect = bubble.enclose_text(width, height, settings)
        text_rect = QRectF((rect.width() - width) / 2,
                          (rect.height() - height) / 2, width, height)
        body = bubble.body_path(rect, bubble.body_parameters(settings))
        tip = None
        if settings.tail_length > 0:
            tip = tail_tip(body, rect.center(), settings.tail_angle, settings.tail_length)
        path = bubble.compose_tail(
            body, rect.center(), tip,
            TailParameters(size, settings.thought_size,
                           settings.thought_irregularity, settings.thought_seed,
                           settings.tail_curve, settings.tail_curve_direction))
        return Geometry(rect, text_rect, body, path, tip, lines, metrics)

    def render(self, settings: BubbleSettings, preview: bool = False) -> RenderResult:
        geometry = self.geometry(settings)
        rect, text_rect, body, path, tip, lines, metrics = geometry
        margin = max(8, settings.outline / 2 + 2)
        if preview:
            view_box = path.boundingRect().adjusted(-margin, -margin, margin, margin)
            if tip is None and not settings.lock_tail:
                tip = tail_tip(body, rect.center(), settings.tail_angle, 0)
        else:
            view_box = QRectF(0, 0, max(1, rect.width()), max(1, rect.height()))
        font = QFont(settings.font)
        font.setPixelSize(settings.font_size)
        svg = bubble_svg(
            path, lines, text_rect, font.family(), settings.font_size,
            -_text_bounds(lines, metrics, font, settings.font_size,
                          settings.optical_center).top(),
            settings.fill, settings.stroke, settings.outline,
            settings.text_color, view_box)
        return RenderResult(svg, view_box, tip)

    def move_tail(self, settings: BubbleSettings, point: QPointF) -> BubbleSettings:
        rect, _, body, _, _, _, _ = self.geometry(settings)
        center = rect.center()
        offset = point - center
        if math.hypot(offset.x(), offset.y()) < 1e-6:
            return settings
        handle = tail_tip(body, center, settings.tail_angle, settings.tail_length)
        if math.hypot(point.x() - handle.x(), point.y() - handle.y()) < 1e-6:
            return settings
        angle = math.atan2(offset.y(), offset.x())
        length = settings.tail_length
        if not settings.lock_tail:
            direction = QPointF(math.cos(angle), math.sin(angle))
            anchor = tail_anchor(body, center, direction)
            distance = ((point.x() - anchor.x()) * direction.x()
                        + (point.y() - anchor.y()) * direction.y())
            length = max(0, min(settings.font_size * 10, round(distance)))
        return replace(settings, tail_angle=angle, tail_length=length)
