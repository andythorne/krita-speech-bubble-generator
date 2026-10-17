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


# Captured from the pre-refactor implementation, including its tail composition.
# Quantization makes the fixture insensitive to insignificant platform float noise.
BASELINE_OUTLINES = {
    ("Oval", "Balanced"): "6d0476196587299321b8c92bd7f00d25c5fc7dfb2049f082798045fa77a1913a",
    ("Rounded", "Balanced"): "593b6cd516d27e4d0e2279f66e2417bf7d57b32503e1fa2cdcc8a118cbcc6399",
    ("Square", "Balanced"): "94835c016130c78ff39db063511e6b6d09953831c9afd18b9981f627eea86070",
    ("Thought", "Balanced"): "05c761a460ab639815b2662c9a4db1938c9a446dd1466ec27962733ba7e5e9fd",
    ("Shouting", "Balanced"): "99ebd87d2b14f3fa56d7dc89d02c3dca305b5ebb1aa6bd14ace4b09b69e3511a",
    ("Shouting", "Angular"): "3c89e2cdf1461fe470e38f3ad9045ad183871b85f07970e6262983918ee5ff7e",
    ("Shouting", "Punchy"): "8e8c6103022901e3c380cf73673ce6142e6c44b575b1b460511a4e98b2e85a20",
    ("Shouting", "Expressive"): "c13d7420b6827e7442ae432073c35c71dab1b9cb8ed691c54e0eb2df287e89f9",
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

    def test_saved_seed_outlines_and_tails_match_original_control_points(self):
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
