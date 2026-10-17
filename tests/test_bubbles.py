"""Editor workflows spanning the real Qt view and substitute native host."""

import json
import math
import os
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QByteArray, QPoint, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFontDatabase, QImage, QTransform, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QCheckBox, QPushButton

from fake_krita import APP, FakeDocument, FakeKrita, FakeLayer, FakeShape

from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, outline_anchor, tail_tip,
)
from krita_speech_bubble_generator.bubbles.registry import BUBBLE_TYPES, SHOUTING_ALGORITHMS
from krita_speech_bubble_generator.krita_speech_bubble_generator import (
    SpeechBubbleDocker,
)
from krita_speech_bubble_generator.bubbles.settings import SHAPE_NAME
from editor_harness import EditorHarness
from krita_speech_bubble_generator.krita_host.canvas_context import canvas_transform


STYLES = tuple(BUBBLE_TYPES)
SHOUTING_SHAPES = tuple(SHOUTING_ALGORITHMS)


class EditorTests(unittest.TestCase):
    def setUp(self):
        image = QImage(32, 24, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        self.snapshotPatch = patch(
            "krita_speech_bubble_generator.krita_host.gateway.canvas_snapshot",
            return_value=(image, QRectF(0, 0, 800, 600)))
        self.snapshot = self.snapshotPatch.start()
        self.docker = EditorHarness(SpeechBubbleDocker())
        self.docker.selectionTimer.stop()
        self.warnings = patch.object(self.docker.view, "warn")
        self.warn = self.warnings.start()

    def tearDown(self):
        self.docker.close()
        self.docker.selectionTimer.stop()
        self.docker.liveTimer.stop()
        self.docker.backgroundTimer.stop()
        self.warnings.stop()
        self.snapshotPatch.stop()
        self.docker.deleteLater()
        FakeKrita.document = None

    def editTarget(self):
        layer = FakeLayer()
        document = FakeDocument(layer)
        FakeKrita.document = document
        group = layer.addShapesFromSvg(self.docker.renderBubble()[0])[0]
        baseline = group.transformation()
        self.docker.saveSettings(document, layer, baseline)
        self.docker.setEditTarget(document, layer, baseline)
        return document, layer, group

    def test_svg_handles_special_characters_and_empty_text(self):
        self.docker.autocenter.setChecked(False)
        for text in ("", "A & B <C>\n\"quoted\"", "Wide WWW\niiiiiiiii"):
            self.docker.bubbleText.setPlainText(text)
            for style in STYLES:
                self.docker.bubbleType.setCurrentText(style)
                svg, view_box, tip = self.docker.renderBubble(preview=True)
                root = ET.fromstring(svg)
                texts = root.findall(".//{http://www.w3.org/2000/svg}text")
                self.assertEqual("\n".join(node.text or "" for node in texts), text)
                self.assertTrue(self.docker.preview.renderer().isValid())
                self.assertGreater(view_box.width(), 0)
                self.assertGreater(view_box.height(), 0)

    def test_newlines_and_actual_font_width(self):
        self.assertEqual(self.docker.getSpeechLines("one two\n\nthree four", 7),
                         ["one two", "", "three", "four"])
        self.docker.autocenter.setChecked(False)
        self.docker.bubbleText.setPlainText("WWWW\niiiiiiii")
        rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
        self.assertGreaterEqual(text_rect.width(), metrics.horizontalAdvance("WWWW"))

    def test_auto_layout_preserves_short_phrases_and_wraps_long_speech(self):
        self.docker.bubbleText.setPlainText("This is a new one")
        self.assertEqual(self.docker.geometry()[5], ["This is a new one"])
        self.docker.bubbleText.setPlainText("This is a new one\nWith a deliberate line break")
        self.assertEqual(self.docker.geometry()[5],
                         ["This is a new one", "With a deliberate line break"])
        text = "A longer piece of dialogue that needs more than one line. " * 8
        self.docker.bubbleText.setPlainText(text)
        lines = self.docker.geometry()[5]
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines), text.strip())

    def test_auto_layout_balances_medium_dialogue_into_two_lines(self):
        text = "This is a moderately long line of dialogue."
        self.docker.bubbleText.setPlainText(text)
        rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
        self.assertEqual(len(lines), 2)
        self.assertEqual(" ".join(lines), text)
        widths = [metrics.horizontalAdvance(line) for line in lines]
        self.assertLess(max(widths), metrics.horizontalAdvance(text) * 0.7)
        self.assertGreater(min(widths), max(widths) * 0.5)

    def test_irregularity_change_regenerates_seed_without_a_pattern_button(self):
        self.docker.bubbleType.setCurrentText("Shouting")
        seed = self.docker.shoutSeed
        self.docker.shoutingSpinBox.setValue(80)
        self.assertNotEqual(self.docker.shoutSeed, seed)
        changed_seed = self.docker.shoutSeed
        self.docker.bubbleText.setPlainText("Keep the same pattern while typing")
        self.assertEqual(self.docker.shoutSeed, changed_seed)
        self.assertFalse(any(button.text() == "New pattern"
                             for button in self.docker.findChildren(type(self.docker.addOnPage))))

    def test_shouting_shape_selector_updates_and_reopens_without_resetting_seed(self):
        self.assertEqual(self.docker.shoutingShape.currentText(), "Balanced")
        self.assertTrue(self.docker.shoutingGroup.isHidden())
        self.docker.bubbleType.setCurrentText("Shouting")
        self.assertFalse(self.docker.shoutingGroup.isHidden())
        self.docker.shoutingSpinBox.setValue(79)
        self.docker.shoutSeed = 17
        self.docker.tailSpinBox.setValue(60)
        document, layer, group = self.editTarget()
        before = self.docker.geometry()
        for shape in SHOUTING_SHAPES:
            with self.subTest(shape=shape):
                self.docker.shoutingShape.setCurrentText(shape)
                self.docker.applyLiveUpdate()
                saved = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
                self.assertEqual(saved["shout_shape"], shape)
                self.assertEqual(saved["shout_seed"], 17)
                geometry = self.docker.geometry()
                self.assertEqual((geometry[0], geometry[1], geometry[5]),
                                 (before[0], before[1], before[5]))
                self.assertEqual(geometry[2], body_path(
                    geometry[0], "Shouting", irregularity=79, seed=17, shouting_shape=shape,
                    nodes=self.docker.shoutingNodesSpinBox.value()))
                direction = QPointF(math.cos(self.docker.tailAngle), math.sin(self.docker.tailAngle))
                anchor = outline_anchor(geometry[2], geometry[0].center(), direction)
                self.assertAlmostEqual(math.hypot(geometry[4].x() - anchor.x(),
                                                 geometry[4].y() - anchor.y()), 60)
                self.assertTrue(self.docker.preview.renderer().isValid())
                namespace = "{http://www.w3.org/2000/svg}"
                preview = ET.fromstring(self.docker.getPreview())
                exported = ET.fromstring(self.docker.renderBubble()[0])
                self.assertEqual(preview.find(".//" + namespace + "path").attrib,
                                 exported.find(".//" + namespace + "path").attrib)
                self.docker.stopEditing()
                self.docker.shoutingShape.setCurrentText("Balanced")
                self.docker.loadSelectedBubble()
                self.assertEqual(self.docker.shoutingShape.currentText(), shape)
                self.assertEqual(self.docker.shoutSeed, 17)
                self.assertEqual(self.docker.geometry()[2], geometry[2])
        self.docker.bubbleType.setCurrentText("Rounded")
        self.assertTrue(self.docker.shoutingGroup.isHidden())
        self.warn.assert_not_called()

    def test_invalid_saved_shouting_shape_is_rejected(self):
        document, layer, group = self.editTarget()
        settings = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        for value in ("Unknown", "", None, 42, [], {}):
            with self.subTest(shape=value):
                settings["shout_shape"] = value
                with self.assertRaisesRegex(ValueError, "Invalid shouting shape"):
                    self.docker.validateSettings(settings)

    def test_older_shouting_bubble_defaults_to_balanced(self):
        self.docker.bubbleType.setCurrentText("Shouting")
        document, layer, group = self.editTarget()
        self.docker.stopEditing()
        key = self.docker.annotationKey(layer)
        settings = json.loads(bytes(document.annotation(key)))
        del settings["shout_shape"]
        document.annotations[key] = QByteArray(json.dumps(settings).encode())
        self.docker.shoutingShape.setCurrentText("Angular")
        self.docker.loadSelectedBubble()
        self.assertEqual(self.docker.shoutingShape.currentText(), "Balanced")
        self.assertEqual(self.docker.shoutSeed, settings["shout_seed"])
        self.warn.assert_not_called()

    def test_nodes_live_update_and_reopen_for_thought_and_every_shouting_shape(self):
        for style, shapes in (("Thought", ("Balanced",)), ("Shouting", SHOUTING_SHAPES)):
            for shape in shapes:
                self.docker.stopEditing()
                self.docker.bubbleType.setCurrentText(style)
                self.docker.shoutingShape.setCurrentText(shape)
                self.docker.tailSpinBox.setValue(60)
                document, layer, group = self.editTarget()
                before = self.docker.geometry()
                seeds = self.docker.shoutSeed, self.docker.thoughtSeed
                control = (self.docker.thoughtNodesSlider if style == "Thought"
                           else self.docker.shoutingNodesSlider)
                key = "thought_nodes" if style == "Thought" else "shout_nodes"
                for nodes in (8, 32, 64):
                    with self.subTest(style=style, shape=shape, nodes=nodes):
                        control.setValue(nodes)
                        self.assertTrue(self.docker.pendingLiveUpdate)
                        self.docker.applyLiveUpdate()
                        saved = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
                        self.assertEqual(saved[key], nodes)
                        self.assertEqual((self.docker.shoutSeed, self.docker.thoughtSeed), seeds)
                        geometry = self.docker.geometry()
                        self.assertEqual((geometry[0], geometry[1], geometry[5]),
                                         (before[0], before[1], before[5]))
                        direction = QPointF(math.cos(self.docker.tailAngle),
                                            math.sin(self.docker.tailAngle))
                        anchor = outline_anchor(geometry[2], geometry[0].center(), direction)
                        self.assertAlmostEqual(math.hypot(geometry[4].x() - anchor.x(),
                                                         geometry[4].y() - anchor.y()), 60)
                        self.assertTrue(self.docker.preview.renderer().isValid())
                        namespace = "{http://www.w3.org/2000/svg}"
                        preview = ET.fromstring(self.docker.getPreview())
                        exported = ET.fromstring(self.docker.renderBubble()[0])
                        self.assertEqual(preview.find(".//" + namespace + "path").attrib,
                                         exported.find(".//" + namespace + "path").attrib)
                        self.docker.stopEditing()
                        control.setValue(16)
                        self.docker.loadSelectedBubble()
                        self.assertEqual(control.value(), nodes)
                        self.assertEqual(self.docker.geometry()[2], geometry[2])
        self.warn.assert_not_called()

    def test_older_bubbles_load_original_node_counts(self):
        for style, shape, count in (("Thought", "Balanced", 16),
                                    ("Shouting", "Balanced", 24),
                                    ("Shouting", "Punchy", 18)):
            with self.subTest(style=style, shape=shape):
                self.docker.stopEditing()
                self.docker.bubbleType.setCurrentText(style)
                self.docker.shoutingShape.setCurrentText(shape)
                document, layer, group = self.editTarget()
                self.docker.stopEditing()
                key = self.docker.annotationKey(layer)
                settings = json.loads(bytes(document.annotation(key)))
                del settings["shout_nodes"]
                del settings["thought_nodes"]
                document.annotations[key] = QByteArray(json.dumps(settings).encode())
                self.docker.shoutingNodesSpinBox.setValue(64)
                self.docker.thoughtNodesSpinBox.setValue(64)
                self.docker.loadSelectedBubble()
                self.assertEqual(self.docker.thoughtNodesSpinBox.value(), 16)
                self.assertEqual(self.docker.shoutingNodesSpinBox.value(),
                                 18 if shape == "Punchy" else 24)
                self.assertEqual(self.docker.geometry()[2], body_path(
                    self.docker.geometry()[0], style, irregularity=settings[
                        "thought_irregularity" if style == "Thought" else "shout_irregularity"],
                    seed=settings["thought_seed" if style == "Thought" else "shout_seed"],
                    shouting_shape=shape, nodes=count))
        self.warn.assert_not_called()

    def test_invalid_saved_node_counts_are_rejected(self):
        document, layer, group = self.editTarget()
        settings = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        for key in ("shout_nodes", "thought_nodes"):
            for value in (7, 65, True, 16.5, "16", None):
                with self.subTest(key=key, value=value):
                    changed = dict(settings, **{key: value})
                    with self.assertRaisesRegex(ValueError, "Invalid " + key):
                        self.docker.validateSettings(changed)

    def test_thought_irregularity_changes_cloud_and_trail_without_moving_text(self):
        self.docker.bubbleType.setCurrentText("Thought")
        self.assertFalse(self.docker.thoughtGroup.isHidden())
        self.assertTrue(self.docker.shoutingGroup.isHidden())
        self.docker.tailSpinBox.setValue(60)
        self.docker.thoughtSizeSpinBox.setValue(200)
        self.docker.thoughtSpinBox.setValue(0)
        before = self.docker.geometry()
        seed, shout_seed = self.docker.thoughtSeed, self.docker.shoutSeed
        self.docker.thoughtSpinBox.setValue(100)
        after = self.docker.geometry()
        self.assertNotEqual(self.docker.thoughtSeed, seed)
        self.assertEqual(self.docker.shoutSeed, shout_seed)
        self.assertNotEqual(before[2], after[2])
        self.assertNotEqual(before[3], after[3])
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])
        self.assertEqual(self.docker.thoughtSizeSpinBox.value(), 200)
        self.assertEqual(self.docker.tailSpinBox.value(), 60)
        direction = QPointF(math.cos(self.docker.tailAngle), math.sin(self.docker.tailAngle))
        anchor = outline_anchor(after[2], after[0].center(), direction)
        self.assertAlmostEqual(math.hypot(after[4].x() - anchor.x(), after[4].y() - anchor.y()), 60)
        self.docker.bubbleType.setCurrentText("Shouting")
        self.assertTrue(self.docker.thoughtGroup.isHidden())
        self.assertFalse(self.docker.shoutingGroup.isHidden())

    def test_maximum_irregularity_still_keeps_text_inside_cloud_and_shouting(self):
        self.docker.autocenter.setChecked(False)
        self.docker.bubbleText.setPlainText("\n".join(["A fairly long line of text"] * 20))
        for style in ("Thought", "Shouting"):
            self.docker.bubbleType.setCurrentText(style)
            self.docker.thoughtSpinBox.setValue(100)
            self.docker.shoutingSpinBox.setValue(100)
            for seed in (0, 17, 99):
                self.docker.thoughtSeed = seed
                self.docker.shoutSeed = seed
                rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
                for corner in (text_rect.topLeft(), text_rect.topRight(),
                               text_rect.bottomLeft(), text_rect.bottomRight()):
                    self.assertTrue(body.contains(corner))

    def test_live_editing_has_no_mode_switch_or_manual_edit_button(self):
        self.assertFalse(hasattr(self.docker, "liveUpdate"))
        self.assertFalse(hasattr(self.docker, "editSelected"))
        self.assertNotIn("Live update", [
            control.text() for control in self.docker.findChildren(QCheckBox)])
        self.assertNotIn("Edit selected bubble", [
            control.text() for control in self.docker.findChildren(QPushButton)])

    def test_speech_controls_are_immediately_below_the_preview(self):
        layout = self.docker.widget().widget().layout()
        self.assertEqual(layout.indexOf(self.docker.speechGroup),
                         layout.indexOf(self.docker.preview) + 1)
        self.assertTrue(self.docker.speechGroup.isAncestorOf(self.docker.bubbleText))
        self.assertTrue(self.docker.speechGroup.isAncestorOf(self.docker.speechFont))

    def test_conditional_controls_and_default_font(self):
        self.assertEqual(self.docker.lockTailLength.text(), "Lock tail length")
        tail_layout = self.docker.tailLengthControls.parentWidget().layout()
        self.assertLess(tail_layout.indexOf(self.docker.lockTailLength),
                        tail_layout.indexOf(self.docker.tailLengthControls))
        self.docker.lockTailLength.setChecked(False)
        self.assertTrue(self.docker.tailLengthControls.isHidden())
        self.assertTrue(self.docker.tailSpinBox.isHidden())
        self.docker.lockTailLength.setChecked(True)
        self.assertFalse(self.docker.tailLengthControls.isHidden())
        self.assertFalse(self.docker.tailSlider.isHidden())
        self.assertTrue(self.docker.tailSpinBox.isHidden())
        self.assertTrue(self.docker.averageLineLength.isHidden())
        self.docker.autocenter.setChecked(False)
        self.assertFalse(self.docker.averageLineLength.isHidden())
        self.docker.autocenter.setChecked(True)
        self.assertTrue(self.docker.averageLineLength.isHidden())
        if "Segoe Print" in QFontDatabase().families():
            self.assertEqual(self.docker.speechFont.currentFont().family(), "Segoe Print")
        else:
            self.assertIn("Segoe Print", self.docker.speechFont.toolTip())

    def test_wheel_scrolls_dock_instead_of_changing_controls(self):
        self.docker.resize(440, 550)
        self.docker.show()
        self.docker.selectionTimer.stop()
        APP.processEvents()
        controls = (self.docker.outlineSlider, self.docker.outlineSpinBox,
                    self.docker.speechFontSize, self.docker.bubbleType, self.docker.speechFont)
        for control in controls:
            before = control.value() if hasattr(control, "value") else control.currentText()
            local = control.rect().center()
            event = QWheelEvent(QPointF(local), QPointF(control.mapToGlobal(local)),
                                QPoint(), QPoint(0, -120), Qt.NoButton,
                                Qt.NoModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(control, event)
            after = control.value() if hasattr(control, "value") else control.currentText()
            self.assertEqual(before, after)
        self.assertGreater(self.docker.widget().verticalScrollBar().value(), 0)

    def test_text_corners_fit_inside_every_body_style(self):
        self.docker.autocenter.setChecked(False)
        self.docker.bubbleText.setPlainText("\n".join(["A fairly long line of text"] * 20))
        for style in STYLES:
            self.docker.bubbleType.setCurrentText(style)
            rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
            for corner in (text_rect.topLeft(), text_rect.topRight(),
                           text_rect.bottomLeft(), text_rect.bottomRight()):
                self.assertTrue(body.contains(corner))

    def test_padding_insets_text_in_every_style_without_changing_wrapping(self):
        self.docker.autocenter.setChecked(False)
        for text in ("A short line", "A long line of speech\nAnother line", ""):
            self.docker.bubbleText.setPlainText(text)
            for style in STYLES:
                self.docker.bubbleType.setCurrentText(style)
                previous = None
                for value in (0, 10, 150, 300):
                    with self.subTest(text=text, style=style, padding=value):
                        self.docker.paddingSpinBox.setValue(value)
                        rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
                        padding = self.docker.speechFontSize.value() * value / 100
                        # Sample the clearance around the text, just inside the boundary.
                        inset = text_rect.adjusted(0.01, 0.01, -0.01, -0.01)
                        if text_rect.width() == 0:
                            inset.setLeft(text_rect.center().x())
                            inset.setRight(text_rect.center().x())
                        for corner in (inset.topLeft(), inset.topRight(),
                                       inset.bottomLeft(), inset.bottomRight()):
                            for step in range(32):
                                angle = step * math.pi / 16
                                offset = QPointF(math.cos(angle), math.sin(angle)) * max(0, padding - 0.01)
                                self.assertTrue(body.contains(corner + offset))
                        if previous is not None:
                            self.assertGreater(rect.width(), previous[0].width())
                            self.assertGreater(rect.height(), previous[0].height())
                            self.assertEqual(text_rect.size(), previous[1].size())
                            self.assertEqual(lines, previous[5])
                        previous = (rect, text_rect, body, path, tip, lines, metrics)
                        self.assertTrue(self.docker.preview.renderer().isValid())
                        preview = ET.fromstring(self.docker.getPreview())
                        exported = ET.fromstring(self.docker.renderBubble()[0])
                        namespace = "{http://www.w3.org/2000/svg}"
                        self.assertEqual(preview.find(".//" + namespace + "path").attrib,
                                         exported.find(".//" + namespace + "path").attrib)

    def test_padding_live_updates_and_keeps_patterns_and_tail_length(self):
        self.docker.bubbleType.setCurrentText("Thought")
        self.docker.tailSpinBox.setValue(60)
        document, layer, group = self.editTarget()
        seeds = self.docker.thoughtSeed, self.docker.shoutSeed
        before = self.docker.geometry()[0]
        self.docker.paddingSpinBox.setValue(250)
        self.assertTrue(self.docker.pendingLiveUpdate)
        self.docker.applyLiveUpdate()
        saved = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        self.assertEqual(saved["padding"], 250)
        self.assertGreater(self.docker.geometry()[0].height(), before.height())
        self.assertEqual((self.docker.thoughtSeed, self.docker.shoutSeed), seeds)
        rect, _, body, _, tip, _, _ = self.docker.geometry()
        direction = QPointF(math.cos(self.docker.tailAngle), math.sin(self.docker.tailAngle))
        anchor = outline_anchor(body, rect.center(), direction)
        self.assertAlmostEqual(math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y()), 60)
        self.warn.assert_not_called()

    def test_invalid_saved_padding_is_rejected(self):
        document, layer, group = self.editTarget()
        key = self.docker.annotationKey(layer)
        settings = json.loads(bytes(document.annotation(key)))
        for value in (-1, 301, 1.5, True, "150"):
            with self.subTest(padding=value):
                settings["padding"] = value
                with self.assertRaisesRegex(ValueError, "Invalid padding"):
                    self.docker.validateSettings(settings)

    def test_drag_reanchors_tail_without_moving_body_or_text(self):
        self.docker.tailSpinBox.setValue(40)
        original = self.docker.geometry()
        for point in (QPointF(-90, 40), QPointF(30, -90),
                      QPointF(400, 50), QPointF(60, 260)):
            self.docker.moveTail(point)
            geometry = self.docker.geometry()
            self.assertEqual(geometry[0], original[0])
            self.assertEqual(geometry[1], original[1])
            self.assertFalse(geometry[2].contains(geometry[4]))
        self.assertLess(self.docker.geometry()[4].y(), 500)

    def test_locked_tail_keeps_length_as_direction_changes(self):
        self.docker.tailSpinBox.setValue(60)
        self.assertTrue(self.docker.lockTailLength.isChecked())
        for point in (QPointF(-1000, 20), QPointF(20, -1000), QPointF(600, 500)):
            self.docker.moveTail(point)
            rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
            direction = QPointF(math.cos(self.docker.tailAngle), math.sin(self.docker.tailAngle))
            anchor = outline_anchor(body, rect.center(), direction)
            self.assertEqual(self.docker.tailSpinBox.value(), 60)
            self.assertAlmostEqual((tip - anchor).manhattanLength(),
                                   (direction * 60).manhattanLength())

    def test_unlocked_tail_drag_changes_length(self):
        self.docker.tailSpinBox.setValue(40)
        self.docker.lockTailLength.setChecked(False)
        rect, text_rect, body, path, tip, lines, metrics = self.docker.geometry()
        target = tail_tip(body, rect.center(), -1.8, 90)
        self.docker.moveTail(target)
        self.assertEqual(self.docker.tailSpinBox.value(), 90)
        self.assertAlmostEqual(self.docker.tailAngle, -1.8)

    def test_zero_length_tail_handle_is_visible_only_when_unlocked(self):
        for style in STYLES:
            with self.subTest(style=style):
                self.docker.bubbleType.setCurrentText(style)
                self.docker.tailSpinBox.setValue(0)
                self.docker.lockTailLength.setChecked(True)
                self.assertIsNone(self.docker.preview.tip)
                before = self.docker.renderBubble()[0]
                self.docker.lockTailLength.setChecked(False)
                rect, _, body, path, tip, _, _ = self.docker.geometry()
                self.assertIsNone(tip)
                self.assertEqual(path, body)
                expected = tail_tip(body, rect.center(), self.docker.tailAngle, 0)
                self.assertEqual(self.docker.preview.tip, expected)
                self.assertEqual(self.docker.renderBubble()[0], before)
                self.assertIsNone(self.docker.renderBubble()[2])
                self.docker.lockTailLength.setChecked(True)
                self.assertIsNone(self.docker.preview.tip)

    def test_unlocked_tail_can_shrink_to_zero_and_be_extended_again(self):
        self.docker.lockTailLength.setChecked(False)
        self.docker.tailSpinBox.setValue(60)
        rect, _, body, _, _, _, _ = self.docker.geometry()
        direction = QPointF(math.cos(self.docker.tailAngle), math.sin(self.docker.tailAngle))
        anchor = outline_anchor(body, rect.center(), direction)
        self.docker.moveTail(rect.center() + (anchor - rect.center()) * 0.5)
        self.assertEqual(self.docker.tailSpinBox.value(), 0)
        self.assertIsNotNone(self.docker.preview.tip)
        self.assertEqual(self.docker.geometry()[3], body)
        self.docker.moveTail(anchor + direction * 50)
        self.assertEqual(self.docker.tailSpinBox.value(), 50)
        self.assertIsNotNone(self.docker.preview.tip)

    def test_preview_mouse_can_drag_a_zero_length_tail(self):
        self.docker.lockTailLength.setChecked(False)
        self.docker.tailSpinBox.setValue(0)
        preview = self.docker.preview
        preview.show()
        APP.processEvents()
        self.assertIsNotNone(preview.tip)
        handle = preview.toWidget(preview.tip, preview.view_box)
        start = QPoint(round(handle.x()), round(handle.y()))
        rect, _, body, _, _, _, _ = self.docker.geometry()
        target = preview.toWidget(tail_tip(body, rect.center(), self.docker.tailAngle, 40),
                                  preview.view_box)
        end = QPoint(round(target.x()), round(target.y()))
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        self.assertTrue(preview.dragging)
        QTest.mouseMove(preview, end)
        QTest.mouseRelease(preview, Qt.LeftButton, pos=end)
        self.assertFalse(preview.dragging)
        self.assertGreater(self.docker.tailSpinBox.value(), 0)

    def test_thought_size_control_is_enabled_only_for_thoughts(self):
        self.assertFalse(self.docker.thoughtSizeGroup.isEnabled())
        self.docker.bubbleType.setCurrentText("Thought")
        self.assertTrue(self.docker.thoughtSizeGroup.isEnabled())
        self.docker.thoughtSizeSpinBox.setValue(250)
        self.assertEqual(self.docker.settings()["thought_size"], 250)
        self.docker.bubbleType.setCurrentText("Oval")
        self.assertFalse(self.docker.thoughtSizeGroup.isEnabled())

    def test_preview_mouse_drag_with_letterboxing(self):
        self.docker.tailSpinBox.setValue(40)
        preview = self.docker.preview
        preview.resize(700, 250)
        preview.show()
        APP.processEvents()
        handle = preview.toWidget(preview.tip, preview.view_box)
        self.assertLess(
            (preview.toBubble(handle, preview.view_box) - preview.tip).manhattanLength(), 1e-6)
        start = QPoint(round(handle.x()), round(handle.y()))
        target = start + QPoint(-60, -30)
        angle = self.docker.tailAngle
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        self.assertTrue(preview.dragging)
        QTest.mouseMove(preview, target)
        QTest.mouseRelease(preview, Qt.LeftButton, pos=target)
        self.assertFalse(preview.dragging)
        self.assertNotEqual(self.docker.tailAngle, angle)

    def test_settings_reopen_from_document(self):
        self.docker.bubbleType.setCurrentText("Thought")
        self.docker.bubbleText.setPlainText("Thinking & wondering...")
        self.docker.tailSpinBox.setValue(60)
        self.docker.tailAngle = -2.1
        self.docker.lockTailLength.setChecked(False)
        self.docker.thoughtSizeSpinBox.setValue(275)
        self.docker.shoutingSpinBox.setValue(85)
        self.docker.shoutingShape.setCurrentText("Expressive")
        self.docker.shoutingNodesSpinBox.setValue(37)
        self.docker.thoughtNodesSpinBox.setValue(29)
        self.docker.shoutSeed = 1729
        self.docker.thoughtSpinBox.setValue(75)
        self.docker.thoughtSeed = 2718
        self.docker.paddingSpinBox.setValue(235)
        expected = self.docker.settings()
        document, layer, group = self.editTarget()
        self.docker.stopEditing()
        self.docker.bubbleType.setCurrentText("Square")
        self.docker.bubbleText.clear()
        self.docker.tailSpinBox.setValue(0)
        self.docker.lockTailLength.setChecked(True)
        self.docker.thoughtSizeSpinBox.setValue(100)
        self.docker.thoughtSpinBox.setValue(15)
        self.docker.paddingSpinBox.setValue(0)
        self.docker.shoutingShape.setCurrentText("Balanced")
        self.docker.shoutingNodesSpinBox.setValue(24)
        self.docker.thoughtNodesSpinBox.setValue(16)
        self.docker.loadSelectedBubble()
        self.assertEqual(self.docker.settings(), expected)
        self.warn.assert_not_called()

    def test_older_round_settings_load_as_rounded_with_new_defaults(self):
        document, layer, group = self.editTarget()
        self.docker.stopEditing()
        key = self.docker.annotationKey(layer)
        settings = json.loads(bytes(document.annotations[key]))
        settings["style"] = "Round"
        del settings["lock_tail"]
        del settings["thought_size"]
        del settings["shout_irregularity"]
        del settings["shout_seed"]
        del settings["shout_shape"]
        del settings["shout_nodes"]
        del settings["thought_nodes"]
        del settings["thought_irregularity"]
        del settings["thought_seed"]
        del settings["padding"]
        document.annotations[key] = QByteArray(json.dumps(settings).encode())
        self.docker.paddingSpinBox.setValue(250)
        self.docker.shoutingShape.setCurrentText("Punchy")
        self.docker.loadSelectedBubble()
        self.assertEqual(self.docker.bubbleType.currentText(), "Rounded")
        self.assertTrue(self.docker.lockTailLength.isChecked())
        self.assertEqual(self.docker.thoughtSizeSpinBox.value(), 100)
        self.assertEqual(self.docker.shoutingSpinBox.value(), 0)
        self.assertEqual(self.docker.shoutSeed, 0)
        self.assertEqual(self.docker.shoutingShape.currentText(), "Balanced")
        self.assertEqual(self.docker.shoutingNodesSpinBox.value(), 24)
        self.assertEqual(self.docker.thoughtNodesSpinBox.value(), 16)
        self.assertEqual(self.docker.thoughtSpinBox.value(), 0)
        self.assertEqual(self.docker.thoughtSeed, 0)
        self.assertEqual(self.docker.paddingSpinBox.value(), 150)
        self.warn.assert_not_called()

    def twoBubbles(self):
        self.docker.bubbleText.setPlainText("First bubble")
        document, first, group = self.editTarget()
        self.docker.stopEditing()
        self.docker.bubbleText.setPlainText("Second bubble")
        second = document.createVectorLayer("Second")
        second_group = second.addShapesFromSvg(self.docker.renderBubble()[0])[0]
        self.docker.saveSettings(document, second, second_group.transformation())
        document.setActiveNode(first)
        group.select()
        self.docker.loadSelectedBubble()
        return document, first, second

    def savedText(self, document, layer, shape_name=SHAPE_NAME):
        return json.loads(bytes(document.annotation(self.docker.annotationKey(layer, shape_name))))["text"]

    def test_canvas_selection_switches_editor_text_without_manual_edit_button(self):
        document, first, second = self.twoBubbles()
        first.items[0].selected = False
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        second.items[0].selected = False
        first.items[0].select()
        document.setActiveNode(first)
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "First bubble")
        self.warn.assert_not_called()

    def test_selection_timer_loads_the_new_bubble(self):
        document, first, second = self.twoBubbles()
        first.items[0].selected = False
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.selectionTimer.start()
        QTest.qWait(220)
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.warn.assert_not_called()

    def test_typing_live_updates_once_and_preserves_shape_selection(self):
        document, layer, group = self.editTarget()
        group.select()
        self.docker.syncSelection()
        document.events.clear()
        self.docker.bubbleText.setPlainText("New text")
        self.docker.bubbleText.setPlainText("New final text")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, layer), "New final text")
        self.assertEqual(document.events.count("projection"), 1)
        self.assertTrue(layer.items[0].isSelected())
        self.assertFalse(self.docker.pendingLiveUpdate)
        self.warn.assert_not_called()

    def test_selection_change_flushes_pending_text_to_old_bubble_not_new_one(self):
        document, first, second = self.twoBubbles()
        self.docker.bubbleText.setPlainText("Edited first bubble")
        self.assertTrue(self.docker.pendingLiveUpdate)
        first.items[0].selected = False
        second.items[0].select()
        document.setActiveNode(second)
        # A single-shot timer is already inactive when its timeout callback runs.
        self.docker.liveTimer.stop()
        self.docker.applyLiveUpdate()
        self.assertEqual(self.savedText(document, first), "Edited first bubble")
        self.assertEqual(self.savedText(document, second), "Second bubble")
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.warn.assert_not_called()

    def test_document_switch_discards_pending_text_without_mutating_either_document(self):
        first_document, first_layer, first_group = self.editTarget()
        original = self.savedText(first_document, first_layer)
        self.docker.bubbleText.setPlainText("Do not flush after leaving the document")
        second_document = FakeDocument(None)
        FakeKrita.document = second_document
        self.docker.applyLiveUpdate()
        self.assertEqual(self.savedText(first_document, first_layer), original)
        self.assertEqual(first_layer.items, [first_group])
        self.assertEqual(second_document.layers, {})
        self.assertIsNone(self.docker.editLayerId)
        self.assertFalse(self.docker.pendingLiveUpdate)
        self.assertFalse(self.docker.liveTimer.isActive())
        FakeKrita.document = first_document
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), original)
        self.warn.assert_not_called()

    def test_hiding_dock_flushes_pending_snapshot_and_stops_owned_timers(self):
        document, layer, group = self.editTarget()
        self.docker.show()
        self.docker.bubbleText.setPlainText("Persist before hiding")
        self.docker.hide()
        self.assertEqual(self.savedText(document, layer), "Persist before hiding")
        self.assertFalse(self.docker.pendingLiveUpdate)
        self.assertFalse(self.docker.liveTimer.isActive())
        self.assertFalse(self.docker.selectionTimer.isActive())
        self.assertFalse(self.docker.backgroundTimer.isActive())
        self.warn.assert_not_called()

    def test_deselection_finishes_pending_edit_then_stops_live_writes(self):
        document, layer, group = self.editTarget()
        group.select()
        self.docker.syncSelection()
        self.docker.bubbleText.setPlainText("Finish this edit")
        group.selected = False
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editLayerId)
        self.assertEqual(self.savedText(document, layer), "Finish this edit")
        document.events.clear()
        self.docker.bubbleText.setPlainText("An unbound draft")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, layer), "Finish this edit")
        self.assertNotIn("projection", document.events)
        self.assertEqual(self.docker.addOnPage.text(), "Add on Page")
        self.warn.assert_not_called()

    def test_layer_selection_automatically_loads_a_generated_bubble(self):
        document, first, second = self.twoBubbles()
        first.items[0].selected = False
        document.setActiveNode(second)
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        self.assertEqual(self.docker.editLayerId, second.uniqueId())

    def test_appearance_changes_always_update_the_selected_bubble(self):
        document, layer, group = self.editTarget()
        self.docker.bubbleType.setCurrentText("Thought")
        self.docker.paddingSpinBox.setValue(210)
        QTest.qWait(220)
        saved = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        self.assertEqual(saved["style"], "Thought")
        self.assertEqual(saved["padding"], 210)
        self.warn.assert_not_called()

    def test_failed_live_update_reports_once_and_next_edit_can_retry(self):
        document, layer, group = self.editTarget()
        original = self.savedText(document, layer)
        layer.fail_import = True
        self.docker.bubbleText.setPlainText("Import will fail")
        QTest.qWait(220)
        self.assertEqual(layer.items, [group])
        self.assertEqual(self.savedText(document, layer), original)
        self.assertFalse(self.docker.pendingLiveUpdate)
        self.assertFalse(self.docker.liveTimer.isActive())
        self.docker.syncSelection()
        QTest.qWait(220)
        self.warn.assert_called_once()
        layer.fail_import = False
        self.docker.bubbleText.setPlainText("Next edit succeeds automatically")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, layer), "Next edit succeeds automatically")
        self.warn.assert_called_once()

    def test_failed_pending_edit_does_not_disable_updates_for_the_next_selection(self):
        document, first, second = self.twoBubbles()
        first.fail_import = True
        self.docker.bubbleText.setPlainText("First edit cannot be imported")
        first.items[0].deselect()
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.syncSelection()
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        self.docker.bubbleText.setPlainText("Second edit succeeds automatically")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, first), "First bubble")
        self.assertEqual(self.savedText(document, second), "Second edit succeeds automatically")
        self.warn.assert_called_once()

    def test_selecting_unrelated_artwork_stops_editing_without_overwriting_it(self):
        document, layer, group = self.editTarget()
        unrelated = document.createVectorLayer("Other artwork")
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editLayerId)
        self.docker.bubbleText.setPlainText("Draft text")
        QTest.qWait(220)
        self.assertEqual(unrelated.items, [])
        self.warn.assert_not_called()

    def test_invalid_bubble_selection_does_not_leave_previous_target_editable(self):
        document, first, second = self.twoBubbles()
        document.annotations[self.docker.annotationKey(second)] = QByteArray(b"{")
        document.setActiveNode(second)
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editLayerId)
        self.docker.bubbleText.setPlainText("Unbound after invalid selection")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, first), "First bubble")
        self.warn.assert_called_once()

    def test_live_shouting_pattern_survives_text_changes_and_reopening(self):
        self.docker.bubbleType.setCurrentText("Shouting")
        self.docker.shoutingSpinBox.setValue(85)
        document, layer, group = self.editTarget()
        seed = self.docker.shoutSeed
        self.docker.bubbleText.setPlainText("A different shout!")
        QTest.qWait(220)
        settings = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        self.assertEqual(settings["shout_seed"], seed)
        self.assertEqual(settings["shout_irregularity"], 85)
        self.docker.loadSelectedBubble()
        self.assertEqual(self.docker.shoutSeed, seed)
        self.assertEqual(self.docker.shoutingSpinBox.value(), 85)
        self.warn.assert_not_called()

    def test_live_thought_pattern_survives_text_tail_edits_and_reopening(self):
        self.docker.bubbleType.setCurrentText("Thought")
        self.docker.thoughtSpinBox.setValue(85)
        self.docker.tailSpinBox.setValue(60)
        document, layer, group = self.editTarget()
        seed = self.docker.thoughtSeed
        self.docker.bubbleText.setPlainText("An irregular thought...")
        self.docker.tailAngle = -0.7
        self.docker.updatePreview()
        QTest.qWait(220)
        settings = json.loads(bytes(document.annotation(self.docker.annotationKey(layer))))
        self.assertEqual(settings["thought_seed"], seed)
        self.assertEqual(settings["thought_irregularity"], 85)
        before = self.docker.getPreview()
        self.docker.loadSelectedBubble()
        self.assertEqual(self.docker.thoughtSeed, seed)
        self.assertEqual(self.docker.thoughtSpinBox.value(), 85)
        self.assertEqual(self.docker.getPreview(), before)
        self.warn.assert_not_called()

    def test_adding_another_bubble_finishes_the_pending_live_edit(self):
        document, first, group = self.editTarget()
        self.docker.bubbleText.setPlainText("Updated before adding another")
        self.docker.startNewBubble()
        self.docker.addOnPageShape()
        second = document.activeNode()
        self.assertNotEqual(first.uniqueId(), second.uniqueId())
        self.assertEqual(self.savedText(document, first), "Updated before adding another")
        self.assertEqual(self.savedText(document, second), "Updated before adding another")
        self.warn.assert_not_called()

    def test_primary_button_updates_instead_of_adding_while_editing(self):
        document, layer, group = self.editTarget()
        self.assertEqual(self.docker.addOnPage.text(), "Update on Page")
        self.assertTrue(self.docker.addDestination.isHidden())
        self.assertFalse(self.docker.newBubbleButton.isHidden())
        self.docker.bubbleText.setPlainText("Update the existing bubble")
        self.docker.addOnPage.click()
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(len(layer.items), 1)
        self.assertEqual(self.savedText(document, layer), "Update the existing bubble")
        self.assertEqual(self.docker.addOnPage.text(), "Update on Page")
        self.warn.assert_not_called()

    def test_new_bubble_button_enters_add_mode_without_reselecting_old_bubble(self):
        document, first, group = self.editTarget()
        group.select()
        self.docker.syncSelection()
        self.docker.bubbleText.setPlainText("Finish the old bubble")
        self.docker.newBubbleButton.click()
        self.assertEqual(self.savedText(document, first), "Finish the old bubble")
        self.assertIsNone(self.docker.editLayerId)
        self.assertFalse(any(shape.isSelected() for shape in first.shapes()))
        self.assertEqual(self.docker.addOnPage.text(), "Add on Page")
        self.assertFalse(self.docker.addDestination.isHidden())
        self.assertTrue(self.docker.newBubbleButton.isHidden())
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editLayerId)
        self.docker.bubbleText.setPlainText("A new bubble draft")
        self.docker.addOnPage.click()
        second = document.activeNode()
        self.assertNotEqual(first.uniqueId(), second.uniqueId())
        self.assertEqual(len(document.layers), 2)
        self.assertEqual(self.savedText(document, first), "Finish the old bubble")
        self.assertEqual(self.savedText(document, second), "A new bubble draft")
        self.assertEqual(self.docker.addOnPage.text(), "Update on Page")
        self.warn.assert_not_called()

    def sharedBubbles(self):
        self.docker.bubbleText.setPlainText("First shared bubble")
        document, layer, first = self.editTarget()
        first.select()
        self.docker.syncSelection()
        self.docker.startNewBubble()
        self.docker.addDestination.setCurrentIndex(1)
        self.docker.addOnPageShape()
        second_name = self.docker.editShapeName
        self.docker.bubbleText.setPlainText("Second shared bubble")
        self.docker.updateBubble()
        return document, layer, first, self.docker.shapeByName(layer, second_name)

    def test_add_to_existing_layer_keeps_both_bubbles_independently_editable(self):
        document, layer, first, second = self.sharedBubbles()
        self.assertEqual(len(document.layers), 1)
        self.assertEqual(len(layer.items), 2)
        self.assertNotEqual(first.name(), second.name())
        self.assertEqual(self.savedText(document, layer, first.name()), "First shared bubble")
        self.assertEqual(self.savedText(document, layer, second.name()), "Second shared bubble")
        self.assertFalse(first.isSelected())
        self.assertTrue(second.isSelected())
        first_transform = first.transformation()
        self.docker.bubbleText.setPlainText("Edited second bubble")
        QTest.qWait(220)
        self.assertEqual(len(layer.items), 2)
        self.assertIn(first, layer.items)
        self.assertEqual(first.transformation(), first_transform)
        self.assertEqual(self.savedText(document, layer, first.name()), "First shared bubble")
        self.assertEqual(self.savedText(document, layer, second.name()), "Edited second bubble")
        self.warn.assert_not_called()

    def test_clicking_different_bubbles_on_one_layer_loads_the_correct_text(self):
        document, layer, first, second = self.sharedBubbles()
        second.deselect()
        first.select()
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "First shared bubble")
        self.docker.bubbleText.setPlainText("Finish first before switching")
        first.deselect()
        second.select()
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second shared bubble")
        self.assertEqual(self.savedText(document, layer, first.name()), "Finish first before switching")
        self.assertEqual(self.docker.editShapeName, second.name())
        self.warn.assert_not_called()

    def test_shared_layer_updates_preserve_unrelated_artwork_and_stacking(self):
        document, layer, first, second = self.sharedBubbles()
        artwork = FakeShape(layer, QTransform.fromTranslate(900, 700))
        artwork.setName("Unrelated artwork")
        artwork.setZIndex(50)
        layer.items.append(artwork)
        first.setZIndex(10)
        second.deselect()
        first.select()
        self.docker.syncSelection()
        self.docker.bubbleText.setPlainText("Update only the first bubble")
        self.docker.updateBubble()
        replacement = self.docker.shapeByName(layer, first.name())
        self.assertEqual(replacement.zIndex(), 10)
        self.assertIn(second, layer.items)
        self.assertIn(artwork, layer.items)
        self.assertEqual(artwork.transformation(), QTransform.fromTranslate(900, 700))
        self.assertEqual(artwork.zIndex(), 50)
        self.warn.assert_not_called()

    def test_primary_update_on_shared_layer_does_not_add_a_third_bubble(self):
        document, layer, first, second = self.sharedBubbles()
        self.docker.bubbleText.setPlainText("Update second without duplicating")
        self.docker.addOnPage.click()
        self.assertEqual(len(layer.items), 2)
        self.assertEqual(len(document.layers), 1)
        self.assertIn(first, layer.items)
        self.assertEqual(self.savedText(document, layer, first.name()), "First shared bubble")
        self.assertEqual(self.savedText(document, layer, second.name()), "Update second without duplicating")
        self.warn.assert_not_called()

    def test_shared_bubble_settings_reopen_in_a_fresh_editor(self):
        document, layer, first, second = self.sharedBubbles()
        editor = EditorHarness(SpeechBubbleDocker())
        try:
            editor.loadSelectedBubble()
            self.assertEqual(editor.editShapeName, second.name())
            self.assertEqual(editor.bubbleText.toPlainText(), "Second shared bubble")
            second.deselect()
            first.select()
            editor.loadSelectedBubble()
            self.assertEqual(editor.editShapeName, first.name())
            self.assertEqual(editor.bubbleText.toPlainText(), "First shared bubble")
        finally:
            editor.close()
            editor.deleteLater()

    def test_switching_selection_automatically_loads_and_updates_the_new_bubble(self):
        document, first, second = self.twoBubbles()
        first.items[0].deselect()
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.syncSelection()
        self.assertEqual(self.docker.bubbleText.toPlainText(), "Second bubble")
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.docker.bubbleText.setPlainText("Second bubble updated automatically")
        QTest.qWait(220)
        self.assertEqual(self.savedText(document, second), "Second bubble updated automatically")
        self.assertEqual(self.savedText(document, first), "First bubble")
        self.warn.assert_not_called()

    def test_selecting_multiple_shared_bubbles_does_not_pick_one_to_overwrite(self):
        document, layer, first, second = self.sharedBubbles()
        first.select()
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editShapeName)
        self.assertEqual(self.docker.addOnPage.text(), "Add on Page")
        self.warn.assert_not_called()

    def test_selecting_a_duplicate_named_bubble_stops_editing_without_a_dialog(self):
        document, layer, original = self.editTarget()
        duplicate = FakeShape(layer, original.transformation())
        duplicate.setName(original.name())
        layer.items.append(duplicate)
        self.docker.startNewBubble()
        duplicate.select()
        self.docker.syncSelection()
        self.assertIsNone(self.docker.editShapeName)
        self.assertEqual(self.docker.addOnPage.text(), "Add on Page")
        self.assertEqual(layer.items, [original, duplicate])
        self.warn.assert_not_called()

    def test_existing_layer_import_failure_preserves_original_bubbles(self):
        document, layer, group = self.editTarget()
        self.docker.startNewBubble()
        self.docker.addDestination.setCurrentIndex(1)
        layer.fail_import = True
        self.docker.addOnPageShape()
        self.assertEqual(layer.items, [group])
        self.assertFalse(getattr(layer, "removed", False))
        self.assertEqual(len(document.layers), 1)
        self.warn.assert_called_once()

    def test_locked_existing_layer_is_not_modified(self):
        document, layer, group = self.editTarget()
        self.docker.startNewBubble()
        self.docker.addDestination.setCurrentIndex(1)
        layer.is_locked = True
        self.docker.addOnPageShape()
        self.assertEqual(layer.items, [group])
        self.assertEqual(len(document.layers), 1)
        self.warn.assert_called_once()

    def test_existing_destination_rejects_a_non_vector_layer(self):
        document, layer, group = self.editTarget()
        self.docker.startNewBubble()
        self.docker.addDestination.setCurrentIndex(1)
        with patch.object(layer, "type", return_value="paintlayer"):
            self.docker.addOnPageShape()
        self.assertEqual(layer.items, [group])
        self.assertEqual(len(document.layers), 1)
        self.warn.assert_called_once()

    def test_existing_layer_grouping_failure_removes_only_the_imported_shapes(self):
        document, layer, group = self.editTarget()
        self.docker.startNewBubble()
        self.docker.addDestination.setCurrentIndex(1)
        with patch.object(self.docker.gateway, "bubble_group", return_value=None):
            self.docker.addOnPageShape()
        self.assertEqual(layer.items, [group])
        self.assertFalse(getattr(layer, "removed", False))
        self.warn.assert_called_once()

    def test_add_places_whole_bubble_on_page_and_saves_settings(self):
        document = FakeDocument(None)
        FakeKrita.document = document
        self.docker.tailSpinBox.setValue(60)
        self.docker.tailAngle = -2.4
        self.docker.addOnPageShape()
        self.assertEqual(len(document.layer.items), 1)
        bounds = document.layer.items[0].boundingBox()
        self.assertGreaterEqual(bounds.left(), 0)
        self.assertGreaterEqual(bounds.top(), 0)
        self.assertTrue(document.annotation(self.docker.annotationKey(document.layer)))
        self.assertEqual(self.docker.addOnPage.text(), "Update on Page")
        self.warn.assert_not_called()

    def test_updates_preserve_canvas_transform_across_repeated_edits(self):
        document, layer, group = self.editTarget()
        delta = QTransform().translate(230, 80).rotate(25).scale(1.7, 0.8)
        group.setTransformation(group.transformation() * delta)
        for style, angle in (("Oval", -2.3), ("Shouting", 0.7), ("Thought", 2.6)):
            self.docker.bubbleType.setCurrentText(style)
            self.docker.tailAngle = angle
            self.docker.tailSpinBox.setValue(60)
            self.docker.updateBubble()
            self.assertEqual(len(layer.items), 1)
            inverse, ok = self.docker.editBaseline.inverted()
            actual = inverse * layer.items[0].transformation()
            for point in (QPointF(), QPointF(100, 50)):
                self.assertLess((actual.map(point) - delta.map(point)).manhattanLength(), 1e-6)
        self.warn.assert_not_called()

    def test_one_update_invalidates_old_imported_and_new_canvas_bounds(self):
        document, layer, group = self.editTarget()
        group.setTransformation(group.transformation() * QTransform.fromTranslate(900, 500))
        old_bounds = group.boundingBox()
        document.events.clear()
        self.docker.bubbleText.setPlainText("A much wider updated speech bubble")
        self.docker.updateBubble()
        events = document.events
        dirty = next(event[1] for event in events if isinstance(event, tuple))
        self.assertTrue(dirty.contains(old_bounds))
        self.assertTrue(dirty.contains(layer.items[0].boundingBox()))
        self.assertLess(events.index("transform"), events.index("shape-update"))
        self.assertLess(events.index("shape-update"), events.index("wait"))
        self.assertLess(events.index("remove"), events.index("wait"))
        self.assertLess(events.index("wait"), events.index("projection"))
        self.assertEqual(events.count("projection"), 1)

    def test_canvas_background_is_on_by_default_and_can_be_refreshed(self):
        image = QImage(800, 600, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        with patch("krita_speech_bubble_generator.krita_host.gateway.canvas_snapshot",
                   return_value=(image, QRectF(0, 0, 800, 600))) as snapshot:
            document, layer, group = self.editTarget()
            self.assertTrue(self.docker.canvasBackground.isChecked())
            self.assertFalse(self.docker.preview.background.isNull())
            self.assertEqual(snapshot.call_count, 1)
            self.docker.refreshBackground.click()
            self.assertEqual(snapshot.call_count, 2)
            self.docker.updateBubble()
            self.assertEqual(snapshot.call_count, 2)
            self.docker.canvasBackground.setChecked(False)
            self.assertTrue(self.docker.preview.background.isNull())
        self.warn.assert_not_called()

    def test_failed_canvas_background_is_reported_and_disabled(self):
        self.editTarget()
        with patch("krita_speech_bubble_generator.krita_host.gateway.canvas_snapshot",
                   side_effect=ValueError("Snapshot failed")):
            self.docker.refreshBackground.click()
        self.assertFalse(self.docker.canvasBackground.isChecked())
        self.assertFalse(self.docker.refreshBackground.isEnabled())
        self.assertTrue(self.docker.preview.background.isNull())
        self.warn.assert_called_once()

    def test_canvas_moves_follow_the_bubble_and_debounce_background_snapshots(self):
        document, layer, group = self.editTarget()
        group.select()
        self.docker.syncSelection()
        self.snapshot.reset_mock()
        before = QTransform(self.docker.preview.bubble_transform)
        for amount in (30, 60, 90):
            transform = group.transformation() * QTransform().translate(amount, 25).rotate(5)
            group.setTransformation(transform)
            self.docker.syncSelection()
            expected = canvas_transform(document, self.docker.editBaseline, group)
            self.assertEqual(self.docker.preview.bubble_transform, expected)
        self.assertNotEqual(before, self.docker.preview.bubble_transform)
        self.snapshot.assert_not_called()
        self.assertTrue(self.docker.backgroundTimer.isActive())
        QTest.qWait(320)
        self.snapshot.assert_called_once_with(document, layer, SHAPE_NAME)
        self.assertFalse(self.docker.backgroundTimer.isActive())
        self.assertFalse(self.docker.liveTimer.isActive())
        self.assertEqual(layer.items, [group])
        self.warn.assert_not_called()

    def test_native_movement_is_detected_without_selection_changes(self):
        document, layer, group = self.editTarget()
        group.select()
        self.docker.syncSelection()
        self.snapshot.reset_mock()
        group.setTransformation(group.transformation() * QTransform.fromTranslate(170, 80))
        self.docker.selectionTimer.start()
        QTest.qWait(200)
        expected = canvas_transform(document, self.docker.editBaseline, group)
        self.assertEqual(self.docker.preview.bubble_transform, expected)
        self.assertTrue(self.docker.backgroundTimer.isActive())
        self.assertEqual(layer.items, [group])
        self.warn.assert_not_called()

    def test_turning_background_off_cancels_the_pending_movement_refresh(self):
        document, layer, group = self.editTarget()
        self.snapshot.reset_mock()
        group.setTransformation(group.transformation() * QTransform.fromTranslate(70, 50))
        self.docker.syncSelection()
        self.assertTrue(self.docker.backgroundTimer.isActive())
        self.docker.canvasBackground.setChecked(False)
        QTest.qWait(320)
        self.snapshot.assert_not_called()
        self.assertFalse(self.docker.backgroundTimer.isActive())
        self.assertTrue(self.docker.preview.background.isNull())
        self.warn.assert_not_called()

    def test_switching_bubbles_cancels_the_old_movement_refresh(self):
        document, first, second = self.twoBubbles()
        group = first.items[0]
        group.setTransformation(group.transformation() * QTransform.fromTranslate(70, 50))
        self.docker.syncSelection()
        self.assertTrue(self.docker.backgroundTimer.isActive())
        self.snapshot.reset_mock()
        group.deselect()
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.syncSelection()
        QTest.qWait(320)
        self.snapshot.assert_called_once_with(document, second, SHAPE_NAME)
        self.assertFalse(self.docker.backgroundTimer.isActive())
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.warn.assert_not_called()

    def test_background_timer_defers_snapshot_while_bubble_is_being_regenerated(self):
        document, layer, group = self.editTarget()
        self.snapshot.reset_mock()
        self.docker.updating = True
        try:
            self.docker.refreshMovedBackground()
        finally:
            self.docker.updating = False
        self.snapshot.assert_not_called()
        self.assertTrue(self.docker.backgroundTimer.isActive())
        self.docker.refreshMovedBackground()
        self.snapshot.assert_called_once_with(document, layer, SHAPE_NAME)
        self.warn.assert_not_called()

    def test_movement_timer_that_observes_a_new_selection_does_not_capture_twice(self):
        document, first, second = self.twoBubbles()
        self.snapshot.reset_mock()
        first.items[0].deselect()
        second.items[0].select()
        document.setActiveNode(second)
        self.docker.refreshMovedBackground()
        self.snapshot.assert_called_once_with(document, second, SHAPE_NAME)
        self.assertEqual(self.docker.editLayerId, second.uniqueId())
        self.warn.assert_not_called()

    def test_new_controls_still_fit_a_compact_dock(self):
        self.docker.resize(440, 1000)
        self.docker.show()
        APP.processEvents()
        scroll = self.docker.widget()
        self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())

    def test_text_input_can_be_resized_by_dragging_handle(self):
        handle = self.docker.textResizeHandle
        self.docker.show()
        APP.processEvents()
        initial = self.docker.bubbleText.height()
        start = handle.rect().center()
        target = start + QPoint(0, 70)
        QTest.mousePress(handle, Qt.LeftButton, pos=start)
        QTest.mouseMove(handle, target)
        QTest.mouseRelease(handle, Qt.LeftButton, pos=target)
        self.assertGreater(self.docker.bubbleText.height(), initial)

    def test_speech_panel_tracks_input_height_without_stretching(self):
        self.docker.resize(440, 1600)
        self.docker.show()
        APP.processEvents()
        handle = self.docker.textResizeHandle
        editor = self.docker.bubbleText
        group = self.docker.speechGroup
        initial_height = editor.height()
        initial_group_height = group.height()
        self.assertEqual(initial_group_height, group.sizeHint().height())
        for delta in (100, -140):
            start = handle.rect().center()
            QTest.mousePress(handle, Qt.LeftButton, pos=start)
            QTest.mouseMove(handle, start + QPoint(0, delta))
            QTest.mouseRelease(handle, Qt.LeftButton, pos=start + QPoint(0, delta))
            QTest.qWait(10)
            self.assertEqual(group.height(), group.sizeHint().height())
            self.assertEqual(group.height() - initial_group_height,
                             editor.height() - initial_height)
        self.assertLess(editor.height(), initial_height)
        self.docker.autocenter.setChecked(False)
        QTest.qWait(10)
        self.assertEqual(group.height(), group.sizeHint().height())
        self.docker.autocenter.setChecked(True)
        QTest.qWait(10)
        self.assertEqual(group.height(), group.sizeHint().height())

    def test_spare_dock_height_does_not_stretch_preview_or_upper_controls(self):
        self.docker.resize(440, 1800)
        self.docker.show()
        QTest.qWait(10)
        controls = (self.docker.addOnPage, self.docker.addDestination,
                    self.docker.editStatus, self.docker.preview)
        original = [control.geometry() for control in controls]
        self.assertEqual(self.docker.preview.height(), 220)
        self.assertEqual(self.docker.editStatus.height(),
                         self.docker.editStatus.sizeHint().height())
        self.docker.resize(440, 2400)
        QTest.qWait(10)
        self.assertEqual([control.geometry() for control in controls], original)
        handle = self.docker.textResizeHandle
        for delta in (150, -190):
            start = handle.rect().center()
            QTest.mousePress(handle, Qt.LeftButton, pos=start)
            QTest.mouseMove(handle, start + QPoint(0, delta))
            QTest.mouseRelease(handle, Qt.LeftButton, pos=start + QPoint(0, delta))
            QTest.qWait(10)
            self.assertEqual([control.geometry() for control in controls], original)
        self.docker.bubbleText.setPlainText("\n".join(["A tall bubble"] * 30))
        QTest.qWait(10)
        self.assertEqual([control.geometry() for control in controls], original)
        self.assertLessEqual(self.docker.widget().widget().width(),
                             self.docker.widget().viewport().width())

    def test_failed_import_preserves_original(self):
        document, layer, group = self.editTarget()
        layer.fail_import = True
        self.docker.updateBubble()
        self.assertEqual(layer.items, [group])
        self.warn.assert_called_once()

    def test_protected_and_unrelated_layers_are_not_overwritten(self):
        document, layer, group = self.editTarget()
        layer.is_locked = True
        self.docker.updateBubble()
        layer.is_locked = False
        group.setName("User's other artwork")
        self.docker.updateBubble()
        FakeKrita.document = FakeDocument(FakeLayer())
        self.docker.updateBubble()
        self.assertEqual(layer.items, [group])
        self.assertEqual(self.warn.call_count, 3)

    def test_missing_document_and_invalid_metadata_show_warnings(self):
        self.docker.addOnPageShape()
        document, layer, group = self.editTarget()
        key = self.docker.annotationKey(layer)
        for data in (b"{", b"[]", b'{"version":2}', b"\xff"):
            document.annotations[key] = QByteArray(data)
            self.docker.loadSelectedBubble()
        self.assertEqual(self.warn.call_count, 5)


if __name__ == "__main__":
    unittest.main()
