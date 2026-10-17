"""Original canvas transform, snapshot, and preview coordinate regressions."""

import unittest
from unittest.mock import MagicMock

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QTransform

from fake_krita import APP, FakeDocument, FakeLayer, FakeShape
from krita_speech_bubble_generator.editor.preview import BubblePreview
from krita_speech_bubble_generator.bubbles.settings import SHAPE_NAME
from krita_speech_bubble_generator.krita_host.canvas_context import canvas_snapshot, canvas_transform


class ContextTests(unittest.TestCase):
    def test_canvas_transform_includes_dpi_rotation_and_scale(self):
        document = FakeDocument(None)
        baseline = QTransform().translate(-15, 7)
        delta = QTransform().translate(90, 40).rotate(30).scale(2, 0.6)
        shape = FakeShape(FakeLayer(), baseline * delta)
        transform = canvas_transform(document, baseline, shape)
        local = QPointF(40, 30)
        points = delta.map(local * (72 / 300))
        expected = points * (300 / 72)
        self.assertLess((transform.map(local) - expected).manhattanLength(), 1e-6)

    def test_context_render_and_mouse_mapping_share_transformed_coordinates(self):
        preview = BubblePreview()
        preview.resize(600, 400)
        image = QImage(800, 600, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        transform = QTransform().translate(250, 200).rotate(37).scale(1.7, 0.8)
        landmark = QPointF(40, 40)
        painter = QPainter(image)
        painter.setBrush(QColor("magenta"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(transform.map(landmark), 8, 8)
        painter.end()
        preview.setContext(image, QRectF(0, 0, 800, 600), transform)
        preview.setBubble(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-100 -100 200 200">'
            '<rect x="0" y="0" width="10" height="10" fill="blue"/></svg>',
            QRectF(-100, -100, 200, 200), None)
        widget_point = preview.toWidget(landmark, preview.view_box)
        mapped = preview.toBubble(widget_point, preview.view_box)
        self.assertLess((mapped - landmark).manhattanLength(), 1e-6)
        rendered = preview.grab().toImage()
        self.assertEqual(rendered.pixelColor(round(widget_point.x()), round(widget_point.y())),
                         QColor("magenta"))
        bubble_point = preview.toWidget(QPointF(5, 5), preview.view_box)
        self.assertEqual(rendered.pixelColor(round(bubble_point.x()), round(bubble_point.y())),
                         QColor("blue"))
        preview.close()

    def snapshotDocuments(self):
        source = MagicMock()
        layer, parent, root = MagicMock(), MagicMock(), MagicMock()
        layer.parentNode.return_value = parent
        parent.parentNode.return_value = root
        root.parentNode.return_value = None
        parent.childNodes.return_value = [MagicMock(), layer]
        root.childNodes.return_value = [parent]
        clone = source.clone.return_value
        clone_parent, clone_layer = MagicMock(), MagicMock()
        clone.rootNode.return_value.childNodes.return_value = [clone_parent]
        clone_parent.childNodes.return_value = [MagicMock(), clone_layer]
        source.width.return_value, source.height.return_value = 4000, 2000
        image = QImage(2048, 1024, QImage.Format_ARGB32)
        clone.thumbnail.return_value = image
        return source, layer, clone, clone_layer

    def test_snapshot_excludes_only_cloned_bubble_and_limits_image_size(self):
        document, layer, clone, cloned_layer = self.snapshotDocuments()
        image, rect = canvas_snapshot(document, layer)
        self.assertEqual(rect, QRectF(0, 0, 4000, 2000))
        clone.thumbnail.assert_called_once_with(2048, 1024)
        cloned_layer.setVisible.assert_called_once_with(False)
        layer.setVisible.assert_not_called()
        clone.close.assert_called_once()

    def test_snapshot_is_closed_even_when_rendering_fails(self):
        document, layer, clone, cloned_layer = self.snapshotDocuments()
        clone.thumbnail.return_value = QImage()
        with self.assertRaises(ValueError):
            canvas_snapshot(document, layer)
        clone.close.assert_called_once()

    def test_shared_layer_snapshot_hides_only_the_edited_bubble(self):
        document, layer, clone, cloned_layer = self.snapshotDocuments()
        edited, other = MagicMock(), MagicMock()
        edited.name.return_value = SHAPE_NAME + "-first"
        other.name.return_value = SHAPE_NAME + "-second"
        cloned_layer.shapes.return_value = [edited, other]
        canvas_snapshot(document, layer, edited.name())
        edited.setVisible.assert_called_once_with(False)
        edited.update.assert_called_once()
        other.setVisible.assert_not_called()
        cloned_layer.setVisible.assert_not_called()
        layer.setVisible.assert_not_called()
        clone.close.assert_called_once()
