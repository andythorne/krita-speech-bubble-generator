from dataclasses import replace
import math
import os
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QByteArray, QPointF, QRectF
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication

from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, bubble_path, path_data, tail_anchor, tail_tip, oval_path,
)
from krita_speech_bubble_generator.bubbles.registry import (
    BUBBLE_TYPES, BUBBLE_STYLES, SHAPES, SHOUTING_ALGORITHMS, resolve_bubble,
)
from krita_speech_bubble_generator.bubbles.renderer import (
    BubbleRenderer, Geometry, RenderResult, automatic_speech_lines, get_speech_lines,
)
from krita_speech_bubble_generator.bubbles.settings import BubbleSettings, TextStyle
from krita_speech_bubble_generator.bubbles.text_runs import speech_runs
from krita_speech_bubble_generator.bubbles.types import BubbleType


APP = QApplication.instance() or QApplication([])
SVG = "{http://www.w3.org/2000/svg}"


def glyph_bounds(font, text):
    path = QPainterPath()
    path.addText(0, 0, font, text)
    return path.boundingRect()


def rendered_text_centroid_y(rendered):
    scale = 3
    box = rendered.view_box
    image = QImage(math.ceil(box.width() * scale), math.ceil(box.height() * scale),
                   QImage.Format_RGBA8888)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.scale(scale, scale)
    painter.translate(-box.left(), -box.top())
    QSvgRenderer(QByteArray(rendered.svg.encode())).render(painter, box)
    painter.end()
    pixels = image.constBits().asstring(image.sizeInBytes())
    weight = moment = 0
    for y in range(image.height()):
        row = pixels[y * image.bytesPerLine():(y + 1) * image.bytesPerLine()]
        ink = sum(max(0, row[x] - max(row[x + 1], row[x + 2]))
                  for x in range(0, image.width() * 4, 4))
        weight += ink
        moment += ink * (y + 0.5)
    if weight == 0:
        raise AssertionError("Expected red text in the rendered SVG")
    return moment / weight / scale + box.top()


class BubbleRendererTests(unittest.TestCase):
    def test_square_alignment_uses_shared_safe_edges_for_plain_and_rich_lines(self):
        text = "Wide lettering\nf\n\nlast"
        for style in BUBBLE_STYLES:
            for alignment in ("Left", "Center", "Right"):
                for styled in (False, True):
                    for optical in (False, True):
                        settings = BubbleSettings(
                            shape="Square", style=style, text=text, font="DejaVu Sans",
                            font_size=35, autocenter=False, padding=0,
                            text_alignment=alignment, optical_center=optical,
                            text_styles=(TextStyle(0, len(text), True, True),) if styled else ())
                        with self.subTest(style=style, alignment=alignment,
                                          styled=styled, optical=optical):
                            geometry = self.renderer.geometry(settings)
                            preview = ET.fromstring(self.renderer.render(settings, True).svg)
                            exported = ET.fromstring(self.renderer.render(settings).svg)
                            nodes = list(exported.iter(SVG + "text"))
                            self.assertEqual(
                                [ET.tostring(node) for node in preview.iter(SVG + "text")],
                                [ET.tostring(node) for node in nodes])
                            runs = speech_runs(settings, geometry.lines)
                            font = QFont(settings.font)
                            font.setPixelSize(settings.font_size)
                            font.setBold(styled)
                            font.setItalic(styled)
                            metrics = QFontMetricsF(font)
                            for node, line, row in zip(nodes, geometry.lines, runs):
                                x = float(node.attrib["x"])
                                y = float(node.attrib["y"])
                                advance = sum(metrics.horizontalAdvance(run.text) for run in row)
                                if node.attrib["text-anchor"] == "middle":
                                    x -= advance / 2
                                ink = glyph_bounds(font, line).translated(x, y)
                                if not ink.isEmpty():
                                    self.assertTrue(geometry.text_rect.adjusted(
                                        -1e-6, -1e-6, 1e-6, 1e-6).contains(ink))
                                left = min(x, ink.left()) if line else x
                                right = max(x + advance, ink.right()) if line else x
                                if alignment == "Left":
                                    self.assertAlmostEqual(left, geometry.text_rect.left())
                                elif alignment == "Right":
                                    self.assertAlmostEqual(right, geometry.text_rect.right())
                                else:
                                    self.assertAlmostEqual(x + advance / 2,
                                                           geometry.text_rect.center().x())

    def test_alignment_respects_wrapping_and_only_affects_capable_shapes(self):
        for shape in SHAPES:
            for automatic, length in ((True, 0), (False, 8), (False, 0)):
                settings = replace(self.settings, shape=shape, autocenter=automatic,
                                   line_length=length, wrapping="Diamond")
                centered = self.renderer.render(settings)
                lines = self.renderer.geometry(settings).lines
                for alignment in ("Left", "Right"):
                    variant = replace(settings, text_alignment=alignment)
                    actual = self.renderer.render(variant)
                    self.assertEqual(self.renderer.geometry(variant).lines, lines)
                    self.assertEqual(actual, BubbleRenderer().render(variant))
                    if not SHAPES[shape].capabilities.text_alignment:
                        self.assertEqual(actual, centered)
                self.assertEqual(self.renderer.render(settings), centered)
        for text in ("", "\n", "   "):
            for alignment in ("Left", "Right"):
                settings = BubbleSettings(shape="Square", text=text, text_alignment=alignment)
                self.assertTrue(QSvgRenderer(QByteArray(
                    self.renderer.render(settings).svg.encode())).isValid())

    def test_emphasis_survives_word_wrapping_whitespace_and_unicode(self):
        text = "\U0001f600\talpha   beta\n\nalpha beta"
        start = text.index("beta")
        for automatic, length in ((True, 0), (False, 8), (False, 0)):
            settings = replace(BubbleSettings(), text=text, autocenter=automatic,
                               line_length=length,
                               text_styles=(TextStyle(start, start + 4, True, True),))
            lines = self.renderer.geometry(settings).lines
            runs = speech_runs(settings, lines)
            self.assertEqual(["".join(run.text for run in row) for row in runs], lines)
            emphasized = [run.text for row in runs for run in row if run.bold]
            self.assertEqual(emphasized, ["beta"])
            exports = [ET.fromstring(self.renderer.render(settings, preview).svg)
                       for preview in (True, False)]
            text_nodes = [[ET.tostring(node) for node in root.iter(SVG + "text")]
                          for root in exports]
            self.assertEqual(*text_nodes)
            spans = list(exports[0].iter(SVG + "tspan"))
            bold = [span for span in spans if span.attrib["font-weight"] == "bold"]
            self.assertEqual([span.text for span in bold], ["beta"])
            self.assertEqual(bold[0].attrib["font-style"], "italic")

    def test_emphasis_sizing_includes_actual_formatted_ink_and_optical_centering(self):
        settings = replace(
            BubbleSettings(), text="Wide bold\nitalic f", font="DejaVu Sans",
            font_size=35, autocenter=False, padding=0, style="Square",
            text_styles=(TextStyle(0, 9, True), TextStyle(10, 18, False, True)))
        for optical in (False, True):
            styled = replace(settings, optical_center=optical)
            geometry = self.renderer.geometry(styled)
            runs = speech_runs(styled, geometry.lines)
            root = ET.fromstring(self.renderer.render(styled).svg)
            for node, row in zip(root.iter(SVG + "text"), runs):
                x = float(node.attrib["x"])
                y = float(node.attrib["y"])
                for run in row:
                    font = QFont(styled.font)
                    font.setPixelSize(styled.font_size)
                    font.setBold(run.bold)
                    font.setItalic(run.italic)
                    ink = glyph_bounds(font, run.text).translated(x, y)
                    if not ink.isEmpty():
                        self.assertTrue(geometry.text_rect.adjusted(
                            -1e-6, -1e-6, 1e-6, 1e-6).contains(ink))
                    x += QFontMetricsF(font).horizontalAdvance(run.text)
            self.assertTrue(QSvgRenderer(QByteArray(ET.tostring(root))).isValid())

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
        for style in BUBBLE_STYLES:
            with self.subTest(style=style):
                settings = replace(self.settings, style=style, tail_length=43,
                                   thought_irregularity=79, shout_irregularity=61)
                result = self.renderer.geometry(settings)
                self.assertIsInstance(result, Geometry)
                self.assertIs(result.body_rect, result[0])
                bubble = resolve_bubble(style, settings.shout_shape)
                contour = oval_path(result.body_rect)
                body = bubble.decorate(oval_path(result.body_rect),
                                       bubble.body_parameters(settings),
                                       lambda point: SHAPES[settings.shape].project(
                                           contour, point, settings))
                self.assertEqual(path_data(result.body), path_data(body))
                self.assertEqual(result.tip, tail_tip(
                    body, result.body_rect.center(), settings.tail_angle, 43))
                self.assertEqual(result.path, bubble_path(
                    body, result.body_rect.center(), result.tip, style,
                    settings.font_size, settings.thought_size,
                    settings.thought_irregularity, settings.thought_seed,
                    outline_width=settings.outline))
                self.assertTrue(result.body_rect.contains(result.text_rect))

    def test_measurements_match_rendered_font_size_and_preserve_line_spacing(self):
        for size in (1, 14, 18, 35, 99):
            with self.subTest(size=size):
                settings = replace(self.settings, text="AVATAR To Wa\n\nThird line",
                                   font_size=size, line_length=0)
                font = QFont(settings.font)
                font.setPixelSize(size)
                metrics = QFontMetricsF(font)
                geometry = self.renderer.geometry(settings)
                self.assertEqual(geometry.text_rect.width(), max(
                    max(metrics.horizontalAdvance(line),
                        metrics.horizontalAdvance(line) - 2 * glyph_bounds(font, line).left(),
                        2 * glyph_bounds(font, line).right() - metrics.horizontalAdvance(line))
                    for line in geometry.lines))
                top = min(-metrics.capHeight(), min(
                    index * size + glyph_bounds(font, line).top()
                    for index, line in enumerate(geometry.lines)))
                bottom = max(2 * size, max(
                    index * size + glyph_bounds(font, line).bottom()
                    for index, line in enumerate(geometry.lines)))
                self.assertEqual(geometry.text_rect.height(), bottom - top)
                rendered_text = []
                for preview in (False, True):
                    root = ET.fromstring(self.renderer.render(settings, preview).svg)
                    nodes = list(root.iter(SVG + "text"))
                    self.assertEqual([node.text or "" for node in nodes],
                                     ["AVATAR To Wa", "", "Third line"])
                    for index, node in enumerate(nodes):
                        self.assertEqual(float(node.attrib["font-size"]), size)
                        self.assertEqual(float(node.attrib["y"]),
                                         geometry.text_rect.top() - top + index * size)
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

    def test_thought_blob_counts_match_preview_export_and_preserve_body_and_placement(self):
        for advanced in (False, True):
            for curve in (0, 75):
                settings = replace(
                    self.settings, style="Thought", tail_length=100, tail_angle=0,
                    tail_advanced=advanced, tail_curve=curve, thought_irregularity=0)
                original = self.renderer.geometry(settings)
                for count in range(1, 11):
                    with self.subTest(advanced=advanced, curve=curve, count=count):
                        changed = replace(settings, thought_blobs=count)
                        geometry = self.renderer.geometry(changed)
                        self.assertEqual(len(geometry.path.toSubpathPolygons()), count + 1)
                        self.assertEqual(geometry.body, original.body)
                        self.assertEqual(geometry.text_rect, original.text_rect)
                        self.assertEqual(geometry.tip, original.tip)
                        preview, exported = [self.renderer.render(changed, preview)
                                             for preview in (True, False)]
                        self.assertEqual(preview.tail_start,
                                         self.renderer.render(settings, True).tail_start)
                        paths = [ET.fromstring(result.svg).find(".//" + SVG + "path").attrib
                                 for result in (preview, exported)]
                        self.assertEqual(*paths)
                        if count == 3:
                            self.assertEqual(geometry.path, original.path)
                disabled = self.renderer.geometry(replace(changed, tail_enabled=False))
                self.assertEqual(disabled.path, disabled.body)
        for style in ("Sharp", "Rounded", "Shouting"):
            settings = replace(self.settings, style=style, tail_length=100)
            self.assertEqual(self.renderer.render(settings),
                             self.renderer.render(replace(settings, thought_blobs=10)))

    def test_disabling_tail_removes_geometry_and_handles_without_clearing_settings(self):
        for style in BUBBLE_STYLES:
            for advanced in (False, True):
                with self.subTest(style=style, advanced=advanced):
                    settings = replace(
                        self.settings, style=style, tail_length=83, tail_advanced=advanced,
                        tail_start_angle=-0.5, tail_end_x=230, tail_end_y=-80, lock_tail=False)
                    before = self.renderer.render(settings, preview=True)
                    disabled = replace(settings, tail_enabled=False)
                    geometry = self.renderer.geometry(disabled)
                    self.assertEqual(geometry.path, geometry.body)
                    for preview in (False, True):
                        rendered = self.renderer.render(disabled, preview)
                        self.assertIsNone(rendered.tip)
                        self.assertIsNone(rendered.tail_start)
                    self.assertEqual(self.renderer.move_tail(disabled, QPointF(900, 400)), disabled)
                    self.assertEqual(
                        self.renderer.move_tail_start(disabled, QPointF(20, 0)), disabled)
                    self.assertEqual(self.renderer.render(
                        replace(disabled, tail_enabled=True), preview=True), before)

    def test_advanced_tail_points_are_independent_across_all_shapes_and_styles(self):
        for shape in SHAPES:
            for style in BUBBLE_STYLES:
                for locked in (False, True):
                    with self.subTest(shape=shape, style=style, locked=locked):
                        initial = replace(
                            self.settings, shape=shape, style=style, tail_length=85,
                            tail_angle=0.2, tail_advanced=True, lock_tail=locked)
                        before = self.renderer.geometry(initial)
                        center = before.body_rect.center()
                        moved = self.renderer.move_tail_start(initial, center + QPointF(80, -40))
                        after = self.renderer.geometry(moved)
                        start = self.renderer.render(moved, preview=True).tail_start
                        expected_start = tail_tip(
                            after.body, center, math.atan2(-40, 80), 0)
                        self.assertEqual(start, expected_start)
                        self.assertEqual(after.tip, before.tip)
                        self.assertNotEqual(after.path, before.path)
                        self.assertEqual(after.body, before.body)
                        self.assertEqual(after.text_rect, before.text_rect)
                        target = center + QPointF(220, -65)
                        moved_end = self.renderer.move_tail(moved, target)
                        rendered = self.renderer.render(moved_end, preview=True)
                        self.assertEqual(rendered.tip, target)
                        self.assertEqual(rendered.tail_start, start)
                        self.assertEqual((moved_end.tail_length, moved_end.lock_tail), (85, locked))
                        self.assertEqual((moved_end.shout_seed, moved_end.thought_seed),
                                         (initial.shout_seed, initial.thought_seed))

    def test_advanced_tail_clamps_inside_endpoints_and_supports_zero_simple_length(self):
        settings = replace(self.settings, tail_advanced=True, tail_length=0, lock_tail=True)
        geometry = self.renderer.geometry(settings)
        self.assertIsNotNone(geometry.tip)
        self.assertNotEqual(geometry.path, geometry.body)
        center = geometry.body_rect.center()
        for point in (center, center + QPointF(1, 0), center + QPointF(-1, -1)):
            with self.subTest(point=point):
                moved = self.renderer.move_tail(settings, point)
                rendered = self.renderer.render(moved, preview=True)
                self.assertFalse(geometry.body.contains(rendered.tip))
                self.assertGreater((rendered.tip - rendered.tail_start).manhattanLength(), 0)
                self.assertEqual(self.renderer.move_tail_start(moved, center), moved)
        moved = self.renderer.move_tail(settings, center + QPointF(220, 60))
        enlarged = replace(moved, font_size=99, text="A much bigger bubble", padding=300)
        enlarged_geometry = self.renderer.geometry(enlarged)
        self.assertFalse(enlarged_geometry.body.contains(enlarged_geometry.tip))

    def test_advanced_curves_share_preview_export_geometry_and_preserve_both_points(self):
        for style in BUBBLE_STYLES:
            for direction in ("Up", "Down"):
                with self.subTest(style=style, direction=direction):
                    settings = replace(
                        self.settings, style=style, tail_advanced=True, tail_length=85,
                        tail_angle=0.2, tail_start_angle=-0.5,
                        tail_end_x=200, tail_end_y=30)
                    straight = self.renderer.render(settings, preview=True)
                    curved = replace(settings, tail_curve=80, tail_curve_direction=direction)
                    preview = self.renderer.render(curved, preview=True)
                    exported = self.renderer.render(curved)
                    self.assertEqual(preview.tip, straight.tip)
                    self.assertEqual(preview.tail_start, straight.tail_start)
                    self.assertNotEqual(preview.svg, straight.svg)
                    roots = [ET.fromstring(result.svg) for result in (preview, exported)]
                    self.assertEqual(roots[0].find(".//" + SVG + "path").attrib,
                                     roots[1].find(".//" + SVG + "path").attrib)

    def test_switching_tail_modes_restores_each_placement(self):
        simple = replace(self.settings, tail_length=85)
        advanced = self.renderer.move_tail_start(
            replace(simple, tail_advanced=True), QPointF(800, 0))
        advanced = self.renderer.move_tail(advanced, QPointF(500, 160))
        simple_again = replace(advanced, tail_advanced=False)
        self.assertEqual(self.renderer.render(simple_again), self.renderer.render(simple))
        self.assertEqual(self.renderer.render(replace(simple_again, tail_advanced=True)),
                         self.renderer.render(advanced))

    def test_curves_preserve_body_text_tip_and_shared_preview_export_path(self):
        for style in BUBBLE_TYPES:
            settings = replace(self.settings, style=style, tail_length=100)
            straight = self.renderer.geometry(settings)
            for bend in ("Up", "Down"):
                with self.subTest(style=style, bend=bend):
                    curved = replace(settings, tail_curve=80, tail_curve_direction=bend)
                    geometry = self.renderer.geometry(curved)
                    self.assertEqual(geometry.body, straight.body)
                    self.assertEqual(geometry.body_rect, straight.body_rect)
                    self.assertEqual(geometry.text_rect, straight.text_rect)
                    self.assertEqual(geometry.lines, straight.lines)
                    self.assertEqual(geometry.tip, straight.tip)
                    self.assertNotEqual(geometry.path, straight.path)
                    self.assertEqual(geometry.path, bubble_path(
                        geometry.body, geometry.body_rect.center(), geometry.tip,
                        style, settings.font_size, settings.thought_size,
                        settings.thought_irregularity, settings.thought_seed, 80, bend,
                        outline_width=settings.outline))
                    preview = self.renderer.render(curved, preview=True)
                    exported = self.renderer.render(curved)
                    self.assertEqual(
                        ET.fromstring(preview.svg).find(".//" + SVG + "path").attrib,
                        ET.fromstring(exported.svg).find(".//" + SVG + "path").attrib)
                    self.assertTrue(preview.view_box.contains(geometry.path.boundingRect()))
                    moved = self.renderer.move_tail(curved, geometry.tip + QPointF(10, 20))
                    self.assertEqual(moved.tail_length, curved.tail_length)
                    self.assertEqual(moved.tail_curve, 80)
                    self.assertEqual(moved.tail_curve_direction, bend)

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

    def test_custom_oval_padding_is_independent_and_removes_the_aspect_ratio_cap(self):
        settings = replace(
            self.settings, text="Damn Kara looks\nso hot now...", line_length=0)
        original = self.renderer.geometry(settings)
        custom = replace(settings, oval_custom=True)
        generous = self.renderer.geometry(custom)
        tight = self.renderer.geometry(replace(custom, oval_vertical_padding=0))
        wider = self.renderer.geometry(replace(custom, padding=250))
        self.assertEqual(generous.body_rect.width(), tight.body_rect.width())
        self.assertEqual(generous.body_rect.height(), wider.body_rect.height())
        self.assertGreater(wider.body_rect.width(), generous.body_rect.width())
        self.assertLess(tight.body_rect.height(), generous.body_rect.height())
        self.assertLess(tight.body_rect.height(), original.body_rect.height())
        self.assertGreater(tight.body_rect.width() / tight.body_rect.height(), 2)
        for geometry in (generous, tight, wider):
            self.assertEqual(geometry.lines, original.lines)
            self.assertEqual(geometry.text_rect.size(), original.text_rect.size())

    def test_squared_oval_fits_text_with_less_extra_space_and_smooth_closed_curves(self):
        settings = replace(self.settings, oval_custom=True, oval_vertical_padding=0)
        ellipse = self.renderer.geometry(settings)
        squared = self.renderer.geometry(replace(settings, oval_squareness=100))
        self.assertLess(squared.body_rect.width(), ellipse.body_rect.width())
        self.assertLess(squared.body_rect.height(), ellipse.body_rect.height())
        self.assertEqual(squared.text_rect.size(), ellipse.text_rect.size())
        for index in range(1, squared.body.elementCount(), 3):
            self.assertTrue(squared.body.elementAt(index).isCurveTo())
        self.assertEqual(squared.body.boundingRect(), squared.body_rect)
        self.assertTrue(path_data(squared.body).endswith("Z"))

    def test_custom_oval_encloses_text_for_all_shapes_paddings_and_aspect_ratios(self):
        for text in ("Hi", "A very long unwrapped line of dialogue",
                     "One\nTwo\nThree\nFour\nFive", ""):
            for horizontal, vertical in ((0, 0), (150, 0), (0, 150), (300, 300)):
                for squareness in (0, 25, 50, 75, 100):
                    with self.subTest(text=text, horizontal=horizontal,
                                      vertical=vertical, squareness=squareness):
                        settings = replace(
                            self.settings, text=text, line_length=0, oval_custom=True,
                            padding=horizontal, oval_vertical_padding=vertical,
                            oval_squareness=squareness)
                        geometry = self.renderer.geometry(settings)
                        inset = geometry.text_rect.adjusted(0.01, 0.01, -0.01, -0.01)
                        if geometry.text_rect.width() == 0:
                            inset.setLeft(geometry.text_rect.center().x())
                            inset.setRight(geometry.text_rect.center().x())
                        for corner in (inset.topLeft(), inset.topRight(),
                                       inset.bottomLeft(), inset.bottomRight()):
                            self.assertTrue(geometry.body.contains(corner))

    def test_custom_options_do_not_affect_unsupported_or_disabled_styles(self):
        for style in BUBBLE_TYPES:
            settings = replace(self.settings, style=style)
            original = self.renderer.geometry(settings)
            changed = replace(settings, oval_vertical_padding=0, oval_squareness=100)
            geometry = self.renderer.geometry(changed)
            self.assertEqual(geometry.body_rect, original.body_rect)
            self.assertEqual(geometry.body, original.body)
            self.assertEqual(geometry.text_rect, original.text_rect)

    def test_thought_and_shouting_custom_padding_and_squareness_share_oval_sizing(self):
        for style in ("Thought", "Shouting"):
            with self.subTest(style=style):
                settings = replace(
                    self.settings, style=style, text="A long line of dialogue",
                    line_length=0, oval_custom=True, oval_vertical_padding=0)
                original = self.renderer.geometry(replace(settings, oval_custom=False))
                ellipse = self.renderer.geometry(settings)
                taller = self.renderer.geometry(replace(settings, oval_vertical_padding=150))
                wider = self.renderer.geometry(replace(settings, padding=300))
                squared = self.renderer.geometry(replace(settings, oval_squareness=100))
                self.assertEqual(ellipse.body_rect.width(), taller.body_rect.width())
                self.assertEqual(ellipse.body_rect.height(), wider.body_rect.height())
                self.assertGreater(taller.body_rect.height(), ellipse.body_rect.height())
                self.assertGreater(wider.body_rect.width(), ellipse.body_rect.width())
                self.assertGreater(ellipse.body_rect.width() / ellipse.body_rect.height(), 2)
                self.assertLess(squared.body_rect.width(), ellipse.body_rect.width())
                self.assertLess(squared.body_rect.height(), ellipse.body_rect.height())
                for geometry in (ellipse, taller, wider, squared):
                    self.assertEqual(geometry.lines, original.lines)
                    self.assertEqual(geometry.text_rect.size(), original.text_rect.size())
                oval = self.renderer.geometry(replace(settings, style="Oval"))
                self.assertEqual(ellipse.body_rect, oval.body_rect)

    def test_custom_clouds_and_all_shouting_algorithms_enclose_the_padded_text(self):
        variants = [("Thought", "Balanced")]
        variants.extend(("Shouting", algorithm) for algorithm in SHOUTING_ALGORITHMS)
        for style, algorithm in variants:
            for nodes in (8, 24, 64):
                for squareness in (0, 50, 100):
                    for text, horizontal, vertical in (
                            ("Wide dialogue with more words", 0, 0),
                            ("One\nTwo\nThree\nFour", 0, 150),
                            ("Hi", 150, 0)):
                        with self.subTest(style=style, algorithm=algorithm, nodes=nodes,
                                          squareness=squareness, text=text):
                            settings = replace(
                                self.settings, style=style, shout_shape=algorithm,
                                text=text, line_length=0, oval_custom=True,
                                padding=horizontal, oval_vertical_padding=vertical,
                                oval_squareness=squareness,
                                thought_nodes=nodes, shout_nodes=nodes,
                                thought_irregularity=100, shout_irregularity=100,
                                thought_seed=17, shout_seed=17)
                            geometry = self.renderer.geometry(settings)
                            dx = settings.font_size * horizontal / 100 * 2
                            dy = settings.font_size * vertical / 100
                            padded = QPainterPath()
                            padded.addRect(geometry.text_rect.adjusted(
                                -dx + 0.01, -dy + 0.01, dx - 0.01, dy - 0.01))
                            self.assertTrue(geometry.body.contains(padded))
                            self.assertEqual(self.renderer.geometry(settings).body,
                                             geometry.body)

    def test_custom_shapes_use_actual_outline_for_locked_and_dragged_tails(self):
        variants = [("Oval", "Balanced"), ("Thought", "Balanced")]
        variants.extend(("Shouting", algorithm) for algorithm in SHOUTING_ALGORITHMS)
        for style, algorithm in variants:
            with self.subTest(style=style, algorithm=algorithm):
                self._assert_custom_shape_tail_geometry(style, algorithm)

    def _assert_custom_shape_tail_geometry(self, style, algorithm):
        for squareness in (0, 50, 100):
            for locked in (False, True):
                settings = replace(
                    self.settings, style=style, shout_shape=algorithm,
                    text="Wide dialogue", line_length=0, oval_custom=True,
                    oval_vertical_padding=0, oval_squareness=squareness,
                    tail_length=43, lock_tail=locked, tail_curve=70)
                geometry = self.renderer.geometry(settings)
                for degrees in range(0, 360, 45):
                    with self.subTest(squareness=squareness, locked=locked, degrees=degrees):
                        angle = math.radians(degrees)
                        direction = QPointF(math.cos(angle), math.sin(angle))
                        anchor = tail_anchor(geometry.body, geometry.body_rect.center(), direction)
                        moved = self.renderer.move_tail(settings, anchor + direction * 70)
                        result = self.renderer.geometry(moved)
                        self.assertEqual(moved.tail_length, 43 if locked else 70)
                        self.assertEqual(result.body, geometry.body)
                        self.assertEqual(result.text_rect, geometry.text_rect)
                        self.assertAlmostEqual(
                            math.hypot(result.tip.x() - anchor.x(), result.tip.y() - anchor.y()),
                            moved.tail_length)
                        self.assertTrue(result.path.contains(geometry.body_rect.center()))
                        preview = ET.fromstring(self.renderer.render(moved, preview=True).svg)
                        exported = ET.fromstring(self.renderer.render(moved).svg)
                        self.assertEqual(preview.find(".//" + SVG + "path").attrib,
                                         exported.find(".//" + SVG + "path").attrib)

    def test_zero_padding_retains_only_necessary_outline_and_shape_clearance(self):
        for style in BUBBLE_TYPES:
            for size, outline in ((1, 0), (14, 3), (35, 50)):
                with self.subTest(style=style, size=size, outline=outline):
                    settings = replace(
                        self.settings, style=style, text="Zero padding\nStill readable",
                        padding=0, font_size=size, outline=outline)
                    geometry = self.renderer.geometry(settings)
                    clearance = outline / 2
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

    def test_zero_square_padding_has_no_hidden_margin_or_font_size_multiplier(self):
        for size in (8, 14, 35, 99):
            settings = replace(self.settings, style="Square", text="AVATAR To Wa",
                               line_length=0, font_size=size, padding=0, outline=0)
            geometry = self.renderer.geometry(settings)
            font = QFont(settings.font)
            font.setPixelSize(size)
            self.assertEqual(geometry.text_rect.width(),
                             QFontMetricsF(font).horizontalAdvance(settings.text))
            self.assertEqual(geometry.body_rect, geometry.text_rect)
            outlined = self.renderer.geometry(replace(settings, outline=6))
            self.assertAlmostEqual(outlined.body_rect.width() - geometry.body_rect.width(), 12)
            self.assertAlmostEqual(outlined.body_rect.height() - geometry.body_rect.height(), 6)

    def test_tight_fit_contains_actual_glyph_ink_including_accents_and_descenders(self):
        for style in BUBBLE_TYPES:
            for text in ("j", "\u00c1\u00c9gj", "First line\njazz glyphs\n\u00c9lan"):
                for custom in (False, True):
                    with self.subTest(style=style, text=text, custom=custom):
                        settings = replace(
                            self.settings, style=style, text=text, line_length=0,
                            font="DejaVu Serif", padding=0, outline=3,
                            oval_custom=custom, oval_vertical_padding=0, oval_squareness=65)
                        geometry = self.renderer.geometry(settings)
                        root = ET.fromstring(self.renderer.render(settings).svg)
                        font = QFont(settings.font)
                        font.setPixelSize(settings.font_size)
                        for line, node in zip(geometry.lines, root.iter(SVG + "text")):
                            ink = glyph_bounds(font, line)
                            origin = QPointF(
                                geometry.body_rect.center().x()
                                - geometry.metrics.horizontalAdvance(line) / 2,
                                float(node.attrib["y"]))
                            ink.translate(origin)
                            self.assertTrue(geometry.text_rect.adjusted(
                                -1e-6, -1e-6, 1e-6, 1e-6).contains(ink))
                            inset = ink.adjusted(0.01, 0.01, -0.01, -0.01)
                            for corner in (inset.topLeft(), inset.topRight(),
                                           inset.bottomLeft(), inset.bottomRight()):
                                self.assertTrue(geometry.body.contains(corner))

    def test_optical_centering_balances_rendered_ink_in_both_directions(self):
        top_heavy = ("She used to be a chubby\nlittle girl when\n"
                     "we were at school\ntogether!")
        for font in ("DejaVu Sans", "DejaVu Serif"):
            for text in (top_heavy, "\n".join(reversed(top_heavy.split("\n")))):
                with self.subTest(font=font, text=text):
                    settings = replace(self.settings, text=text, line_length=0,
                                       font=font, text_color="#ff0000")
                    geometric = self.renderer.geometry(settings)
                    before = rendered_text_centroid_y(self.renderer.render(settings, preview=True))
                    enabled = replace(settings, optical_center=True)
                    optical = self.renderer.geometry(enabled)
                    after = rendered_text_centroid_y(self.renderer.render(enabled, preview=True))
                    self.assertGreater(abs(before - geometric.body_rect.center().y()), 2)
                    self.assertAlmostEqual(after, optical.body_rect.center().y(), delta=0.35)
                    self.assertEqual(optical.lines, geometric.lines)
                    self.assertEqual(optical.text_rect.width(), geometric.text_rect.width())
                    self.assertGreaterEqual(optical.text_rect.height(), geometric.text_rect.height())

    def test_optical_layout_keeps_ink_inside_each_style_without_changing_spacing_or_tail_lock(self):
        for style in BUBBLE_TYPES:
            for text in ("WWWWWWWWWW\nj", "j\nWWWWWWWWWW"):
                with self.subTest(style=style, text=text):
                    settings = replace(
                        self.settings, style=style, text=text, line_length=0,
                        optical_center=True, padding=0, tail_length=43,
                        oval_custom=True, oval_vertical_padding=0, oval_squareness=70)
                    geometry = self.renderer.geometry(settings)
                    font = QFont(settings.font)
                    font.setPixelSize(settings.font_size)
                    preview = ET.fromstring(self.renderer.render(settings, preview=True).svg)
                    exported = ET.fromstring(self.renderer.render(settings).svg)
                    preview_text = list(preview.iter(SVG + "text"))
                    exported_text = list(exported.iter(SVG + "text"))
                    self.assertEqual([node.attrib for node in preview_text],
                                     [node.attrib for node in exported_text])
                    self.assertAlmostEqual(float(preview_text[1].attrib["y"])
                                           - float(preview_text[0].attrib["y"]), settings.font_size)
                    for line, node in zip(geometry.lines, preview_text):
                        ink = glyph_bounds(font, line)
                        ink.translate(QPointF(
                            float(node.attrib["x"]) - geometry.metrics.horizontalAdvance(line) / 2,
                            float(node.attrib["y"])))
                        self.assertTrue(geometry.text_rect.adjusted(
                            -1e-6, -1e-6, 1e-6, 1e-6).contains(ink))
                        inset = ink.adjusted(0.01, 0.01, -0.01, -0.01)
                        for corner in (inset.topLeft(), inset.topRight(),
                                       inset.bottomLeft(), inset.bottomRight()):
                            self.assertTrue(geometry.body.contains(corner))
                    direction = QPointF(math.cos(settings.tail_angle), math.sin(settings.tail_angle))
                    anchor = tail_anchor(geometry.body, geometry.body_rect.center(), direction)
                    self.assertAlmostEqual(
                        math.hypot(geometry.tip.x() - anchor.x(), geometry.tip.y() - anchor.y()), 43)

    def test_optical_centering_without_visible_ink_retains_geometric_layout(self):
        for text in ("", "\n\n", "  \n \n"):
            settings = replace(self.settings, text=text, line_length=0)
            self.assertEqual(self.renderer.render(settings).svg,
                             self.renderer.render(replace(settings, optical_center=True)).svg)

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

    def test_unlocked_tail_uses_outline_distance_rounding_and_absolute_limit(self):
        for style in BUBBLE_TYPES:
            settings = replace(self.settings, style=style, lock_tail=False)
            geometry = self.renderer.geometry(settings)
            center = geometry.body_rect.center()
            direction = QPointF(math.cos(0.37), math.sin(0.37))
            anchor = tail_anchor(geometry.body, center, direction)
            for distance, expected in ((37.2, 37), (37.8, 38), (650, 650), (10000, 990)):
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
        with patch.dict(BUBBLE_STYLES, {bubble.identifier: bubble}):
            geometry = self.renderer.geometry(settings)
            self.assertEqual(geometry.body, oval_path(geometry.body_rect))
            self.assertIn("<svg", self.renderer.render(settings).svg)
        calls = []

        def resolve(style, algorithm, shape):
            calls.append((style, algorithm, shape))
            return bubble

        self.assertEqual(BubbleRenderer(resolve).geometry(self.settings).body_rect,
                         QRectF(0, 0, 600, 300))
        self.assertEqual(calls, [(self.settings.style, self.settings.shout_shape,
                                  self.settings.shape)])
