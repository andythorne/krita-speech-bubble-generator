import json
import math
import random
import uuid

from PyQt5.QtCore import QByteArray, QPointF, QRectF, Qt, QSignalBlocker, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPixmap, QTransform
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QColorDialog, QComboBox, QFontComboBox, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)
from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita

from .bubble_geometry import (
    MAX_NODES, MIN_NODES, SHOUTING_SHAPES, STYLES, body_path, bubble_path,
    bubble_svg, outline_anchor, tail_tip,
)
from .bubble_preview import BubblePreview
from .canvas_context import canvas_snapshot, canvas_transform
from .text_resize_handle import TextResizeHandle
from .wheel_guard import WheelGuard


# Keep the saved-document format compatible with bubbles created before the rename.
ANNOTATION_PREFIX = "rsbg-bubble-"
SHAPE_NAME = "rsbg-bubble"


def transform_values(transform):
    return [transform.m11(), transform.m12(), transform.m21(),
            transform.m22(), transform.dx(), transform.dy()]


class SpeechBubbleDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Krita Speech Bubble Generator")
        self.tailAngle = math.pi / 4
        self.loading = False
        self.editDocument = None
        self.editLayerId = None
        self.editShapeName = None
        self.editBaseline = None
        self.updating = False
        self.lastAppliedSettings = None
        self.pendingLiveUpdate = False
        self.shoutSeed = random.randrange(2 ** 31)
        self.thoughtSeed = random.randrange(2 ** 31)
        self.observedDocument = None
        self.observedLayerId = None
        self.observedShapeNames = ()
        self.liveTimer = QTimer(self)
        self.liveTimer.setSingleShot(True)
        self.liveTimer.setInterval(150)
        self.liveTimer.timeout.connect(self.applyLiveUpdate)
        self.selectionTimer = QTimer(self)
        self.selectionTimer.setInterval(150)
        self.selectionTimer.timeout.connect(self.syncSelection)
        self.backgroundTimer = QTimer(self)
        self.backgroundTimer.setSingleShot(True)
        self.backgroundTimer.setInterval(250)
        self.backgroundTimer.timeout.connect(self.refreshMovedBackground)
        main = QVBoxLayout()
        main.setAlignment(Qt.AlignTop)

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

        appearance_row = QHBoxLayout()
        bubble_group = QGroupBox("Bubble type")
        bubble_row = QHBoxLayout()
        self.bubbleType = QComboBox()
        self.bubbleType.addItems(STYLES)
        self.bubbleType.setCurrentText("Rounded")
        bubble_row.addWidget(self.bubbleType)
        self.bubbleColor = QColor("white")
        self.bubbleColorButton = self.colorButton(self.bubbleColor)
        bubble_row.addWidget(self.bubbleColorButton)
        bubble_group.setLayout(bubble_row)
        appearance_row.addWidget(bubble_group, 1)

        self.outlineSlider, self.outlineSpinBox, outline_row = self.numberRow(0, 50, 3)
        outline_group = QGroupBox("Outline")
        self.outlineColor = QColor("black")
        self.outlineColorButton = self.colorButton(self.outlineColor)
        outline_row.addWidget(self.outlineColorButton)
        outline_group.setLayout(outline_row)
        appearance_row.addWidget(outline_group, 1)
        main.addLayout(appearance_row)
        padding_group = QGroupBox("Padding")
        self.paddingSlider, self.paddingSpinBox, padding_row = self.numberRow(0, 300, 150)
        self.paddingSpinBox.setSuffix("%")
        padding_group.setToolTip(
            "Space between text and the bubble edge, as a percentage of the text size.")
        padding_group.setLayout(padding_row)
        main.addWidget(padding_group)
        self.shoutingGroup = QGroupBox("Shouting")
        self.shoutingGroup.setToolTip(
            "Vary spike spacing, with subtle changes in spike height and valley depth.")
        shouting_layout = QVBoxLayout()
        shouting_shape_row = QHBoxLayout()
        shouting_shape_row.addWidget(QLabel("Shape"))
        self.shoutingShape = QComboBox()
        self.shoutingShape.addItems(SHOUTING_SHAPES)
        self.shoutingShape.setToolTip(
            "Balanced: restrained curves. Angular: straight sides. "
            "Punchy: short, broad spikes. Expressive: varied spacing and gentle lean.")
        shouting_shape_row.addWidget(self.shoutingShape, 1)
        shouting_layout.addLayout(shouting_shape_row)
        shouting_layout.addWidget(QLabel("Nodes"))
        (self.shoutingNodesSlider, self.shoutingNodesSpinBox,
         shouting_nodes_row) = self.numberRow(MIN_NODES, MAX_NODES, 24)
        self.shoutingNodesSpinBox.setToolTip("Number of spikes around the shouting bubble.")
        shouting_layout.addLayout(shouting_nodes_row)
        shouting_layout.addWidget(QLabel("Irregularity"))
        self.shoutingSlider, self.shoutingSpinBox, shouting_row = self.numberRow(0, 100, 50)
        self.shoutingSpinBox.setSuffix("%")
        shouting_layout.addLayout(shouting_row)
        self.shoutingGroup.setLayout(shouting_layout)
        self.shoutingGroup.setVisible(False)
        main.addWidget(self.shoutingGroup)
        self.thoughtGroup = QGroupBox("Thought")
        thought_layout = QVBoxLayout()
        thought_layout.addWidget(QLabel("Nodes"))
        (self.thoughtNodesSlider, self.thoughtNodesSpinBox,
         thought_nodes_row) = self.numberRow(MIN_NODES, MAX_NODES, 16)
        self.thoughtNodesSpinBox.setToolTip("Number of lobes around the thought cloud.")
        thought_layout.addLayout(thought_nodes_row)
        thought_layout.addWidget(QLabel("Irregularity"))
        self.thoughtSlider, self.thoughtSpinBox, thought_row = self.numberRow(0, 100, 50)
        self.thoughtSpinBox.setSuffix("%")
        self.thoughtGroup.setToolTip(
            "Vary cloud-lobe sizes, spacing and angles, and the shapes of the trail blobs.")
        thought_layout.addLayout(thought_row)
        self.thoughtGroup.setLayout(thought_layout)
        self.thoughtGroup.setVisible(False)
        main.addWidget(self.thoughtGroup)

        tail_group = QGroupBox("Tail")
        tail_layout = QVBoxLayout()
        self.tailLengthControls = QWidget()
        length_layout = QVBoxLayout()
        length_layout.setContentsMargins(0, 0, 0, 0)
        length_layout.addWidget(QLabel("Length (0 hides tail)"))
        self.tailSlider, self.tailSpinBox, tail_row = self.numberRow(0, 140, 0)
        self.tailSpinBox.setVisible(False)
        length_layout.addLayout(tail_row)
        self.tailLengthControls.setLayout(length_layout)
        self.lockTailLength = QCheckBox("Lock tail length")
        self.lockTailLength.setChecked(True)
        self.lockTailLength.setToolTip(
            "Lock to set the length with the slider. Unlock to set it by dragging the tail.")
        tail_layout.addWidget(self.lockTailLength)
        tail_layout.addWidget(self.tailLengthControls)
        self.thoughtSizeGroup = QGroupBox("Thought blob size")
        self.thoughtSizeSlider, self.thoughtSizeSpinBox, thought_row = self.numberRow(25, 400, 100)
        self.thoughtSizeSpinBox.setSuffix("%")
        self.thoughtSizeGroup.setLayout(thought_row)
        self.thoughtSizeGroup.setEnabled(False)
        self.thoughtSizeGroup.setVisible(False)
        tail_layout.addWidget(self.thoughtSizeGroup)
        tail_group.setLayout(tail_layout)
        main.addWidget(tail_group)

        self.speechGroup = QGroupBox("Speech")
        self.speechGroup.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        speech = QVBoxLayout()
        font_row = QHBoxLayout()
        self.speechFont = QFontComboBox()
        self.speechFont.setCurrentFont(QFont("Segoe Print"))
        self.speechFont.setToolTip(
            "Default: Segoe Print, when installed. Otherwise the system font is used.")
        font_row.addWidget(self.speechFont)
        self.speechFontSize = QSpinBox()
        self.speechFontSize.setRange(1, 99)
        self.speechFontSize.setValue(14)
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
         line_row) = self.numberRow(0, 100, 0)
        self.averageLineLength.setLayout(line_row)
        self.averageLineLength.setVisible(False)
        speech.addWidget(self.averageLineLength)
        self.speechGroup.setLayout(speech)
        main.insertWidget(main.indexOf(self.preview) + 1, self.speechGroup)

        for control in (self.outlineSpinBox, self.paddingSpinBox, self.averageLineLengthSpinBox,
                        self.tailSpinBox, self.thoughtSizeSpinBox,
                        self.shoutingNodesSpinBox, self.thoughtNodesSpinBox):
            control.valueChanged.connect(self.updatePreview)
        self.speechFontSize.valueChanged.connect(self.fontSizeChanged)
        self.bubbleType.currentIndexChanged.connect(self.bubbleStyleChanged)
        self.bubbleText.textChanged.connect(self.updatePreview)
        self.speechFont.currentFontChanged.connect(self.updatePreview)
        self.autocenter.toggled.connect(self.averageLineLength.setHidden)
        self.autocenter.toggled.connect(self.updatePreview)
        self.lockTailLength.toggled.connect(self.tailLengthControls.setVisible)
        self.lockTailLength.toggled.connect(self.updatePreview)
        self.shoutingSpinBox.valueChanged.connect(lambda: self.changePattern("shoutSeed"))
        self.shoutingShape.currentIndexChanged.connect(self.updatePreview)
        self.thoughtSpinBox.valueChanged.connect(lambda: self.changePattern("thoughtSeed"))
        self.bubbleColorButton.clicked.connect(
            lambda: self.changeColor("bubbleColor", self.bubbleColorButton))
        self.outlineColorButton.clicked.connect(
            lambda: self.changeColor("outlineColor", self.outlineColorButton))
        self.currentFontColorButton.clicked.connect(
            lambda: self.changeColor("speechFontColor", self.currentFontColorButton))
        self.preview.tailMoved.connect(self.moveTail)
        self.addOnPage.clicked.connect(self.addOnPageShape)
        self.newBubbleButton.clicked.connect(self.startNewBubble)
        self.canvasBackground.toggled.connect(self.toggleCanvasBackground)
        self.refreshBackground.clicked.connect(self.refreshCanvasBackground)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        widget = QWidget()
        widget.setLayout(main)
        scroll.setWidget(widget)
        self.setWidget(scroll)
        self.wheelGuard = WheelGuard(scroll, self)
        for control in widget.findChildren(QWidget):
            if isinstance(control, (QAbstractSpinBox, QComboBox, QSlider)):
                control.installEventFilter(self.wheelGuard)
                if isinstance(control, (QAbstractSpinBox, QComboBox)) and control.lineEdit() is not None:
                    control.lineEdit().installEventFilter(self.wheelGuard)
        self.updatePreview()

    def numberRow(self, minimum, maximum, value):
        row = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        spin = QSpinBox()
        for control in (slider, spin):
            control.setRange(minimum, maximum)
            control.setValue(value)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        row.addWidget(slider)
        row.addWidget(spin)
        return slider, spin, row

    def colorButton(self, color):
        button = QPushButton()
        button.setFixedWidth(36)
        self.setColorIcon(button, color)
        return button

    def setColorIcon(self, button, color):
        image = QPixmap(24, 24)
        image.fill(color)
        button.setIcon(QIcon(image))

    def changeColor(self, attribute, button):
        color = QColorDialog.getColor(getattr(self, attribute), self)
        if color.isValid():
            setattr(self, attribute, color)
            self.setColorIcon(button, color)
            self.updatePreview()

    def fontSizeChanged(self):
        maximum = self.speechFontSize.value() * 10
        self.tailSlider.setMaximum(maximum)
        self.tailSpinBox.setMaximum(maximum)
        self.updatePreview()

    def bubbleStyleChanged(self):
        thought = self.bubbleType.currentText() == "Thought"
        self.thoughtSizeGroup.setEnabled(thought)
        self.thoughtSizeGroup.setVisible(thought)
        self.thoughtGroup.setVisible(thought)
        self.shoutingGroup.setVisible(self.bubbleType.currentText() == "Shouting")
        self.updatePreview()

    def changePattern(self, attribute):
        if not self.loading:
            seed = (getattr(self, attribute) + random.randrange(1, 2 ** 31)) % (2 ** 31)
            setattr(self, attribute, seed)
            self.updatePreview()

    def getSpeechLines(self, text, lineLength, measure=len):
        lines = []
        for paragraph in text.split("\n"):
            if lineLength <= 0:
                lines.append(paragraph)
                continue
            line = ""
            for word in paragraph.split():
                if line and measure(line + " " + word) > lineLength:
                    lines.append(line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            lines.append(line)
        return lines

    def automaticSpeechLines(self, text, width, measure):
        result = []
        for paragraph in text.split("\n"):
            lines = self.getSpeechLines(paragraph, width, measure)
            if len(lines) > 1:
                low = min(width, max(measure(word) for word in paragraph.split()))
                high = width
                # Keep the chosen line count, but avoid a long first line and tiny last line.
                for _ in range(10):
                    middle = (low + high) / 2
                    if len(self.getSpeechLines(paragraph, middle, measure)) <= len(lines):
                        high = middle
                    else:
                        low = middle
                lines = self.getSpeechLines(paragraph, high, measure)
            result.extend(lines)
        return result

    def geometry(self):
        text = self.bubbleText.toPlainText()
        size = self.speechFontSize.value()
        font = self.speechFont.currentFont()
        font.setPixelSize(size)
        metrics = QFontMetricsF(font)
        if self.autocenter.isChecked():
            total_width = sum(metrics.horizontalAdvance(line) for line in text.split("\n"))
            target_width = max(size * 16, math.sqrt(total_width * size * 1.3 * 2))
            lines = self.automaticSpeechLines(text, target_width, metrics.horizontalAdvance)
        else:
            lines = self.getSpeechLines(text, self.averageLineLengthSpinBox.value())
        width = max(metrics.horizontalAdvance(line) for line in lines)
        height = metrics.height() + (len(lines) - 1) * size * 1.3
        style = self.bubbleType.currentText()
        padding = size * self.paddingSpinBox.value() / 100
        if style in ("Oval", "Thought", "Shouting"):
            body_width = (width + 2 * padding) * math.sqrt(2)
            body_height = (height + 2 * padding) * math.sqrt(2)
        else:
            body_width = width + 2 * padding
            body_height = height + 2 * padding
        body_width = max(1, body_width)
        body_height = max(1, body_height)
        # Stable body coordinates: changing tail direction never moves the text.
        rect = QRectF(0, 0, body_width, body_height)
        text_rect = QRectF((body_width - width) / 2,
                          (body_height - height) / 2, width, height)
        if style == "Thought":
            irregularity, seed = self.thoughtSpinBox.value(), self.thoughtSeed
            nodes = self.thoughtNodesSpinBox.value()
        else:
            irregularity, seed = self.shoutingSpinBox.value(), self.shoutSeed
            nodes = self.shoutingNodesSpinBox.value()
        corner_radius = min(size * 3, padding)
        body = body_path(rect, style, corner_radius, irregularity, seed,
                         self.shoutingShape.currentText(), nodes)
        tip = None
        if self.tailSpinBox.value() > 0:
            tip = tail_tip(body, rect.center(), self.tailAngle, self.tailSpinBox.value())
        path = bubble_path(body, rect.center(), tip, style, size,
                           self.thoughtSizeSpinBox.value(),
                           self.thoughtSpinBox.value(), self.thoughtSeed)
        return rect, text_rect, body, path, tip, lines, metrics

    def renderBubble(self, preview=False):
        rect, text_rect, body, path, tip, lines, metrics = self.geometry()
        margin = max(8, self.outlineSpinBox.value() / 2 + 2)
        if preview:
            view_box = path.boundingRect().adjusted(-margin, -margin, margin, margin)
            if tip is None and not self.lockTailLength.isChecked():
                tip = tail_tip(body, rect.center(), self.tailAngle, 0)
        else:
            # Do not translate the SVG origin when the tail changes sides.
            view_box = QRectF(0, 0, max(1, rect.width()), max(1, rect.height()))
        svg = bubble_svg(
            path, lines, text_rect, self.speechFont.currentFont().family(),
            self.speechFontSize.value(), metrics.ascent(), self.bubbleColor.name(),
            self.outlineColor.name(), self.outlineSpinBox.value(),
            self.speechFontColor.name(), view_box)
        return svg, view_box, tip

    def getPreview(self):
        return self.renderBubble(preview=True)[0]

    def updatePreview(self, *args):
        if not self.loading:
            self.preview.setBubble(*self.renderBubble(preview=True))
            if (not self.updating and self.editLayerId is not None
                    and self.settings() != self.lastAppliedSettings):
                self.pendingLiveUpdate = True
                self.liveTimer.start()
            elif not self.updating and self.settings() == self.lastAppliedSettings:
                self.pendingLiveUpdate = False
                self.liveTimer.stop()

    def moveTail(self, point):
        rect, text_rect, body, path, tip, lines, metrics = self.geometry()
        offset = point - rect.center()
        if math.hypot(offset.x(), offset.y()) < 1e-6:
            return
        self.tailAngle = math.atan2(offset.y(), offset.x())
        if not self.lockTailLength.isChecked():
            direction = QPointF(math.cos(self.tailAngle), math.sin(self.tailAngle))
            anchor = outline_anchor(body, rect.center(), direction)
            distance = (point.x() - anchor.x()) * direction.x() + (
                point.y() - anchor.y()) * direction.y()
            self.tailSpinBox.setValue(max(0, min(self.tailSpinBox.maximum(), round(distance))))
        self.updatePreview()

    def settings(self):
        return {
            "version": 1, "style": self.bubbleType.currentText(),
            "text": self.bubbleText.toPlainText(),
            "font": self.speechFont.currentFont().family(),
            "font_size": self.speechFontSize.value(),
            "fill": self.bubbleColor.name(), "stroke": self.outlineColor.name(),
            "text_color": self.speechFontColor.name(),
            "outline": self.outlineSpinBox.value(),
            "padding": self.paddingSpinBox.value(),
            "autocenter": self.autocenter.isChecked(),
            "line_length": self.averageLineLengthSpinBox.value(),
            "tail_length": self.tailSpinBox.value(), "tail_angle": self.tailAngle,
            "lock_tail": self.lockTailLength.isChecked(),
            "thought_size": self.thoughtSizeSpinBox.value(),
            "shout_irregularity": self.shoutingSpinBox.value(),
            "shout_shape": self.shoutingShape.currentText(),
            "shout_nodes": self.shoutingNodesSpinBox.value(),
            "shout_seed": self.shoutSeed,
            "thought_irregularity": self.thoughtSpinBox.value(),
            "thought_nodes": self.thoughtNodesSpinBox.value(),
            "thought_seed": self.thoughtSeed,
        }

    def annotationKey(self, layer, shape_name=SHAPE_NAME):
        key = ANNOTATION_PREFIX + layer.uniqueId().toString()
        return key if shape_name == SHAPE_NAME else key + "-" + shape_name

    def saveSettings(self, document, layer, baseline, shape_name=SHAPE_NAME):
        settings = self.settings()
        settings["baseline"] = transform_values(baseline)
        document.setAnnotation(self.annotationKey(layer, shape_name), "Speech bubble settings",
                               QByteArray(json.dumps(settings).encode("utf-8")))

    def warn(self, message):
        QMessageBox.warning(self, "Speech bubble generator", message)

    def addOnPageShape(self):
        if self.loading or self.updating:
            return
        if self.editLayerId is not None:
            return self.updateBubble()
        document = Krita.instance().activeDocument()
        if document is None:
            self.warn("Open a document before adding a bubble.")
            return
        self.flushLiveUpdate()
        self.updating = True
        try:
            self.addBubbleToLayer(document)
        finally:
            self.updating = False

    def startNewBubble(self):
        self.flushLiveUpdate()
        document = Krita.instance().activeDocument()
        layer = document.activeNode() if document else None
        if layer is not None and layer.type() == "vectorlayer":
            for shape in layer.shapes():
                self.deselectShape(shape)
        self.stopEditing()
        self.observedDocument = document
        self.observedLayerId = layer.uniqueId() if layer else None
        self.observedShapeNames = ()
        self.editStatus.setText("New bubble")

    def updatePageAction(self):
        editing = self.editLayerId is not None
        self.addOnPage.setText("Update on Page" if editing else "Add on Page")
        self.newBubbleButton.setVisible(editing)
        self.addDestination.setVisible(not editing)

    def addBubbleToLayer(self, document):
        created_layer = self.addDestination.currentIndex() == 0
        if created_layer:
            layer = document.createVectorLayer(self.bubbleText.toPlainText()[:16] or "Speech bubble")
            document.rootNode().addChildNode(layer, None)
        else:
            layer = document.activeNode()
            if layer is None or layer.type() != "vectorlayer":
                self.warn("Select a vector layer before adding a bubble to an existing layer.")
                return
            if layer.locked():
                self.warn("Unlock the selected vector layer before adding a bubble.")
                return
        previous_shapes = layer.shapes()
        name_in_use = any(shape.name() == SHAPE_NAME for shape in previous_shapes)
        name_in_use = name_in_use or bool(document.annotation(self.annotationKey(layer)))
        shape_name = SHAPE_NAME + "-" + uuid.uuid4().hex if name_in_use else SHAPE_NAME
        shapes = layer.addShapesFromSvg(self.renderBubble()[0])
        if not shapes:
            if created_layer:
                layer.remove()
            self.warn("Krita could not import the bubble SVG.")
            return
        group = self.bubbleGroup(layer, shapes, shape_name)
        if group is None:
            if created_layer:
                layer.remove()
            else:
                for shape in shapes:
                    shape.remove()
            self.warn("Krita could not group the bubble shapes.")
            return
        baseline = group.transformation()
        group.setZIndex(max((shape.zIndex() for shape in previous_shapes), default=-1) + 1)
        bounds = group.boundingBox()
        margin = self.speechFontSize.value()
        x, y = margin, margin
        if not created_layer and previous_shapes:
            previous = previous_shapes[-1].boundingBox()
            x, y = max(margin, previous.left() + margin), max(margin, previous.top() + margin)
        placement = QTransform.fromTranslate(x - bounds.left(), y - bounds.top())
        self.placeShape(group, baseline * placement)
        self.saveSettings(document, layer, baseline, shape_name)
        document.setActiveNode(layer)
        for shape in previous_shapes:
            if self.shapeSelected(shape):
                self.deselectShape(shape)
        group.select()
        self.refreshCanvas(document)
        self.setEditTarget(document, layer, baseline, shape_name)

    def bubbleGroup(self, layer, shapes, shape_name=SHAPE_NAME):
        if len(shapes) == 1 and shapes[0].type() == "groupshape":
            group = shapes[0]
        else:
            group = layer.createGroupShape(shape_name, shapes)
        if group is not None:
            group.setName(shape_name)
        return group

    def setEditTarget(self, document, layer, baseline, shape_name=SHAPE_NAME):
        self.liveTimer.stop()
        self.backgroundTimer.stop()
        self.pendingLiveUpdate = False
        self.editDocument = document
        self.editLayerId = layer.uniqueId()
        self.editShapeName = shape_name
        self.editBaseline = baseline
        self.lastAppliedSettings = self.settings()
        self.observedDocument = document
        self.observedLayerId = layer.uniqueId()
        self.observedShapeNames = self.selectedShapeNames(layer.shapes())
        self.updatePageAction()
        self.editStatus.setText("Editing: " + layer.name())
        self.canvasBackground.setEnabled(True)
        self.preview.setContext()
        if self.canvasBackground.isChecked():
            self.refreshCanvasBackground()
        self.updatePreview()

    def shapeSelected(self, shape):
        if shape.isSelected():
            return True
        return shape.type() == "groupshape" and any(
            self.shapeSelected(child) for child in shape.children())

    def deselectShape(self, shape):
        if shape.type() == "groupshape":
            for child in shape.children():
                self.deselectShape(child)
        if shape.isSelected():
            shape.deselect()

    def selectedShapeNames(self, shapes):
        return tuple(sorted(shape.name() for shape in shapes if self.shapeSelected(shape)))

    def bubbleShapes(self, document, layer):
        return [
            shape for shape in layer.shapes()
            if shape.type() == "groupshape"
            and (shape.name() == SHAPE_NAME or shape.name().startswith(SHAPE_NAME + "-"))
            and document.annotation(self.annotationKey(layer, shape.name()))
        ]

    def shapeByName(self, layer, shape_name):
        shapes = [shape for shape in layer.shapes() if shape.name() == shape_name]
        return shapes[0] if len(shapes) == 1 and shapes[0].type() == "groupshape" else None

    def resolveBubble(self, document, layer, shape_name=None):
        bubbles = self.bubbleShapes(document, layer)
        if shape_name is not None:
            matches = [shape for shape in bubbles if shape.name() == shape_name]
            return matches[0] if len(matches) == 1 else None
        selected = self.selectedShapeNames(layer.shapes())
        if len(selected) == 1:
            matches = [shape for shape in bubbles if shape.name() == selected[0]]
            return matches[0] if len(matches) == 1 else None
        if not selected and len(bubbles) == 1:
            return bubbles[0]
        return None

    def flushLiveUpdate(self):
        if not self.pendingLiveUpdate:
            return
        self.liveTimer.stop()
        self.pendingLiveUpdate = False
        if Krita.instance().activeDocument() == self.editDocument:
            return self.updateBubble()

    def applyLiveUpdate(self):
        if self.loading or self.updating:
            return
        # Resolve a selection change before deciding which bubble can receive this edit.
        self.syncSelection()
        if (self.editLayerId is not None
                and self.settings() != self.lastAppliedSettings):
            return self.updateBubble()

    def stopEditing(self):
        self.liveTimer.stop()
        self.backgroundTimer.stop()
        self.pendingLiveUpdate = False
        self.editDocument = None
        self.editLayerId = None
        self.editShapeName = None
        self.editBaseline = None
        self.lastAppliedSettings = None
        self.updatePageAction()
        self.canvasBackground.setEnabled(False)
        self.refreshBackground.setEnabled(False)
        self.editStatus.setText("New bubble - select a bubble to edit")
        self.preview.setContext()
        self.updatePreview()

    def syncSelection(self, force=False):
        if self.loading or self.updating:
            return
        document = Krita.instance().activeDocument()
        layer = document.activeNode() if document else None
        layer_id = layer.uniqueId() if layer else None
        vector_layer = layer is not None and layer.type() == "vectorlayer"
        bubbles = self.bubbleShapes(document, layer) if vector_layer else []
        shapes = layer.shapes() if bubbles else []
        selected = self.selectedShapeNames(shapes)
        layer_changed = document != self.observedDocument or layer_id != self.observedLayerId
        if not force and not layer_changed and selected == self.observedShapeNames:
            self.syncCanvasPlacement()
            return
        self.observedDocument = document
        self.observedLayerId = layer_id
        self.observedShapeNames = selected
        target = None
        if len(selected) == 1:
            target = self.resolveBubble(document, layer, selected[0])
        elif not selected and len(bubbles) == 1 and (
                layer_changed or (force and self.editShapeName == bubbles[0].name())):
            target = bubbles[0]
        target_name = target.name() if target is not None else None
        same_target = (
            document == self.editDocument and layer_id == self.editLayerId
            and target_name == self.editShapeName)
        if not same_target:
            self.flushLiveUpdate()
        if target is None:
            self.stopEditing()
        elif not same_target:
            self.loadSelectedBubble(target_name)
        else:
            self.syncCanvasPlacement()

    def syncCanvasPlacement(self):
        if (self.editDocument is None or not self.canvasBackground.isChecked()
                or self.preview.dragging or self.preview.background.isNull()):
            return
        document = Krita.instance().activeDocument()
        if document != self.editDocument:
            return
        layer = document.nodeByUniqueID(self.editLayerId)
        shape = self.shapeByName(layer, self.editShapeName) if layer is not None else None
        if shape is None:
            self.stopEditing()
            return
        try:
            transform = canvas_transform(document, self.editBaseline, shape)
        except ValueError as error:
            self.disableCanvasBackground(error)
            return
        if transform != self.preview.bubble_transform:
            self.preview.setContext(self.preview.background, self.preview.canvas_rect, transform)
            self.updatePreview()
            self.backgroundTimer.start()

    def refreshMovedBackground(self):
        if self.loading or self.updating:
            self.backgroundTimer.start()
            return
        target = (self.editDocument, self.editLayerId, self.editShapeName)
        self.syncSelection()
        if target != (self.editDocument, self.editLayerId, self.editShapeName):
            return
        if (self.editDocument is not None and self.canvasBackground.isChecked()
                and Krita.instance().activeDocument() == self.editDocument):
            self.refreshCanvasBackground()

    def placeShape(self, group, transform, old_bounds=None):
        dirty = group.boundingBox()
        if old_bounds is not None:
            dirty = dirty.united(old_bounds)
        group.setTransformation(transform)
        group.updateAbsolute(dirty.united(group.boundingBox()))
        group.update()

    def refreshCanvas(self, document):
        # Flush the vector layer's delayed rasterization before recomposing the image.
        document.waitForDone()
        document.refreshProjection()

    def toggleCanvasBackground(self, enabled):
        self.backgroundTimer.stop()
        self.refreshBackground.setEnabled(enabled)
        if enabled:
            self.refreshCanvasBackground()
        else:
            self.preview.setContext()
            self.updatePreview()

    def disableCanvasBackground(self, error):
        self.backgroundTimer.stop()
        self.preview.setContext()
        blocker = QSignalBlocker(self.canvasBackground)
        self.canvasBackground.setChecked(False)
        del blocker
        self.refreshBackground.setEnabled(False)
        self.updatePreview()
        self.warn("Cannot show the canvas background: " + str(error))

    def refreshCanvasBackground(self):
        self.backgroundTimer.stop()
        document = Krita.instance().activeDocument()
        layer = None
        if document is not None and document == self.editDocument:
            layer = document.nodeByUniqueID(self.editLayerId)
        try:
            if layer is None:
                raise ValueError("Open the document containing the bubble being edited")
            shape = self.shapeByName(layer, self.editShapeName)
            if shape is None:
                raise ValueError("The bubble's vector group has changed")
            transform = canvas_transform(document, self.editBaseline, shape)
            image, rect = canvas_snapshot(document, layer, self.editShapeName)
        except ValueError as error:
            self.disableCanvasBackground(error)
            return
        self.preview.setContext(image, rect, transform)
        self.refreshBackground.setEnabled(True)
        self.updatePreview()

    def loadSelectedBubble(self, shape_name=None):
        if self.loading or self.updating:
            return
        document = Krita.instance().activeDocument()
        layer = document.activeNode() if document else None
        if layer is None or layer.type() != "vectorlayer":
            self.flushLiveUpdate()
            self.stopEditing()
            self.warn("Select a bubble vector layer made with this version of the plugin.")
            return
        self.flushLiveUpdate()
        shape = self.resolveBubble(document, layer, shape_name)
        if shape is None:
            self.stopEditing()
            self.warn("Select one generated bubble on this vector layer to edit it.")
            return
        data = bytes(document.annotation(self.annotationKey(layer, shape.name())))
        try:
            settings = json.loads(data.decode("utf-8"))
            self.validateSettings(settings)
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            self.stopEditing()
            self.warn("Cannot read this bubble's settings: " + str(error))
            return
        self.loading = True
        try:
            self.bubbleType.setCurrentText(settings["style"])
            self.bubbleText.setPlainText(settings["text"])
            self.speechFont.setCurrentFont(QFont(settings["font"]))
            self.speechFontSize.setValue(settings["font_size"])
            self.outlineSpinBox.setValue(settings["outline"])
            self.paddingSpinBox.setValue(settings["padding"])
            self.autocenter.setChecked(settings["autocenter"])
            self.averageLineLengthSpinBox.setValue(settings["line_length"])
            self.tailSpinBox.setValue(settings["tail_length"])
            self.tailAngle = settings["tail_angle"]
            self.lockTailLength.setChecked(settings["lock_tail"])
            self.thoughtSizeSpinBox.setValue(settings["thought_size"])
            self.thoughtSpinBox.setValue(settings["thought_irregularity"])
            self.thoughtNodesSpinBox.setValue(settings["thought_nodes"])
            self.thoughtSeed = settings["thought_seed"]
            self.shoutingSpinBox.setValue(settings["shout_irregularity"])
            self.shoutingShape.setCurrentText(settings["shout_shape"])
            self.shoutingNodesSpinBox.setValue(settings["shout_nodes"])
            self.shoutSeed = settings["shout_seed"]
            for attribute, key, button in (
                ("bubbleColor", "fill", self.bubbleColorButton),
                ("outlineColor", "stroke", self.outlineColorButton),
                ("speechFontColor", "text_color", self.currentFontColorButton),
            ):
                color = QColor(settings[key])
                setattr(self, attribute, color)
                self.setColorIcon(button, color)
        finally:
            self.loading = False
        self.setEditTarget(document, layer, QTransform(*settings["baseline"]), shape.name())
        self.updatePreview()

    def validateSettings(self, settings):
        if not isinstance(settings, dict):
            raise ValueError("Invalid bubble settings")
        if settings.get("style") == "Round":
            settings["style"] = "Rounded"
        settings.setdefault("lock_tail", True)
        settings.setdefault("thought_size", 100)
        settings.setdefault("shout_irregularity", 0)
        settings.setdefault("shout_seed", 0)
        settings.setdefault("shout_shape", "Balanced")
        settings.setdefault("shout_nodes", 18 if settings["shout_shape"] == "Punchy" else 24)
        settings.setdefault("thought_irregularity", 0)
        settings.setdefault("thought_nodes", 16)
        settings.setdefault("thought_seed", 0)
        settings.setdefault("padding", 150)
        if settings["version"] != 1 or settings["style"] not in STYLES:
            raise ValueError("Unsupported bubble format")
        if settings["shout_shape"] not in SHOUTING_SHAPES:
            raise ValueError("Invalid shouting shape")
        for key in ("text", "font", "fill", "stroke", "text_color"):
            if not isinstance(settings[key], str):
                raise ValueError("Invalid " + key)
        for key in ("fill", "stroke", "text_color"):
            if not QColor(settings[key]).isValid():
                raise ValueError("Invalid " + key)
        for key, low, high in (
            ("font_size", 1, 99), ("outline", 0, 50), ("padding", 0, 300),
            ("line_length", 0, 100),
            ("tail_length", 0, settings["font_size"] * 10),
            ("thought_size", 25, 400),
            ("shout_nodes", MIN_NODES, MAX_NODES), ("thought_nodes", MIN_NODES, MAX_NODES),
            ("shout_irregularity", 0, 100), ("shout_seed", 0, 2 ** 31 - 1),
            ("thought_irregularity", 0, 100), ("thought_seed", 0, 2 ** 31 - 1),
        ):
            if type(settings[key]) is not int or not low <= settings[key] <= high:
                raise ValueError("Invalid " + key)
        if type(settings["autocenter"]) is not bool:
            raise ValueError("Invalid text alignment")
        if type(settings["lock_tail"]) is not bool:
            raise ValueError("Invalid tail length lock")
        if not isinstance(settings["tail_angle"], (int, float)) or not math.isfinite(settings["tail_angle"]):
            raise ValueError("Invalid tail angle")
        if len(settings["baseline"]) != 6 or not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in settings["baseline"]
        ):
            raise ValueError("Invalid bubble transform")
        if not QTransform(*settings["baseline"]).isInvertible():
            raise ValueError("Invalid bubble transform")

    def updateBubble(self):
        if self.loading or self.updating:
            return False
        self.liveTimer.stop()
        self.pendingLiveUpdate = False
        self.updating = True
        try:
            return self.writeBubble()
        finally:
            self.updating = False

    def writeBubble(self):
        document = Krita.instance().activeDocument()
        if document is None or document != self.editDocument:
            self.warn("Return to the document containing the bubble being edited.")
            return
        layer = document.nodeByUniqueID(self.editLayerId)
        if layer is None or layer.type() != "vectorlayer":
            self.warn("The bubble layer no longer exists. Select a bubble and reopen it.")
            return
        if layer.locked():
            self.warn("Unlock the bubble layer before updating it.")
            return
        old_shape = self.shapeByName(layer, self.editShapeName)
        if old_shape is None:
            self.warn("The bubble's vector structure has changed. Updating would overwrite manual edits.")
            return
        selected = self.shapeSelected(old_shape)
        inverse, invertible = self.editBaseline.inverted()
        if not invertible:
            self.warn("The saved bubble transform is not invertible.")
            return
        # Preserve canvas moves, rotations and scaling, not the old tail's bounds.
        delta = inverse * old_shape.transformation()
        shapes = layer.addShapesFromSvg(self.renderBubble()[0])
        if not shapes:
            self.warn("Krita could not import the updated bubble SVG.")
            return
        group = self.bubbleGroup(layer, shapes, self.editShapeName)
        if group is None:
            for shape in shapes:
                shape.remove()
            self.warn("Krita could not group the updated bubble shapes.")
            return
        baseline = group.transformation()
        self.placeShape(group, baseline * delta, old_shape.boundingBox())
        group.setZIndex(old_shape.zIndex())
        if not old_shape.remove():
            group.remove()
            self.warn("Krita could not replace the original bubble.")
            return
        if selected:
            group.select()
        self.saveSettings(document, layer, baseline, self.editShapeName)
        self.editBaseline = baseline
        self.lastAppliedSettings = self.settings()
        self.refreshCanvas(document)
        if self.canvasBackground.isChecked():
            try:
                transform = canvas_transform(document, baseline, group)
            except ValueError as error:
                self.disableCanvasBackground(error)
            else:
                self.preview.setContext(self.preview.background, self.preview.canvas_rect, transform)
                self.updatePreview()
        return True

    def canvasChanged(self, canvas):
        self.syncSelection()
        if self.editDocument is not None and self.canvasBackground.isChecked():
            self.refreshCanvasBackground()

    def showEvent(self, event):
        super().showEvent(event)
        self.selectionTimer.start()

    def hideEvent(self, event):
        self.flushLiveUpdate()
        self.selectionTimer.stop()
        self.backgroundTimer.stop()
        super().hideEvent(event)


Krita.instance().addDockWidgetFactory(DockWidgetFactory(
    "Krita Speech Bubble Generator", DockWidgetFactoryBase.DockRight, SpeechBubbleDocker))
