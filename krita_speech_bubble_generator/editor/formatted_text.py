"""Limited inline emphasis, without accepting arbitrary pasted rich text."""

from typing import List, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QKeySequence, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QShortcut, QTextEdit, QWidget

from ..bubbles.settings import TextStyle


def _qt_position(text: str, position: int) -> int:
    return len(text[:position].encode("utf-16-le")) // 2


class FormattedTextEdit(QTextEdit):
    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.setAcceptRichText(False)
        for key, action in ((QKeySequence.StandardKey.Bold, self.toggle_bold),
                            (QKeySequence.StandardKey.Italic, self.toggle_italic)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(action)

    def toggle_bold(self) -> None:
        self.toggle_emphasis(True)

    def toggle_italic(self) -> None:
        self.toggle_emphasis(False)

    def toggle_emphasis(self, bold: bool) -> None:
        cursor = self.textCursor()
        current = cursor.charFormat()
        formatting = QTextCharFormat()
        if bold:
            formatting.setFontWeight(
                QFont.Weight.Normal if current.fontWeight() >= QFont.Weight.Bold
                else QFont.Weight.Bold)
        else:
            formatting.setFontItalic(not current.fontItalic())
        self.mergeCurrentCharFormat(formatting)
        self.setFocus()

    def text_styles(self) -> Tuple[TextStyle, ...]:
        text = self.toPlainText()
        styles: List[TextStyle] = []
        cursor = QTextCursor(self.document())
        offset = 0
        for index, character in enumerate(text):
            cursor.setPosition(offset)
            offset += 2 if ord(character) > 0xffff else 1
            cursor.setPosition(offset, QTextCursor.MoveMode.KeepAnchor)
            formatting = cursor.charFormat()
            bold = formatting.fontWeight() >= QFont.Weight.Bold
            italic = formatting.fontItalic()
            if bold or italic:
                start = index
                if (styles and styles[-1].end == start
                        and (styles[-1].bold, styles[-1].italic) == (bold, italic)):
                    start = styles.pop().start
                styles.append(TextStyle(start, index + 1, bold, italic))
        return tuple(styles)

    def load_styles(self, styles: Tuple[TextStyle, ...]) -> None:
        text = self.toPlainText()
        selection = self.textCursor()
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        formatting = QTextCharFormat()
        formatting.setFontWeight(QFont.Weight.Normal)
        formatting.setFontItalic(False)
        cursor.mergeCharFormat(formatting)
        for style in styles:
            cursor.setPosition(_qt_position(text, style.start))
            cursor.setPosition(_qt_position(text, style.end), QTextCursor.MoveMode.KeepAnchor)
            formatting.setFontWeight(QFont.Weight.Bold if style.bold else QFont.Weight.Normal)
            formatting.setFontItalic(style.italic)
            cursor.mergeCharFormat(formatting)
        cursor.endEditBlock()
        self.setTextCursor(selection)
        if not text:
            self.setCurrentCharFormat(formatting)
