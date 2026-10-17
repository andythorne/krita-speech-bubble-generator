from dataclasses import replace
import math
import os
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath
from PyQt5.QtWidgets import QApplication

from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, bubble_path, outline_anchor, path_data, tail_tip,
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
        self.assertEqual(automatic_speech_lines("aa bb cc dd ee", 11, len),
                         ["aa bb cc", "dd ee"])
        self.assertEqual(automatic_speech_lines("\n", 10, len), ["", ""])
        self.assertEqual(get_speech_lines("", 1), [""])
        self.assertEqual(automatic_speech_lines("unbreakable", 2, len),
                         ["unbreakable"])

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
                        settings.font_size * settings.padding / 100),
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
            anchor = outline_anchor(geometry.body, center, direction)
            for distance, expected in ((37.2, 37), (37.8, 38), (-2, 0), (10000, 180)):
                with self.subTest(style=style, distance=distance):
                    result = self.renderer.move_tail(settings, anchor + direction * distance)
                    self.assertEqual(result.tail_length, expected)
                    self.assertAlmostEqual(result.tail_angle, 0.37)

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
