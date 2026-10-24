"""Host-independent text layout, bubble geometry, and SVG rendering."""

from __future__ import annotations

from dataclasses import replace
import math
import sys
from typing import Callable, List, NamedTuple, Optional, TYPE_CHECKING, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QFont, QFontMetricsF, QPainterPath

from .geometry import bubble_svg, filled_path_centroid, tail_anchor, tail_tip
from .registry import SHAPES, resolve_bubble
from .settings import INTEGER_RANGES
from .types import BubbleType, TailParameters
from .text_runs import TextRun, speech_runs, styled_font

if TYPE_CHECKING:
    from .settings import BubbleSettings, TextStyle


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
    tail_start: Optional[QPointF] = None


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


def _diamond_partition(prefix: List[float], weights: List[int],
                       space: float, unit: float) -> List[int]:
    """Find the original least-cost partition, retaining the earliest tied start."""
    length = len(prefix) - 1
    count = len(weights)
    previous = [0.0]
    backpointers: List[List[int]] = []
    scale = max(1.0, unit)
    monotone = all(left <= right for left, right in zip(prefix, prefix[1:]))
    extent = max(abs(value) for value in prefix)
    for row, weight in enumerate(weights):
        target = max(1.0, unit * weight)
        first = row + 1
        last = length - (count - row - 1)
        current = [math.inf] * (last + 1)
        starts = [0] * (last + 1)
        # Squared distance on ordered prefix widths is Monge: optimal starts
        # cannot move backwards as ends increase. Keep near-tied starts in the
        # search bounds too, so floating-point roundoff cannot exclude a winner.
        # This allowance only widens search bounds; scores and ties remain exact.
        magnitude = (extent + abs(space) + abs(target)) / scale
        tolerance = 64 * sys.float_info.epsilon * (
            max(value for value in previous if math.isfinite(value)) + magnitude * magnitude + 1)

        def solve(low: int, high: int, start_low: int, start_high: int) -> None:
            if low > high:
                return
            end = (low + high) // 2
            best_cost = math.inf
            best_start = near_low = near_high = start_low
            for start in range(start_low, min(end - 1, start_high) + 1):
                if not math.isfinite(previous[start]):
                    continue
                width = prefix[end] - prefix[start] - space
                error = (width - target) / scale
                value = previous[start] + error * error
                if value < best_cost - tolerance:
                    near_low = start
                if value <= best_cost + tolerance:
                    near_high = start
                if value < best_cost:
                    best_start, best_cost = start, value
            current[end], starts[end] = best_cost, best_start
            solve(low, end - 1, start_low, near_high if monotone else start_high)
            solve(end + 1, high, near_low if monotone else start_low, start_high)

        solve(length if row == count - 1 else first, last, row, len(previous) - 1)
        previous = current
        backpointers.append(starts)
    ends = [length]
    for starts in reversed(backpointers[1:]):
        ends.append(starts[ends[-1]])
    return list(reversed(ends))


def diamond_speech_lines(text: str, measure: Callable[[str], float] = len,
                         word_widths: Optional[List[float]] = None) -> List[str]:
    """Partition words against symmetric, increasing then decreasing line widths."""
    result: List[str] = []
    position = 0
    for paragraph in text.split("\n"):
        words = paragraph.split()
        widths = ([measure(word) for word in words] if word_widths is None else
                  word_widths[position:position + len(words)])
        position += len(words)
        if len(words) < 3:
            result.append(" ".join(words))
            continue
        count = len(automatic_speech_lines(paragraph))
        count = max(3, count + (1 if count % 2 == 0 else 0))
        count = min(count, len(words) if len(words) % 2 else len(words) - 1)
        weights = [min(index + 1, count - index) for index in range(count)]
        space = measure(" ")
        prefix = [0.0]
        for width in widths:
            prefix.append(prefix[-1] + width + space)
        unit = (prefix[-1] - count * space) / sum(weights)
        breaks = _diamond_partition(prefix, weights, space, unit)

        def balance_cost(ends: List[int]) -> float:
            starts = [0] + ends[:-1]
            actual = [prefix[end] - prefix[start] - space
                      for start, end in zip(starts, ends)]
            cost = sum((width - unit * weight) ** 2
                       for width, weight in zip(actual, weights))
            cost += 2 * sum((actual[index] - actual[-index - 1]) ** 2
                            for index in range(count // 2))
            for index in range(count // 2):
                cost += 4 * max(0.0, actual[index] - actual[index + 1]) ** 2
                cost += 4 * max(0.0, actual[-index - 1] - actual[-index - 2]) ** 2
            return cost

        # Whole words cannot always hit symmetric targets. Refine neighboring
        # breaks to favor mirror balance rather than arbitrary equal-cost ties.
        cost = balance_cost(breaks)
        for _ in range(len(words)):
            best, best_cost = breaks, cost
            for index in range(count - 1):
                for shift in (-1, 1):
                    candidate = list(breaks)
                    candidate[index] += shift
                    start = candidate[index - 1] if index else 0
                    if not start < candidate[index] < candidate[index + 1]:
                        continue
                    candidate_cost = balance_cost(candidate)
                    if candidate_cost < best_cost - 1e-9:
                        best, best_cost = candidate, candidate_cost
            if best is breaks:
                break
            breaks, cost = best, best_cost
        start = 0
        for end in breaks:
            result.append(" ".join(words[start:end]))
            start = end
    return result


class TextLayout(NamedTuple):
    bounds: QRectF
    line_bounds: List[QRectF]
    line_origins: List[float]


class _TextLayoutKey(NamedTuple):
    text: str
    text_styles: Tuple[TextStyle, ...]
    font: str
    font_size: int
    autocenter: bool
    wrapping: str
    line_length: int
    optical_center: bool
    text_alignment: str


class _MeasuredText(NamedTuple):
    lines: List[str]
    runs: List[List[TextRun]]
    font: QFont
    metrics: QFontMetricsF
    layout: TextLayout


def _text_layout(lines: List[str], metrics: QFontMetricsF, font: QFont,
                 size: int, optical_center: bool = False,
                 runs: Optional[List[List[TextRun]]] = None,
                 alignment: str = "Center") -> TextLayout:
    half_width = 0.0
    top = -metrics.capHeight()
    bottom = (len(lines) - 1) * size
    lettering = QPainterPath()
    lettering.setFillRule(Qt.FillRule.WindingFill)
    line_bounds: List[QRectF] = []
    line_origins: List[float] = []
    outlines: List[QPainterPath] = []
    for index, line in enumerate(lines):
        # Shaped outlines preserve kerning, unlike tightBoundingRect's glyph sums.
        glyphs = QPainterPath()
        advance = 0.0
        for run in runs[index] if runs is not None else [TextRun(line)]:
            run_font = styled_font(font, run)
            glyphs.addText(advance, 0, run_font, run.text)
            advance += QFontMetricsF(run_font).horizontalAdvance(run.text)
        ink = glyphs.boundingRect()
        half_width = max(half_width, advance / 2,
                         advance / 2 - ink.left(), ink.right() - advance / 2)
        top = min(top, index * size + ink.top())
        bottom = max(bottom, index * size + ink.bottom())
        left = min(0.0, ink.left()) - advance / 2
        right = max(advance, ink.right()) - advance / 2
        row_top = min(-metrics.capHeight(), ink.top()) + index * size
        row_bottom = max(0.0, ink.bottom()) + index * size
        line_bounds.append(QRectF(left, row_top, right - left, row_bottom - row_top))
        line_origins.append(-advance / 2)
        if optical_center:
            outlines.append(glyphs)
    for index, row in enumerate(line_bounds):
        shift = (-half_width - row.left() if alignment == "Left" else
                 half_width - row.right() if alignment == "Right" else 0.0)
        row.translate(shift, 0)
        line_origins[index] += shift
        if optical_center:
            outlines[index].translate(line_origins[index], index * size)
            lettering.addPath(outlines[index])
    if optical_center:
        centroid = filled_path_centroid(lettering)
        if centroid is not None:
            # Reserve enough room on both sides of the optical center for all ink.
            half_height = max(centroid.y() - top, bottom - centroid.y())
            top, bottom = centroid.y() - half_height, centroid.y() + half_height
    return TextLayout(QRectF(-half_width, top, half_width * 2, bottom - top),
                      line_bounds, line_origins)


def _text_bounds(lines: List[str], metrics: QFontMetricsF, font: QFont,
                 size: int, optical_center: bool = False,
                 runs: Optional[List[List[TextRun]]] = None) -> QRectF:
    return _text_layout(lines, metrics, font, size, optical_center, runs).bounds


def measured_line_bounds(lines: List[str], metrics: QFontMetricsF, font: QFont,
                         size: int, runs: List[List[TextRun]]) -> List[QRectF]:
    return _text_layout(lines, metrics, font, size, runs=runs).line_bounds


class BubbleRenderer:
    def __init__(self, resolver: Callable[[str, str, str], BubbleType] = resolve_bubble) -> None:
        self._resolve = resolver
        self._text_cache: Optional[Tuple[_TextLayoutKey, _MeasuredText]] = None

    def _measure_text(self, settings: BubbleSettings) -> _MeasuredText:
        size = settings.font_size
        font = QFont(settings.font)
        font.setPixelSize(size)
        key = _TextLayoutKey(
            settings.text, settings.text_styles, font.key(), size,
            settings.autocenter, settings.wrapping, settings.line_length,
            settings.optical_center, SHAPES[settings.shape].text_alignment(settings))
        if self._text_cache is not None and self._text_cache[0] == key:
            return self._text_cache[1]
        metrics = QFontMetricsF(font)
        if settings.autocenter:
            if settings.wrapping == "Diamond":
                word_runs = speech_runs(settings, settings.text.split())
                widths = [sum(QFontMetricsF(styled_font(font, run)).horizontalAdvance(run.text)
                              for run in row) for row in word_runs]
                lines = diamond_speech_lines(settings.text, metrics.horizontalAdvance, widths)
            else:
                lines = automatic_speech_lines(settings.text)
        else:
            lines = get_speech_lines(settings.text, settings.line_length)
        runs = speech_runs(settings, lines)
        layout = _text_layout(
            lines, metrics, font, size, settings.optical_center, runs, key.text_alignment)
        measured = _MeasuredText(lines, runs, font, metrics, layout)
        # Only retain the most recent lettering, independently of body/tail edits.
        self._text_cache = key, measured
        return measured

    def geometry(self, settings: BubbleSettings) -> Geometry:
        return self._geometry(settings, self._measure_text(settings))

    def _geometry(self, settings: BubbleSettings, measured: _MeasuredText) -> Geometry:
        bounds, line_bounds, _ = measured.layout
        bubble = self._resolve(settings.style, settings.shout_shape, settings.shape)
        center = bounds.center()
        centered = bounds.translated(-center)
        positioned = [line.translated(-center) for line in line_bounds]
        positioned[0].setTop(centered.top())
        positioned[-1].setBottom(centered.bottom())
        rect, text_rect, body = bubble.layout_body(centered, positioned, settings)
        anchor, tip = self._tail_points(settings, rect, body)
        path = bubble.compose_tail(
            body, rect.center(), tip,
            TailParameters(settings.font_size, settings.thought_size,
                           settings.thought_irregularity, settings.thought_seed,
                           settings.tail_curve, settings.tail_curve_direction, anchor,
                           thought_blobs=settings.thought_blobs,
                           outline_width=settings.outline))
        return Geometry(rect, text_rect, body, path, tip, list(measured.lines), measured.metrics)

    @staticmethod
    def _outside_tip(body: QPainterPath, center: QPointF, point: QPointF,
                     fallback_angle: float) -> QPointF:
        offset = point - center
        distance = math.hypot(offset.x(), offset.y())
        angle = (math.atan2(offset.y(), offset.x())
                 if not offset.isNull() else fallback_angle)
        minimum_tip = tail_tip(body, center, angle, 1)
        minimum = math.hypot(minimum_tip.x() - center.x(), minimum_tip.y() - center.y())
        return point if distance >= minimum else minimum_tip

    def _tail_points(self, settings: BubbleSettings, rect: QRectF,
                     body: QPainterPath) -> Tuple[Optional[QPointF], Optional[QPointF]]:
        if not settings.tail_enabled:
            return None, None
        center = rect.center()
        if settings.tail_advanced:
            angle = (settings.tail_angle if settings.tail_start_angle is None
                     else settings.tail_start_angle)
            anchor = tail_tip(body, center, angle, 0)
            if settings.tail_end_x is None or settings.tail_end_y is None:
                tip = tail_tip(body, center, settings.tail_angle, settings.tail_length or 20)
            else:
                tip = self._outside_tip(
                    body, center, center + QPointF(settings.tail_end_x, settings.tail_end_y),
                    settings.tail_angle)
            return anchor, tip
        tip = (tail_tip(body, center, settings.tail_angle, settings.tail_length)
               if settings.tail_length > 0 else None)
        return None, tip

    def render(self, settings: BubbleSettings, preview: bool = False) -> RenderResult:
        measured = self._measure_text(settings)
        rect, text_rect, body, path, tip, lines, _ = self._geometry(settings, measured)
        margin = max(8, settings.outline / 2 + 2)
        if preview:
            view_box = path.boundingRect().adjusted(-margin, -margin, margin, margin)
            if tip is None and settings.tail_enabled and not settings.lock_tail:
                tip = tail_tip(body, rect.center(), settings.tail_angle, 0)
        else:
            view_box = QRectF(0, 0, max(1, rect.width()), max(1, rect.height()))
        start, _ = self._tail_points(settings, rect, body)
        svg = bubble_svg(
            path, lines, text_rect, measured.font.family(), settings.font_size,
            -measured.layout.bounds.top(),
            settings.fill, settings.stroke, settings.outline,
            settings.text_color, view_box, measured.runs,
            measured.layout.line_origins
            if SHAPES[settings.shape].text_alignment(settings) != "Center" else None)
        return RenderResult(svg, view_box, tip, start)

    def move_tail(self, settings: BubbleSettings, point: QPointF) -> BubbleSettings:
        if not settings.tail_enabled:
            return settings
        rect, _, body, _, _, _, _ = self.geometry(settings)
        center = rect.center()
        if settings.tail_advanced:
            tip = self._outside_tip(body, center, point, settings.tail_angle) - center
            return replace(settings, tail_end_x=tip.x(), tail_end_y=tip.y())
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
            minimum, maximum = INTEGER_RANGES["tail_length"]
            length = max(minimum, min(maximum, round(distance)))
        return replace(settings, tail_angle=angle, tail_length=length)

    def move_tail_start(self, settings: BubbleSettings, point: QPointF) -> BubbleSettings:
        if not settings.tail_enabled or not settings.tail_advanced:
            return settings
        rect, _, _, _, tip, _, _ = self.geometry(settings)
        center = rect.center()
        offset = point - center
        if offset.isNull():
            return settings
        # Freeze the displayed endpoint even when it was derived from simple settings.
        if tip is None:
            raise ValueError("An enabled advanced tail must have an endpoint")
        end = tip - center
        return replace(settings, tail_start_angle=math.atan2(offset.y(), offset.x()),
                       tail_end_x=end.x(), tail_end_y=end.y())
