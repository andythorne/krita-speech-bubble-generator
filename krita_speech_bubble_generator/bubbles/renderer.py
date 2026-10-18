"""Host-independent text layout, bubble geometry, and SVG rendering."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Callable, List, NamedTuple, Optional, TYPE_CHECKING

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QFont, QFontMetricsF, QPainterPath

from .geometry import bubble_svg, tail_anchor, tail_tip
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
        font.setPixelSize(int(size * 1.3))
        metrics = QFontMetricsF(font)
        width = max(metrics.horizontalAdvance(line) for line in lines)
        height = metrics.capHeight() + (len(lines) - 1) * size
        bubble = self._resolve(settings.style, settings.shout_shape)
        padding = bubble.enclosure_padding(settings)
        rect = bubble.body_rect(width, height, padding)
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
        svg = bubble_svg(
            path, lines, text_rect, QFont(settings.font).family(), settings.font_size,
            metrics.capHeight(), settings.fill, settings.stroke, settings.outline,
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
