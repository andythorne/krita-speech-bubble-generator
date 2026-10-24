"""Portable settings and independent editing of clipboard copies."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QTransform

from fake_krita import APP, FakeDocument, FakeKrita, FakeShape
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import (
    BubbleSettings, SettingsError, TextStyle,
)
from krita_speech_bubble_generator.editor.contracts import GatewayError
from krita_speech_bubble_generator.editor.presenter import EditorPresenter
from krita_speech_bubble_generator.editor.view import BubbleEditorView
from krita_speech_bubble_generator.krita_host.gateway import KritaGateway
from krita_speech_bubble_generator.krita_host.recovery import (
    SETTINGS_NAME, group_settings,
)


class CopyPasteTests(unittest.TestCase):
    def setUp(self):
        self.document = FakeDocument(None)
        FakeKrita.document = self.document
        self.renderer = BubbleRenderer()
        self.gateway = KritaGateway(FakeKrita, self.renderer)
        self.settings = BubbleSettings(
            text="Copy this bubble", text_styles=(TextStyle(0, 4, bold=True),),
            style="Shouting", shout_seed=173, thought_seed=291,
            tail_advanced=True, tail_start_angle=0.7, tail_end_x=240, tail_end_y=180)

    def tearDown(self):
        FakeKrita.document = None

    def create(self, **changes):
        settings = replace(self.settings, **changes)
        return self.gateway.create(settings, self.renderer.render(settings).svg, True)

    def copy(self, loaded, document, layer=None, rename=False):
        source_layer = loaded.target.document.nodeByUniqueID(loaded.target.layer_id)
        source = self.gateway.shape_by_name(source_layer, loaded.target.shape_name)
        svg = source.toSvg()
        document.setActiveNode(layer or document.createVectorLayer("Pasted"))
        layer = document.activeNode()
        for shape in layer.shapes():
            self.gateway.deselect_shape(shape)
        copied = layer.addShapesFromSvg(svg)[0]
        copied.setTransformation(source.transformation() * QTransform.fromTranslate(80, 40))
        if rename:
            copied.setName(copied.name() + "1")
        copied.select()
        FakeKrita.document = document
        inverse, _ = QTransform(*loaded.target.baseline).inverted()
        expected = (
            QTransform.fromScale(72 / loaded.target.document.xRes(),
                                 72 / loaded.target.document.xRes())
            * inverse * copied.transformation()
            * QTransform.fromScale(document.xRes() / 72, document.yRes() / 72))
        return layer, copied, expected

    def assert_placement(self, target, expected):
        actual = self.gateway.placement(target)
        for point in (QPointF(), QPointF(100, 50), QPointF(-30, 120)):
            self.assertLess((actual.map(point) - expected.map(point)).manhattanLength(), 1e-6)

    def test_cross_document_copy_restores_all_settings_without_source_annotations(self):
        for text in ("Copy this bubble", "", "Same dialogue", "Accents \u00e9 & < >"):
            with self.subTest(text=text):
                FakeKrita.document = self.document
                original = self.create(text=text, text_styles=())
                destination = FakeDocument(None)
                layer, copied, expected = self.copy(original, destination)
                original_shapes = layer.shapes()
                matrix = copied.transformation()
                observations = self.gateway.observe()
                self.assertEqual(observations.bubble_names, (copied.name(),))
                self.assertEqual(destination.annotations, {})
                with patch.object(layer, "addShapesFromSvg") as importer:
                    loaded = self.gateway.load_selected()
                importer.assert_not_called()
                self.assertEqual(loaded.settings, original.settings)
                self.assertEqual(copied.transformation(), matrix)
                self.assertEqual(layer.shapes(), original_shapes)
                self.assert_placement(loaded.target, expected)
                for dialogue in (text, "Edited after paste"):
                    settings = replace(loaded.settings, text=dialogue, text_styles=())
                    target = self.gateway.update(
                        loaded.target, settings, self.renderer.render(settings).svg)
                    self.assert_placement(target, expected)
                    loaded = self.gateway.load_selected()
                    self.assertEqual(loaded.settings, settings)
                    self.assertEqual(group_settings(layer.items[0]), settings)

    def test_copy_retains_rich_text_seeds_and_tail_settings(self):
        original = self.create()
        destination = FakeDocument(None)
        _, copied, _ = self.copy(original, destination)
        copied.children()[0].setName(copied.children()[0].name() + "1")
        loaded = self.gateway.recover_selected()
        self.assertEqual(loaded.settings, self.settings)
        self.assertEqual(group_settings(copied), self.settings)

    def test_shared_layer_copy_gets_independent_id_and_preserves_siblings(self):
        original = self.create()
        layer = self.document.activeNode()
        source = layer.items[0]
        sibling = FakeShape(layer, QTransform.fromTranslate(900, 700))
        sibling.setName("Unrelated artwork")
        layer.items.append(sibling)
        source_matrix = source.transformation()
        source_record = bytes(self.document.annotation(original.target.shape_name))
        _, copied, expected = self.copy(original, self.document, layer)
        copied.setZIndex(13)
        loaded = self.gateway.load_selected(original.target.shape_name)
        self.assertNotEqual(loaded.target.shape_name, original.target.shape_name)
        self.assertEqual(loaded.settings, self.settings)
        self.assertEqual(copied.zIndex(), 13)
        self.assert_placement(loaded.target, expected)
        settings = replace(loaded.settings, text="Only the pasted bubble", text_styles=())
        target = self.gateway.update(
            loaded.target, settings, self.renderer.render(settings).svg)
        self.assert_placement(target, expected)
        self.assertEqual(layer.items[:2], [source, sibling])
        self.assertEqual(source.transformation(), source_matrix)
        self.assertEqual(bytes(self.document.annotation(original.target.shape_name)), source_record)
        self.assertEqual(group_settings(source), self.settings)
        self.assertEqual(layer.items[-1].zIndex(), 13)

    def test_copy_to_another_layer_does_not_share_document_identity(self):
        original = self.create()
        _, copied, expected = self.copy(original, self.document)
        loaded = self.gateway.load_selected()
        self.assertNotEqual(loaded.target.shape_name, original.target.shape_name)
        self.assertEqual(loaded.settings, original.settings)
        self.assert_placement(loaded.target, expected)
        self.assertEqual(group_settings(copied), original.settings)

    def test_native_renamed_copy_is_detected_without_document_records(self):
        original = self.create()
        destination = FakeDocument(None)
        _, copied, expected = self.copy(original, destination, rename=True)
        old_name = copied.name()
        loaded = self.gateway.load_selected()
        self.assertNotEqual(loaded.target.shape_name, old_name)
        self.assertRegex(loaded.target.shape_name, r"^rsbg-bubble-[0-9a-f]{32}$")
        self.assertEqual(loaded.settings, self.settings)
        self.assert_placement(loaded.target, expected)

    def test_native_shape_fragment_can_use_layer_namespace_prefixes(self):
        original = self.create()
        destination = FakeDocument(None)
        _, copied, expected = self.copy(original, destination)
        fragment = copied.toSvg().replace(
            "<g ", '<g sodipodi:nodetypes="cc" krita:test="value" ', 1)
        with patch.object(copied, "toSvg", return_value=fragment):
            loaded = self.gateway.load_selected()
        self.assertEqual(loaded.settings, original.settings)
        self.assert_placement(loaded.target, expected)

    def test_several_copies_with_identical_or_empty_text_recover_one_at_a_time(self):
        for text in ("Same dialogue", ""):
            with self.subTest(text=text):
                FakeKrita.document = self.document
                first = self.create(text=text, text_styles=(), padding=30)
                second = self.create(text=text, text_styles=(), padding=80)
                destination = FakeDocument(None)
                layer, first_copy, _ = self.copy(first, destination)
                _, second_copy, _ = self.copy(second, destination, layer)
                sibling = FakeShape(layer, QTransform())
                sibling.setName("Artwork")
                layer.items.append(sibling)
                for copied, original in ((first_copy, first), (second_copy, second)):
                    for shape in layer.shapes():
                        self.gateway.deselect_shape(shape)
                    copied.children()[0].select()
                    before = layer.shapes()
                    loaded = self.gateway.recover_selected()
                    self.assertEqual(loaded.settings, original.settings)
                    self.assertEqual(layer.shapes(), before)
                    self.assertEqual(self.gateway.load_selected(), loaded)

    def test_copy_survives_source_closing_and_destination_reopening(self):
        original = self.create()
        destination = FakeDocument(None)
        layer, _, expected = self.copy(original, destination)
        reopened = FakeDocument(layer)
        FakeKrita.document = reopened
        self.gateway = KritaGateway(FakeKrita, self.renderer)
        loaded = self.gateway.load_selected()
        self.assertEqual(loaded.settings, original.settings)
        self.assert_placement(loaded.target, expected)
        reopened_again = FakeDocument(layer)
        reopened_again.annotations = dict(reopened.annotations)
        FakeKrita.document = reopened_again
        self.assertEqual(self.gateway.load_selected().settings, original.settings)

    def test_repast_in_a_layer_with_stale_annotations_uses_the_copied_groups_settings(self):
        original = self.create()
        destination = FakeDocument(None)
        layer, copied, _ = self.copy(original, destination)
        loaded = self.gateway.load_selected()
        edited = replace(loaded.settings, text="Destination edit", text_styles=(), padding=80)
        self.gateway.update(loaded.target, edited, self.renderer.render(edited).svg)
        layer.items[0].remove()
        _, copied, expected = self.copy(original, destination, layer)
        restored = self.gateway.load_selected()
        self.assertEqual(restored.settings, original.settings)
        self.assert_placement(restored.target, expected)

    def test_paste_into_different_resolution_keeps_native_point_placement(self):
        original = self.create()
        destination = FakeDocument(None)
        with patch.object(destination, "xRes", return_value=144), \
                patch.object(destination, "yRes", return_value=144):
            _, _, expected = self.copy(original, destination)
            loaded = self.gateway.load_selected()
            self.assert_placement(loaded.target, expected)
            target = self.gateway.update(
                loaded.target, loaded.settings, self.renderer.render(loaded.settings).svg)
            self.assert_placement(target, expected)

    def test_loading_older_group_adds_portable_settings_without_redrawing(self):
        original = self.create()
        layer = self.document.activeNode()
        group = layer.items[0]
        for child in group.children():
            child.setName("old-shape")
        with patch.object(layer, "addShapesFromSvg") as importer:
            self.assertEqual(self.gateway.load_selected(), original)
        importer.assert_not_called()
        self.assertEqual(group_settings(group), original.settings)
        destination = FakeDocument(None)
        self.copy(original, destination)
        self.assertEqual(self.gateway.load_selected().settings, original.settings)

    def test_missing_invalid_and_ambiguous_metadata_never_changes_artwork(self):
        for mode in ("missing", "invalid", "multiple", "locked"):
            with self.subTest(mode=mode):
                FakeKrita.document = self.document
                original = self.create()
                destination = FakeDocument(None)
                layer, group, _ = self.copy(original, destination)
                if mode == "missing":
                    group.children()[0].setName("outline")
                elif mode == "invalid":
                    group.children()[0].setName(SETTINGS_NAME + "00-end")
                elif mode == "multiple":
                    group.children()[1].setName(group.children()[0].name())
                else:
                    layer.is_locked = True
                shapes, matrix, name = layer.shapes(), group.transformation(), group.name()
                with self.assertRaises((GatewayError, SettingsError)):
                    self.gateway.load_selected()
                self.assertEqual(destination.annotations, {})
                self.assertEqual(layer.shapes(), shapes)
                self.assertEqual(group.transformation(), matrix)
                self.assertEqual(group.name(), name)

    def test_presenter_detects_same_name_paste_while_editing_original(self):
        original = self.create()
        layer = self.document.activeNode()
        view = BubbleEditorView()
        presenter = EditorPresenter(view, self.gateway, self.renderer, lambda low, high: low)
        presenter.state.background_enabled = False
        try:
            with patch.object(view, "warn") as warning:
                presenter.sync_selection()
                _, copied, _ = self.copy(original, self.document, layer)
                presenter.sync_selection()
                self.assertEqual(presenter.state.target.shape_name, copied.name())
                self.assertNotEqual(presenter.state.target.shape_name, original.target.shape_name)
                self.assertEqual(presenter.state.applied.text, original.settings.text)
                warning.assert_not_called()
        finally:
            presenter.live_timer.stop()
            presenter.selection_timer.stop()
            presenter.background_timer.stop()
            view.deleteLater()
            presenter.deleteLater()
            APP.processEvents()
