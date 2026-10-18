from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
import math
import unittest

from PyQt5.QtGui import QTransform

from krita_speech_bubble_generator.bubbles.settings import (
    BubbleSettings, INTEGER_RANGES, SettingsError, decode_record, encode_record,
    settings_from_dict, transform_values, validate_settings,
)


class SettingsTests(unittest.TestCase):
    def test_defaults_use_oval_without_overriding_saved_styles(self):
        self.assertEqual(BubbleSettings().style, "Oval")
        self.assertEqual(settings_from_dict({}).style, "Oval")
        for style in ("Oval", "Rounded", "Square", "Thought", "Shouting"):
            with self.subTest(style=style):
                self.assertEqual(settings_from_dict({"style": style}).style, style)

    def test_serialization_includes_every_setting_with_its_current_value(self) -> None:
        changed = BubbleSettings(
            style="Shouting", text="Changed", font="Serif", font_size=20,
            fill="#123456", stroke="#654321", text_color="#112233",
            outline=5, padding=120, autocenter=False, line_length=30,
            optical_center=True,
            oval_custom=True, oval_vertical_padding=35, oval_squareness=65,
            tail_length=50, tail_angle=-1.5, lock_tail=False, thought_size=125,
            tail_curve=73, tail_curve_direction="Down",
            shout_irregularity=70, shout_shape="Expressive", shout_nodes=32,
            shout_seed=123, thought_irregularity=60, thought_nodes=20,
            thought_seed=456)
        for settings in (BubbleSettings(), changed):
            with self.subTest(settings=settings):
                self.assertEqual(settings.to_dict(), {"version": 1, **asdict(settings)})

    def record(self, **changes):
        values = BubbleSettings().to_dict()
        values["baseline"] = [1, 0, 0, 1, -7, 12]
        values.update(changes)
        return values

    def test_settings_are_immutable_and_baseline_is_not_an_editable_field(self):
        settings = BubbleSettings()
        with self.assertRaises(FrozenInstanceError):
            settings.text = "Changed"
        self.assertNotIn("baseline", settings.to_dict())
        self.assertNotIn("version", settings.__dataclass_fields__)
        self.assertNotEqual(settings, replace(settings, text="Changed"))

    def test_complete_record_round_trip(self):
        settings = replace(
            BubbleSettings(), style="Shouting", text="A & B\n\u00e9!",
            font="Serif", tail_length=80, tail_angle=-2.8,
            lock_tail=False, shout_shape="Expressive", shout_seed=1729,
            thought_seed=2718, shout_nodes=37, thought_nodes=29,
            tail_curve=73, tail_curve_direction="Down", oval_custom=True,
            oval_vertical_padding=35, oval_squareness=65, optical_center=True)
        baseline = QTransform(0.8, 0.2, -0.1, 1.5, -7, 12)
        encoded = encode_record(settings, baseline)
        record = decode_record(encoded)
        self.assertEqual(record.settings, settings)
        self.assertEqual(record.baseline, transform_values(baseline))
        self.assertEqual(json.loads(encoded)["version"], 1)

    def test_fresh_defaults_are_distinct_from_legacy_defaults(self):
        values = self.record(style="Round")
        for field in (
            "lock_tail", "thought_size", "shout_irregularity", "shout_seed",
            "shout_shape", "shout_nodes", "thought_irregularity", "thought_nodes",
            "thought_seed", "padding", "tail_curve", "tail_curve_direction",
            "oval_custom", "oval_vertical_padding", "oval_squareness",
            "optical_center",
        ):
            del values[field]
        old = deepcopy(values)
        normalized = validate_settings(values)
        self.assertEqual(values, old)
        self.assertEqual(normalized["style"], "Rounded")
        self.assertEqual(normalized["shout_irregularity"], 0)
        self.assertEqual(normalized["thought_irregularity"], 0)
        self.assertEqual(normalized["shout_nodes"], 24)
        self.assertEqual(normalized["thought_nodes"], 16)
        self.assertEqual(normalized["padding"], 150)
        self.assertTrue(normalized["lock_tail"])
        self.assertEqual(normalized["tail_curve"], 0)
        self.assertEqual(normalized["tail_curve_direction"], "Up")
        self.assertFalse(normalized["oval_custom"])
        self.assertEqual(normalized["oval_vertical_padding"], 150)
        self.assertEqual(normalized["oval_squareness"], 0)
        self.assertFalse(normalized["optical_center"])
        fresh = settings_from_dict({})
        self.assertEqual(fresh.shout_irregularity, 50)
        self.assertEqual(fresh.thought_irregularity, 50)

    def test_legacy_punchy_node_default_is_not_fresh_node_default(self):
        values = self.record(shout_shape="Punchy")
        del values["shout_nodes"]
        self.assertEqual(validate_settings(values)["shout_nodes"], 18)
        self.assertEqual(
            settings_from_dict({"shout_shape": "Punchy"}).shout_nodes, 24)

    def test_each_integer_field_rejects_bool_fraction_and_out_of_range(self):
        for field, (low, high) in INTEGER_RANGES.items():
            for value in (True, False, low - 1, high + 1, 1.5, "3", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(SettingsError, "Invalid " + field):
                        validate_settings(self.record(**{field: value}))

    def test_tail_limit_follows_font_size(self):
        validate_settings(self.record(font_size=2, tail_length=20))
        for value in (-1, 21, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "tail_length"):
                    validate_settings(self.record(font_size=2, tail_length=value))

    def test_invalid_identifiers_have_explicit_errors(self):
        for key, message in (("style", "Unsupported bubble format"),
                             ("shout_shape", "Invalid shouting shape")):
            for value in ("Unknown", "", None, 42, [], {}):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(SettingsError, message):
                        validate_settings(self.record(**{key: value}))

    def test_saved_version_is_required_and_not_a_boolean(self):
        for value in (True, False, 0, 2, 1.0, None, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "Unsupported"):
                    validate_settings(self.record(version=value))
        values = self.record()
        del values["version"]
        with self.assertRaises(SettingsError):
            validate_settings(values)

    def test_invalid_tail_curve_directions_are_rejected(self):
        for value in ("Unknown", "up", "", None, 42, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "tail curve direction"):
                    validate_settings(self.record(tail_curve_direction=value))

    def test_missing_required_fields_do_not_become_fresh_defaults(self):
        for key in ("text", "font", "font_size", "tail_length", "autocenter"):
            values = self.record()
            del values[key]
            with self.subTest(key=key), self.assertRaisesRegex(SettingsError, key):
                validate_settings(values)

    def test_malformed_json_and_non_record_values_fail_explicitly(self):
        for value in (b"\xff", b"{", b"null", b"[]", b"1", b'"text"'):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                decode_record(value)

    def test_invalid_baselines_are_rejected(self):
        for value in (
            None, 1, "matrix", {}, [], [1, 0, 0, 1, 0],
            [1, 0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 0, 0],
            [1, 0, 0, 1, math.inf, 0], [1, 0, 0, 1, math.nan, 0],
            [1, 0, 0, 1, True, 0], [1, 0, 0, 1, "0", 0],
            [1, 0, 0, 1, 10 ** 400, 0],
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "bubble transform"):
                    validate_settings(self.record(baseline=value))

    def test_invalid_angles_are_rejected(self):
        for value in (math.inf, -math.inf, math.nan, True, None, "0", 10 ** 400):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "tail angle"):
                    validate_settings(self.record(tail_angle=value))

    def test_invalid_colors_and_boolean_controls_are_rejected(self):
        for key in ("fill", "stroke", "text_color"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(SettingsError, key):
                    validate_settings(self.record(**{key: "not-a-color"}))
        for key in ("autocenter", "lock_tail", "oval_custom", "optical_center"):
            for value in (0, 1, "true", None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(SettingsError):
                        validate_settings(self.record(**{key: value}))

    def test_encoding_also_validates_settings_and_baseline(self):
        with self.assertRaisesRegex(SettingsError, "padding"):
            encode_record(replace(BubbleSettings(), padding=-1), QTransform())
        with self.assertRaisesRegex(SettingsError, "bubble transform"):
            encode_record(BubbleSettings(), QTransform(0, 0, 0, 0, 0, 0))

    def test_unknown_metadata_does_not_leak_into_editable_values(self):
        values = self.record(future_metadata={"extra": "data"})
        settings = settings_from_dict(values, legacy=True)
        self.assertNotIn("future_metadata", settings.to_dict())
        self.assertEqual(values["future_metadata"], {"extra": "data"})
