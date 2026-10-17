"""A substitute host; real Qt still owns widgets, timers, and rendering."""

import os
import sys
import types
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QByteArray, QRectF, QUuid
from PyQt5.QtGui import QTransform
from PyQt5.QtWidgets import QApplication, QDockWidget


class FakeKrita:
    document = None
    factories = []

    @classmethod
    def instance(cls):
        return cls

    @classmethod
    def activeDocument(cls):
        return cls.document

    @classmethod
    def addDockWidgetFactory(cls, factory):
        cls.factories.append(factory)


krita = types.ModuleType("krita")
krita.Krita = FakeKrita
krita.DockWidget = QDockWidget
krita.DockWidgetFactory = lambda *args: args
krita.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=0)
sys.modules.setdefault("krita", krita)

from krita_speech_bubble_generator.bubbles.settings import SHAPE_NAME

APP = QApplication.instance() or QApplication([])


class FakeShape:
    def __init__(self, layer, baseline):
        self.layer = layer
        self.matrix = baseline
        self.shape_name = SHAPE_NAME
        self.selected = False
        self.z_index = 0
        self.is_visible = True

    def isSelected(self):
        return self.selected

    def select(self):
        self.selected = True

    def deselect(self):
        self.selected = False

    def zIndex(self):
        return self.z_index

    def setZIndex(self, value):
        self.z_index = value

    def setVisible(self, visible):
        self.is_visible = visible

    def children(self):
        return []

    def type(self):
        return "groupshape"

    def name(self):
        return self.shape_name

    def setName(self, name):
        self.shape_name = name

    def transformation(self):
        return QTransform(self.matrix)

    def absoluteTransformation(self):
        return self.transformation()

    def boundingBox(self):
        return self.matrix.mapRect(QRectF(-10, -20, 200, 120))

    def setTransformation(self, matrix):
        self.matrix = QTransform(matrix)
        self.layer.events.append("transform")

    def updateAbsolute(self, bounds):
        self.layer.events.append(("dirty", QRectF(bounds)))

    def update(self):
        self.layer.events.append("shape-update")

    def remove(self):
        self.layer.items.remove(self)
        self.layer.events.append("remove")
        return True


class FakeLayer:
    def __init__(self):
        self.identifier = QUuid.createUuid()
        self.items = []
        self.is_locked = False
        self.fail_import = False
        self.events = []

    def uniqueId(self):
        return self.identifier

    def name(self):
        return "Test bubble"

    def type(self):
        return "vectorlayer"

    def locked(self):
        return self.is_locked

    def remove(self):
        self.removed = True
        return True

    def shapes(self):
        return list(self.items)

    def addShapesFromSvg(self, svg):
        if self.fail_import:
            return []
        root = ET.fromstring(svg)
        path = root.find(".//{http://www.w3.org/2000/svg}path")
        baseline = QTransform.fromTranslate(-len(path.attrib["d"]) / 100, -7)
        shape = FakeShape(self, baseline)
        self.items.append(shape)
        return [shape]


class FakeDocument:
    def __init__(self, layer):
        self.layer = layer
        self.annotations = {}
        self.events = []
        self.layers = {}
        if layer:
            layer.events = self.events
            self.layers[layer.uniqueId().toString()] = layer

    def activeNode(self):
        return self.layer

    def rootNode(self):
        return self

    def createVectorLayer(self, name):
        self.layer = FakeLayer()
        self.layer.events = self.events
        self.layers[self.layer.uniqueId().toString()] = self.layer
        return self.layer

    def addChildNode(self, layer, above):
        return True

    def setActiveNode(self, layer):
        self.layer = layer

    def annotation(self, key):
        return self.annotations.get(key, QByteArray())

    def setAnnotation(self, key, description, value):
        self.annotations[key] = value

    def nodeByUniqueID(self, identifier):
        return self.layers.get(identifier.toString()) if identifier is not None else None

    def refreshProjection(self):
        self.events.append("projection")

    def waitForDone(self):
        self.events.append("wait")

    def xRes(self):
        return 300

    def yRes(self):
        return 300
