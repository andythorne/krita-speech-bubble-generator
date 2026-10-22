"""Recovery is deliberately limited to one original-style bubble per layer."""

import math
import unittest

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QTransform

from legacy_fixture import NORTH_PATH, legacy_corner_path, legacy_svg
from krita_speech_bubble_generator.bubbles.settings import SettingsError
from krita_speech_bubble_generator.krita_host.legacy import read_legacy_bubble


class LegacyBubbleTests(unittest.TestCase):
    def test_recovers_appearance_and_joins_text_for_automatic_centering(self):
        bubble = read_legacy_bubble(legacy_svg())
        settings = bubble.settings
        self.assertEqual(settings.text, "First & second A bold word")
        self.assertEqual(settings.font, "Sans Serif")
        self.assertEqual(settings.font_size, 14)
        self.assertEqual((settings.shape, settings.style), ("Oval", "Sharp"))
        self.assertEqual((settings.fill, settings.stroke, settings.text_color),
                         ("#ffffff", "#112233", "#334455"))
        self.assertEqual(settings.outline, 3)
        self.assertTrue(settings.autocenter)
        self.assertEqual(settings.padding, 0)
        self.assertEqual(settings.line_length, 0)
        self.assertEqual(settings.tail_length, 10)
        self.assertEqual(bubble.tip, QPointF(123, 0))
        self.assertAlmostEqual(settings.tail_angle, math.atan2(-51, -0.5))
        self.assertEqual(bubble.body, QRectF(0, 10, 247, 82))
        self.assertEqual(bubble.shape_count, 3)

    def test_corner_tail_retains_original_tip_and_uses_the_body_center_direction(self):
        for horizontal in (-1, 1):
            for vertical in (-1, 1):
                bubble = read_legacy_bubble(legacy_svg(
                    path=legacy_corner_path(horizontal, vertical)))
                self.assertEqual(bubble.body, QRectF(0, 0, 240, 100))
                expected = QPointF(260 if horizontal > 0 else -20,
                                  -20 if vertical < 0 else 120)
                self.assertEqual(bubble.tip, expected)
                offset = expected - bubble.body.center()
                self.assertAlmostEqual(bubble.settings.tail_angle,
                                       math.atan2(offset.y(), offset.x()))
                self.assertNotAlmostEqual(abs(bubble.settings.tail_angle), math.pi / 4)

    def test_joins_embedded_line_breaks_and_blank_lines_with_single_spaces(self):
        svg = legacy_svg().replace("First &amp; second", " First\n &amp;  second ").replace(
            ">A ", ">\n A ")
        settings = read_legacy_bubble(svg).settings
        self.assertEqual(settings.text, "First & second A bold word")
        self.assertTrue(settings.autocenter)

    def test_recovers_curved_tail_directions_and_no_tail(self):
        paths = (
            ("M156 0C246 0 291 18 291 55C291 92 246 110 156 110"
             "C66 110 21 94 21 63L0 55L21 47C21 16 66 0 156 0Z", math.pi, 21),
            ("M146 0C237 0 283 14 283 41C283 68 237 82 146 82"
             "C110 82 78 79 51 74L0 92L37 70C19 62 10 52 10 41"
             "C10 14 55 0 146 0Z", None, 14),
            ("M123 0C206 0 247 14 247 41C247 68 206 82 123 82"
             "C41 82 0 68 0 41C0 14 41 0 123 0Z", None, 0),
        )
        for path, angle, length in paths:
            with self.subTest(length=length):
                settings = read_legacy_bubble(legacy_svg(path=path)).settings
                self.assertEqual(settings.tail_length, length)
                if angle is not None:
                    self.assertAlmostEqual(settings.tail_angle, angle)
                elif length:
                    self.assertGreater(settings.tail_angle, math.pi / 2)

    def test_recovers_unsaved_quadratic_and_square_upstream_paths(self):
        rounded = "M123 10Q247 10 247 51Q247 92 123 92Q0 92 0 51Q0 10 123 10Z"
        square = "M123 10L247 10L247 51L247 92L123 92L0 92L0 51L0 10L123 10Z"
        for path in (rounded, square):
            with self.subTest(path=path):
                settings = read_legacy_bubble(legacy_svg(path=path)).settings
                self.assertEqual((settings.shape, settings.style), ("Oval", "Sharp"))
                self.assertEqual(settings.tail_length, 0)

    def test_placement_preserves_rotated_scaled_and_translated_body(self):
        transform = QTransform().scale(0.4, 0.7).rotate(28).translate(100, 200)
        matrix = "matrix({} {} {} {} {} {})".format(
            transform.m11(), transform.m12(), transform.m21(), transform.m22(),
            transform.dx(), transform.dy())
        bubble = read_legacy_bubble(legacy_svg(transform=matrix, text_transform=matrix))
        generated = QRectF(0, 0, 300, 140)
        placement = bubble.placement(generated)
        for before, after in ((generated.center(), bubble.body.center()),
                              (generated.topLeft(), bubble.body.topLeft()),
                              (generated.bottomRight(), bubble.body.bottomRight())):
            self.assertLess((placement.map(before) - transform.map(after)).manhattanLength(),
                            1e-6)

    def test_rejects_other_artwork_groups_multiple_outlines_and_unsupported_paths(self):
        for svg in (
            "", "<svg/>", "<svg><text>Not a bubble</text></svg>",
            legacy_svg(extra='<rect width="100" height="100"/>'),
            legacy_svg(extra='<path d="' + NORTH_PATH + '"/>'),
            legacy_svg().replace("<defs/>", "<defs/><g>").replace("</svg>", "</g></svg>"),
            legacy_svg(path="M0 0A10 10 0 0 1 20 20Z"),
            legacy_svg(path="M0 0L1 0L1 1Z M2 2L3 2L3 3Z"),
            legacy_svg(path=NORTH_PATH.replace("L123 0", "L123 0L125 0")),
            legacy_svg().replace('stroke-linejoin="round"', 'stroke-linejoin="miter"'),
        ):
            with self.subTest(svg=svg[:80]):
                with self.assertRaises(SettingsError):
                    read_legacy_bubble(svg)

    def test_rejects_misaligned_text_bad_settings_and_noninvertible_transforms(self):
        for svg in (
            legacy_svg(text_transform="matrix(1 0 0 1 0 0)"),
            legacy_svg(transform="matrix(0 0 0 0 0 0)"),
            legacy_svg(transform="rotate(45)"),
            legacy_svg().replace('x="147" y="71"', 'x="999" y="71"'),
            legacy_svg().replace('y="71"', 'y="12"'),
            legacy_svg().replace("font-size: 14", "font-size: 14.5"),
            legacy_svg().replace('fill="#ffffff"', 'fill="url(#gradient)"'),
            legacy_svg().replace('stroke-width="3"', 'stroke-width="nan"'),
            legacy_svg().replace("L123 0", "L1e999 0"),
        ):
            with self.subTest(svg=svg[:80]):
                with self.assertRaises(SettingsError):
                    read_legacy_bubble(svg)
