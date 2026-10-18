"""Recovery of saved bubbles after native layer merges and group renaming."""

from dataclasses import replace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QTransform

from fake_krita import FakeDocument, FakeKrita, FakeLayer, FakeShape
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import (
    SHAPE_NAME, BubbleSettings, SettingsError,
)
from krita_speech_bubble_generator.editor.contracts import GatewayError
from krita_speech_bubble_generator.krita_host.gateway import KritaGateway
from krita_speech_bubble_generator.krita_host.recovery import detached_group, matching_records


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.renderer = BubbleRenderer()
        self.gateway = KritaGateway(FakeKrita, self.renderer)
        self.layer = FakeLayer()
        self.document = FakeDocument(self.layer)
        FakeKrita.document = self.document
        self.settings = BubbleSettings(text="Recover this dialogue", shout_seed=17, thought_seed=29)
        self.source = FakeLayer()
        self.gateway.save_settings(
            self.document, self.source, self.settings, QTransform().scale(0.8, 1.1))
        self.group = FakeShape(self.layer, QTransform().translate(80, 35).rotate(23).scale(2, 0.7))
        self.group.setName(SHAPE_NAME + "2")
        self.group.select()
        self.layer.items.append(self.group)
        self.sibling = FakeShape(self.layer, QTransform.fromTranslate(900, 700))
        self.sibling.setName("Other artwork")
        self.layer.items.append(self.sibling)
        self.set_svg()

    def tearDown(self):
        FakeKrita.document = None

    def set_svg(self, settings=None, transform="matrix(0.24 0 0 0.24 -4.8 -4.8)"):
        rendered = ET.fromstring(self.renderer.render(settings or self.settings).svg)
        root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg")
        group = ET.SubElement(root, "g", id=self.group.name())
        for child in rendered.iter():
            if child.tag.rsplit("}", 1)[-1] in ("path", "text"):
                child.set("transform", transform)
                group.append(child)
        self.layer.svg = ET.tostring(root, encoding="unicode")

    def test_recovery_reconnects_settings_without_redrawing_or_changing_other_artwork(self):
        shapes = self.layer.shapes()
        old_matrix = self.group.transformation()
        old_name = self.group.name()
        old_annotations = dict(self.document.annotations)
        self.group.setZIndex(13)
        with patch.object(self.layer, "addShapesFromSvg") as importer:
            loaded = self.gateway.recover_selected()
        importer.assert_not_called()
        self.assertEqual(self.layer.shapes(), shapes)
        self.assertEqual(self.group.transformation(), old_matrix)
        self.assertEqual(self.group.zIndex(), 13)
        self.assertTrue(self.group.isSelected())
        self.assertFalse(self.sibling.isSelected())
        self.assertNotEqual(loaded.target.shape_name, old_name)
        self.assertTrue(loaded.target.shape_name.startswith(SHAPE_NAME + "-"))
        self.assertEqual(loaded.settings, self.settings)
        self.assertEqual(self.gateway.load_selected(), loaded)
        for key, value in old_annotations.items():
            self.assertEqual(self.document.annotation(key), value)
        self.assertEqual(len(self.document.annotations), len(old_annotations) + 2)

    def test_selection_automatically_restores_older_merged_bubbles(self):
        annotations = dict(self.document.annotations)
        observed = self.gateway.observe()
        self.assertEqual(observed.selected_names, (self.group.name(),))
        self.assertEqual(observed.bubble_names, (self.group.name(),))
        self.assertEqual(self.document.annotations, annotations)
        with patch.object(self.layer, "addShapesFromSvg") as importer:
            loaded = self.gateway.load_selected()
        importer.assert_not_called()
        self.assertEqual(loaded.settings, self.settings)
        self.assertEqual(self.gateway.load_selected(), loaded)
        self.assertTrue(self.document.annotation(loaded.target.shape_name))

    def test_ambiguous_older_bubble_is_not_automatically_reconnected(self):
        self.gateway.save_settings(self.document, FakeLayer(), self.settings, QTransform())
        annotations = dict(self.document.annotations)
        name = self.group.name()
        with self.assertRaisesRegex(GatewayError, "unique"):
            self.gateway.load_selected()
        self.assertEqual(self.document.annotations, annotations)
        self.assertEqual(self.group.name(), name)

    def test_first_and_subsequent_updates_keep_fitted_placement_and_siblings(self):
        old = detached_group(self.layer.svg, self.group.name())
        expected = (old.placement(self.renderer.render(self.settings).svg)
                    * self.group.transformation()
                    * QTransform.fromScale(300 / 72, 300 / 72))
        loaded = self.gateway.recover_selected()
        for text in (self.settings.text, "Changed lettering"):
            settings = replace(self.settings, text=text)
            target = self.gateway.update(loaded.target, settings, self.renderer.render(settings).svg)
            actual = self.gateway.placement(target)
            for point in (QPointF(), QPointF(100, 50), QPointF(-30, 120)):
                self.assertLess((actual.map(point) - expected.map(point)).manhattanLength(), 1e-6)
            self.assertIn(self.sibling, self.layer.shapes())
            self.assertEqual(len(self.layer.shapes()), 2)
            loaded = self.gateway.load_selected()
            self.assertEqual(loaded.target, target)
            self.assertEqual(loaded.settings, settings)

    def test_placement_maps_regenerated_outline_bounds_through_baked_child_transform(self):
        recovered = detached_group(self.layer.svg, self.group.name())
        generated_svg = self.renderer.render(self.settings).svg
        plain = detached_group(
            self.layer.svg.replace('transform="matrix(0.24 0 0 0.24 -4.8 -4.8)"', ""),
            self.group.name())
        placement = recovered.placement(generated_svg)
        for point in (plain.outline.rect().topLeft(), plain.outline.rect().bottomRight()):
            expected = recovered.outline.matrix().map(point)
            self.assertLess((placement.map(point) - expected).manhattanLength(), 1e-6)

    def test_recovery_supports_every_bubble_style_and_keeps_seeds(self):
        for style in ("Oval", "Rounded", "Square", "Thought", "Shouting"):
            with self.subTest(style=style):
                self.setUp()
                settings = replace(self.settings, style=style)
                self.gateway.save_settings(self.document, self.source, settings, QTransform())
                self.set_svg(settings)
                loaded = self.gateway.recover_selected()
                self.assertEqual(loaded.settings, settings)
                self.gateway.update(loaded.target, settings, self.renderer.render(settings).svg)
                self.assertEqual(self.gateway.load_selected().settings, settings)

    def test_existing_stable_group_id_uses_scoped_record_not_duplicate_default_record(self):
        name = SHAPE_NAME + "-" + "a" * 32
        self.group.setName(name)
        self.set_svg()
        scoped = replace(self.settings, padding=23, autocenter=False)
        self.gateway.save_settings(
            self.document, self.source, scoped, QTransform(), self.group.name())
        loaded = self.gateway.recover_selected()
        self.assertEqual(loaded.settings, scoped)
        self.assertEqual(loaded.target.shape_name, name)

    def test_renamed_group_text_matching_ignores_wrapping_and_whitespace(self):
        self.settings = replace(self.settings, text="Recover\nthis   dialogue")
        self.gateway.save_settings(self.document, self.source, self.settings, QTransform())
        loaded = self.gateway.recover_selected()
        self.assertEqual(loaded.settings, self.settings)

    def assert_refused_without_changes(self, message):
        annotations = dict(self.document.annotations)
        name = self.group.name()
        transform = self.group.transformation()
        shapes = self.layer.shapes()
        with self.assertRaisesRegex(GatewayError, message):
            self.gateway.recover_selected()
        self.assertEqual(self.document.annotations, annotations)
        self.assertEqual(self.group.name(), name)
        self.assertEqual(self.group.transformation(), transform)
        self.assertEqual(self.layer.shapes(), shapes)

    def test_duplicate_text_records_are_refused_instead_of_guessed(self):
        other = FakeLayer()
        self.gateway.save_settings(self.document, other, self.settings, QTransform())
        self.assert_refused_without_changes("unique")

    def test_records_from_existing_layers_are_not_stolen(self):
        self.document.layers[self.source.uniqueId().toString()] = self.source
        self.assert_refused_without_changes("unique")

    def test_missing_or_different_lettering_is_refused(self):
        self.document.annotations.clear()
        self.assert_refused_without_changes("unique")
        self.gateway.save_settings(
            self.document, self.source, replace(self.settings, text="Different"), QTransform())
        self.assert_refused_without_changes("unique")

    def test_locked_multi_selected_unselected_and_nonbubble_groups_are_refused(self):
        self.layer.is_locked = True
        self.assert_refused_without_changes("Unlock")
        self.layer.is_locked = False
        self.sibling.select()
        self.assert_refused_without_changes("exactly one")
        self.sibling.deselect()
        self.group.deselect()
        self.assert_refused_without_changes("exactly one")
        self.group.select()
        self.group.setName("Manual artwork")
        self.assert_refused_without_changes("generated")

    def test_empty_text_and_altered_structure_are_refused(self):
        self.set_svg(replace(self.settings, text=""))
        self.assert_refused_without_changes("lettering")
        self.set_svg()
        root = ET.fromstring(self.layer.svg)
        ET.SubElement(list(root)[0], "rect", width="5", height="5")
        self.layer.svg = ET.tostring(root, encoding="unicode")
        self.assert_refused_without_changes("intact")

    def test_invalid_geometry_is_refused(self):
        self.set_svg(transform="scale(0)")
        self.assert_refused_without_changes("geometry")

    def test_invalid_saved_record_is_reported_without_writing(self):
        key = self.gateway.annotation_key(self.source)
        self.document.annotations[key] = b"not json"
        annotations = dict(self.document.annotations)
        with self.assertRaises(SettingsError):
            self.gateway.recover_selected()
        self.assertEqual(self.document.annotations, annotations)

    def test_already_recovered_bubble_is_not_rebound(self):
        loaded = self.gateway.recover_selected()
        self.assert_refused_without_changes("already editable")
        self.assertEqual(self.gateway.load_selected(), loaded)

    def test_unrelated_annotation_names_are_ignored(self):
        self.document.annotations["rsbg-bubble-{not-a-uuid}"] = b"not json"
        self.document.annotations["unrelated"] = b"not json"
        records = matching_records(self.document, self.group.name(), self.settings.text)
        self.assertEqual(len(records), 1)
