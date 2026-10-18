from dataclasses import replace
import math
import os
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QFont, QFontMetricsF, QPainterPath
from PyQt5.QtWidgets import QApplication

from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, bubble_path, path_data, tail_anchor, tail_tip,
)
from krita_speech_bubble_generator.bubbles.registry import BUBBLE_TYPES
from krita_speech_bubble_generator.bubbles.renderer import (
    BubbleRenderer, Geometry, RenderResult, automatic_speech_lines, get_speech_lines,
)
from krita_speech_bubble_generator.bubbles.settings import BubbleSettings
from krita_speech_bubble_generator.bubbles.types import BubbleType


APP = QApplication.instance() or QApplication([])
SVG = "{http://www.w3.org/2000/svg}"


class BubbleRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = BubbleRenderer()
        self.settings = BubbleSettings(
            text='One & two <three>\n\nA longer last line',
            font="DejaVu Sans", font_size=18, autocenter=False,
            line_length=12, shout_seed=17, thought_seed=99)

    def test_wrapping_preserves_paragraphs_and_balances_automatic_lines(self):
        self.assertEqual(get_speech_lines(" alpha   beta\n\nlongword ", 0),
                         [" alpha   beta", "", "longword "])
        self.assertEqual(get_speech_lines("alpha beta gamma\n\nlongword", 8),
                         ["alpha", "beta", "gamma", "", "longword"])
        self.assertEqual(automatic_speech_lines("aa bb cc dd ee"),
                         ["aa bb cc", "dd ee"])
        self.assertEqual(automatic_speech_lines("\n"), ["", ""])
        self.assertEqual(get_speech_lines("", 1), [""])
        self.assertEqual(automatic_speech_lines("unbreakable"),
                         ["unbreakable"])

    def test_automatic_wrapping_matches_original_example_independent_of_font_and_size(self):
        text = "Rogudator's speech bubble generator!"
        expected = ["Rogudator's", "speech bubble", "generator!"]
        self.assertEqual(automatic_speech_lines(text), expected)
        for font in ("DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono"):
            for size in (8, 14, 35, 99):
                with self.subTest(font=font, size=size):
                    geometry = self.renderer.geometry(replace(
                        self.settings, text=text, font=font, font_size=size, autocenter=True))
                    self.assertEqual(geometry.lines, expected)
        self.assertEqual(automatic_speech_lines("Hello\n\nworld"), ["Hello", "", "world"])

    def test_named_geometry_matches_direct_type_and_tail_api(self):
        for style in BUBBLE_TYPES:
            with self.subTest(style=style):
                settings = replace(self.settings, style=style, tail_length=43,
                                   thought_irregularity=79, shout_irregularity=61)
                result = self.renderer.geometry(settings)
                self.assertIsInstance(result, Geometry)
                self.assertIs(result.body_rect, result[0])
                thought = BUBBLE_TYPES[style].capabilities.thought
                body = body_path(
                    result.body_rect, style,
                    min(settings.font_size * 3,
                        BUBBLE_TYPES[style].enclosure_padding(settings)),
                    settings.thought_irregularity if thought else settings.shout_irregularity,
                    settings.thought_seed if thought else settings.shout_seed,
                    settings.shout_shape,
                    settings.thought_nodes if thought else settings.shout_nodes)
                self.assertEqual(path_data(result.body), path_data(body))
                self.assertEqual(result.tip, tail_tip(
                    body, result.body_rect.center(), settings.tail_angle, 43))
                self.assertEqual(result.path, bubble_path(
                    body, result.body_rect.center(), result.tip, style,
                    settings.font_size, settings.thought_size,
                    settings.thought_irregularity, settings.thought_seed))
                self.assertTrue(result.body_rect.contains(result.text_rect))

    def test_original_text_measurements_and_line_spacing_in_preview_and_export(self):
        for size in (1, 14, 18, 35, 99):
            with self.subTest(size=size):
                settings = replace(self.settings, text="AVATAR To Wa\n\nThird line",
                                   font_size=size, line_length=0)
                font = QFont(settings.font)
                font.setPixelSize(int(size * 1.3))
                metrics = QFontMetricsF(font)
                geometry = self.renderer.geometry(settings)
                self.assertEqual(geometry.text_rect.width(), max(
                    metrics.horizontalAdvance(line) for line in geometry.lines))
                self.assertEqual(geometry.text_rect.height(),
                                 metrics.capHeight() + 2 * size)
                rendered_text = []
                for preview in (False, True):
                    root = ET.fromstring(self.renderer.render(settings, preview).svg)
                    nodes = list(root.iter(SVG + "text"))
                    self.assertEqual([node.text or "" for node in nodes],
                                     ["AVATAR To Wa", "", "Third line"])
                    for index, node in enumerate(nodes):
                        self.assertEqual(float(node.attrib["font-size"]), size)
                        self.assertEqual(float(node.attrib["y"]),
                                         geometry.text_rect.top() +
                                         metrics.capHeight() + index * size)
                        self.assertNotIn("letter-spacing", node.attrib)
                        self.assertNotIn("word-spacing", node.attrib)
                    rendered_text.append([node.attrib for node in nodes])
                self.assertEqual(*rendered_text)

    def test_preview_and_export_use_same_path_and_different_frames(self):
        settings = replace(self.settings, tail_length=140, tail_angle=-math.pi)
        geometry = self.renderer.geometry(settings)
        preview = self.renderer.render(settings, preview=True)
        exported = self.renderer.render(settings)
        self.assertIsInstance(exported, RenderResult)
        self.assertEqual(exported.view_box, geometry.body_rect)
        self.assertEqual(preview.view_box,
                         geometry.path.boundingRect().adjusted(-8, -8, 8, 8))
        preview_root, export_root = ET.fromstring(preview.svg), ET.fromstring(exported.svg)
        self.assertEqual(preview_root.find(".//" + SVG + "path").attrib,
                         export_root.find(".//" + SVG + "path").attrib)
        self.assertEqual(export_root.find(SVG + "g").attrib["id"], "rsbg-bubble")
        self.assertEqual([node.text or "" for node in export_root.iter(SVG + "text")],
                         geometry.lines)

    def test_preview_margin_accounts_for_outline(self):
        settings = replace(self.settings, outline=50)
        geometry = self.renderer.geometry(settings)
        preview = self.renderer.render(settings, preview=True)
        self.assertEqual(preview.view_box,
                         geometry.path.boundingRect().adjusted(-27, -27, 27, 27))

    def test_oval_is_fuller_and_encloses_short_long_and_multiline_text(self):
        for text in ("Hi", "A very long unwrapped line of dialogue", "One\nTwo\nThree", ""):
            for padding in (0, 10, 150, 300):
                with self.subTest(text=text, padding=padding):
                    geometry = self.renderer.geometry(replace(
                        self.settings, text=text, line_length=0, padding=padding))
                    rect = geometry.body_rect
                    self.assertLessEqual(rect.width() / rect.height(), 2 + 1e-9)
                    inset = geometry.text_rect.adjusted(0.01, 0.01, -0.01, -0.01)
                    if geometry.text_rect.width() == 0:
                        inset.setLeft(geometry.text_rect.center().x())
                        inset.setRight(geometry.text_rect.center().x())
                    for corner in (inset.topLeft(), inset.topRight(),
                                   inset.bottomLeft(), inset.bottomRight()):
                        self.assertTrue(geometry.body.contains(corner))

    def test_horizontal_padding_shrinks_more_than_vertical_padding_for_every_style(self):
        for style in BUBBLE_TYPES:
            with self.subTest(style=style):
                settings = replace(self.settings, style=style, text="Hi", line_length=0)
                large = self.renderer.geometry(replace(settings, padding=150))
                small = self.renderer.geometry(replace(settings, padding=50))
                dx = large.body_rect.width() - small.body_rect.width()
                dy = large.body_rect.height() - small.body_rect.height()
                self.assertGreater(dx, dy)
                self.assertEqual(large.text_rect.size(), small.text_rect.size())
                self.assertEqual(large.lines, small.lines)

    def test_non_oval_zero_padding_retains_spacing_clear_of_the_outline(self):
        for style in ("Rounded", "Square", "Thought", "Shouting"):
            for size, outline in ((1, 0), (14, 3), (35, 50)):
                with self.subTest(style=style, size=size, outline=outline):
                    settings = replace(
                        self.settings, style=style, text="Zero padding\nStill readable",
                        padding=0, font_size=size, outline=outline)
                    geometry = self.renderer.geometry(settings)
                    clearance = size * 0.5 + outline / 2
                    inset = geometry.text_rect.adjusted(0.01, 0.01, -0.01, -0.01)
                    for corner in (inset.topLeft(), inset.topRight(),
                                   inset.bottomLeft(), inset.bottomRight()):
                        for step in range(32):
                            angle = step * math.pi / 16
                            point = corner + QPointF(math.cos(angle), math.sin(angle)) * clearance
                            self.assertTrue(geometry.body.contains(point))
                    if style == "Rounded":
                        self.assertGreater(BUBBLE_TYPES[style].body_parameters(
                            settings).corner_radius, 0)

    def test_zero_tail_handle_is_preview_only_and_obeys_lock(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                settings = replace(self.settings, tail_length=0, lock_tail=locked)
                geometry = self.renderer.geometry(settings)
                self.assertIsNone(geometry.tip)
                self.assertEqual(geometry.path, geometry.body)
                self.assertIsNone(self.renderer.render(settings).tip)
                preview_tip = self.renderer.render(settings, preview=True).tip
                if locked:
                    self.assertIsNone(preview_tip)
                else:
                    self.assertEqual(preview_tip, tail_tip(
                        geometry.body, geometry.body_rect.center(), settings.tail_angle, 0))

    def test_tail_edit_retains_body_origin_text_rect_and_pattern_seed(self):
        for style in BUBBLE_TYPES:
            with self.subTest(style=style):
                original = replace(self.settings, style=style, tail_length=43)
                geometry = self.renderer.geometry(original)
                moved = self.renderer.move_tail(
                    original, geometry.body_rect.center() + QPointF(-500, -200))
                result = self.renderer.geometry(moved)
                self.assertEqual(result.body_rect, geometry.body_rect)
                self.assertEqual(result.text_rect, geometry.text_rect)
                self.assertEqual(result.body, geometry.body)
                self.assertEqual(moved.tail_length, 43)
                self.assertEqual(moved.shout_seed, original.shout_seed)
                self.assertEqual(moved.thought_seed, original.thought_seed)
                self.assertAlmostEqual(moved.tail_angle, math.atan2(-200, -500))
                self.assertIs(self.renderer.move_tail(
                    original, geometry.body_rect.center()), original)

    def test_unlocked_tail_uses_outline_distance_rounding_and_font_limit(self):
        for style in BUBBLE_TYPES:
            settings = replace(self.settings, style=style, lock_tail=False)
            geometry = self.renderer.geometry(settings)
            center = geometry.body_rect.center()
            direction = QPointF(math.cos(0.37), math.sin(0.37))
            anchor = tail_anchor(geometry.body, center, direction)
            for distance, expected in ((37.2, 37), (37.8, 38), (10000, 180)):
                with self.subTest(style=style, distance=distance):
                    result = self.renderer.move_tail(settings, anchor + direction * distance)
                    self.assertEqual(result.tail_length, expected)
                    self.assertAlmostEqual(result.tail_angle, 0.37)
            result = self.renderer.move_tail(settings, center + QPointF(1, 0))
            self.assertEqual(result.tail_length, 0)

    def test_dragging_a_handle_without_moving_it_retains_its_angle_and_length(self):
        for style in BUBBLE_TYPES:
            for length in (0, 40):
                settings = replace(
                    self.settings, style=style, tail_length=length, lock_tail=False)
                geometry = self.renderer.geometry(settings)
                point = tail_tip(geometry.body, geometry.body_rect.center(),
                                 settings.tail_angle, length)
                self.assertIs(self.renderer.move_tail(settings, point), settings)

    def test_dragging_is_continuous_and_center_aligned_without_corner_or_spike_snapping(self):
        for style in BUBBLE_TYPES:
            for locked in (False, True):
                with self.subTest(style=style, locked=locked):
                    settings = replace(self.settings, style=style, tail_length=43,
                                       lock_tail=locked, font_size=35)
                    geometry = self.renderer.geometry(settings)
                    center = geometry.body_rect.center()
                    previous = None
                    for step in range(41):
                        point = QPointF(geometry.body.boundingRect().right() + 50,
                                        center.y() - 20 + step)
                        moved = self.renderer.move_tail(settings, point)
                        expected_angle = math.atan2(point.y() - center.y(),
                                                    point.x() - center.x())
                        self.assertAlmostEqual(moved.tail_angle, expected_angle)
                        if previous is not None:
                            self.assertGreater(moved.tail_angle, previous)
                            self.assertLess(moved.tail_angle - previous, 0.02)
                        previous = moved.tail_angle
                        result = self.renderer.geometry(moved)
                        offset = result.tip - center
                        pointer = point - center
                        self.assertAlmostEqual(
                            offset.x() * pointer.y() - offset.y() * pointer.x(), 0)
                        if locked:
                            self.assertEqual(moved.tail_length, 43)
                        else:
                            error = result.tip - point
                            self.assertLessEqual(math.hypot(error.x(), error.y()), 0.500001)
                        self.assertEqual(result.body, geometry.body)
                        self.assertEqual(result.text_rect, geometry.text_rect)

    def test_text_and_tail_edits_do_not_consume_global_random_state(self):
        settings = replace(self.settings, style="Shouting", shout_shape="Expressive")
        import random
        before = random.getstate()
        self.renderer.render(settings, preview=True)
        self.renderer.render(replace(settings, text="New text", tail_angle=-1,
                                     tail_length=91))
        self.assertEqual(random.getstate(), before)

    def test_new_bubble_type_can_be_registered_without_renderer_changes(self):
        class CustomBubble(BubbleType):
            identifier = label = "Custom"

            def body_rect(self, width, height, padding):
                return QRectF(0, 0, 600, 300)

            def body_path(self, rect, parameters=None):
                path = QPainterPath()
                path.addRect(rect)
                return path

        bubble = CustomBubble()
        settings = replace(self.settings, style=bubble.identifier)
        with patch.dict(BUBBLE_TYPES, {bubble.identifier: bubble}):
            geometry = self.renderer.geometry(settings)
            self.assertEqual(geometry.body_rect, QRectF(0, 0, 600, 300))
            self.assertEqual(geometry.body, bubble.body_path(geometry.body_rect))
            self.assertIn("<svg", self.renderer.render(settings).svg)
        calls = []

        def resolve(style, algorithm):
            calls.append((style, algorithm))
            return bubble

        self.assertEqual(BubbleRenderer(resolve).geometry(self.settings).body_rect,
                         QRectF(0, 0, 600, 300))
        self.assertEqual(calls, [(self.settings.style, self.settings.shout_shape)])
