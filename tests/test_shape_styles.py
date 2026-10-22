from dataclasses import replace
import json
import math
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QFont, QPainterPath, QTransform
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication

from krita_speech_bubble_generator.bubbles.geometry import path_data, tail_anchor
from krita_speech_bubble_generator.bubbles.registry import (
    BUBBLE_STYLES, SHAPES, SHOUTING_ALGORITHMS, resolve_bubble,
)
from krita_speech_bubble_generator.bubbles.renderer import (
    BubbleRenderer, automatic_speech_lines, diamond_speech_lines, measured_line_bounds,
    _text_bounds,
)
from krita_speech_bubble_generator.bubbles.settings import (
    BubbleSettings, SettingsError, TextStyle, decode_record, encode_record, settings_from_dict,
)
from krita_speech_bubble_generator.bubbles.shapes import BubbleShape, convex_hull, subdivide
from krita_speech_bubble_generator.bubbles.text_runs import speech_runs
from krita_speech_bubble_generator.editor.view import BubbleEditorView


APP = QApplication.instance() or QApplication([])
SVG = "{http://www.w3.org/2000/svg}"


class ShapeStyleTests(unittest.TestCase):
    def setUp(self):
        self.renderer = BubbleRenderer()

    def test_all_twelve_combinations_use_shape_padding_and_keep_tail_contract(self):
        for shape in SHAPES:
            for style in BUBBLE_STYLES:
                for algorithm in SHOUTING_ALGORITHMS:
                    with self.subTest(shape=shape, style=style, algorithm=algorithm):
                        settings = BubbleSettings(
                            shape=shape, style=style, text="Short\nA much wider line\nEnd",
                            font="DejaVu Sans", autocenter=False, font_size=22,
                            padding=40, oval_custom=True, oval_vertical_padding=30,
                            tail_length=47, tail_angle=-0.7, tail_curve=64,
                            shout_shape=algorithm, shout_seed=1729, thought_seed=2718)
                        geometry = self.renderer.geometry(settings)
                        center = geometry.body_rect.center()
                        direction = QPointF(math.cos(settings.tail_angle),
                                            math.sin(settings.tail_angle))
                        anchor = tail_anchor(geometry.body, center, direction)
                        self.assertAlmostEqual(
                            math.hypot(geometry.tip.x() - anchor.x(),
                                       geometry.tip.y() - anchor.y()), 47, places=5)
                        moved = self.renderer.move_tail(settings, center + QPointF(-300, 80))
                        self.assertEqual(moved.tail_length, 47)
                        self.assertEqual((moved.shout_seed, moved.thought_seed), (1729, 2718))
                        self.assertEqual(path_data(geometry.body),
                                         path_data(self.renderer.geometry(settings).body))
                        roots = [ET.fromstring(self.renderer.render(settings, preview).svg)
                                 for preview in (True, False)]
                        for tag in ("path", "text"):
                            self.assertEqual(
                                [ET.tostring(node) for node in roots[0].iter(SVG + tag)],
                                [ET.tostring(node) for node in roots[1].iter(SVG + tag)])

    def test_tracing_encloses_positioned_rich_ink_empty_lines_and_padding_after_smoothing(self):
        texts = ("", "\n", "f", "jÁW\n\nA much longer line\nfj", "Wide\nI\nWide")
        for text in texts:
            for style in BUBBLE_STYLES:
                for optical in (False, True):
                    with self.subTest(text=text, style=style, optical=optical):
                        settings = BubbleSettings(
                            shape="Tracing", style=style, text=text, font="DejaVu Serif",
                            font_size=31, autocenter=False, padding=15, oval_custom=True,
                            oval_vertical_padding=35, optical_center=optical,
                            text_styles=(TextStyle(0, len(text), True, True),) if text else ())
                        geometry = self.renderer.geometry(settings)
                        font = QFont(settings.font)
                        font.setPixelSize(settings.font_size)
                        runs = speech_runs(settings, geometry.lines)
                        bounds = _text_bounds(geometry.lines, geometry.metrics, font,
                                              settings.font_size, optical, runs)
                        rows = measured_line_bounds(geometry.lines, geometry.metrics, font,
                                                    settings.font_size, runs)
                        horizontal, vertical = SHAPES["Tracing"].padding(settings)
                        offset = geometry.text_rect.topLeft() - bounds.topLeft()
                        for row in rows:
                            padded = row.translated(offset).adjusted(
                                -horizontal + 1e-5, -vertical + 1e-5,
                                horizontal - 1e-5, vertical - 1e-5)
                            self.assertTrue(geometry.body.contains(padded))
                        self.assertTrue(math.isfinite(geometry.body.boundingRect().width()))

    def test_sharp_tracing_keeps_hull_angles_and_rounded_subdivides(self):
        settings = BubbleSettings(shape="Tracing", text="Top\nA much wider middle line\nEnd",
                                  autocenter=False, padding=0, outline=0)
        sharp = self.renderer.geometry(settings)
        rounded = self.renderer.geometry(replace(settings, style="Rounded"))
        self.assertLess(sharp.body.elementCount(), rounded.body.elementCount())
        self.assertNotEqual(path_data(sharp.body), path_data(rounded.body))
        points = [QPointF(0, 0), QPointF(10, 0), QPointF(10, 10), QPointF(0, 10)]
        self.assertEqual(len(subdivide(points)), 32)
        self.assertEqual(len(convex_hull(points + [QPointF(5, 5)])), 4)

    def test_thought_cloud_rounds_exposed_polygon_corners_without_moving_text(self):
        for shape in ("Tracing", "Square"):
            for text in ("Oh my god...", "Top\nA much wider middle line\nEnd",
                         "I\nI\nI\nI\nI\nI\nI"):
                for nodes in (8, 16, 64):
                    for irregularity, seed in ((0, 0), (100, 17), (100, 2718)):
                        with self.subTest(shape=shape, text=text, nodes=nodes,
                                          irregularity=irregularity, seed=seed):
                            settings = BubbleSettings(
                                shape=shape, text=text, font="DejaVu Sans",
                                font_size=30, autocenter=False, tail_enabled=False,
                                thought_nodes=nodes, thought_irregularity=irregularity,
                                thought_seed=seed)
                            sharp = self.renderer.geometry(settings)
                            thought_settings = replace(settings, style="Thought")
                            thought = self.renderer.geometry(thought_settings)
                            self.assertEqual(thought.body_rect, sharp.body_rect)
                            self.assertEqual(thought.text_rect, sharp.text_rect)
                            self.assertEqual(thought.lines, sharp.lines)
                            for index in range(sharp.body.elementCount()):
                                vertex = sharp.body.elementAt(index)
                                neighborhood = QPainterPath()
                                neighborhood.addEllipse(QPointF(vertex.x, vertex.y), 0.1, 0.1)
                                self.assertTrue(thought.body.contains(neighborhood))
                            self.assertEqual(
                                thought.body, self.renderer.geometry(thought_settings).body)
                            roots = [ET.fromstring(self.renderer.render(thought_settings, preview).svg)
                                     for preview in (True, False)]
                            for tag in ("path", "text"):
                                self.assertEqual(
                                    [ET.tostring(node) for node in roots[0].iter(SVG + tag)],
                                    [ET.tostring(node) for node in roots[1].iter(SVG + tag)])

    def test_rounded_square_keeps_four_long_straight_edges_and_padded_enclosure(self):
        for text in ("I", "I\nI\nI\nI\nI\nI\nI", "A very wide line of dialogue",
                     BubbleSettings().text):
            for padding in (0, 15, 150, 300):
                for outline in (0, 3, 50):
                    with self.subTest(text=text, padding=padding, outline=outline):
                        settings = BubbleSettings(
                            shape="Square", style="Rounded", text=text, font="DejaVu Serif",
                            autocenter=False, padding=padding, outline=outline,
                            text_styles=(TextStyle(0, len(text), True, True),))
                        geometry = self.renderer.geometry(settings)
                        horizontal, vertical = SHAPES["Square"].padding(settings)
                        padded = geometry.text_rect.adjusted(
                            -horizontal + 1e-5, -vertical + 1e-5,
                            horizontal - 1e-5, vertical - 1e-5)
                        self.assertTrue(geometry.body.contains(padded))
                        straight = []
                        for index in range(1, geometry.body.elementCount()):
                            point = geometry.body.elementAt(index)
                            previous = geometry.body.elementAt(index - 1)
                            if point.isLineTo():
                                straight.append((abs(point.x - previous.x),
                                                 abs(point.y - previous.y)))
                        box = geometry.body.boundingRect()
                        self.assertEqual(sum(dx >= box.width() * 0.6 for dx, dy in straight), 2)
                        self.assertEqual(sum(dy >= box.height() * 0.6 for dx, dy in straight), 2)
                        roots = [ET.fromstring(self.renderer.render(settings, preview).svg)
                                 for preview in (True, False)]
                        self.assertEqual(
                            [node.attrib["d"] for node in roots[0].iter(SVG + "path")],
                            [node.attrib["d"] for node in roots[1].iter(SVG + "path")])

    def test_oval_decoration_preserves_existing_seeded_patterns_at_the_same_size(self):
        for style in ("Thought", "Shouting"):
            for algorithm in SHOUTING_ALGORITHMS:
                for squareness in (0, 50, 100):
                    settings = BubbleSettings(
                        style=style, shout_shape=algorithm, oval_custom=True,
                        oval_squareness=squareness, thought_seed=1729, shout_seed=2718)
                    geometry = self.renderer.geometry(settings)
                    legacy = resolve_bubble(style, algorithm)
                    expected = legacy.body_path(
                        geometry.body_rect, legacy.body_parameters(settings))
                    self.assertEqual(geometry.body, expected)

    def test_shape_extension_needs_only_registry_composition_not_renderer_dispatch(self):
        class CustomShape(BubbleShape):
            identifier = label = "Custom"

            def contour(self, bounds, lines, settings):
                path = QPainterPath()
                path.addRect(QRectF(-300, -150, 600, 300))
                return path

        shape = CustomShape()
        with patch.dict(SHAPES, {shape.identifier: shape}):
            settings = BubbleSettings(shape=shape.identifier)
            geometry = self.renderer.geometry(settings)
            self.assertEqual(geometry.body_rect, QRectF(0, 0, 600, 300))
            self.assertEqual(geometry.body.boundingRect(), geometry.body_rect)
            self.assertEqual(settings_from_dict(settings.to_dict()), settings)
            self.assertIn("<svg", self.renderer.render(settings).svg)

    def test_padding_proportions_independent_axes_and_shape_capabilities(self):
        base = BubbleSettings(shape="Square", text="A wide rectangle", autocenter=False)
        low = self.renderer.geometry(replace(base, padding=20))
        high = self.renderer.geometry(replace(base, padding=80))
        self.assertAlmostEqual(high.body_rect.width() - low.body_rect.width(),
                               2 * (high.body_rect.height() - low.body_rect.height()))
        self.assertGreater(low.body_rect.width(), low.body_rect.height())
        for shape in SHAPES:
            settings = replace(base, shape=shape, oval_custom=True, padding=60,
                               oval_vertical_padding=20)
            initial = self.renderer.geometry(settings)
            taller = self.renderer.geometry(replace(settings, oval_vertical_padding=100))
            self.assertAlmostEqual(initial.body_rect.width(), taller.body_rect.width())
            self.assertGreater(taller.body_rect.height(), initial.body_rect.height())
            squared = self.renderer.geometry(replace(settings, oval_squareness=90))
            if not SHAPES[shape].capabilities.squareness:
                self.assertEqual(path_data(initial.body), path_data(squared.body))

    def test_legacy_mapping_is_additive_nonmutating_and_round_trips_all_combinations(self):
        mapping = {"Oval": ("Oval", "Sharp"), "Square": ("Square", "Sharp"),
                   "Round": ("Square", "Rounded"), "Rounded": ("Square", "Rounded"),
                   "Thought": ("Oval", "Thought"), "Shouting": ("Oval", "Shouting")}
        for old, expected in mapping.items():
            values = BubbleSettings().to_dict()
            del values["shape"], values["wrapping"]
            values.update(style=old, baseline=[1, 0, 0, 1, 0, 0])
            original = json.dumps(values)
            loaded = decode_record(original.encode()).settings
            self.assertEqual((loaded.shape, loaded.style), expected)
            self.assertEqual(loaded.wrapping, "Standard")
            self.assertEqual(json.dumps(values), original)
        for shape in SHAPES:
            for style in BUBBLE_STYLES:
                settings = BubbleSettings(shape=shape, style=style, wrapping="Diamond")
                self.assertEqual(decode_record(encode_record(settings, QTransform())).settings,
                                 settings)
        for values in ({"shape": "Triangle"}, {"wrapping": "Unknown"}, {"style": "Unknown"}):
            with self.assertRaises(SettingsError):
                settings_from_dict(values)

    def test_diamond_has_symmetric_measured_distribution_and_preserves_rich_text(self):
        words = ["word"] * 25
        lines = diamond_speech_lines(" ".join(words))
        lengths = [len(line) for line in lines]
        self.assertEqual(lengths, lengths[::-1])
        middle = len(lines) // 2
        self.assertEqual(lengths[:middle + 1], sorted(lengths[:middle + 1]))
        self.assertEqual(" ".join(lines).split(), words)
        text = "Álpha  beta gamma delta epsilon zeta eta theta\n\nlast paragraph"
        settings = BubbleSettings(text=text, wrapping="Diamond",
                                  text_styles=(TextStyle(0, 5, True, True),
                                               TextStyle(13, 30, False, True)))
        for shape in SHAPES:
            for style in BUBBLE_STYLES:
                candidate = replace(settings, shape=shape, style=style)
                geometry = self.renderer.geometry(candidate)
                self.assertEqual(" ".join(geometry.lines).split(), text.split())
                self.assertIn("", geometry.lines)
                runs = speech_runs(candidate, geometry.lines)
                self.assertEqual([run.text for row in runs for run in row if run.bold], ["Álpha"])
                root = ET.fromstring(self.renderer.render(candidate).svg)
                self.assertEqual(["".join(node.itertext()) for node in root.iter(SVG + "text")],
                                 geometry.lines)
        for length in (0, 12):
            manual = replace(settings, autocenter=False, line_length=length)
            self.assertEqual(self.renderer.geometry(manual).lines,
                             self.renderer.geometry(replace(manual, wrapping="Standard")).lines)
        self.assertEqual(automatic_speech_lines("aa bb cc dd ee"), ["aa bb cc", "dd ee"])

    def test_advanced_ui_resets_values_without_restoring_and_load_is_silent(self):
        view = BubbleEditorView()
        self.addCleanup(view.deleteLater)
        spy = QSignalSpy(view.edited)
        settings = BubbleSettings(shape="Tracing", style="Thought", wrapping="Diamond",
                                  font="DejaVu Sans",
                                  oval_custom=True, padding=75, oval_vertical_padding=25,
                                  oval_squareness=80)
        self.assertEqual(view.load_settings(settings), settings)
        self.assertEqual(len(spy), 0)
        self.assertTrue(view.squarenessControls.isHidden())
        view.ovalGroup.setChecked(False)
        simple = view.initial_settings()
        self.assertEqual((simple.oval_vertical_padding, simple.oval_squareness), (75, 0))
        self.assertTrue(view.advancedPadding.isHidden())
        view.ovalGroup.setChecked(True)
        self.assertEqual(view.initial_settings().oval_vertical_padding, 75)
        self.assertEqual(view.initial_settings().oval_squareness, 0)
        view.bubbleShape.setCurrentText("Oval")
        self.assertFalse(view.squarenessControls.isHidden())
        self.assertEqual(view.initial_settings().style, "Thought")
        view.autocenter.setChecked(False)
        self.assertFalse(view.wrapping.isEnabled())
        self.assertEqual(view.wrapping.currentText(), "Diamond")

    def test_copy_appearance_includes_shape_style_wrapping_and_seeds_not_dialogue_or_tail(self):
        source = BubbleSettings(shape="Tracing", style="Shouting", wrapping="Diamond",
                                text="source", shout_seed=11, thought_seed=12)
        target = BubbleSettings(text="target", tail_angle=-1.2, tail_length=31, lock_tail=False,
                                shout_seed=21, thought_seed=22,
                                text_styles=(TextStyle(0, 3, True),))
        pasted = target.with_style_from(source)
        self.assertEqual((pasted.shape, pasted.style, pasted.wrapping),
                         ("Tracing", "Shouting", "Diamond"))
        for field in ("text", "text_styles", "tail_angle", "tail_length", "lock_tail"):
            self.assertEqual(getattr(pasted, field), getattr(target, field))
        self.assertEqual((pasted.shout_seed, pasted.thought_seed), (11, 12))
