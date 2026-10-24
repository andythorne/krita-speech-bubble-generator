"""Deterministic partition-work and measured-lettering reuse regressions."""

from dataclasses import fields, replace
import random
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF

from fake_krita import APP
from test_presenter import SubstituteGateway, SubstituteView
from krita_speech_bubble_generator.bubbles import renderer as rendering
from krita_speech_bubble_generator.bubbles.registry import BUBBLE_STYLES, SHAPES
from krita_speech_bubble_generator.bubbles.settings import BubbleSettings, TextStyle
from krita_speech_bubble_generator.editor.presenter import EditorPresenter


def exhaustive_partition(prefix, weights, space, unit):
    """The original candidate-list search, including its first-minimum tie rule."""
    length = len(prefix) - 1
    previous = {0: (0.0, [])}
    for row, weight in enumerate(weights):
        current = {}
        target = max(1.0, unit * weight)
        for end in range(row + 1, length - (len(weights) - row - 1) + 1):
            candidates = []
            for start, (cost, breaks) in previous.items():
                if start >= end:
                    continue
                width = prefix[end] - prefix[start] - space
                error = (width - target) / max(1.0, unit)
                candidates.append((cost + error * error, breaks + [end]))
            if candidates:
                current[end] = min(candidates, key=lambda item: item[0])
        previous = current
    return previous[length][1]


class CountingPrefix(list):
    def __init__(self, values):
        super().__init__(values)
        self.reads = 0

    def __getitem__(self, index):
        self.reads += 1
        return super().__getitem__(index)


class TextLayoutPerformanceTests(unittest.TestCase):
    def test_partition_matches_exhaustive_search_including_ties_and_roundoff(self):
        rng = random.Random(7351)
        cases = [
            ([0.0] * 25, 0.0),
            ([4.0] * 31, 1.0),
            ([1.0 + (index % 3) * 1e-14 for index in range(40)], 0.25),
            ([1e-12, 1e12, 0.0, 1.0] * 9, 1e-12),
            # Nonmonotone custom measurements retain the exhaustive fallback.
            ([4.0, -2.0, 1.0] * 9, 0.0),
        ]
        for _ in range(160):
            cases.append(([rng.choice((0.0, 0.125, 1.0, 3.0, rng.random() * 100))
                           for _ in range(rng.randrange(3, 50))],
                          rng.choice((0.0, 0.25, 1.0, 5.0))))
        for widths, space in cases:
            prefix = [0.0]
            for width in widths:
                prefix.append(prefix[-1] + width + space)
            for count in (3, min(7, len(widths))):
                weights = [min(index + 1, count - index) for index in range(count)]
                unit = (prefix[-1] - count * space) / sum(weights)
                with self.subTest(widths=widths, space=space, count=count):
                    self.assertEqual(rendering._diamond_partition(prefix, weights, space, unit),
                                     exhaustive_partition(prefix, weights, space, unit))

    def test_thousand_word_partition_avoids_quadratic_candidate_work(self):
        length = 1000
        prefix = CountingPrefix([index * 5.0 for index in range(length + 1)])
        weights = [min(index + 1, 33 - index) for index in range(33)]
        ends = rendering._diamond_partition(prefix, weights, 1.0,
                                           (prefix[-1] - 33) / sum(weights))
        self.assertEqual(ends[-1], length)
        self.assertEqual(len(ends), len(weights))
        self.assertTrue(all(left < right for left, right in zip([0] + ends, ends)))
        # The original visits over 14 million candidates (two prefix reads each).
        # Bound actual search work, not elapsed time on a particular machine.
        self.assertLess(prefix.reads, 1_000_000)

    def test_svg_matches_original_partition_for_all_shapes_styles_and_modes(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda\n\nlast line"
        settings = BubbleSettings(
            text=text, font="DejaVu Sans", text_styles=(
                TextStyle(0, 12, True), TextStyle(17, 40, False, True)),
            tail_length=50, optical_center=True)
        for shape in SHAPES:
            for style in BUBBLE_STYLES:
                for wrapping in ("Standard", "Diamond"):
                    for automatic, length in ((True, 0), (False, 0), (False, 12)):
                        variant = replace(settings, shape=shape, style=style, wrapping=wrapping,
                                          autocenter=automatic, line_length=length)
                        with self.subTest(shape=shape, style=style, wrapping=wrapping,
                                          automatic=automatic, length=length):
                            actual = rendering.BubbleRenderer().render(variant, preview=True)
                            with patch.object(rendering, "_diamond_partition",
                                              exhaustive_partition):
                                expected = rendering.BubbleRenderer().render(variant, preview=True)
                            self.assertEqual(actual, expected)
                            exported = rendering.BubbleRenderer().render(variant)
                            with patch.object(rendering, "_diamond_partition",
                                              exhaustive_partition):
                                self.assertEqual(
                                    exported, rendering.BubbleRenderer().render(variant))

    def test_presenter_long_rich_text_and_tail_drag_measure_lettering_once(self):
        text = " ".join(["word"] * 1000)
        for wrapping in ("Standard", "Diamond"):
            renderer = rendering.BubbleRenderer()
            presenter = EditorPresenter(SubstituteView(), SubstituteGateway(), renderer,
                                        lambda low, high: 17)
            settings = BubbleSettings(
                text=text, text_styles=(TextStyle(0, len(text), True, True),),
                shape="Tracing", style="Rounded", wrapping=wrapping, tail_length=50)
            with patch.object(rendering, "_text_layout", wraps=rendering._text_layout) as layout:
                with patch.object(rendering, "diamond_speech_lines",
                                  wraps=rendering.diamond_speech_lines) as diamond:
                    presenter.edit(settings)
                    initial = renderer.geometry(settings)
                    for point in (QPointF(250, -100), QPointF(-300, 200), QPointF(50, 400)):
                        presenter.move_tail(point)
                        current = renderer.geometry(presenter.state.draft)
                        self.assertEqual(current.lines, initial.lines)
                        self.assertEqual(current.text_rect, initial.text_rect)
                        self.assertEqual(current.body, initial.body)
                    self.assertEqual(layout.call_count, 1)
                    self.assertEqual(diamond.call_count, int(wrapping == "Diamond"))
            with patch.object(rendering, "_diamond_partition", exhaustive_partition):
                self.assertEqual(
                    presenter.view.rendered,
                    rendering.BubbleRenderer().render(presenter.state.draft, preview=True))
            self.assertFalse(presenter.view.warnings)

    def test_every_lettering_setting_invalidates_the_cache(self):
        settings = BubbleSettings(text="alpha beta gamma\ndelta", font="DejaVu Sans",
                                  shape="Square", wrapping="Diamond")
        variants = {
            "text": "other words\n\nend",
            "text_styles": (TextStyle(0, 10, True, True),),
            "font": "DejaVu Sans Mono",
            "font_size": 29,
            "autocenter": False,
            "wrapping": "Standard",
            "line_length": 7,
            "optical_center": True,
            "text_alignment": "Right",
        }
        for field, value in variants.items():
            with self.subTest(field=field):
                renderer = rendering.BubbleRenderer()
                renderer.render(settings)
                variant = replace(settings, **{field: value})
                with patch.object(rendering, "_text_layout", wraps=rendering._text_layout) as layout:
                    actual = renderer.render(variant, preview=True)
                    renderer.render(variant)
                    self.assertEqual(layout.call_count, 1)
                self.assertEqual(actual, rendering.BubbleRenderer().render(variant, preview=True))

    def test_body_tail_and_paint_settings_reuse_text_but_rebuild_correct_geometry(self):
        settings = BubbleSettings(text="alpha beta gamma\ndelta", font="DejaVu Sans",
                                  wrapping="Diamond", tail_length=50)
        variants = dict(
            shape="Tracing", style="Thought", fill="#123456", stroke="#654321",
            text_color="#abcdef", outline=8, padding=75, oval_custom=True,
            oval_vertical_padding=25, oval_squareness=80, tail_length=75, tail_angle=-1.0,
            tail_enabled=False, tail_advanced=True, tail_start_angle=-0.8,
            tail_end_x=220.5, tail_end_y=120.5,
            lock_tail=False, tail_curve=65, tail_curve_direction="Down", thought_size=150,
            thought_blobs=7,
            shout_irregularity=75, shout_shape="Wave", shout_nodes=32, shout_seed=42,
            thought_irregularity=75, thought_nodes=24, thought_seed=99)
        lettering_fields = {
            "text", "text_styles", "font", "font_size", "autocenter", "wrapping",
            "line_length", "optical_center", "text_alignment",
        }
        self.assertEqual(set(variants) | lettering_fields,
                         {field.name for field in fields(BubbleSettings)})
        renderer = rendering.BubbleRenderer()
        measure = rendering._text_layout
        with patch.object(rendering, "_text_layout", wraps=rendering._text_layout) as layout:
            renderer.render(settings)
            for field, value in variants.items():
                with self.subTest(field=field):
                    variant = replace(settings, **{field: value})
                    actual = renderer.render(variant, preview=True)
                    self.assertEqual(layout.call_count, 1)
                    with patch.object(rendering, "_text_layout", measure):
                        expected = rendering.BubbleRenderer().render(variant, preview=True)
                    self.assertEqual(actual, expected)

    def test_cache_is_instance_owned_single_entry_and_public_lines_are_independent(self):
        settings = BubbleSettings(wrapping="Diamond")
        renderer = rendering.BubbleRenderer()
        with patch.object(rendering, "_text_layout", wraps=rendering._text_layout) as layout:
            expected = renderer.render(settings)
            geometry = renderer.geometry(settings)
            geometry.lines.clear()
            self.assertEqual(renderer.render(settings), expected)
            self.assertEqual(layout.call_count, 1)
            rendering.BubbleRenderer().render(settings)
            self.assertEqual(layout.call_count, 2)
            renderer.render(replace(settings, text="replacement"))
            renderer.render(settings)
            self.assertEqual(layout.call_count, 4)
