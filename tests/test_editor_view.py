"""Real Qt form binding without native document or presenter internals."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QTextCursor
from PyQt5.QtTest import QSignalSpy, QTest

from fake_krita import APP
from krita_speech_bubble_generator.bubbles.registry import BUBBLE_TYPES, SHOUTING_ALGORITHMS
from krita_speech_bubble_generator.bubbles.renderer import BubbleRenderer
from krita_speech_bubble_generator.bubbles.settings import INTEGER_RANGES, BubbleSettings
from krita_speech_bubble_generator.editor.view import BubbleEditorView


class EditorViewTests(unittest.TestCase):
    def setUp(self):
        self.view = BubbleEditorView()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

    def test_options_and_control_order_come_from_ordered_registries(self):
        self.assertEqual(
            [self.view.bubbleType.itemText(i) for i in range(self.view.bubbleType.count())],
            list(BUBBLE_TYPES))
        self.assertEqual(
            [self.view.shoutingShape.itemText(i) for i in range(self.view.shoutingShape.count())],
            list(SHOUTING_ALGORITHMS))
        layout = self.view.widget().layout()
        self.assertEqual(layout.indexOf(self.view.speechGroup), layout.indexOf(self.view.preview) + 1)
        self.assertEqual(self.view.preview.height(), 220)
        self.assertEqual(self.view.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOn)

    def test_numeric_controls_share_settings_ranges_and_fresh_defaults(self):
        defaults = BubbleSettings()
        for field, control in self.view._numbers.items():
            with self.subTest(field=field):
                bounds = ((0, defaults.font_size * 10) if field == "tail_length"
                          else INTEGER_RANGES[field])
                self.assertEqual((control.minimum(), control.maximum()), bounds)
                self.assertEqual(control.value(), getattr(defaults, field))

    def test_batch_load_suppresses_all_semantic_edits_and_establishes_ranges_first(self):
        edits = QSignalSpy(self.view.edited)
        original = self.view.initial_settings()
        loaded = replace(
            original, style="Thought", text="Stored text", font_size=70,
            tail_length=650, padding=235, lock_tail=False, autocenter=False,
            line_length=24, shout_shape="Expressive", shout_nodes=37, thought_nodes=29,
            shout_irregularity=85, thought_irregularity=75, shout_seed=1729, thought_seed=2718,
            tail_angle=-2.1, thought_size=275, fill="#123456", stroke="#654321",
            text_color="#112233")
        result = self.view.load_settings(loaded)
        self.assertEqual(result, loaded)
        self.assertEqual(len(edits), 0)
        self.assertEqual(self.view.tailSlider.maximum(), 700)
        self.assertEqual(self.view.tailSpinBox.value(), 650)
        self.assertTrue(self.view.tailLengthControls.isHidden())
        self.assertFalse(self.view.thoughtGroup.isHidden())
        self.assertFalse(self.view.averageLineLength.isHidden())
        self.assertTrue(self.view.shoutingGroup.isHidden())
        self.assertEqual(self.view.shoutingSlider.value(), 85)
        self.assertEqual(self.view.thoughtNodesSlider.value(), 29)

    def test_user_edit_emits_one_snapshot_and_intent_but_never_generates_seeds(self):
        initial = replace(self.view.initial_settings(), shout_seed=17, thought_seed=29)
        self.view.load_settings(initial)
        edits = QSignalSpy(self.view.edited)
        self.view.shoutingSlider.setValue(80)
        self.assertEqual(len(edits), 1)
        settings, fields = edits[0]
        self.assertEqual(fields, ("shout_irregularity",))
        self.assertEqual(settings.shout_irregularity, 80)
        self.assertEqual((settings.shout_seed, settings.thought_seed), (17, 29))

    def test_font_size_change_clamps_tail_and_emits_only_the_final_consistent_snapshot(self):
        self.view.load_settings(replace(self.view.initial_settings(), font_size=70, tail_length=650))
        edits = QSignalSpy(self.view.edited)
        self.view.speechFontSize.setValue(10)
        self.assertEqual(len(edits), 1)
        settings, fields = edits[0]
        self.assertEqual((settings.font_size, settings.tail_length), (10, 100))
        self.assertEqual(fields, ("font_size", "tail_length"))

    def test_presenter_reflection_does_not_reset_cursor_selection_focus_or_height(self):
        self.view.show()
        self.view.bubbleText.setPlainText("Keep this selected text")
        self.view.bubbleText.setFixedHeight(240)
        self.view.bubbleText.setFocus()
        cursor = self.view.bubbleText.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(9, QTextCursor.KeepAnchor)
        self.view.bubbleText.setTextCursor(cursor)
        APP.processEvents()
        self.view.reflect_settings(replace(self.view.initial_settings(), shout_seed=99))
        current = self.view.bubbleText.textCursor()
        self.assertEqual((current.position(), current.anchor()), (cursor.position(), cursor.anchor()))
        self.assertTrue(self.view.bubbleText.hasFocus())
        self.assertEqual(self.view.bubbleText.height(), 240)
        self.view.edited.connect(lambda settings, fields: self.view.reflect_settings(settings))
        QTest.keyClicks(self.view.bubbleText, "one")
        self.assertEqual(self.view.bubbleText.toPlainText(), "Keep one selected text")
        self.assertEqual(self.view.bubbleText.textCursor().position(), 8)

    def test_background_status_does_not_emit_a_recursive_toggle(self):
        toggles = QSignalSpy(self.view.background_toggled)
        self.view.show_background(False, True)
        self.assertEqual(len(toggles), 0)
        self.assertFalse(self.view.canvasBackground.isChecked())
        self.assertTrue(self.view.canvasBackground.isEnabled())
        self.assertFalse(self.view.refreshBackground.isEnabled())
        self.view.show_background(True, False)
        self.assertEqual(len(toggles), 0)
        self.assertFalse(self.view.canvasBackground.isEnabled())
        self.assertFalse(self.view.refreshBackground.isEnabled())

    def test_semantic_page_new_and_tail_signals_do_not_expose_widgets(self):
        pages = QSignalSpy(self.view.page_requested)
        new = QSignalSpy(self.view.new_requested)
        tails = QSignalSpy(self.view.tail_moved)
        self.view.addDestination.setCurrentIndex(1)
        self.view.addOnPage.click()
        self.view.newBubbleButton.click()
        self.view.preview.tailMoved.emit(QPointF(42, 19))
        self.assertEqual(list(pages), [[False]])
        self.assertEqual(len(new), 1)
        self.assertEqual(tails[0][0], QPointF(42, 19))

    def test_rendering_preserves_active_drag_frame(self):
        settings = replace(self.view.initial_settings(), tail_length=40)
        renderer = BubbleRenderer()
        self.view.show_render(renderer.render(settings, preview=True))
        preview = self.view.preview
        preview.dragging = True
        preview.drag_view_box = QRectF(preview.view_box)
        before = QRectF(preview.view_box)
        self.view.load_settings(replace(settings, tail_angle=-2))
        self.view.show_render(renderer.render(self.view.initial_settings(), preview=True))
        self.assertTrue(self.view.is_dragging())
        self.assertEqual(preview.view_box, before)
        self.assertTrue(preview.renderer().isValid())

    def test_color_dialog_cancel_is_silent_and_accepted_color_emits_an_edit(self):
        edits = QSignalSpy(self.view.edited)
        with patch("krita_speech_bubble_generator.editor.view.QColorDialog.getColor",
                   return_value=QColor()):
            self.view.bubbleColorButton.click()
        self.assertEqual(len(edits), 0)
        with patch("krita_speech_bubble_generator.editor.view.QColorDialog.getColor",
                   return_value=QColor("#123456")):
            self.view.bubbleColorButton.click()
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0][0].fill, "#123456")
        self.assertEqual(edits[0][1], ("fill",))
