"""The existing Qt form and local widget behavior, without document access."""

from dataclasses import fields, replace
from typing import Callable, Dict, Optional, Set, Tuple

from PyQt5.QtCore import Qt, QSignalBlocker, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QColorDialog, QComboBox, QFontComboBox, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSizePolicy, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .preview import BubblePreview
from .contracts import PreviewContext, RenderedBubble
from ..bubbles.registry import BUBBLE_TYPES, SHOUTING_ALGORITHMS, resolve_bubble
from ..bubbles.settings import INTEGER_RANGES, BubbleSettings
from .tail_compass import TailCompass
from .text_resize_handle import TextResizeHandle
from .wheel_guard import WheelGuard


class BubbleEditorView(QScrollArea):
    edited = pyqtSignal(object, tuple)
    tail_moved = pyqtSignal(object)
    page_requested = pyqtSignal(bool)
    new_requested = pyqtSignal()
    import_requested = pyqtSignal()
    background_toggled = pyqtSignal(bool)
    refresh_requested = pyqtSignal()
    destination_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = BubbleSettings()
        self._loading = False
        main = QVBoxLayout()
        main.setAlignment(Qt.AlignmentFlag.AlignTop)

        page_actions = QHBoxLayout()
        self.addOnPage = QPushButton("Add on Page")
        page_actions.addWidget(self.addOnPage)
        self.newBubbleButton = QPushButton("New bubble")
        self.newBubbleButton.setVisible(False)
        page_actions.addWidget(self.newBubbleButton)
        main.addLayout(page_actions)
        self.addDestination = QComboBox()
        self.addDestination.addItems(("New vector layer", "Selected vector layer"))
        self.addDestination.setToolTip("Add a bubble on its own layer or on the active vector layer.")
        main.addWidget(self.addDestination)
        self.importOldBubble = QPushButton("Import old bubble")
        self.importOldBubble.setToolTip(
            "Recover one original Rogudator bubble from the selected vector layer. "
            "The layer must contain only its ungrouped outline and text. "
            "The first edit redraws the bubble and flattens per-word formatting.")
        self.editStatus = QLabel("New bubble")
        self.editStatus.setWordWrap(True)
        main.addWidget(self.editStatus)

        preview_label = QLabel("Preview - drag the blue handle to reposition the tail")
        preview_label.setWordWrap(True)
        main.addWidget(preview_label)
        self.preview = BubblePreview(self)
        self.preview.setFixedHeight(self.preview.minimumHeight())
        main.addWidget(self.preview)
        context_row = QHBoxLayout()
        self.canvasBackground = QCheckBox("Canvas background")
        self.canvasBackground.setChecked(True)
        self.canvasBackground.setEnabled(False)
        self.canvasBackground.setToolTip(
            "Show the artwork behind the edited bubble. Follows canvas moves automatically; "
            "refresh after other artwork changes.")
        self.refreshBackground = QPushButton("Refresh background")
        self.refreshBackground.setEnabled(False)
        context_row.addWidget(self.canvasBackground)
        context_row.addWidget(self.refreshBackground)
        main.addLayout(context_row)

        self.optionsTabs = QTabWidget()
        self.optionsTabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.textTab = QWidget()
        self.bubbleTab = QWidget()
        self.tailTab = QWidget()
        self.importTab = QWidget()
        text_options = QVBoxLayout(self.textTab)
        bubble_options = QVBoxLayout(self.bubbleTab)
        tail_options = QVBoxLayout(self.tailTab)
        import_options = QVBoxLayout(self.importTab)
        for layout in (text_options, bubble_options, tail_options, import_options):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for page, label in ((self.textTab, "Text"), (self.bubbleTab, "Bubble"),
                            (self.tailTab, "Tail"), (self.importTab, "Import")):
            self.optionsTabs.addTab(page, label)
        main.addWidget(self.optionsTabs)

        self.speechGroup = QGroupBox("Speech")
        self.speechGroup.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        speech = QVBoxLayout()
        font_row = QHBoxLayout()
        self.speechFont = QFontComboBox()
        self.speechFont.setCurrentFont(QFont("Segoe Print"))
        self.speechFont.setToolTip(
            "Default: Segoe Print, when installed. Otherwise the system font is used.")
        font_row.addWidget(self.speechFont)
        self.speechFontSize = QSpinBox()
        self.speechFontSize.setRange(*INTEGER_RANGES["font_size"])
        self.speechFontSize.setValue(self._settings.font_size)
        font_row.addWidget(self.speechFontSize)
        self.speechFontColor = QColor("black")
        self.currentFontColorButton = self.colorButton(self.speechFontColor)
        font_row.addWidget(self.currentFontColorButton)
        speech.addLayout(font_row)
        self.bubbleText = QTextEdit("Krita speech bubble generator!")
        speech.addWidget(self.bubbleText)
        self.textResizeHandle = TextResizeHandle(self.bubbleText)
        speech.addWidget(self.textResizeHandle)
        self.autocenter = QCheckBox("Center automatically")
        self.autocenter.setChecked(True)
        speech.addWidget(self.autocenter)
        self.averageLineLength = QGroupBox("Characters per line (0 keeps line breaks)")
        (self.averageLineLengthSlider, self.averageLineLengthSpinBox,
         line_row) = self.numberRow("line_length")
        self.averageLineLength.setLayout(line_row)
        self.averageLineLength.setVisible(False)
        speech.addWidget(self.averageLineLength)
        self.speechGroup.setLayout(speech)
        text_options.addWidget(self.speechGroup)

        appearance_row = QHBoxLayout()
        bubble_group = QGroupBox("Bubble type")
        bubble_row = QHBoxLayout()
        self.bubbleType = QComboBox()
        self.bubbleType.addItems(tuple(BUBBLE_TYPES))
        self.bubbleType.setCurrentText(self._settings.style)
        bubble_row.addWidget(self.bubbleType)
        self.bubbleColor = QColor("white")
        self.bubbleColorButton = self.colorButton(self.bubbleColor)
        bubble_row.addWidget(self.bubbleColorButton)
        bubble_group.setLayout(bubble_row)
        appearance_row.addWidget(bubble_group, 1)

        self.outlineSlider, self.outlineSpinBox, outline_row = self.numberRow("outline")
        outline_group = QGroupBox("Outline")
        self.outlineColor = QColor("black")
        self.outlineColorButton = self.colorButton(self.outlineColor)
        outline_row.addWidget(self.outlineColorButton)
        outline_group.setLayout(outline_row)
        appearance_row.addWidget(outline_group, 1)
        bubble_options.addLayout(appearance_row)
        padding_group = QGroupBox("Padding")
        self.paddingSlider, self.paddingSpinBox, padding_row = self.numberRow("padding")
        self.paddingSpinBox.setSuffix("%")
        padding_group.setToolTip(
            "Extra space as a percentage of text size. Horizontal padding is twice vertical padding. "
            "Non-oval styles retain minimum spacing at 0%.")
        padding_group.setLayout(padding_row)
        bubble_options.addWidget(padding_group)
        self.shoutingGroup = QGroupBox("Shouting")
        self.shoutingGroup.setToolTip(
            "Vary spike spacing, with subtle changes in spike height and valley depth.")
        shouting_layout = QVBoxLayout()
        shouting_shape_row = QHBoxLayout()
        shouting_shape_row.addWidget(QLabel("Shape"))
        self.shoutingShape = QComboBox()
        self.shoutingShape.addItems(tuple(SHOUTING_ALGORITHMS))
        self.shoutingShape.setToolTip(
            "Balanced: restrained curves. Angular: straight sides. "
            "Punchy: short, broad spikes. Expressive: varied spacing and gentle lean.")
        shouting_shape_row.addWidget(self.shoutingShape, 1)
        shouting_layout.addLayout(shouting_shape_row)
        shouting_layout.addWidget(QLabel("Nodes"))
        (self.shoutingNodesSlider, self.shoutingNodesSpinBox,
         shouting_nodes_row) = self.numberRow("shout_nodes")
        self.shoutingNodesSpinBox.setToolTip("Number of spikes around the shouting bubble.")
        shouting_layout.addLayout(shouting_nodes_row)
        shouting_layout.addWidget(QLabel("Irregularity"))
        self.shoutingSlider, self.shoutingSpinBox, shouting_row = self.numberRow("shout_irregularity")
        self.shoutingSpinBox.setSuffix("%")
        shouting_layout.addLayout(shouting_row)
        self.shoutingGroup.setLayout(shouting_layout)
        self.shoutingGroup.setVisible(False)
        bubble_options.addWidget(self.shoutingGroup)
        self.thoughtGroup = QGroupBox("Thought")
        thought_layout = QVBoxLayout()
        thought_layout.addWidget(QLabel("Nodes"))
        (self.thoughtNodesSlider, self.thoughtNodesSpinBox,
         thought_nodes_row) = self.numberRow("thought_nodes")
        self.thoughtNodesSpinBox.setToolTip("Number of lobes around the thought cloud.")
        thought_layout.addLayout(thought_nodes_row)
        thought_layout.addWidget(QLabel("Irregularity"))
        self.thoughtSlider, self.thoughtSpinBox, thought_row = self.numberRow("thought_irregularity")
        self.thoughtSpinBox.setSuffix("%")
        self.thoughtGroup.setToolTip(
            "Vary cloud-lobe sizes, spacing and angles, and the shapes of the trail blobs.")
        thought_layout.addLayout(thought_row)
        self.thoughtGroup.setLayout(thought_layout)
        self.thoughtGroup.setVisible(False)
        bubble_options.addWidget(self.thoughtGroup)

        tail_group = QGroupBox("Tail")
        tail_layout = QVBoxLayout()
        tail_columns = QHBoxLayout()
        position_column = QVBoxLayout()
        position_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        position_column.addWidget(QLabel("Position"))
        self.tailCompass = TailCompass(self)
        self.tailCompass.set_angle(self._settings.tail_angle)
        position_column.addWidget(self.tailCompass)
        tail_columns.addLayout(position_column)
        self.tailLengthControls = QWidget()
        length_layout = QVBoxLayout()
        length_layout.setContentsMargins(0, 0, 0, 0)
        length_layout.addWidget(QLabel("Length (0 hides tail)"))
        self.tailSlider, self.tailSpinBox, tail_row = self.numberRow("tail_length")
        length_layout.addLayout(tail_row)
        self.tailLengthControls.setLayout(length_layout)
        self.lockTailLength = QCheckBox("Lock tail length")
        self.lockTailLength.setChecked(True)
        self.lockTailLength.setToolTip(
            "Lock to set the length with the slider or number input. "
            "Unlock to set it by dragging the tail.")
        length_column = QVBoxLayout()
        length_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        length_column.addWidget(self.lockTailLength)
        length_column.addWidget(self.tailLengthControls)
        tail_columns.addLayout(length_column, 1)
        tail_layout.addLayout(tail_columns)
        self.thoughtSizeGroup = QGroupBox("Thought blob size")
        self.thoughtSizeSlider, self.thoughtSizeSpinBox, thought_row = self.numberRow("thought_size")
        self.thoughtSizeSpinBox.setSuffix("%")
        self.thoughtSizeGroup.setLayout(thought_row)
        self.thoughtSizeGroup.setEnabled(False)
        self.thoughtSizeGroup.setVisible(False)
        tail_layout.addWidget(self.thoughtSizeGroup)
        tail_group.setLayout(tail_layout)
        tail_options.addWidget(tail_group)

        self.importInstructions = QLabel(
            "Recover an editable bubble made with the original Rogudator plugin. "
            "Select its vector layer, then click Import old bubble. "
            "If you are editing another bubble, click New bubble first.")
        self.importInstructions.setWordWrap(True)
        import_options.addWidget(self.importInstructions)
        self.importLimitations = QLabel(
            "The layer must contain exactly one ungrouped bubble outline and its text, "
            "with no other artwork.\n\n"
            "Import recovers text, font, colours, outline width and tail position. "
            "It starts with Oval and automatic wrapping, fitting padding to the old body.\n\n"
            "The artwork stays unchanged until you edit it or click Update on Page. "
            "The first edit redraws the bubble: its shape, wrapping and tail may differ, "
            "and per-word formatting such as bold is lost. Save a copy first.\n\n"
            "Save as .kra after import to keep the bubble editable.")
        self.importLimitations.setWordWrap(True)
        import_options.addWidget(self.importLimitations)
        import_options.addWidget(self.importOldBubble)

        self._numbers: Dict[str, QSpinBox] = {
            "font_size": self.speechFontSize, "outline": self.outlineSpinBox,
            "padding": self.paddingSpinBox, "line_length": self.averageLineLengthSpinBox,
            "tail_length": self.tailSpinBox, "thought_size": self.thoughtSizeSpinBox,
            "shout_irregularity": self.shoutingSpinBox, "shout_nodes": self.shoutingNodesSpinBox,
            "thought_irregularity": self.thoughtSpinBox, "thought_nodes": self.thoughtNodesSpinBox,
        }
        for field, control in self._numbers.items():
            if field != "font_size":
                control.valueChanged.connect(self._number_changed(field))
        self.speechFontSize.valueChanged.connect(self.fontSizeChanged)
        self.bubbleType.currentIndexChanged.connect(self.bubbleStyleChanged)
        self.bubbleText.textChanged.connect(lambda: self._emit("text"))
        self.speechFont.currentFontChanged.connect(lambda: self._emit("font"))
        self.autocenter.toggled.connect(self.averageLineLength.setHidden)
        self.autocenter.toggled.connect(lambda: self._emit("autocenter"))
        self.lockTailLength.toggled.connect(self.tailLengthControls.setEnabled)
        self.lockTailLength.toggled.connect(lambda: self._emit("lock_tail"))
        self.shoutingShape.currentIndexChanged.connect(lambda: self._emit("shout_shape"))
        for attribute, field, button in (
            ("bubbleColor", "fill", self.bubbleColorButton),
            ("outlineColor", "stroke", self.outlineColorButton),
            ("speechFontColor", "text_color", self.currentFontColorButton),
        ):
            button.clicked.connect(self._color_changed(attribute, field, button))
        self.preview.tailMoved.connect(self.tail_moved.emit)
        self.tailCompass.angle_selected.connect(self._tail_angle_changed)
        self.addOnPage.clicked.connect(
            lambda: self.page_requested.emit(self.addDestination.currentIndex() == 0))
        self.newBubbleButton.clicked.connect(self.new_requested.emit)
        self.importOldBubble.clicked.connect(self.import_requested.emit)
        self.canvasBackground.toggled.connect(self.background_toggled.emit)
        self.refreshBackground.clicked.connect(self.refresh_requested.emit)
        self.addDestination.currentIndexChanged.connect(self._destination_changed)

        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        widget = QWidget()
        widget.setLayout(main)
        self.setWidget(widget)
        self.wheelGuard = WheelGuard(self, self)
        for control in widget.findChildren(QWidget):
            if isinstance(control, (QAbstractSpinBox, QComboBox, QSlider)):
                control.installEventFilter(self.wheelGuard)
                if isinstance(control, (QAbstractSpinBox, QComboBox)):
                    line_edit = (QAbstractSpinBox.lineEdit(control)
                                 if isinstance(control, QAbstractSpinBox)
                                 else QComboBox.lineEdit(control))
                    if line_edit is not None:
                        line_edit.installEventFilter(self.wheelGuard)

    def _number_changed(self, field: str) -> Callable[[int], None]:
        def changed(value: int) -> None:
            self._emit(field)
        return changed

    def _destination_changed(self, index: int) -> None:
        self.destination_changed.emit(index == 0)

    def _color_changed(self, attribute: str, field: str,
                       button: QPushButton) -> Callable[[bool], None]:
        def changed(checked: bool = False) -> None:
            self.changeColor(attribute, field, button)
        return changed

    @staticmethod
    def _number_value(settings: BubbleSettings, field: str) -> int:
        value: object = getattr(settings, field)
        if not isinstance(value, int):
            raise ValueError("Not an integer setting: " + field)
        return value

    def numberRow(self, field: str) -> Tuple[QSlider, QSpinBox, QHBoxLayout]:
        minimum, maximum = ((0, self._settings.font_size * 10) if field == "tail_length"
                            else INTEGER_RANGES[field])
        value = self._number_value(self._settings, field)
        row = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        spin = QSpinBox()
        for control in (slider, spin):
            control.setRange(minimum, maximum)
            control.setValue(value)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        row.addWidget(slider)
        row.addWidget(spin)
        return slider, spin, row

    def colorButton(self, color: QColor) -> QPushButton:
        button = QPushButton()
        button.setFixedWidth(36)
        self.setColorIcon(button, color)
        return button

    @staticmethod
    def setColorIcon(button: QPushButton, color: QColor) -> None:
        image = QPixmap(24, 24)
        image.fill(color)
        button.setIcon(QIcon(image))

    def changeColor(self, attribute: str, field: str, button: QPushButton) -> None:
        colors = {"bubbleColor": self.bubbleColor, "outlineColor": self.outlineColor,
                  "speechFontColor": self.speechFontColor}
        color = QColorDialog.getColor(colors[attribute], self)
        if color.isValid():
            setattr(self, attribute, color)
            self.setColorIcon(button, color)
            self._emit(field)

    def fontSizeChanged(self) -> None:
        loading = self._loading
        self._loading = True
        try:
            maximum = self.speechFontSize.value() * 10
            self.tailSlider.setMaximum(maximum)
            self.tailSpinBox.setMaximum(maximum)
        finally:
            self._loading = loading
        self._emit("font_size", "tail_length")

    def bubbleStyleChanged(self) -> None:
        capabilities = resolve_bubble(
            self.bubbleType.currentText(), self.shoutingShape.currentText()).capabilities
        self.thoughtSizeGroup.setEnabled(capabilities.thought)
        self.thoughtSizeGroup.setVisible(capabilities.thought)
        self.thoughtGroup.setVisible(capabilities.thought)
        self.shoutingGroup.setVisible(capabilities.shouting)
        self._emit("style")

    def _emit(self, *fields: str) -> None:
        if not self._loading:
            self.edited.emit(self.initial_settings(), fields)

    def _tail_angle_changed(self, angle: float) -> None:
        if not self._loading:
            self._settings = replace(self._settings, tail_angle=angle)
            self._emit("tail_angle")

    def initial_settings(self) -> BubbleSettings:
        return replace(
            self._settings, **{field: control.value() for field, control in self._numbers.items()},
            style=self.bubbleType.currentText(), text=self.bubbleText.toPlainText(),
            font=self.speechFont.currentFont().family(), fill=self.bubbleColor.name(),
            stroke=self.outlineColor.name(), text_color=self.speechFontColor.name(),
            autocenter=self.autocenter.isChecked(), lock_tail=self.lockTailLength.isChecked(),
            shout_shape=self.shoutingShape.currentText())

    def load_settings(self, settings: BubbleSettings) -> BubbleSettings:
        return self._bind_settings(settings, {field.name for field in fields(BubbleSettings)})

    def reflect_settings(self, settings: BubbleSettings) -> BubbleSettings:
        current = self.initial_settings().to_dict()
        values = settings.to_dict()
        changed = {field.name for field in fields(BubbleSettings)
                   if current[field.name] != values[field.name]}
        return self._bind_settings(settings, changed)

    def _bind_settings(self, settings: BubbleSettings, changed: Set[str]) -> BubbleSettings:
        self._loading = True
        try:
            self._settings = settings
            if "tail_angle" in changed:
                self.tailCompass.set_angle(settings.tail_angle)
            if "style" in changed:
                self.bubbleType.setCurrentText(settings.style)
            if "text" in changed and self.bubbleText.toPlainText() != settings.text:
                self.bubbleText.setPlainText(settings.text)
            if "font" in changed and self.speechFont.currentFont().family() != settings.font:
                self.speechFont.setCurrentFont(QFont(settings.font))
            if "font_size" in changed:
                self.speechFontSize.setValue(settings.font_size)
                self.tailSlider.setMaximum(settings.font_size * 10)
                self.tailSpinBox.setMaximum(settings.font_size * 10)
            for field, control in self._numbers.items():
                if field in changed:
                    control.setValue(self._number_value(settings, field))
            if "autocenter" in changed:
                self.autocenter.setChecked(settings.autocenter)
                self.averageLineLength.setHidden(settings.autocenter)
            if "lock_tail" in changed:
                self.lockTailLength.setChecked(settings.lock_tail)
                self.tailLengthControls.setEnabled(settings.lock_tail)
            if "shout_shape" in changed:
                self.shoutingShape.setCurrentText(settings.shout_shape)
            for attribute, field, value, button in (
                ("bubbleColor", "fill", settings.fill, self.bubbleColorButton),
                ("outlineColor", "stroke", settings.stroke, self.outlineColorButton),
                ("speechFontColor", "text_color", settings.text_color, self.currentFontColorButton),
            ):
                if field in changed:
                    color = QColor(value)
                    setattr(self, attribute, color)
                    self.setColorIcon(button, color)
            if "style" in changed:
                self.bubbleStyleChanged()
            return self.initial_settings()
        finally:
            self._loading = False

    def show_render(self, rendered: RenderedBubble) -> None:
        self.preview.setBubble(rendered.svg, rendered.view_box, rendered.tip)

    def show_context(self, context: Optional[PreviewContext]) -> None:
        if context is None:
            self.preview.setContext()
        else:
            self.preview.setContext(context.image, context.rect, context.transform)

    def show_mode(self, editing: bool, label: str) -> None:
        self.addOnPage.setText("Update on Page" if editing else "Add on Page")
        self.newBubbleButton.setVisible(editing)
        self.addDestination.setVisible(not editing)
        self.importOldBubble.setVisible(not editing)
        self.editStatus.setText(label)

    def show_background(self, enabled: bool, available: bool) -> None:
        blocker = QSignalBlocker(self.canvasBackground)
        self.canvasBackground.setChecked(enabled)
        del blocker
        self.canvasBackground.setEnabled(available)
        self.refreshBackground.setEnabled(enabled and available)

    def is_dragging(self) -> bool:
        return self.preview.dragging

    def set_new_layer(self, new_layer: bool) -> None:
        blocker = QSignalBlocker(self.addDestination)
        self.addDestination.setCurrentIndex(0 if new_layer else 1)
        del blocker

    def warn(self, message: str) -> None:
        QMessageBox.warning(self, "Speech bubble generator", message)
