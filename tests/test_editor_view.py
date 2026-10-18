"""Real Qt form binding without native document or presenter internals."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QTextCursor
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QLabel

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
        self.assertEqual(layout.indexOf(self.view.optionsTabs), layout.indexOf(self.view.preview) + 2)
        self.assertEqual(layout.indexOf(self.view.optionsTabs), layout.count() - 1)
        self.assertEqual(self.view.preview.height(), 220)
        self.assertEqual(self.view.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOn)

    def test_options_are_grouped_into_text_bubble_tail_and_import_tabs(self):
        self.assertEqual(
            [self.view.optionsTabs.tabText(index)
             for index in range(self.view.optionsTabs.count())],
            ["Text", "Bubble", "Tail", "Import"])
        self.assertIs(self.view.optionsTabs.currentWidget(), self.view.textTab)
        for page, controls in (
            (self.view.textTab, (
                self.view.speechFont, self.view.speechFontSize,
                self.view.currentFontColorButton, self.view.bubbleText,
                self.view.textResizeHandle, self.view.autocenter,
                self.view.opticalCenter,
                self.view.averageLineLength)),
            (self.view.bubbleTab, (
                self.view.bubbleType, self.view.bubbleColorButton,
                self.view.outlineSlider, self.view.outlineSpinBox,
                self.view.outlineColorButton, self.view.paddingSlider,
                self.view.paddingSpinBox, self.view.shoutingGroup,
                self.view.thoughtGroup, self.view.ovalGroup,
                self.view.ovalVerticalPaddingSlider, self.view.ovalVerticalPaddingSpinBox,
                self.view.ovalSquarenessSlider, self.view.ovalSquarenessSpinBox)),
            (self.view.tailTab, (
                self.view.tailCompass, self.view.lockTailLength,
                self.view.tailSlider, self.view.tailSpinBox, self.view.thoughtSizeGroup,
                self.view.tailCurveSlider, self.view.tailCurveSpinBox,
                self.view.tailCurveDirection)),
            (self.view.importTab, (
                self.view.importInstructions, self.view.importLimitations,
                self.view.importOldBubble, self.view.recoverBubble,
                self.view.recoveryInstructions)),
        ):
            for control in controls:
                with self.subTest(page=page, control=control):
                    self.assertTrue(page.isAncestorOf(control))
            for shared in (self.view.preview, self.view.addOnPage,
                           self.view.addDestination, self.view.canvasBackground,
                           self.view.refreshBackground):
                self.assertFalse(page.isAncestorOf(shared))

    def test_switching_tabs_preserves_settings_text_selection_and_shared_preview(self):
        self.view.show()
        settings = replace(
            self.view.initial_settings(), text="Keep this dialogue", style="Thought",
            tail_length=65, padding=175, thought_nodes=29, shout_nodes=37,
            shout_seed=1729, thought_seed=2718)
        self.view.load_settings(settings)
        self.view.show_render(BubbleRenderer().render(settings, preview=True))
        self.view.bubbleText.setFixedHeight(180)
        cursor = self.view.bubbleText.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(9, QTextCursor.KeepAnchor)
        self.view.bubbleText.setTextCursor(cursor)
        preview_box = QRectF(self.view.preview.view_box)
        edits = QSignalSpy(self.view.edited)
        for page in (self.view.bubbleTab, self.view.tailTab,
                     self.view.importTab, self.view.textTab):
            self.view.optionsTabs.setCurrentWidget(page)
            APP.processEvents()
            self.assertEqual(self.view.initial_settings(), settings)
            self.assertEqual(len(edits), 0)
            self.assertTrue(self.view.preview.isVisible())
            self.assertTrue(self.view.addOnPage.isVisible())
            self.assertEqual(self.view.preview.height(), 220)
            self.assertEqual(self.view.preview.view_box, preview_box)
            self.assertEqual(self.view.bubbleText.height(), 180)
            current = self.view.bubbleText.textCursor()
            self.assertEqual((current.position(), current.anchor()),
                             (cursor.position(), cursor.anchor()))

    def test_recovery_action_emits_only_a_recovery_request(self):
        requests = QSignalSpy(self.view.recovery_requested)
        imports = QSignalSpy(self.view.import_requested)
        edits = QSignalSpy(self.view.edited)
        self.view.recoverBubble.click()
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(imports), 0)
        self.assertEqual(len(edits), 0)
        self.assertIn("removed layers", self.view.recoveryInstructions.text())
        self.assertIn("Ambiguous", self.view.recoveryInstructions.text())

    def test_numeric_controls_share_settings_ranges_and_fresh_defaults(self):
        defaults = BubbleSettings()
        for field, control in self.view._numbers.items():
            with self.subTest(field=field):
                bounds = ((0, defaults.font_size * 10) if field == "tail_length"
                          else INTEGER_RANGES[field])
                self.assertEqual((control.minimum(), control.maximum()), bounds)
                self.assertEqual(control.value(), getattr(defaults, field))

    def test_initial_style_is_oval(self):
        self.assertEqual(self.view.bubbleType.currentText(), "Oval")
        self.assertEqual(self.view.initial_settings().style, "Oval")

    def test_batch_load_suppresses_all_semantic_edits_and_establishes_ranges_first(self):
        edits = QSignalSpy(self.view.edited)
        original = self.view.initial_settings()
        loaded = replace(
            original, style="Thought", text="Stored text", font_size=70,
            tail_length=650, padding=235, lock_tail=False, autocenter=False,
            line_length=24, shout_shape="Expressive", shout_nodes=37, thought_nodes=29,
            shout_irregularity=85, thought_irregularity=75, shout_seed=1729, thought_seed=2718,
            tail_angle=-2.1, thought_size=275, fill="#123456", stroke="#654321",
            text_color="#112233", tail_curve=73, tail_curve_direction="Down",
            oval_custom=True, oval_vertical_padding=25, oval_squareness=80,
            optical_center=True)
        result = self.view.load_settings(loaded)
        self.assertEqual(result, loaded)
        self.assertEqual(len(edits), 0)
        self.assertEqual(self.view.tailSlider.maximum(), 700)
        self.assertEqual(self.view.tailSpinBox.value(), 650)
        self.assertFalse(self.view.tailLengthControls.isHidden())
        self.assertFalse(self.view.tailLengthControls.isEnabled())
        self.assertFalse(self.view.thoughtGroup.isHidden())
        self.assertFalse(self.view.averageLineLength.isHidden())
        self.assertTrue(self.view.shoutingGroup.isHidden())
        self.assertEqual(self.view.shoutingSlider.value(), 85)
        self.assertEqual(self.view.thoughtNodesSlider.value(), 29)
        self.assertEqual(self.view.tailCurveSlider.value(), 73)
        self.assertEqual(self.view.tailCurveDirection.currentText(), "Down")

    def test_optical_centering_emits_only_its_setting_and_loads_without_edits(self):
        initial = self.view.initial_settings()
        self.assertFalse(self.view.opticalCenter.isChecked())
        edits = QSignalSpy(self.view.edited)
        self.view.opticalCenter.setChecked(True)
        enabled = replace(initial, optical_center=True)
        self.assertEqual(list(edits), [[enabled, ("optical_center",)]])
        self.view.reflect_settings(initial)
        self.assertFalse(self.view.opticalCenter.isChecked())
        self.assertEqual(len(edits), 1)
        self.view.load_settings(enabled)
        self.assertTrue(self.view.opticalCenter.isChecked())
        self.assertEqual(self.view.initial_settings(), enabled)
        self.assertEqual(len(edits), 1)

    def test_oval_controls_are_opt_in_and_emit_only_the_changed_setting(self):
        initial = self.view.initial_settings()
        self.assertFalse(self.view.ovalGroup.isHidden())
        self.assertFalse(self.view.ovalGroup.isChecked())
        self.assertFalse(self.view.ovalVerticalPaddingSpinBox.isEnabled())
        self.assertFalse(self.view.ovalSquarenessSpinBox.isEnabled())
        edits = QSignalSpy(self.view.edited)
        self.view.ovalGroup.setChecked(True)
        enabled = replace(initial, oval_custom=True)
        self.assertEqual(list(edits), [[enabled, ("oval_custom",)]])
        self.assertTrue(self.view.ovalVerticalPaddingSpinBox.isEnabled())
        self.assertEqual(self.view.paddingGroup.title(), "Horizontal padding")
        self.view.ovalVerticalPaddingSlider.setValue(20)
        padded = replace(enabled, oval_vertical_padding=20)
        self.assertEqual(edits[1], [padded, ("oval_vertical_padding",)])
        self.assertEqual(self.view.ovalVerticalPaddingSpinBox.value(), 20)
        self.view.ovalSquarenessSpinBox.setValue(65)
        squared = replace(padded, oval_squareness=65)
        self.assertEqual(edits[2], [squared, ("oval_squareness",)])
        self.assertEqual(self.view.ovalSquarenessSlider.value(), 65)
        self.view.ovalGroup.setChecked(False)
        self.assertEqual(edits[3], [replace(squared, oval_custom=False), ("oval_custom",)])
        self.assertEqual(self.view.paddingGroup.title(), "Padding")
        self.assertFalse(self.view.ovalSquarenessSpinBox.isEnabled())

    def test_oval_options_survive_style_switches_and_programmatic_reflection(self):
        initial = replace(self.view.initial_settings(), oval_custom=True,
                          oval_vertical_padding=25, oval_squareness=80)
        self.view.load_settings(initial)
        for style in BUBBLE_TYPES:
            self.view.bubbleType.setCurrentText(style)
            self.assertEqual(self.view.ovalGroup.isHidden(),
                             not BUBBLE_TYPES[style].capabilities.oval)
            self.assertEqual(self.view.initial_settings(), replace(initial, style=style))
            self.assertEqual(self.view.paddingGroup.title(),
                             "Horizontal padding" if style == "Oval" else "Padding")
        edits = QSignalSpy(self.view.edited)
        reflected = replace(initial, oval_vertical_padding=0, oval_squareness=50)
        self.view.reflect_settings(reflected)
        self.assertEqual(self.view.initial_settings(), reflected)
        self.assertEqual(len(edits), 0)
        self.assertFalse(self.view.ovalGroup.isHidden())
        self.assertEqual(self.view.paddingGroup.title(), "Horizontal padding")

    def test_tail_curve_controls_emit_snapshots_without_changing_length_or_seeds(self):
        initial = replace(
            self.view.initial_settings(), tail_length=65, lock_tail=False,
            shout_seed=17, thought_seed=29)
        self.view.load_settings(initial)
        edits = QSignalSpy(self.view.edited)
        self.view.tailCurveSlider.setValue(70)
        curved = replace(initial, tail_curve=70)
        self.assertEqual(self.view.tailCurveSpinBox.value(), 70)
        self.assertEqual(list(edits), [[curved, ("tail_curve",)]])
        self.view.tailCurveDirection.setCurrentText("Down")
        down = replace(curved, tail_curve_direction="Down")
        self.assertEqual(edits[1], [down, ("tail_curve_direction",)])
        self.view.tailCurveSpinBox.setValue(25)
        self.assertEqual(self.view.tailCurveSlider.value(), 25)
        self.assertEqual(edits[2], [replace(down, tail_curve=25), ("tail_curve",)])
        reflected = replace(down, tail_curve=45, tail_curve_direction="Up")
        self.view.reflect_settings(reflected)
        self.assertEqual(self.view.initial_settings(), reflected)
        self.assertEqual(len(edits), 3)

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

    def test_compass_directions_emit_only_angle_and_preserve_all_other_settings(self):
        directions = {
            "N": -math.pi / 2, "NE": -math.pi / 4, "E": 0,
            "SE": math.pi / 4, "S": math.pi / 2, "SW": 3 * math.pi / 4,
            "W": math.pi, "NW": -3 * math.pi / 4,
        }
        for style in BUBBLE_TYPES:
            for length, locked in ((0, True), (0, False), (65, True), (65, False)):
                for direction, angle in directions.items():
                    with self.subTest(style=style, length=length, locked=locked,
                                      direction=direction):
                        initial = replace(
                            self.view.initial_settings(), style=style, text="Keep my text",
                            tail_length=length, lock_tail=locked, tail_angle=0.123,
                            shout_seed=1729, thought_seed=2718, padding=175,
                            autocenter=False, line_length=20)
                        self.view.load_settings(initial)
                        edits = QSignalSpy(self.view.edited)
                        self.view.tailCompass.buttons[direction].click()
                        expected = replace(initial, tail_angle=angle)
                        self.assertEqual(list(edits), [[expected, ("tail_angle",)]])
                        self.assertEqual(self.view.initial_settings(), expected)
                        self.assertEqual(
                            [name for name, button in self.view.tailCompass.buttons.items()
                             if button.isChecked()], [direction])

    def test_tail_position_and_length_controls_are_in_top_aligned_columns(self):
        self.view.resize(480, 900)
        self.view.optionsTabs.setCurrentWidget(self.view.tailTab)
        self.view.show()
        for style in ("Oval", "Thought"):
            for locked in (True, False):
                with self.subTest(style=style, locked=locked):
                    self.view.load_settings(replace(
                        self.view.initial_settings(), style=style, lock_tail=locked))
                    APP.processEvents()
                    content = self.view.widget()
                    compass = self.view.tailCompass
                    lock = self.view.lockTailLength
                    compass_right = compass.mapTo(content, compass.rect().topRight()).x()
                    lock_position = lock.mapTo(content, lock.rect().topLeft())
                    self.assertLess(compass_right, lock_position.x())
                    position_label = next(
                        label for label in compass.parentWidget().findChildren(QLabel)
                        if label.text() == "Position")
                    self.assertEqual(
                        position_label.mapTo(content, position_label.rect().topLeft()).y(),
                        lock_position.y())
                    self.assertFalse(self.view.tailLengthControls.isHidden())
                    self.assertFalse(self.view.tailSpinBox.isHidden())
                    self.assertEqual(self.view.tailSlider.isEnabled(), locked)
                    self.assertEqual(self.view.tailSpinBox.isEnabled(), locked)
                    length = self.view.tailLengthControls
                    length_position = length.mapTo(content, length.rect().topLeft())
                    self.assertEqual(length_position.x(), lock_position.x())
                    self.assertGreater(length_position.y(), lock_position.y())
                    row = length.layout().itemAt(1).layout()
                    self.assertEqual(row.indexOf(self.view.tailSlider), 0)
                    self.assertEqual(row.indexOf(self.view.tailSpinBox), 1)

    def test_tail_length_inputs_stay_synchronized_and_show_dragged_length_when_disabled(self):
        edits = QSignalSpy(self.view.edited)
        self.view.tailSpinBox.setValue(47)
        self.assertEqual(self.view.tailSlider.value(), 47)
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0][1], ("tail_length",))
        self.view.tailSlider.setValue(20)
        self.assertEqual(self.view.tailSpinBox.value(), 20)
        self.assertEqual(len(edits), 2)
        self.view.lockTailLength.setChecked(False)
        count = len(edits)
        settings = replace(self.view.initial_settings(), tail_length=65)
        self.view.reflect_settings(settings)
        self.assertEqual(len(edits), count)
        self.assertEqual(self.view.tailSpinBox.value(), 65)
        self.assertEqual(self.view.tailSlider.value(), 65)
        self.assertFalse(self.view.tailSpinBox.isEnabled())
        self.assertFalse(self.view.tailSlider.isEnabled())
        self.view.lockTailLength.setChecked(True)
        self.assertTrue(self.view.tailSpinBox.isEnabled())
        self.assertTrue(self.view.tailSlider.isEnabled())
        self.assertEqual(self.view.tailSpinBox.value(), 65)

    def test_compass_load_and_drag_reflection_are_silent_and_do_not_snap(self):
        edits = QSignalSpy(self.view.edited)
        selected = lambda: [
            name for name, button in self.view.tailCompass.buttons.items()
            if button.isChecked()]
        self.assertEqual(selected(), ["SE"])
        initial = self.view.initial_settings()
        for bind in (self.view.load_settings, self.view.reflect_settings):
            for angle, direction in (
                (-math.pi, "W"), (2 * math.pi, "E"), (-math.pi / 2, "N"),
                (0.123, None), (math.pi / 4 + 1e-5, None),
            ):
                with self.subTest(binding=bind.__name__, angle=angle):
                    settings = replace(initial, tail_angle=angle)
                    self.assertEqual(bind(settings), settings)
                    self.assertEqual(selected(), [] if direction is None else [direction])
                    self.assertEqual(self.view.initial_settings().tail_angle, angle)
        self.assertEqual(len(edits), 0)

    def test_compass_selected_direction_stays_checked_when_clicked_again(self):
        edits = QSignalSpy(self.view.edited)
        self.view.tailCompass.buttons["SE"].click()
        self.assertTrue(self.view.tailCompass.buttons["SE"].isChecked())
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0][1], ("tail_angle",))

    def test_compass_has_eight_accessible_arrows_around_noninteractive_center(self):
        compass = self.view.tailCompass
        layout = compass.layout()
        expected = (("NW", "N", "NE"), ("W", None, "E"), ("SW", "S", "SE"))
        self.assertEqual(layout.count(), 9)
        for row, directions in enumerate(expected):
            for column, direction in enumerate(directions):
                widget = layout.itemAtPosition(row, column).widget()
                if direction is None:
                    self.assertNotIn(widget, compass.buttons.values())
                    self.assertEqual(widget.focusPolicy(), Qt.NoFocus)
                else:
                    self.assertIs(widget, compass.buttons[direction])
                    self.assertTrue(widget.accessibleName())
                    self.assertTrue(widget.toolTip())
                    self.assertTrue(widget.isCheckable())
                    self.assertEqual(widget.text(), "")
        self.view.show()
        APP.processEvents()

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
        imports = QSignalSpy(self.view.import_requested)
        self.view.addDestination.setCurrentIndex(1)
        self.view.addOnPage.click()
        self.view.newBubbleButton.click()
        self.view.importOldBubble.click()
        self.view.preview.tailMoved.emit(QPointF(42, 19))
        self.assertEqual(list(pages), [[False]])
        self.assertEqual(len(new), 1)
        self.assertEqual(len(imports), 1)
        self.assertEqual(tails[0][0], QPointF(42, 19))

    def test_import_action_is_available_only_outside_saved_bubble_editing(self):
        self.view.optionsTabs.setCurrentWidget(self.view.importTab)
        self.view.show()
        APP.processEvents()
        layout = self.view.importTab.layout()
        self.assertEqual(layout.indexOf(self.view.importOldBubble), layout.count() - 1)
        self.assertTrue(self.view.importOldBubble.isVisible())
        for label in (self.view.importInstructions, self.view.importLimitations):
            self.assertTrue(label.isVisible())
            self.assertTrue(label.wordWrap())
        self.assertIn("original Rogudator plugin", self.view.importInstructions.text())
        for limitation in ("ungrouped", "no other artwork", "first edit redraws",
                           "per-word formatting", "Save a copy", ".kra"):
            self.assertIn(limitation, self.view.importLimitations.text())
        self.view.show_mode(True, "Editing")
        self.assertTrue(self.view.importOldBubble.isHidden())
        self.assertTrue(self.view.importInstructions.isVisible())
        self.assertIn("New bubble", self.view.importInstructions.text())
        self.view.show_mode(False, "New bubble")
        self.assertTrue(self.view.importOldBubble.isVisible())

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
