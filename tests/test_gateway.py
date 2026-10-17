"""Native-boundary behavior exercised against explicit substitute documents."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QImage, QTransform

from fake_krita import FakeDocument, FakeKrita, FakeLayer, FakeShape
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import (
    ANNOTATION_PREFIX, SHAPE_NAME, BubbleSettings, decode_record,
)
from krita_speech_bubble_generator.editor.contracts import GatewayError, TargetMissing
from krita_speech_bubble_generator.krita_host.gateway import KritaGateway


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = KritaGateway(FakeKrita)
        self.renderer = BubbleRenderer()
        self.settings = BubbleSettings(text="First bubble", shout_seed=17, thought_seed=29)
        self.document = FakeDocument(None)
        FakeKrita.document = self.document

    def tearDown(self):
        FakeKrita.document = None

    def create(self, settings=None, new_layer=True):
        settings = settings or self.settings
        return self.gateway.create(settings, self.renderer.render(settings).svg, new_layer)

    def update(self, target, settings=None):
        settings = settings or replace(self.settings, text="Edited")
        return self.gateway.update(target, settings, self.renderer.render(settings).svg)

    def test_create_saves_version_one_record_and_returns_only_identity_and_baseline(self):
        loaded = self.create()
        layer = self.document.activeNode()
        shape = layer.items[0]
        self.assertEqual(loaded.target.shape_name, SHAPE_NAME)
        record = decode_record(bytes(self.document.annotation(self.gateway.annotation_key(layer))))
        self.assertEqual(record.settings, self.settings)
        self.assertEqual(record.baseline, loaded.target.baseline)
        self.assertTrue(shape.isSelected())
        self.assertGreaterEqual(shape.boundingBox().left(), self.settings.font_size)
        self.assertGreaterEqual(shape.boundingBox().top(), self.settings.font_size)
        self.assertEqual(self.document.events[-2:], ["wait", "projection"])
        self.assertEqual(self.gateway.observe().selected_names, (SHAPE_NAME,))

    def test_shared_layer_uses_unique_names_and_annotation_keys(self):
        first = self.create()
        layer = self.document.activeNode()
        first_shape = layer.items[0]
        first_shape.setZIndex(13)
        second = self.create(replace(self.settings, text="Second"), False)
        self.assertEqual(len(layer.items), 2)
        self.assertNotEqual(first.target.shape_name, second.target.shape_name)
        self.assertTrue(second.target.shape_name.startswith(SHAPE_NAME + "-"))
        self.assertEqual(layer.items[1].zIndex(), 14)
        self.assertFalse(first_shape.isSelected())
        self.assertTrue(layer.items[1].isSelected())
        self.assertEqual(self.gateway.annotation_key(layer),
                         ANNOTATION_PREFIX + layer.uniqueId().toString())
        self.assertTrue(self.gateway.annotation_key(layer, second.target.shape_name).endswith(
            "-" + second.target.shape_name))
        first_shape.select()
        self.assertIsNone(self.gateway.resolve_bubble(self.document, layer))

    def test_explicit_target_updates_its_layer_not_the_current_native_selection(self):
        first = self.create()
        first_layer = self.document.activeNode()
        old = first_layer.items[0]
        second = self.create(replace(self.settings, text="Second"), True)
        second_layer = self.document.activeNode()
        second_shape = second_layer.items[0]
        updated = self.update(first.target)
        self.assertNotIn(old, first_layer.items)
        self.assertEqual(second_layer.items, [second_shape])
        self.assertEqual(updated.identity, first.target.identity)
        self.assertEqual(decode_record(bytes(self.document.annotation(
            self.gateway.annotation_key(first_layer)))).settings.text, "Edited")
        self.assertEqual(self.gateway.load_selected().target, second.target)

    def test_repeated_updates_preserve_transform_selection_stacking_and_siblings(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        old.setZIndex(12)
        delta = QTransform().translate(400, 120).rotate(31).scale(1.7, 0.8)
        old.setTransformation(QTransform(*loaded.target.baseline) * delta)
        sibling = FakeShape(layer, QTransform.fromTranslate(900, 700))
        sibling.setName("Artwork")
        sibling.setZIndex(50)
        layer.items.append(sibling)
        target = loaded.target
        for style in ("Thought", "Shouting", "Square"):
            target = self.update(target, replace(self.settings, style=style, tail_length=60))
            group = self.gateway.shape_by_name(layer, target.shape_name)
            inverse, invertible = QTransform(*target.baseline).inverted()
            actual = inverse * group.transformation()
            for point in (QPointF(), QPointF(100, 50)):
                self.assertLess((actual.map(point) - delta.map(point)).manhattanLength(), 1e-6)
            self.assertTrue(group.isSelected())
            self.assertEqual(group.zIndex(), 12)
            self.assertEqual(len(layer.items), 2)
            self.assertIn(sibling, layer.items)
            self.assertEqual(sibling.transformation(), QTransform.fromTranslate(900, 700))
            self.assertEqual(sibling.zIndex(), 50)

    def test_locked_deleted_duplicate_and_cross_document_targets_reject_without_import(self):
        loaded = self.create()
        layer = self.document.activeNode()
        original = layer.items[0]
        with patch.object(layer, "addShapesFromSvg", wraps=layer.addShapesFromSvg) as importer:
            layer.is_locked = True
            with self.assertRaisesRegex(GatewayError, "Unlock"):
                self.update(loaded.target)
            layer.is_locked = False
            duplicate = FakeShape(layer, QTransform())
            layer.items.append(duplicate)
            with self.assertRaises(TargetMissing):
                self.update(loaded.target)
            layer.items.remove(duplicate)
            self.document.layers.clear()
            with self.assertRaises(TargetMissing):
                self.update(loaded.target)
            FakeKrita.document = FakeDocument(None)
            with self.assertRaisesRegex(GatewayError, "Return to the document"):
                self.update(loaded.target)
            importer.assert_not_called()
        self.assertEqual(layer.items, [original])

    def test_failed_import_preserves_original_annotation_and_baseline(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        record = bytes(self.document.annotation(self.gateway.annotation_key(layer)))
        layer.fail_import = True
        with self.assertRaisesRegex(GatewayError, "import the updated"):
            self.update(loaded.target)
        self.assertEqual(layer.items, [old])
        self.assertEqual(bytes(self.document.annotation(self.gateway.annotation_key(layer))), record)
        self.assertEqual(self.gateway.load_selected().target, loaded.target)

    def test_group_failure_cleans_only_imported_shapes_for_add_and_update(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        record = bytes(self.document.annotation(self.gateway.annotation_key(layer)))
        with patch.object(self.gateway, "bubble_group", return_value=None):
            with self.assertRaisesRegex(GatewayError, "group"):
                self.create(new_layer=False)
            self.assertEqual(layer.items, [old])
            with self.assertRaisesRegex(GatewayError, "group"):
                self.update(loaded.target)
            self.assertEqual(layer.items, [old])
        self.assertFalse(getattr(layer, "removed", False))
        self.assertEqual(bytes(self.document.annotation(self.gateway.annotation_key(layer))), record)

    def test_failed_original_removal_cleans_replacement_and_does_not_save_new_record(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        record = bytes(self.document.annotation(self.gateway.annotation_key(layer)))
        with patch.object(old, "remove", return_value=False):
            with self.assertRaisesRegex(GatewayError, "replace the original"):
                self.update(loaded.target)
        self.assertEqual(layer.items, [old])
        self.assertEqual(bytes(self.document.annotation(self.gateway.annotation_key(layer))), record)

    def test_failed_cleanup_is_reported_instead_of_silently_treating_import_as_removed(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        replacement = FakeShape(layer, QTransform())
        def import_replacement(svg):
            layer.items.append(replacement)
            return [replacement]
        with patch.object(layer, "addShapesFromSvg", side_effect=import_replacement), \
                patch.object(old, "remove", return_value=False), \
                patch.object(replacement, "remove", return_value=False):
            with self.assertRaisesRegex(GatewayError, "replace or remove"):
                self.update(loaded.target)
        self.assertIn(old, layer.items)
        self.assertEqual(decode_record(bytes(self.document.annotation(
            self.gateway.annotation_key(layer)))).settings, loaded.settings)

    def test_recursive_selection_and_deselection_include_selected_children(self):
        self.create()
        layer = self.document.activeNode()
        group = layer.items[0]
        group.deselect()
        child = FakeShape(layer, QTransform())
        child.setName("inner-path")
        child.select()
        with patch.object(group, "children", return_value=[child]):
            self.assertEqual(self.gateway.selected_names(layer.shapes()), (SHAPE_NAME,))
            self.assertIs(self.gateway.resolve_bubble(self.document, layer), group)
            observed = self.gateway.deselect()
            self.assertEqual(observed.selected_names, ())
            self.assertFalse(child.isSelected())

    def test_import_failure_removes_new_layer_but_never_an_existing_layer(self):
        layer = FakeLayer()
        layer.fail_import = True
        with patch.object(self.document, "createVectorLayer", return_value=layer):
            with self.assertRaisesRegex(GatewayError, "import"):
                self.create()
        self.assertTrue(layer.removed)
        existing = FakeLayer()
        existing.fail_import = True
        self.document.setActiveNode(existing)
        with self.assertRaisesRegex(GatewayError, "import"):
            self.create(new_layer=False)
        self.assertFalse(getattr(existing, "removed", False))

    def test_new_layer_attachment_and_cleanup_failures_are_explicit(self):
        layer = FakeLayer()
        with patch.object(self.document, "createVectorLayer", return_value=layer), \
                patch.object(self.document, "addChildNode", return_value=False):
            with self.assertRaisesRegex(GatewayError, "add the bubble layer"):
                self.create()
        self.assertTrue(layer.removed)
        layer.fail_import = True
        with patch.object(self.document, "createVectorLayer", return_value=layer), \
                patch.object(layer, "remove", return_value=False):
            with self.assertRaisesRegex(GatewayError, "remove the failed bubble import"):
                self.create()

    def test_snapshot_resolves_current_group_and_never_hides_shared_siblings(self):
        loaded = self.create()
        layer = self.document.activeNode()
        image = QImage(2, 2, QImage.Format_ARGB32)
        rect = QRectF(0, 0, 800, 600)
        with patch("krita_speech_bubble_generator.krita_host.gateway.canvas_snapshot",
                   return_value=(image, rect)) as snapshot:
            context = self.gateway.snapshot(loaded.target)
            snapshot.assert_called_once_with(self.document, layer, SHAPE_NAME)
        self.assertIs(context.image, image)
        self.assertEqual(context.rect, rect)
        self.assertEqual(context.transform, self.gateway.placement(loaded.target))

    def test_snapshot_and_transform_failures_have_explicit_gateway_failure_semantics(self):
        loaded = self.create()
        with patch("krita_speech_bubble_generator.krita_host.gateway.canvas_snapshot",
                   side_effect=ValueError("Snapshot failed")):
            with self.assertRaisesRegex(GatewayError, "Snapshot failed"):
                self.gateway.snapshot(loaded.target)
        with patch.object(self.document, "xRes", return_value=0):
            with self.assertRaisesRegex(GatewayError, "resolution"):
                self.gateway.placement(loaded.target)
