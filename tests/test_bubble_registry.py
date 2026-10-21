from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from krita_speech_bubble_generator.bubbles.registry import (
    BUBBLE_TYPES, SHOUTING_ALGORITHMS, build_registry, resolve_bubble,
)
from krita_speech_bubble_generator.bubbles.types import BubbleCapabilities
from krita_speech_bubble_generator.bubbles.shouting_algorithms import ShoutingAlgorithm


class BubbleRegistryTests(unittest.TestCase):
    def test_builder_rejects_duplicate_type_and_algorithm_identifiers(self):
        for registry in (BUBBLE_TYPES, SHOUTING_ALGORITHMS):
            implementations = list(registry.values())
            duplicate = type(implementations[0])()
            with self.subTest(identifier=duplicate.identifier):
                with self.assertRaisesRegex(ValueError, "Duplicate registry identifier"):
                    build_registry(implementations + [duplicate])

    def test_builder_preserves_declaration_order_and_instances(self):
        implementations = list(reversed(list(BUBBLE_TYPES.values())))
        registry = build_registry(iter(implementations))
        self.assertEqual(list(registry), [bubble.identifier for bubble in implementations])
        for bubble in implementations:
            self.assertIs(registry[bubble.identifier], bubble)

    def test_selector_order_identifiers_and_legacy_node_counts(self):
        self.assertEqual(tuple(BUBBLE_TYPES.keys()),
                         ("Oval", "Rounded", "Square", "Thought", "Shouting"))
        self.assertEqual(tuple(SHOUTING_ALGORITHMS.keys()),
                         ("Balanced", "Angular", "Punchy", "Expressive"))
        for key, bubble in BUBBLE_TYPES.items():
            self.assertEqual(bubble.identifier, key)
            self.assertEqual(bubble.label, key)
            self.assertEqual(bubble.capabilities,
                             BubbleCapabilities(thought=key == "Thought",
                                                shouting=key == "Shouting",
                                                custom_enclosure=key in (
                                                    "Oval", "Thought", "Shouting")))
        for key, algorithm in SHOUTING_ALGORITHMS.items():
            self.assertEqual(algorithm.identifier, key)
            self.assertEqual(algorithm.label, key)
            self.assertEqual(algorithm.legacy_nodes, 18 if key == "Punchy" else 24)

    def test_unknown_and_unhashable_identifiers_raise_value_error(self):
        class UnhashableString(str):
            __hash__ = None

        for key in ("Unknown", "Round", None, 1, True, [], {}, set(),
                    UnhashableString("Oval")):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "bubble style"):
                    resolve_bubble(key)
        for key in ("Unknown", None, [], {}, UnhashableString("Balanced")):
            with self.subTest(algorithm=key):
                with self.assertRaisesRegex(ValueError, "shouting shape"):
                    resolve_bubble("Shouting", key)

    def test_capabilities_are_immutable_values(self):
        capabilities = BUBBLE_TYPES["Thought"].capabilities
        with self.assertRaises(FrozenInstanceError):
            capabilities.thought = False

    def test_added_algorithm_requires_no_dispatch_changes(self):
        class CustomAlgorithm(ShoutingAlgorithm):
            identifier = label = "Custom"

            def outline(self, nodes=None, irregularity=50, seed=0):
                return SHOUTING_ALGORITHMS["Angular"].outline(nodes, irregularity, seed)

        algorithm = CustomAlgorithm()
        with patch.dict(SHOUTING_ALGORITHMS, {algorithm.identifier: algorithm}):
            bubble = resolve_bubble("Shouting", algorithm.identifier)
            self.assertIs(bubble.algorithm, algorithm)
            self.assertEqual(tuple(SHOUTING_ALGORITHMS)[-1], "Custom")
