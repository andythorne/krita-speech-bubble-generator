import hashlib
import unittest

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QTransform

from krita_speech_bubble_generator.bubbles.geometry import (
    body_path, bubble_path, path_data, tail_tip,
)
from krita_speech_bubble_generator.bubbles.registry import (
    BUBBLE_TYPES, SHOUTING_ALGORITHMS, resolve_bubble,
)
from krita_speech_bubble_generator.bubbles.types import (
    BodyParameters, BubbleCapabilities, BubbleType, ShoutingBubble, TailParameters,
)
from krita_speech_bubble_generator.bubbles.shouting_algorithms import (
    ShoutingAlgorithm, ShoutingOutline,
)


# Captured with straight, tapered tails aligned to the bubble-center-to-tip axis.
# Quantization makes the fixture insensitive to insignificant platform float noise.
BASELINE_OUTLINES = {
    ("Oval", "Balanced"): "18a72f29dc7fa29fe42712387f2c8f790ec6716f2a758fab230f4f37b1541142",
    ("Rounded", "Balanced"): "977ec98c323c78ca891fd9a7bdd4d2fed4e10d6050d8b90a840cf7a6c979d2b8",
    ("Square", "Balanced"): "bfed0596b1825d9c402af8d8a26c99bc83557f39308ad91b831ef99ccdc21e05",
    ("Thought", "Balanced"): "05c761a460ab639815b2662c9a4db1938c9a446dd1466ec27962733ba7e5e9fd",
    ("Shouting", "Balanced"): "fd0fc4f480f47a84cc7aeb140391443d69a24993a0eda3e604708def0b7cc99c",
    ("Shouting", "Angular"): "90a2ea7183c66ddc6a68d5acbb9a117d55267d8103c8280464120eef1ec53667",
    ("Shouting", "Punchy"): "f62a577061c736b1d1e26a5e0790a21759f784a284436f65d0f4e0f45edd422f",
    ("Shouting", "Expressive"): "24593c819fd979adf63f2a25e0b4161766fdfbbd8b0d906e78dfd7ac86dd4bbc",
}


def update_fingerprint(digest, path):
    digest.update(str(path.elementCount()).encode("ascii"))
    for i in range(path.elementCount()):
        element = path.elementAt(i)
        digest.update("{}:{:.8f},{:.8f};".format(
            element.type, element.x, element.y).encode("ascii"))


class GeometryStrategyTests(unittest.TestCase):
    def test_families_are_explicit_abstract_contracts(self):
        with self.assertRaises(TypeError):
            BubbleType()
        with self.assertRaises(TypeError):
            ShoutingAlgorithm()
        self.assertEqual(len({type(value) for value in BUBBLE_TYPES.values()}), 5)
        self.assertEqual(len({type(value) for value in SHOUTING_ALGORITHMS.values()}), 4)
        for bubble in BUBBLE_TYPES.values():
            self.assertIsInstance(bubble, BubbleType)
            self.assertEqual(type(bubble).__bases__, (BubbleType,))
            self.assertIsInstance(bubble.capabilities, BubbleCapabilities)
        for algorithm in SHOUTING_ALGORITHMS.values():
            self.assertIsInstance(algorithm, ShoutingAlgorithm)
            self.assertEqual(type(algorithm).__bases__, (ShoutingAlgorithm,))

    def test_saved_seed_outlines_and_center_aligned_tails_match_control_points(self):
        for (style, algorithm), expected in BASELINE_OUTLINES.items():
            with self.subTest(style=style, algorithm=algorithm):
                digest = hashlib.sha256()
                for rect in (QRectF(0, 0, 240, 100),
                             QRectF(-13.25, 21.5, 83.75, 179.125)):
                    for nodes in (None, 8, 24, 64):
                        for amount, seed in ((0, 99), (50, 0), (79, 17),
                                             (100, 2147483647)):
                            body = body_path(
                                rect, style, 19.75, amount, seed, algorithm, nodes)
                            update_fingerprint(digest, body)
                            for angle in (-2.7, 0, 1.3):
                                tip = tail_tip(body, rect.center(), angle, 37)
                                update_fingerprint(digest, bubble_path(
                                    body, rect.center(), tip, style, 14, 175,
                                    amount, seed))
                self.assertEqual(digest.hexdigest(), expected)

    def test_shouting_composes_an_injected_normalized_outline(self):
        class Diamond(ShoutingAlgorithm):
            identifier = label = "Diamond"

            def outline(self, nodes=None, irregularity=50, seed=0):
                self.received = (nodes, irregularity, seed)
                return ShoutingOutline(QPointF(0, -1), (
                    (QPointF(1, 0),), (QPointF(0, 1),), (QPointF(-1, 0),)))

        algorithm = Diamond()
        bubble = ShoutingBubble(algorithm)
        path = bubble.body_path(QRectF(10, 20, 80, 40), BodyParameters(
            irregularity=79, seed=17, nodes=8))
        self.assertEqual(algorithm.received, (8, 79, 17))
        self.assertEqual(path.boundingRect(), QRectF(10, 20, 80, 40))
        self.assertEqual(path.elementAt(0).x, 50)
        self.assertEqual(path.elementAt(0).y, 20)

    def test_mapping_precedes_quadratic_to_cubic_conversion(self):
        outline = ShoutingOutline(QPointF(-0.17, 0.63), (
            (QPointF(0.234, -0.732), QPointF(0.991, 0.37)),))
        transform = QTransform().translate(31.7, -2.9).scale(119.3, 53.1)
        path = outline.to_path(transform)
        expected = QPainterPath()
        expected.moveTo(transform.map(outline.start))
        expected.quadTo(transform.map(outline.segments[0][0]),
                        transform.map(outline.segments[0][1]))
        expected.closeSubpath()
        self.assertEqual(path_data(path), path_data(expected))

    def test_composition_does_not_mutate_shared_algorithms(self):
        rect = QRectF(0, 0, 240, 100)
        balanced = resolve_bubble("Shouting")
        first = balanced.body_path(rect, BodyParameters(seed=17))
        expressive = resolve_bubble("Shouting", "Expressive")
        expressive.body_path(rect, BodyParameters(seed=99))
        self.assertEqual(balanced.body_path(rect, BodyParameters(seed=17)), first)
        self.assertIs(balanced.algorithm, SHOUTING_ALGORITHMS["Balanced"])
        self.assertIs(expressive.algorithm, SHOUTING_ALGORITHMS["Expressive"])

    def test_types_share_enclosure_and_tail_contracts(self):
        for bubble in BUBBLE_TYPES.values():
            with self.subTest(style=bubble.identifier):
                rect = bubble.body_rect(60, 20, 15)
                self.assertEqual(rect.topLeft(), QPointF())
                self.assertGreaterEqual(rect.width(), 90)
                self.assertGreaterEqual(rect.height(), 50)
                body = bubble.body_path(rect)
                self.assertEqual(bubble.compose_tail(
                    body, rect.center(), None, TailParameters(14)), body)
                self.assertEqual(bubble.compose_tail(
                    body, rect.center(), rect.center(), TailParameters(14)), body)
                self.assertTrue(body.contains(rect.center()))

    def test_invalid_counts_are_rejected_at_both_geometry_boundaries(self):
        for nodes in (True, False, 7, 65, 24.0, "24", [], {}):
            with self.subTest(nodes=nodes):
                with self.assertRaises(ValueError):
                    BodyParameters(nodes=nodes)
                for algorithm in SHOUTING_ALGORITHMS.values():
                    with self.assertRaises(ValueError):
                        algorithm.outline(nodes=nodes)
