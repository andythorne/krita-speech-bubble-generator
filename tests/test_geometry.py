"""Original contour regression coverage, independent of editor workflows."""

import math
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QPointF, QRectF

from fake_krita import APP
from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, bubble_path, path_data, tail_anchor, tail_tip,
)
from krita_speech_bubble_generator.bubbles.registry import BUBBLE_TYPES, SHOUTING_ALGORITHMS


STYLES = tuple(BUBBLE_TYPES)
SHOUTING_SHAPES = tuple(SHOUTING_ALGORITHMS)


class GeometryTests(unittest.TestCase):
    @staticmethod
    def shouting_vertices(path, rect):
        def point(index):
            element = path.elementAt(index)
            return QPointF((element.x - rect.center().x()) * 2 / rect.width(),
                           (element.y - rect.center().y()) * 2 / rect.height())

        stride = 6 if path.elementAt(1).isCurveTo() else 2
        count = (path.elementCount() - 1) // stride
        return ([point(i * stride) for i in range(count)],
                [point(i * stride + stride // 2) for i in range(count)])

    def test_tails_connect_in_every_direction(self):
        rect = QRectF(0, 0, 240, 100)
        for style in STYLES:
            body = body_path(rect, style)
            for degrees in range(0, 360, 5):
                with self.subTest(style=style, degrees=degrees):
                    angle = math.radians(degrees)
                    tip = tail_tip(body, rect.center(), angle, 60)
                    direction = QPointF(math.cos(angle), math.sin(angle))
                    anchor = tail_anchor(body, rect.center(), direction)
                    self.assertAlmostEqual(
                        math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y()), 60)
                    self.assertFalse(body.contains(tip))
                    path = bubble_path(body, rect.center(), tip, style, 14)
                    self.assertTrue(path.contains(rect.center()))
                    if style != "Thought":
                        for fraction in (0.01, 0.2, 0.5, 0.9):
                            self.assertTrue(path.contains(anchor + (tip - anchor) * fraction))
                    else:
                        for fraction in (0.25, 0.58, 0.87):
                            self.assertTrue(path.contains(anchor + (tip - anchor) * fraction))

    def test_no_tail_does_not_change_body(self):
        for style in STYLES:
            body = body_path(QRectF(0, 0, 240, 100), style)
            self.assertEqual(bubble_path(body, QPointF(120, 50), None, style, 14), body)
            self.assertEqual(bubble_path(body, QPointF(120, 50), QPointF(120, 50), style, 14), body)

    def test_curved_tails_follow_both_bends_in_every_direction(self):
        rect = QRectF(0, 0, 240, 100)
        for style in STYLES:
            body = body_path(rect, style)
            for degrees in range(0, 360, 30):
                angle = math.radians(degrees)
                direction = QPointF(math.cos(angle), math.sin(angle))
                perpendicular = QPointF(-direction.y(), direction.x())
                anchor = tail_anchor(body, rect.center(), direction)
                tip = tail_tip(body, rect.center(), angle, 60)
                for curve in (25, 100):
                    for bend, sign in (("Up", -1), ("Down", 1)):
                        with self.subTest(style=style, degrees=degrees,
                                          curve=curve, bend=bend):
                            path = bubble_path(
                                body, rect.center(), tip, style, 14,
                                curve=curve, curve_direction=bend)
                            fractions = ((0.25, 0.58, 0.87) if style == "Thought"
                                         else (0.2, 0.5, 0.8))
                            for fraction in fractions:
                                point = anchor + (tip - anchor) * fraction + perpendicular * (
                                    sign * 60 * curve / 100 * 2 * fraction * (1 - fraction) ** 2)
                                self.assertTrue(path.contains(point))
                            self.assertTrue(path.contains(rect.center()))
                            self.assertTrue(path_data(path).endswith("Z"))

    def test_curved_short_speech_tails_keep_the_tip_and_taper(self):
        rect = QRectF(0, 0, 240, 100)
        for style in ("Oval", "Rounded", "Square", "Shouting"):
            body = body_path(rect, style)
            anchor = tail_anchor(body, rect.center(), QPointF(1, 0))
            for length in (3, 14, 60):
                for bend, sign in (("Up", -1), ("Down", 1)):
                    with self.subTest(style=style, length=length, bend=bend):
                        tip = tail_tip(body, rect.center(), 0, length)
                        path = bubble_path(
                            body, rect.center(), tip, style, 14,
                            curve=100, curve_direction=bend)
                        for fraction in (0.2, 0.5, 0.8):
                            axis = anchor + QPointF(
                                length * fraction,
                                sign * length * 2 * fraction * (1 - fraction) ** 2)
                            half_width = 14 * 0.4 * (1 - fraction)
                            for side in (-1, 1):
                                self.assertTrue(path.contains(
                                    axis + QPointF(0, side * half_width * 0.7)))
                                outside = axis + QPointF(0, side * (half_width + 0.5))
                                if not body.contains(outside):
                                    self.assertFalse(path.contains(outside))
                        self.assertFalse(path.contains(tip + QPointF(0.1, 0)))
                        self.assertEqual(body.subtracted(path).elementCount(), 0)

    def test_curve_has_no_effect_without_a_tail_or_at_zero_amount(self):
        rect = QRectF(0, 0, 240, 100)
        for style in STYLES:
            body = body_path(rect, style)
            tip = tail_tip(body, rect.center(), 0, 60)
            straight = bubble_path(body, rect.center(), tip, style, 14)
            for bend in ("Up", "Down"):
                with self.subTest(style=style, bend=bend):
                    self.assertEqual(bubble_path(
                        body, rect.center(), tip, style, 14,
                        curve=0, curve_direction=bend), straight)
                    self.assertEqual(bubble_path(
                        body, rect.center(), None, style, 14,
                        curve=100, curve_direction=bend), body)

    def test_curved_speech_tails_ease_into_the_pointing_axis_without_a_hook(self):
        rect = QRectF(0, 0, 240, 100)
        for style in ("Oval", "Rounded", "Square", "Shouting"):
            body = body_path(rect, style)
            for degrees in range(0, 360, 45):
                angle = math.radians(degrees)
                direction = QPointF(math.cos(angle), math.sin(angle))
                for length in (3, 14, 60, 140):
                    tip = tail_tip(body, rect.center(), angle, length)
                    for bend in ("Up", "Down"):
                        with self.subTest(style=style, degrees=degrees,
                                          length=length, bend=bend):
                            path = bubble_path(
                                body, rect.center(), tip, style, 14,
                                curve=100, curve_direction=bend)
                            near_tip = tip - direction * (length * 0.01)
                            self.assertFalse(body.contains(near_tip))
                            self.assertTrue(path.contains(near_tip))
                            self.assertFalse(path.contains(tip + direction * 0.1))

    def test_small_speech_tails_keep_a_visible_width_without_extending_the_tip(self):
        rect = QRectF(0, 0, 240, 100)
        for style in ("Oval", "Rounded", "Square", "Shouting"):
            body = body_path(rect, style)
            for degrees in range(0, 360, 45):
                with self.subTest(style=style, degrees=degrees):
                    angle = math.radians(degrees)
                    direction = QPointF(math.cos(angle), math.sin(angle))
                    perpendicular = QPointF(-direction.y(), direction.x())
                    anchor = tail_anchor(body, rect.center(), direction)
                    tip = tail_tip(body, rect.center(), angle, 3)
                    path = bubble_path(body, rect.center(), tip, style, 14)
                    self.assertAlmostEqual(math.hypot(
                        tip.x() - anchor.x(), tip.y() - anchor.y()), 3)
                    for side in (-1, 1):
                        point = anchor + direction * 1.5 + perpendicular * side
                        self.assertFalse(body.contains(point))
                        self.assertTrue(path.contains(point))
                    self.assertFalse(path.contains(tip + direction * 0.01))
                    self.assertEqual(body.subtracted(path).elementCount(), 0)

    def test_diagonal_tail_is_symmetric_about_the_bubble_center_to_tip_axis(self):
        for style in ("Oval", "Rounded", "Square", "Shouting"):
            for width, height in ((240, 100), (100, 240)):
                rect = QRectF(0, 0, width, height)
                body = body_path(rect, style)
                for degrees in (45, 135, 225, 315):
                    with self.subTest(style=style, width=width, degrees=degrees):
                        angle = math.radians(degrees)
                        direction = QPointF(math.cos(angle), math.sin(angle))
                        perpendicular = QPointF(-direction.y(), direction.x())
                        anchor = tail_anchor(body, rect.center(), direction)
                        tip = tail_tip(body, rect.center(), angle, 60)
                        self.assertAlmostEqual(abs(tip.x() - anchor.x()),
                                               abs(tip.y() - anchor.y()))
                        self.assertAlmostEqual(
                            (tip - rect.center()).x() * direction.y()
                            - (tip - rect.center()).y() * direction.x(), 0)
                        path = bubble_path(body, rect.center(), tip, style, 14)
                        for along in (5, 15, 30, 45, 55):
                            axis = anchor + direction * along
                            self.assertTrue(path.contains(axis))
                            for offset in (0.5, 1, 2, 4, 6, 8, 10):
                                left = axis + perpendicular * offset
                                right = axis - perpendicular * offset
                                if not body.contains(left) and not body.contains(right):
                                    self.assertEqual(path.contains(left), path.contains(right))

    def test_speech_tail_has_a_narrow_straight_taper_without_a_leaf_shaped_bulge(self):
        rect = QRectF(0, 0, 240, 100)
        font_size = 14
        for style in ("Oval", "Rounded", "Square", "Shouting"):
            body = body_path(rect, style)
            for degrees in (45, 135, 225, 315):
                angle = math.radians(degrees)
                direction = QPointF(math.cos(angle), math.sin(angle))
                perpendicular = QPointF(-direction.y(), direction.x())
                anchor = tail_anchor(body, rect.center(), direction)
                for length in (3, 14, 60):
                    with self.subTest(style=style, degrees=degrees, length=length):
                        tip = tail_tip(body, rect.center(), angle, length)
                        path = bubble_path(body, rect.center(), tip, style, font_size)
                        for fraction in (0.1, 0.25, 0.5, 0.75, 0.9):
                            axis = anchor + direction * (length * fraction)
                            half_width = font_size * 0.4 * (1 - fraction)
                            for side in (-1, 1):
                                self.assertTrue(path.contains(
                                    axis + perpendicular * (side * half_width * 0.9)))
                                outside = axis + perpendicular * (side * (half_width + 0.15))
                                if not body.contains(outside):
                                    self.assertFalse(path.contains(outside))

    def test_styles_have_distinct_outlines(self):
        paths = [body_path(QRectF(0, 0, 240, 100), style) for style in STYLES]
        for i, path in enumerate(paths):
            for other in paths[i + 1:]:
                self.assertNotEqual(path, other)

    def test_svg_contours_are_closed_for_consistent_outline_joins(self):
        for style in STYLES:
            body = body_path(QRectF(0, 0, 240, 100), style)
            tip = tail_tip(body, QPointF(120, 50), 0.7, 60)
            path = bubble_path(body, QPointF(120, 50), tip, style, 14)
            self.assertTrue(path_data(path).endswith("Z"))

    def test_oval_and_rounded_rectangle_have_different_corners(self):
        rect = QRectF(0, 0, 240, 100)
        corner = QPointF(15, 15)
        self.assertTrue(body_path(rect, "Rounded", 20).contains(corner))
        self.assertFalse(body_path(rect, "Oval").contains(corner))

    def test_thought_blob_size_increases_radius_without_holes(self):
        rect = QRectF(0, 0, 240, 100)
        body = body_path(rect, "Thought")
        tip = tail_tip(body, rect.center(), 0, 100)
        anchor = tail_anchor(body, rect.center(), QPointF(1, 0))
        first_center = anchor + (tip - anchor) * 0.25
        small = bubble_path(body, rect.center(), tip, "Thought", 14, 100)
        large = bubble_path(body, rect.center(), tip, "Thought", 14, 400)
        edge = first_center + QPointF(0, 10)
        self.assertFalse(small.contains(edge))
        self.assertTrue(large.contains(edge))
        self.assertTrue(large.contains(first_center))

    def test_shouting_randomness_is_stable_seeded_and_adjustable(self):
        rect = QRectF(0, 0, 240, 100)
        regular = body_path(rect, "Shouting", irregularity=0, seed=17)
        self.assertEqual(regular, body_path(rect, "Shouting", irregularity=0, seed=99))
        low = body_path(rect, "Shouting", irregularity=25, seed=17)
        high = body_path(rect, "Shouting", irregularity=100, seed=17)
        self.assertEqual(high, body_path(rect, "Shouting", irregularity=100, seed=17))
        self.assertNotEqual(high, body_path(rect, "Shouting", irregularity=100, seed=99))
        self.assertNotEqual(low, high)
        low_tips, _ = self.shouting_vertices(low, rect)
        high_tips, _ = self.shouting_vertices(high, rect)
        low_radii = [math.hypot(point.x(), point.y()) for point in low_tips]
        high_radii = [math.hypot(point.x(), point.y()) for point in high_tips]
        self.assertGreater(max(high_radii) - min(high_radii), max(low_radii) - min(low_radii))
        for seed in range(5):
            body = body_path(rect, "Shouting", irregularity=100, seed=seed)
            for degrees in range(0, 360, 15):
                tip = tail_tip(body, rect.center(), math.radians(degrees), 60)
                path = bubble_path(body, rect.center(), tip, "Shouting", 14)
                self.assertTrue(path.contains(rect.center()))

    def test_shouting_randomizes_spacing_with_tightly_bounded_heights_and_valleys(self):
        rect = QRectF(0, 0, 240, 100)
        for amount in (0, 25, 50, 79, 100):
            for seed in range(100):
                with self.subTest(amount=amount, seed=seed):
                    body = body_path(rect, "Shouting", irregularity=amount, seed=seed)
                    tips, valleys = self.shouting_vertices(body, rect)
                    radii = [math.hypot(point.x(), point.y()) for point in tips]
                    valley_radii = [math.hypot(point.x(), point.y()) for point in valleys]
                    variation = amount / 100
                    self.assertGreaterEqual(min(radii), 1.25 - 0.025 * variation - 1e-9)
                    self.assertLessEqual(max(radii), 1.25 + 0.025 * variation + 1e-9)
                    self.assertGreaterEqual(min(valley_radii), 1.02 - 0.01 * variation - 1e-9)
                    self.assertLessEqual(max(valley_radii), 1.02 + 0.01 * variation + 1e-9)
                    widths = []
                    for i, tip in enumerate(tips):
                        angle = math.atan2(tip.y(), tip.x())
                        left = valleys[i - 1]
                        right = valleys[i]
                        incoming = (angle - math.atan2(left.y(), left.x())) % (2 * math.pi)
                        outgoing = (math.atan2(right.y(), right.x()) - angle) % (2 * math.pi)
                        widths.append(incoming + outgoing)
                        self.assertAlmostEqual(incoming, outgoing)
                    self.assertLessEqual(max(widths) / min(widths),
                                         (1 + 0.35 * variation) / (1 - 0.35 * variation) + 1e-9)
                    if amount:
                        self.assertGreater(max(widths) - min(widths), 0.02 * variation)
                        self.assertGreater(max(radii) - min(radii), 0.02 * variation)
                        self.assertGreater(max(valley_radii) - min(valley_radii), 0.01 * variation)

    def test_shouting_spikes_do_not_fold_or_cross_at_any_aspect_ratio(self):
        for width, height in ((240, 100), (100, 240), (1000, 10), (10, 1000)):
            rect = QRectF(0, 0, width, height)
            for amount in (0, 50, 100):
                for shape in SHOUTING_SHAPES:
                    for seed in (0, 17, 99, 1729):
                        with self.subTest(width=width, height=height, amount=amount,
                                          shape=shape, seed=seed):
                            body = body_path(rect, "Shouting", irregularity=amount, seed=seed,
                                             shouting_shape=shape)
                            polygons = body.toSubpathPolygons()
                            self.assertEqual(len(polygons), 1)
                            points = [QPointF((point.x() - rect.center().x()) * 2 / width,
                                              (point.y() - rect.center().y()) * 2 / height)
                                      for point in polygons[0]]
                            sweep = 0
                            for left, right in zip(points, points[1:]):
                                angle = math.atan2(left.x() * right.y() - left.y() * right.x(),
                                                   left.x() * right.x() + left.y() * right.y())
                                self.assertGreaterEqual(angle, -1e-9)
                                sweep += angle
                            self.assertAlmostEqual(sweep, 2 * math.pi)

    def test_shouting_shapes_are_distinct_seeded_and_have_bounded_spikes(self):
        rect = QRectF(0, 0, 240, 100)
        paths = [body_path(rect, "Shouting", irregularity=79, seed=17, shouting_shape=shape)
                 for shape in SHOUTING_SHAPES]
        for i, path in enumerate(paths):
            for other in paths[i + 1:]:
                self.assertNotEqual(path, other)
        for shape in SHOUTING_SHAPES:
            regular = body_path(rect, "Shouting", irregularity=0, seed=17, shouting_shape=shape)
            self.assertEqual(regular, body_path(
                rect, "Shouting", irregularity=0, seed=99, shouting_shape=shape))
            for amount in (50, 79, 100):
                for seed in range(20):
                    with self.subTest(shape=shape, amount=amount, seed=seed):
                        body = body_path(rect, "Shouting", irregularity=amount, seed=seed,
                                         shouting_shape=shape)
                        self.assertEqual(body, body_path(
                            rect, "Shouting", irregularity=amount, seed=seed, shouting_shape=shape))
                        self.assertNotEqual(body, body_path(
                            rect, "Shouting", irregularity=amount, seed=seed + 1,
                            shouting_shape=shape))
                        tips, valleys = self.shouting_vertices(body, rect)
                        self.assertEqual(len(tips), 18 if shape == "Punchy" else 24)
                        for tip in tips:
                            radius = math.hypot(tip.x(), tip.y())
                            self.assertGreaterEqual(radius, 1.135 - 1e-9)
                            self.assertLessEqual(radius, 1.285 + 1e-9)
                        for valley in valleys:
                            radius = math.hypot(valley.x(), valley.y())
                            self.assertGreaterEqual(radius, 1.01 - 1e-9)
                            self.assertLessEqual(radius, 1.03 + 1e-9)
                        self.assertTrue(path_data(body).endswith("Z"))
                        if shape == "Angular":
                            self.assertIn("L", path_data(body))
                            self.assertNotIn("C", path_data(body))
                        else:
                            self.assertIn("C", path_data(body))
                            self.assertNotIn("L", path_data(body))

    def test_expressive_shouting_has_gentle_bounded_lean(self):
        rect = QRectF(0, 0, 240, 100)
        for seed in range(20):
            body = body_path(rect, "Shouting", irregularity=100, seed=seed,
                             shouting_shape="Expressive")
            tips, valleys = self.shouting_vertices(body, rect)
            leans = []
            for i, tip in enumerate(tips):
                angle = math.atan2(tip.y(), tip.x())
                left, right = valleys[i - 1], valleys[i]
                incoming = (angle - math.atan2(left.y(), left.x())) % (2 * math.pi)
                outgoing = (math.atan2(right.y(), right.x()) - angle) % (2 * math.pi)
                leans.append(abs(incoming - outgoing) / (incoming + outgoing))
            self.assertGreater(max(leans), 0.1)
            self.assertLessEqual(max(leans), 0.2 + 1e-9)

    def test_all_shouting_shapes_keep_tails_connected(self):
        for shape in SHOUTING_SHAPES:
            rect = QRectF(0, 0, 240, 100)
            body = body_path(rect, "Shouting", irregularity=100, seed=17,
                             shouting_shape=shape)
            for degrees in range(0, 360, 5):
                angle = math.radians(degrees)
                direction = QPointF(math.cos(angle), math.sin(angle))
                anchor = tail_anchor(body, rect.center(), direction)
                tip = tail_tip(body, rect.center(), angle, 60)
                path = bubble_path(body, rect.center(), tip, "Shouting", 14)
                self.assertAlmostEqual(math.hypot(tip.x() - anchor.x(), tip.y() - anchor.y()), 60)
                for fraction in (0.01, 0.2, 0.5, 0.9):
                    self.assertTrue(path.contains(anchor + (tip - anchor) * fraction))

    def test_unknown_shouting_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown shouting shape"):
            body_path(QRectF(0, 0, 240, 100), "Shouting", shouting_shape="Unknown")

    def test_shouting_nodes_control_the_exact_spike_count_for_every_shape(self):
        rect = QRectF(0, 0, 240, 100)
        for shape in SHOUTING_SHAPES:
            previous = None
            for nodes in (8, 12, 24, 64):
                with self.subTest(shape=shape, nodes=nodes):
                    body = body_path(rect, "Shouting", irregularity=100, seed=17,
                                     shouting_shape=shape, nodes=nodes)
                    tips, valleys = self.shouting_vertices(body, rect)
                    self.assertEqual(len(tips), nodes)
                    self.assertEqual(len(valleys), nodes)
                    self.assertNotEqual(body, previous)
                    self.assertEqual(body, body_path(
                        rect, "Shouting", irregularity=100, seed=17,
                        shouting_shape=shape, nodes=nodes))
                    self.assertTrue(path_data(body).endswith("Z"))
                    previous = body

    def test_thought_nodes_add_scaled_lobes_and_keep_the_cloud_connected(self):
        rect = QRectF(0, 0, 240, 100)
        from krita_speech_bubble_generator.bubbles import types as geometry_module
        for nodes in (8, 16, 32, 64):
            with self.subTest(nodes=nodes):
                with patch.object(geometry_module, "ellipse_path",
                                  wraps=geometry_module.ellipse_path) as lobe:
                    body = body_path(rect, "Thought", irregularity=79, seed=17, nodes=nodes)
                    self.assertEqual(lobe.call_count, nodes)
                    for call in lobe.call_args_list:
                        self.assertLessEqual(call.args[1], 0.24 * 16 / nodes * 1.5)
                        self.assertLessEqual(call.args[2], 0.30 * 16 / nodes * 1.5)
                self.assertEqual(body, body_path(
                    rect, "Thought", irregularity=79, seed=17, nodes=nodes))
                self.assertEqual(len(body.toSubpathPolygons()), 1)
                for degrees in range(0, 360, 5):
                    angle = math.radians(degrees)
                    point = rect.center() + QPointF(
                        rect.width() * 0.495 * math.cos(angle),
                        rect.height() * 0.495 * math.sin(angle))
                    self.assertTrue(body.contains(point))

    def test_invalid_node_counts_are_rejected(self):
        for style in ("Thought", "Shouting"):
            for nodes in (0, 7, 65, -1, 16.5, True, "16"):
                with self.subTest(style=style, nodes=nodes):
                    with self.assertRaisesRegex(ValueError, "Invalid node count"):
                        body_path(QRectF(0, 0, 240, 100), style, nodes=nodes)

    def test_shouting_has_smooth_curved_valleys_and_sharp_tips(self):
        body = body_path(QRectF(0, 0, 240, 100), "Shouting", irregularity=100, seed=17)
        self.assertIn("C", path_data(body))
        self.assertNotIn("L", path_data(body))
        self.assertEqual(sum(body.elementAt(i).isCurveTo()
                             for i in range(body.elementCount())), 48)

        def point(index):
            element = body.elementAt(index)
            return QPointF(element.x, element.y)

        for i in range(24):
            valley = point(3 + i * 6)
            incoming = valley - point(2 + i * 6)
            outgoing = point(4 + i * 6) - valley
            self.assertLess((incoming - outgoing).manhattanLength(), 1e-8)
            tip = point(6 + i * 6)
            incoming = tip - point(5 + i * 6)
            outgoing = point(7 + i * 6 if i < 23 else 1) - tip
            dot = incoming.x() * outgoing.x() + incoming.y() * outgoing.y()
            magnitude = math.hypot(incoming.x(), incoming.y()) * math.hypot(outgoing.x(), outgoing.y())
            self.assertLess(dot / magnitude, 0.95)

    def test_curved_shouting_preserves_the_inner_text_ellipse(self):
        rect = QRectF(0, 0, 400, 100)
        for shape in SHOUTING_SHAPES:
            for nodes in (8, 16, 64):
                for seed in range(10):
                    body = body_path(rect, "Shouting", irregularity=100, seed=seed,
                                     shouting_shape=shape, nodes=nodes)
                    for degrees in range(0, 360, 5):
                        angle = math.radians(degrees)
                        point = rect.center() + QPointF(
                            rect.width() * 0.495 * math.cos(angle),
                            rect.height() * 0.495 * math.sin(angle))
                        self.assertTrue(body.contains(point))

    def test_thought_cloud_irregularity_is_seeded_and_adjustable(self):
        rect = QRectF(0, 0, 240, 100)
        regular = body_path(rect, "Thought", irregularity=0, seed=17)
        self.assertEqual(regular, body_path(rect, "Thought", irregularity=0, seed=99))
        irregular = body_path(rect, "Thought", irregularity=100, seed=17)
        self.assertEqual(irregular, body_path(rect, "Thought", irregularity=100, seed=17))
        self.assertNotEqual(irregular, regular)
        self.assertNotEqual(irregular, body_path(rect, "Thought", irregularity=100, seed=99))
        self.assertEqual(len(irregular.toSubpathPolygons()), 1)
        self.assertTrue(irregular.contains(rect.center()))

    def test_thought_trail_irregularity_is_stable_and_keeps_body_intact(self):
        rect = QRectF(0, 0, 240, 100)
        body = body_path(rect, "Thought", irregularity=100, seed=17)
        tip = tail_tip(body, rect.center(), 0.7, 100)
        regular = bubble_path(body, rect.center(), tip, "Thought", 14, 150, 0, 17)
        self.assertEqual(regular, bubble_path(body, rect.center(), tip, "Thought", 14, 150, 0, 99))
        irregular = bubble_path(body, rect.center(), tip, "Thought", 14, 150, 100, 17)
        self.assertNotEqual(irregular, regular)
        self.assertEqual(irregular, bubble_path(body, rect.center(), tip, "Thought", 14, 150, 100, 17))
        self.assertNotEqual(irregular, bubble_path(body, rect.center(), tip, "Thought", 14, 150, 100, 99))
        self.assertEqual(body.subtracted(irregular).elementCount(), 0)

    def test_sharp_angle_tails_are_connected_on_elongated_bubbles(self):
        for width, height in ((800, 40), (40, 800), (1000, 10), (10, 1000)):
            rect = QRectF(0, 0, width, height)
            for style in ("Oval", "Rounded", "Square", "Shouting"):
                body = body_path(rect, style, 42, 100, 19)
                for length in (1, 10, 100):
                    for degrees in range(0, 360, 5):
                        with self.subTest(width=width, height=height, style=style,
                                          length=length, degrees=degrees):
                            tip = tail_tip(body, rect.center(), math.radians(degrees), length)
                            path = bubble_path(body, rect.center(), tip, style, 14)
                            self.assertEqual(len(path.toSubpathPolygons()), 1)
