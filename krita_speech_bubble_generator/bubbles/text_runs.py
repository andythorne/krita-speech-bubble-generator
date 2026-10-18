"""Map source formatting through the existing word-based wrapping."""

from dataclasses import dataclass
import re
from typing import List, TYPE_CHECKING

from PyQt5.QtGui import QFont

if TYPE_CHECKING:
    from .settings import BubbleSettings


@dataclass(frozen=True)
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False


def styled_font(base: QFont, run: TextRun) -> QFont:
    font = QFont(base)
    font.setBold(run.bold)
    font.setItalic(run.italic)
    return font


def speech_runs(settings: "BubbleSettings", lines: List[str]) -> List[List[TextRun]]:
    if not settings.text_styles:
        return [[TextRun(line)] for line in lines]
    source = settings.text
    position = 0
    style_index = 0
    result: List[List[TextRun]] = []
    for line in lines:
        indices: List[int] = []
        if settings.autocenter or settings.line_length > 0:
            for word in re.finditer(r"\S+", line):
                start = source.index(word.group(), position)
                if indices:
                    indices.append(position)
                indices.extend(range(start, start + len(word.group())))
                position = start + len(word.group())
        else:
            indices = list(range(position, position + len(line)))
            position += len(line) + 1
        runs: List[TextRun] = []
        for character, index in zip(line, indices):
            while (style_index < len(settings.text_styles)
                   and settings.text_styles[style_index].end <= index):
                style_index += 1
            bold = italic = False
            if style_index < len(settings.text_styles):
                style = settings.text_styles[style_index]
                if style.start <= index < style.end:
                    bold, italic = style.bold, style.italic
            if runs and (runs[-1].bold, runs[-1].italic) == (bold, italic):
                runs[-1] = TextRun(runs[-1].text + character, bold, italic)
            else:
                runs.append(TextRun(character, bold, italic))
        result.append(runs or [TextRun("")])
    return result
