"""Native-boundary behavior exercised against explicit substitute documents."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QImage, QTransform

from fake_krita import FakeDocument, FakeKrita, FakeLayer, FakeShape
from legacy_fixture import legacy_corner_path, legacy_svg
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import (
    ANNOTATION_PREFIX, SHAPE_NAME, BubbleSettings, SettingsError, decode_record,
)
from krita_speech_bubble_generator.editor.contracts import GatewayError, TargetMissing
from krita_speech_bubble_generator.krita_host.gateway import KritaGateway
from krita_speech_bubble_generator.krita_host.legacy import read_legacy_bubble


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.renderer = BubbleRenderer()
        self.gateway = KritaGateway(FakeKrita, self.renderer)
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

    def legacy_layer(self):
        layer = self.document.createVectorLayer("Old bubble")
        layer.svg = legacy_svg()
        for i in range(3):
            shape = FakeShape(layer, QTransform.fromTranslate(i * 3, i * 4))
            shape.setName("shape" + str(i))
            shape.type = lambda: "pathshape"
            layer.items.append(shape)
        return layer

    def test_import_groups_existing_artwork_and_saves_settings_without_redrawing(self):
        layer = self.legacy_layer()
        originals = layer.shapes()
        transforms = [shape.transformation() for shape in originals]
        with patch.object(layer, "addShapesFromSvg", wraps=layer.addShapesFromSvg) as importer:
            loaded = self.gateway.import_legacy()
            importer.assert_not_called()
        group = layer.items[0]
        self.assertEqual(group.children(), originals)
        self.assertEqual([shape.transformation() for shape in originals], transforms)
        self.assertEqual(loaded.settings.text, "First & second A bold word")
        self.assertEqual(loaded.settings.style, "Oval")
        self.assertTrue(loaded.settings.autocenter)
        self.assertTrue(group.isSelected())
        self.assertEqual(self.gateway.load_selected(), loaded)
        self.assertEqual(self.gateway.observe().bubble_names, (loaded.target.shape_name,))

    def test_imported_bubble_first_update_retains_old_body_canvas_placement(self):
        layer = self.legacy_layer()
        legacy = read_legacy_bubble(layer.svg)
        loaded = self.gateway.import_legacy()
        target = self.update(loaded.target, loaded.settings)
        actual = self.gateway.placement(target)
        body = self.renderer.render(loaded.settings).view_box
        expected = legacy.placement(body) * QTransform.fromScale(
            self.document.xRes() / 72, self.document.yRes() / 72)
        for point in (QPointF(), body.center(), body.bottomRight()):
            self.assertLess((actual.map(point) - expected.map(point)).manhattanLength(), 1e-6)
        self.assertEqual(len(layer.items), 1)
        self.assertEqual(self.gateway.load_selected().target, target)

    def test_import_fits_corner_tail_to_original_tip_after_body_reflow_and_transforms(self):
        for horizontal in (-1, 1):
            for vertical in (-1, 1):
                for length in (3, 20, 60):
                    for transform in (QTransform(),
                                      QTransform().scale(0.4, 0.7).rotate(28).translate(100, 200)):
                        with self.subTest(horizontal=horizontal, vertical=vertical,
                                          length=length, transform=transform):
                            layer = self.legacy_layer()
                            matrix = "matrix({} {} {} {} {} {})".format(
                                transform.m11(), transform.m12(), transform.m21(),
                                transform.m22(), transform.dx(), transform.dy())
                            layer.svg = legacy_svg(
                                path=legacy_corner_path(horizontal, vertical, length),
                                transform=matrix, text_transform=matrix)
                            legacy = read_legacy_bubble(layer.svg)
                            loaded = self.gateway.import_legacy()
                            geometry = self.renderer.geometry(loaded.settings)
                            placement = legacy.placement(geometry.body_rect)
                            inverse, invertible = placement.inverted()
                            self.assertTrue(invertible)
                            original_tip = legacy.transform.map(legacy.tip)
                            expected = inverse.map(original_tip)
                            offset = geometry.tip - expected
                            self.assertLessEqual(math.hypot(offset.x(), offset.y()), 0.500001)
                            self.assertTrue(loaded.settings.lock_tail)
                            target = self.update(loaded.target, loaded.settings)
                            actual = self.gateway.placement(target).map(geometry.tip)
                            scale = QTransform.fromScale(
                                self.document.xRes() / 72, self.document.yRes() / 72)
                            expected_canvas = scale.map(original_tip)
                            rounding_error = self.gateway.placement(target).map(expected) - actual
                            self.assertLessEqual(
                                (actual - expected_canvas).manhattanLength(),
                                rounding_error.manhattanLength() + 1e-5)
                            self.assertEqual(self.gateway.load_selected().settings, loaded.settings)

    def test_import_padding_fits_reflowed_text_without_double_counting_oval_clearance(self):
        examples = (
            legacy_svg(),
            legacy_svg().replace("First &amp; second", "Hi").replace(
                "A <tspan style=\"font-weight: 700;\">bold</tspan> word", "there"),
            legacy_svg(path="M0 0L2000 0L2000 1000L0 1000L0 0Z"),
        )
        paddings = []
        for svg in examples:
            with self.subTest(svg=svg):
                layer = self.legacy_layer()
                layer.svg = svg
                legacy = read_legacy_bubble(svg)
                loaded = self.gateway.import_legacy()
                settings = loaded.settings
                fitting = [
                    padding for padding in range(301)
                    if (self.renderer.geometry(replace(settings, padding=padding)).body_rect.width()
                        <= legacy.body.width()
                        and self.renderer.geometry(
                            replace(settings, padding=padding)).body_rect.height()
                        <= legacy.body.height())]
                expected = max(fitting, default=0)
                self.assertEqual(settings.padding, expected)
                self.assertEqual(self.gateway.load_selected().settings, settings)
                paddings.append(settings.padding)
        self.assertLess(paddings[0], paddings[1])
        self.assertGreater(paddings[1], 0)
        self.assertEqual(paddings[2], 300)

    def test_import_padding_is_independent_of_canvas_scale_and_rotation(self):
        expected = None
        for transform in (QTransform(), QTransform().scale(0.4, 0.7).rotate(28)):
            with self.subTest(transform=transform):
                matrix = "matrix({} {} {} {} {} {})".format(
                    transform.m11(), transform.m12(), transform.m21(), transform.m22(),
                    transform.dx(), transform.dy())
                layer = self.legacy_layer()
                layer.svg = legacy_svg(transform=matrix, text_transform=matrix)
                settings = self.gateway.import_legacy().settings
                if expected is None:
                    expected = settings.padding
                self.assertEqual(settings.padding, expected)

    def test_import_baseline_handles_group_normalization_and_later_canvas_transforms(self):
        layer = self.legacy_layer()
        original_grouping = layer.createGroupShape
        grouping = QTransform().translate(44, -23).rotate(12)
        def normalized_group(name, shapes):
            group = original_grouping(name, shapes)
            group.setTransformation(grouping)
            return group
        with patch.object(layer, "createGroupShape", side_effect=normalized_group):
            loaded = self.gateway.import_legacy()
        group = layer.items[0]
        moved = QTransform().translate(80, 120).rotate(-31).scale(1.2, 0.9)
        group.setTransformation(group.transformation() * moved)
        body = self.renderer.render(loaded.settings).view_box
        expected = (
            read_legacy_bubble(layer.svg).placement(body) * moved
            * QTransform.fromScale(self.document.xRes() / 72, self.document.yRes() / 72))
        target = self.update(loaded.target, loaded.settings)
        actual = self.gateway.placement(target)
        for point in (body.topLeft(), body.center(), body.bottomRight()):
            self.assertLess((actual.map(point) - expected.map(point)).manhattanLength(), 1e-6)

    def test_import_rejects_ambiguous_locked_or_already_editable_layers_without_changes(self):
        with self.assertRaisesRegex(GatewayError, "Select"):
            self.gateway.import_legacy()
        layer = self.legacy_layer()
        originals = layer.shapes()
        layer.is_locked = True
        with self.assertRaisesRegex(GatewayError, "Unlock"):
            self.gateway.import_legacy()
        layer.is_locked = False
        layer.svg = legacy_svg(extra='<rect width="20" height="20"/>')
        with self.assertRaises(SettingsError):
            self.gateway.import_legacy()
        layer.svg = legacy_svg()
        layer.items.append(FakeShape(layer, QTransform()))
        with self.assertRaisesRegex(GatewayError, "ungrouped"):
            self.gateway.import_legacy()
        layer.items.pop()
        self.assertEqual(layer.shapes(), originals)
        self.assertEqual(self.document.annotations, {})
        loaded = self.gateway.import_legacy()
        key = self.gateway.annotation_key(layer, loaded.target.shape_name)
        record = bytes(self.document.annotation(key))
        with self.assertRaisesRegex(GatewayError, "already"):
            self.gateway.import_legacy()
        self.assertEqual(bytes(self.document.annotation(key)), record)
        self.assertEqual(self.gateway.load_selected(), loaded)

    def test_import_group_failure_does_not_discard_original_artwork(self):
        layer = self.legacy_layer()
        originals = layer.shapes()
        with patch.object(layer, "createGroupShape", return_value=None):
            with self.assertRaisesRegex(GatewayError, "group"):
                self.gateway.import_legacy()
        self.assertEqual(layer.shapes(), originals)
        self.assertEqual(self.document.annotations, {})

    def test_create_saves_version_one_record_and_returns_only_identity_and_baseline(self):
        loaded = self.create()
        layer = self.document.activeNode()
        shape = layer.items[0]
        self.assertRegex(loaded.target.shape_name, r"^rsbg-bubble-[0-9a-f]{32}$")
        key = self.gateway.annotation_key(layer, loaded.target.shape_name)
        record = decode_record(bytes(self.document.annotation(key)))
        self.assertEqual(bytes(self.document.annotation(loaded.target.shape_name)),
                         bytes(self.document.annotation(key)))
        self.assertEqual(record.settings, self.settings)
        self.assertEqual(record.baseline, loaded.target.baseline)
        self.assertTrue(shape.isSelected())
        self.assertGreaterEqual(shape.boundingBox().left(), self.settings.font_size)
        self.assertGreaterEqual(shape.boundingBox().top(), self.settings.font_size)
        self.assertEqual(self.document.events[-2:], ["wait", "projection"])
        self.assertEqual(self.gateway.observe().selected_names, (loaded.target.shape_name,))

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
            self.gateway.annotation_key(first_layer, first.target.shape_name)))).settings.text, "Edited")
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
            duplicate.setName(original.name())
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
        key = self.gateway.annotation_key(layer, loaded.target.shape_name)
        record = bytes(self.document.annotation(key))
        layer.fail_import = True
        with self.assertRaisesRegex(GatewayError, "import the updated"):
            self.update(loaded.target)
        self.assertEqual(layer.items, [old])
        self.assertEqual(bytes(self.document.annotation(key)), record)
        self.assertEqual(self.gateway.load_selected().target, loaded.target)

    def test_group_failure_cleans_only_imported_shapes_for_add_and_update(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        key = self.gateway.annotation_key(layer, loaded.target.shape_name)
        record = bytes(self.document.annotation(key))
        with patch.object(self.gateway, "bubble_group", return_value=None):
            with self.assertRaisesRegex(GatewayError, "group"):
                self.create(new_layer=False)
            self.assertEqual(layer.items, [old])
            with self.assertRaisesRegex(GatewayError, "group"):
                self.update(loaded.target)
            self.assertEqual(layer.items, [old])
        self.assertFalse(getattr(layer, "removed", False))
        self.assertEqual(bytes(self.document.annotation(key)), record)

    def test_failed_original_removal_cleans_replacement_and_does_not_save_new_record(self):
        loaded = self.create()
        layer = self.document.activeNode()
        old = layer.items[0]
        key = self.gateway.annotation_key(layer, loaded.target.shape_name)
        record = bytes(self.document.annotation(key))
        with patch.object(old, "remove", return_value=False):
            with self.assertRaisesRegex(GatewayError, "replace the original"):
                self.update(loaded.target)
        self.assertEqual(layer.items, [old])
        self.assertEqual(bytes(self.document.annotation(key)), record)

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
            self.gateway.annotation_key(layer, loaded.target.shape_name)))).settings, loaded.settings)

    def test_recursive_selection_and_deselection_include_selected_children(self):
        loaded = self.create()
        layer = self.document.activeNode()
        group = layer.items[0]
        group.deselect()
        child = FakeShape(layer, QTransform())
        child.setName("inner-path")
        child.select()
        with patch.object(group, "children", return_value=[child]):
            self.assertEqual(self.gateway.selected_names(layer.shapes()), (loaded.target.shape_name,))
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
            snapshot.assert_called_once_with(self.document, layer, loaded.target.shape_name)
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
