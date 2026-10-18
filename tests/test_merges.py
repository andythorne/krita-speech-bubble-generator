"""Layer-independent bubble identity and native-style reparenting workflows."""

from dataclasses import replace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QTransform

from fake_krita import APP, FakeDocument, FakeKrita, FakeLayer, FakeShape
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import SHAPE_NAME, BubbleSettings, decode_record
from krita_speech_bubble_generator.editor.contracts import TargetMissing
from krita_speech_bubble_generator.editor.presenter import EditorPresenter
from krita_speech_bubble_generator.editor.view import BubbleEditorView
from krita_speech_bubble_generator.krita_host.gateway import KritaGateway


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.document = FakeDocument(None)
        FakeKrita.document = self.document
        self.renderer = BubbleRenderer()
        self.gateway = KritaGateway(FakeKrita, self.renderer)
        self.settings = BubbleSettings(text="Same lettering", shout_seed=17, thought_seed=29)

    def tearDown(self):
        FakeKrita.document = None

    def create(self, **values):
        settings = replace(self.settings, **values)
        return self.gateway.create(settings, self.renderer.render(settings).svg, True)

    def merge(self, bubbles, remove_sources=True, destination=None):
        """Bake group transforms into children, as native SVG reparenting can."""
        merged = destination or self.document.createVectorLayer("Merged")
        self.document.setActiveNode(merged)
        root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg")
        expected = {}
        source_ids = set()
        for index, loaded in enumerate(bubbles):
            source = self.document.nodeByUniqueID(loaded.target.layer_id)
            shape = self.gateway.shape_by_name(source, loaded.target.shape_name)
            expected[shape.name()] = self.gateway.placement(loaded.target)
            source_ids.add(source.uniqueId().toString())
            inverse, _ = QTransform(*loaded.target.baseline).inverted()
            old_placement = QTransform.fromScale(72 / 300, 72 / 300) * inverse * shape.transformation()
            parent = QTransform.fromTranslate(40 + index * 30, 60 + index * 20)
            inverse_parent, _ = parent.inverted()
            child_transform = old_placement * inverse_parent
            native_group = ET.SubElement(root, "g", id=shape.name())
            rendered = ET.fromstring(self.renderer.render(loaded.settings).svg)
            matrix = "matrix({} {} {} {} {} {})".format(
                child_transform.m11(), child_transform.m12(),
                child_transform.m21(), child_transform.m22(),
                child_transform.dx(), child_transform.dy())
            for element in rendered.iter():
                if element.tag.rsplit("}", 1)[-1] in ("path", "text"):
                    element.set("transform", matrix)
                    native_group.append(element)
            source.items.remove(shape)
            shape.layer = merged
            shape.setTransformation(parent)
            merged.items.append(shape)
        merged.svg = ET.tostring(root, encoding="unicode")
        if remove_sources:
            for identifier in source_ids:
                del self.document.layers[identifier]
        return merged, expected

    def assert_placement(self, target, expected):
        actual = self.gateway.placement(target)
        for point in (QPointF(), QPointF(100, 50), QPointF(-30, 120)):
            self.assertLess((actual.map(point) - expected.map(point)).manhattanLength(), 1e-6)

    def select(self, layer, name):
        for shape in layer.shapes():
            shape.deselect()
        self.gateway.shape_by_name(layer, name).select()
        self.document.setActiveNode(layer)
        return self.gateway.load_selected()

    def test_new_bubbles_have_unique_ids_even_on_separate_layers(self):
        first, second = self.create(), self.create()
        self.assertNotEqual(first.target.shape_name, second.target.shape_name)
        for loaded in (first, second):
            self.assertRegex(loaded.target.shape_name, r"^rsbg-bubble-[0-9a-f]{32}$")
            record = decode_record(bytes(self.document.annotation(loaded.target.shape_name)))
            self.assertEqual(record.settings, loaded.settings)
            self.assertEqual(record.baseline, loaded.target.baseline)

    def test_merged_duplicate_and_empty_lettering_loads_automatically_without_redrawing(self):
        originals = [self.create(padding=30), self.create(padding=80), self.create(text="")]
        merged, expected = self.merge(originals)
        shapes = merged.shapes()
        with patch.object(merged, "addShapesFromSvg") as importer:
            for original in originals:
                loaded = self.select(merged, original.target.shape_name)
                self.assertEqual(loaded.settings, original.settings)
                self.assertEqual(loaded.target.shape_name, original.target.shape_name)
                self.assertEqual(loaded.target.layer_id, merged.uniqueId())
                self.assert_placement(loaded.target, expected[loaded.target.shape_name])
        importer.assert_not_called()
        self.assertEqual(merged.shapes(), shapes)

    def test_reload_before_selecting_merged_bubbles_uses_saved_document_data_only(self):
        originals = [self.create(padding=30), self.create(padding=80)]
        merged, expected = self.merge(originals)
        reopened = FakeDocument(merged)
        reopened.annotations = dict(self.document.annotations)
        self.document = reopened
        FakeKrita.document = reopened
        self.gateway = KritaGateway(FakeKrita, self.renderer)
        self.assertEqual(set(self.gateway.observe().bubble_names),
                         {loaded.target.shape_name for loaded in originals})
        for original in originals:
            loaded = self.select(merged, original.target.shape_name)
            self.assertEqual(loaded.settings, original.settings)
            self.assert_placement(loaded.target, expected[loaded.target.shape_name])

    def test_repeated_merges_and_edits_keep_identity_settings_placement_and_siblings(self):
        bubbles = [self.create(padding=30), self.create(padding=80)]
        names = [loaded.target.shape_name for loaded in bubbles]
        for index in range(3):
            merged, expected = self.merge(bubbles)
            updated = []
            for original in bubbles:
                loaded = self.select(merged, original.target.shape_name)
                settings = replace(loaded.settings, text="Edit " + str(index), padding=40 + index)
                target = self.gateway.update(
                    loaded.target, settings, self.renderer.render(settings).svg)
                self.assert_placement(target, expected[target.shape_name])
                updated.append(self.gateway.load_selected())
                self.assertEqual(len(merged.shapes()), 2)
                self.assertEqual(set(self.gateway.observe().bubble_names), set(names))
                record = decode_record(bytes(self.document.annotation(target.shape_name)))
                self.assertEqual(record.settings, settings)
            bubbles = updated
        self.assertEqual([loaded.target.shape_name for loaded in bubbles], names)

    def test_moving_bubbles_works_even_when_source_layers_still_exist(self):
        originals = [self.create(), self.create(text="")]
        merged, expected = self.merge(originals, remove_sources=False)
        for original in originals:
            self.assertIsNotNone(self.document.nodeByUniqueID(original.target.layer_id))
            loaded = self.select(merged, original.target.shape_name)
            self.assertEqual(loaded.settings, original.settings)
            self.assert_placement(loaded.target, expected[loaded.target.shape_name])

    def test_returning_to_an_old_layer_does_not_reload_its_stale_settings(self):
        original = self.create(padding=30)
        source = self.document.nodeByUniqueID(original.target.layer_id)
        moved, _ = self.merge([original], remove_sources=False)
        loaded = self.select(moved, original.target.shape_name)
        settings = replace(loaded.settings, text="Latest dialogue", padding=90)
        target = self.gateway.update(loaded.target, settings, self.renderer.render(settings).svg)
        moved_bubble = self.gateway.load_selected()
        self.assertEqual(moved_bubble.target, target)
        returned, expected = self.merge([moved_bubble], destination=source)
        restored = self.select(returned, original.target.shape_name)
        self.assertEqual(restored.target.shape_name, original.target.shape_name)
        self.assertEqual(restored.settings, settings)
        self.assert_placement(restored.target, expected[restored.target.shape_name])

    def test_pending_edit_follows_its_exact_id_after_merge_not_the_selected_sibling(self):
        first, second = self.create(padding=30), self.create(padding=80)
        merged, expected = self.merge([first, second])
        self.gateway.shape_by_name(merged, second.target.shape_name).select()
        edited = replace(first.settings, text="Pending edit for first")
        target = self.gateway.update(first.target, edited, self.renderer.render(edited).svg)
        self.assertEqual(target.layer_id, merged.uniqueId())
        self.assertEqual(target.shape_name, first.target.shape_name)
        self.assert_placement(target, expected[target.shape_name])
        self.assertEqual(self.select(merged, first.target.shape_name).settings, edited)
        self.assertEqual(self.select(merged, second.target.shape_name).settings, second.settings)

    def test_ambiguous_relocated_identity_is_never_used_for_a_delayed_write(self):
        first = self.create()
        merged, _ = self.merge([first])
        duplicate = FakeShape(merged, QTransform())
        duplicate.setName(first.target.shape_name)
        merged.items.append(duplicate)
        annotations = dict(self.document.annotations)
        with patch.object(merged, "addShapesFromSvg") as importer:
            with self.assertRaises(TargetMissing):
                self.gateway.update(first.target, self.settings, self.renderer.render(self.settings).svg)
        importer.assert_not_called()
        self.assertEqual(self.document.annotations, annotations)

    def test_old_layer_scoped_bubble_is_upgraded_on_load_without_redrawing(self):
        layer = self.document.createVectorLayer("Old saved bubble")
        group = FakeShape(layer, QTransform().translate(80, 40).rotate(17))
        layer.items.append(group)
        baseline = QTransform().scale(0.24, 0.24)
        self.gateway.save_settings(self.document, layer, self.settings, baseline)
        matrix = group.transformation()
        with patch.object(layer, "addShapesFromSvg") as importer:
            loaded = self.gateway.load_selected()
        importer.assert_not_called()
        self.assertNotEqual(loaded.target.shape_name, SHAPE_NAME)
        self.assertEqual(group.transformation(), matrix)
        self.assertEqual(loaded.settings, self.settings)
        self.assertEqual(QTransform(*loaded.target.baseline), baseline)
        self.assertTrue(self.document.annotation(loaded.target.shape_name))
        self.assertTrue(self.document.annotation(self.gateway.annotation_key(layer)))

    def test_presenter_selection_polling_loads_merged_bubbles_without_recovery_action(self):
        first, second = self.create(), self.create(padding=80)
        first_layer = self.document.nodeByUniqueID(first.target.layer_id)
        first_layer.items[0].select()
        self.document.setActiveNode(first_layer)
        view = BubbleEditorView()
        presenter = EditorPresenter(view, self.gateway, self.renderer, lambda low, high: low)
        presenter.state.background_enabled = False
        try:
            with patch.object(view, "warn") as warning:
                presenter.sync_selection()
                view.bubbleText.setPlainText("Pending first dialogue")
                merged, _ = self.merge([first, second])
                for shape in merged.shapes():
                    shape.deselect()
                self.gateway.shape_by_name(merged, second.target.shape_name).select()
                presenter.sync_selection()
                self.assertEqual(presenter.state.target.shape_name, second.target.shape_name)
                self.assertEqual(presenter.state.draft,
                                 replace(second.settings, font=presenter.state.draft.font))
                self.assertIsNone(presenter.state.pending)
                first_after_merge = self.select(merged, first.target.shape_name)
                self.assertEqual(first_after_merge.settings.text, "Pending first dialogue")
                presenter.sync_selection()
                self.assertEqual(view.bubbleText.toPlainText(), "Pending first dialogue")
                warning.assert_not_called()
        finally:
            presenter.live_timer.stop()
            presenter.selection_timer.stop()
            presenter.background_timer.stop()
            view.deleteLater()
            presenter.deleteLater()
            APP.processEvents()
