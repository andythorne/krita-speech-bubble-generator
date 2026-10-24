from copy import deepcopy
from collections import UserDict
from dataclasses import FrozenInstanceError, asdict, fields, replace
import json
import math
import unittest

from PyQt5.QtGui import QTransform

from krita_speech_bubble_generator.bubbles.settings import (
    BubbleSettings, INTEGER_RANGES, STYLE_FIELDS, SettingsError, TextStyle, decode_record, encode_record,
    settings_from_dict, transform_values, validate_settings,
)


class SettingsTests(unittest.TestCase):
    def test_style_transfer_copies_text_appearance_bubble_options_and_tail_curvature(self):
        source = BubbleSettings(
            shape="Tracing", style="Shouting", wrapping="Diamond", text_alignment="Right",
            text="Source", font="Serif", font_size=28,
            text_color="#112233", text_styles=(TextStyle(0, 3, True),),
            fill="#123456", stroke="#654321", outline=7, padding=65,
            oval_custom=True, oval_vertical_padding=35, oval_squareness=80,
            autocenter=False, optical_center=True, line_length=32,
            tail_length=150, tail_angle=-2.1, lock_tail=False,
            tail_curve=73, tail_curve_direction="Down", thought_size=275, thought_blobs=7,
            shout_shape="Expressive", shout_nodes=37, shout_irregularity=85,
            thought_nodes=29, thought_irregularity=75,
            shout_seed=1729, thought_seed=2718)
        target = replace(BubbleSettings(), shout_seed=123, thought_seed=456,
                         text_styles=(TextStyle(0, 5, False, True),))
        style_fields = (
            "style", "shape", "wrapping", "text_alignment",
            "fill", "stroke", "outline", "padding", "oval_custom",
            "oval_vertical_padding", "oval_squareness", "shout_shape", "shout_nodes",
            "shout_irregularity", "thought_nodes", "thought_irregularity",
            "tail_curve", "tail_curve_direction", "font", "font_size",
            "text_color", "autocenter", "optical_center", "line_length",
            "thought_size", "thought_blobs", "thought_seed", "shout_seed")
        self.assertEqual(set(STYLE_FIELDS), set(style_fields))
        self.assertEqual(
            set(style_fields) | {
                "text", "text_styles", "tail_angle", "tail_length", "lock_tail",
                "tail_enabled", "tail_advanced", "tail_start_angle", "tail_end_x", "tail_end_y"},
            {field.name for field in fields(BubbleSettings)})
        expected = replace(target, **{name: getattr(source, name) for name in style_fields})
        self.assertEqual(target.with_style_from(source), expected)
        self.assertEqual(target.shout_seed, 123)
        self.assertEqual(source.text, "Source")

    def test_defaults_use_oval_without_overriding_saved_styles(self):
        self.assertEqual((BubbleSettings().shape, BubbleSettings().style), ("Oval", "Sharp"))
        self.assertEqual(settings_from_dict({}).wrapping, "Standard")
        mapping = {"Oval": ("Oval", "Sharp"), "Rounded": ("Square", "Rounded"),
                   "Square": ("Square", "Sharp"), "Thought": ("Oval", "Thought"),
                   "Shouting": ("Oval", "Shouting")}
        for style, expected in mapping.items():
            with self.subTest(style=style):
                settings = settings_from_dict({"style": style})
                self.assertEqual((settings.shape, settings.style), expected)

    def test_serialization_includes_every_setting_with_its_current_value(self) -> None:
        changed = BubbleSettings(
            style="Shouting", text="Changed", font="Serif", font_size=20,
            fill="#123456", stroke="#654321", text_color="#112233",
            outline=5, padding=120, autocenter=False, line_length=30,
            optical_center=True,
            oval_custom=True, oval_vertical_padding=35, oval_squareness=65,
            tail_length=50, tail_angle=-1.5, lock_tail=False, thought_size=125, thought_blobs=10,
            tail_curve=73, tail_curve_direction="Down",
            shout_irregularity=70, shout_shape="Expressive", shout_nodes=32,
            shout_seed=123, thought_irregularity=60, thought_nodes=20,
            thought_seed=456, text_styles=(TextStyle(0, 3, bold=True),))
        for settings in (BubbleSettings(), changed):
            with self.subTest(settings=settings):
                expected = {"version": 1, **asdict(settings)}
                expected["text_styles"] = list(expected["text_styles"])
                self.assertEqual(settings.to_dict(), expected)

    def record(self, **changes):
        values = BubbleSettings().to_dict()
        values["baseline"] = [1, 0, 0, 1, -7, 12]
        values.update(changes)
        return values

    def test_text_alignment_defaults_round_trips_and_validates(self):
        self.assertEqual(BubbleSettings().text_alignment, "Center")
        values = self.record(style="Square")
        del values["text_alignment"]
        del values["shape"]
        original = deepcopy(values)
        for legacy in (False, True):
            loaded = settings_from_dict(values, legacy=legacy)
            self.assertEqual((loaded.shape, loaded.text_alignment), ("Square", "Center"))
        self.assertEqual(decode_record(json.dumps(values).encode()).settings.text_alignment,
                         "Center")
        self.assertEqual(values, original)
        for alignment in ("Left", "Center", "Right"):
            settings = BubbleSettings(shape="Square", text_alignment=alignment)
            self.assertEqual(decode_record(encode_record(settings, QTransform())).settings,
                             settings)
        for alignment in ("left", "Justify", "", None, True, 1, []):
            with self.subTest(alignment=alignment), self.assertRaises(SettingsError):
                settings_from_dict(self.record(text_alignment=alignment), legacy=True)

    def test_tail_placement_round_trips_without_becoming_a_copied_style(self):
        settings = BubbleSettings(
            tail_enabled=False, tail_advanced=True, tail_start_angle=-1.2,
            tail_end_x=225.5, tail_end_y=-87.25, tail_length=70, lock_tail=True)
        self.assertEqual(decode_record(encode_record(settings, QTransform())).settings, settings)
        pasted = settings.with_style_from(BubbleSettings(tail_curve=50))
        self.assertEqual(pasted, replace(settings, tail_curve=50))

    def test_thought_blob_count_defaults_round_trips_and_rejects_invalid_values(self):
        self.assertEqual(INTEGER_RANGES["thought_blobs"], (1, 10))
        self.assertEqual(BubbleSettings().thought_blobs, 3)
        values = self.record()
        del values["thought_blobs"]
        for legacy in (False, True):
            self.assertEqual(settings_from_dict(values, legacy=legacy).thought_blobs, 3)
        for count in range(1, 11):
            settings = replace(BubbleSettings(), thought_blobs=count)
            self.assertEqual(decode_record(encode_record(settings, QTransform())).settings,
                             settings)
        for count in (0, 11, -1, True, 3.0, "3", None):
            with self.subTest(count=count), self.assertRaises(SettingsError):
                settings_from_dict(self.record(thought_blobs=count), legacy=True)

    def test_older_tail_settings_default_to_enabled_simple_mode(self):
        values = self.record(tail_length=73)
        new_fields = ("tail_enabled", "tail_advanced", "tail_start_angle",
                      "tail_end_x", "tail_end_y")
        for key in new_fields:
            del values[key]
        original = deepcopy(values)
        for legacy in (False, True):
            settings = settings_from_dict(values, legacy=legacy)
            self.assertTrue(settings.tail_enabled)
            self.assertFalse(settings.tail_advanced)
            self.assertIsNone(settings.tail_start_angle)
            self.assertIsNone(settings.tail_end_x)
            self.assertIsNone(settings.tail_end_y)
            self.assertEqual(settings.tail_length, 73)
        self.assertEqual(values, original)

    def test_invalid_tail_modes_and_placement_are_rejected(self):
        for key in ("tail_enabled", "tail_advanced"):
            for value in (0, 1, "true", None):
                with self.subTest(key=key, value=value), self.assertRaises(SettingsError):
                    settings_from_dict(self.record(**{key: value}), legacy=True)
        for key in ("tail_start_angle", "tail_end_x", "tail_end_y"):
            for value in (True, "1", float("nan"), float("inf"), [], {}):
                with self.subTest(key=key, value=value), self.assertRaises(SettingsError):
                    settings_from_dict(self.record(**{key: value}), legacy=True)
        for values in ({"tail_end_x": 1}, {"tail_end_y": 1}):
            with self.subTest(values=values), self.assertRaises(SettingsError):
                settings_from_dict(self.record(**values), legacy=True)

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
            oval_vertical_padding=35, oval_squareness=65, optical_center=True,
            text_styles=(TextStyle(0, 1, bold=True),
                         TextStyle(1, 5, italic=True),
                         TextStyle(5, 8, bold=True, italic=True)))
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
            "text_styles",
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
        self.assertEqual(normalized["text_styles"], [])
        fresh = settings_from_dict({})
        self.assertEqual(fresh.shout_irregularity, 50)
        self.assertEqual(fresh.thought_irregularity, 50)
        self.assertEqual((fresh.shout_nodes, fresh.thought_nodes), (10, 10))
        self.assertEqual((BubbleSettings().shout_nodes, BubbleSettings().thought_nodes), (10, 10))

    def test_node_defaults_never_replace_explicit_persisted_values(self):
        for shout, thought in ((24, 16), (37, 29), (10, 10)):
            settings = BubbleSettings(shout_nodes=shout, thought_nodes=thought)
            self.assertEqual(settings_from_dict(settings.to_dict()), settings)
            self.assertEqual(decode_record(encode_record(settings, QTransform())).settings,
                             settings)

    def test_style_transfer_preserves_target_emphasis_not_source_offsets(self):
        source = BubbleSettings(text="A long source", text_styles=(TextStyle(5, 13, True),))
        for text, runs in (("", ()), ("X", (TextStyle(0, 1, False, True),))):
            target = BubbleSettings(text=text, text_styles=runs)
            pasted = target.with_style_from(source)
            self.assertEqual((pasted.text, pasted.text_styles), (text, runs))
            self.assertEqual(decode_record(encode_record(pasted, QTransform())).settings, pasted)

    def test_text_styles_default_to_empty_for_fresh_and_saved_settings(self):
        self.assertEqual(BubbleSettings().text_styles, ())
        self.assertEqual(settings_from_dict({}).text_styles, ())
        values = self.record()
        del values["text_styles"]
        self.assertEqual(settings_from_dict(values).text_styles, ())
        self.assertEqual(settings_from_dict(values, legacy=True).text_styles, ())
        self.assertEqual(decode_record(json.dumps(values).encode()).settings.text_styles, ())

    def test_text_styles_are_immutable_and_encode_as_lists_of_dicts(self):
        run = TextStyle(0, 1, bold=True)
        self.assertFalse(run.italic)
        self.assertFalse(TextStyle(0, 1).bold)
        with self.assertRaises(FrozenInstanceError):
            run.bold = False
        settings = replace(BubbleSettings(), text_styles=(run,))
        values = settings.to_dict()
        self.assertEqual(values["text_styles"], [
            {"start": 0, "end": 1, "bold": True, "italic": False}])
        self.assertEqual(settings_from_dict(values), settings)
        values["text_styles"][0]["end"] = 2
        self.assertEqual(settings.text_styles, (run,))

    def test_text_styles_accept_mapping_runs_and_python_unicode_offsets(self):
        text = "A\U0001f600e\u0301Z"
        runs = (
            UserDict(start=1, end=2, bold=True, italic=False),
            UserDict(start=2, end=4, bold=False, italic=True),
            UserDict(start=4, end=5, bold=True, italic=True),
        )
        values = self.record(text=text, text_styles=runs)
        original = deepcopy(values)
        expected = (TextStyle(1, 2, bold=True), TextStyle(2, 4, italic=True),
                    TextStyle(4, 5, bold=True, italic=True))
        self.assertEqual(settings_from_dict(values).text_styles, expected)
        self.assertEqual(validate_settings(values)["text_styles"],
                         [dict(run) for run in runs])
        self.assertEqual(values, original)
        settings = settings_from_dict(values)
        self.assertEqual(decode_record(encode_record(settings, QTransform())).settings,
                         settings)

    def test_malformed_text_styles_are_rejected(self):
        run = {"start": 0, "end": 2, "bold": True, "italic": False}
        invalid = [None, True, 1, "runs", {}, [None], [1], ["run"],
                   [[]], [TextStyle(0, 1, bold=True)]]
        for field in ("start", "end"):
            for value in (None, True, False, 1.0, "1", [], {}):
                invalid.append([{**run, field: value}])
            invalid.append([{key: value for key, value in run.items() if key != field}])
        for field in ("bold", "italic"):
            for value in (None, 0, 1, "true", [], {}):
                invalid.append([{**run, field: value}])
            invalid.append([{key: value for key, value in run.items() if key != field}])
        invalid.extend([
            [{**run, "start": -1}],
            [{**run, "start": 2}],
            [{**run, "end": 0}],
            [{**run, "end": -1}],
            [{**run, "end": 6}],
            [{**run, "bold": False}],
            [run, {**run, "start": 1, "end": 3}],
            [{**run, "start": 2, "end": 3}, run],
            [run, run],
        ])
        for value in invalid:
            with self.subTest(value=value):
                values = self.record(text="A\U0001f600e\u0301Z", text_styles=value)
                with self.assertRaisesRegex(SettingsError, "text_styles"):
                    settings_from_dict(values)
                with self.assertRaisesRegex(SettingsError, "text_styles"):
                    validate_settings(values)
        with self.assertRaisesRegex(SettingsError, "text_styles"):
            settings_from_dict({"text": "", "text_styles": [run]})
        self.assertEqual(settings_from_dict({"text": "", "text_styles": []}).text_styles, ())

    def test_optional_layer_identity_round_trips_without_changing_editable_settings(self):
        settings = BubbleSettings()
        layer_id = "{7c808a68-555b-4f38-b84d-075b92a8913a}"
        encoded = encode_record(settings, QTransform(), layer_id)
        record = decode_record(encoded)
        self.assertEqual(record.settings, settings)
        self.assertEqual(record.layer_id, layer_id)
        self.assertEqual(json.loads(encoded)["version"], 1)
        self.assertNotIn("layer_id", record.settings.to_dict())
        self.assertEqual(decode_record(encode_record(settings, QTransform())).layer_id, "")
        self.assertNotIn("layer_id", json.loads(encode_record(settings, QTransform())))

    def test_invalid_saved_layer_identities_are_rejected(self):
        for value in (None, True, 17, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SettingsError, "layer identity"):
                    decode_record(json.dumps(self.record(layer_id=value)).encode())

    def test_legacy_punchy_node_default_is_not_fresh_node_default(self):
        values = self.record(shout_shape="Punchy")
        del values["shout_nodes"]
        self.assertEqual(validate_settings(values)["shout_nodes"], 18)
        self.assertEqual(
            settings_from_dict({"shout_shape": "Punchy"}).shout_nodes, 10)

    def test_each_integer_field_rejects_bool_fraction_and_out_of_range(self):
        for field, (low, high) in INTEGER_RANGES.items():
            for value in (True, False, low - 1, high + 1, 1.5, "3", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(SettingsError, "Invalid " + field):
                        validate_settings(self.record(**{field: value}))

    def test_absolute_tail_length_round_trips_independently_of_font_size(self):
        for locked in (True, False):
            for font_size, length in ((14, 650), (10, 400), (1, 990), (99, 0)):
                with self.subTest(locked=locked, font_size=font_size, length=length):
                    settings = BubbleSettings(font_size=font_size, tail_length=length,
                                              tail_angle=-1.2, lock_tail=locked)
                    self.assertEqual(settings_from_dict(settings.to_dict()), settings)
                    self.assertEqual(
                        decode_record(encode_record(settings, QTransform())).settings, settings)

    def test_tail_length_rejects_invalid_values_and_retains_overall_maximum(self):
        for value in (-1, 991, True, False, 1.5, 650.0, "650", None,
                      math.nan, math.inf, -math.inf, 10 ** 400):
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
        with self.assertRaisesRegex(SettingsError, "text_styles"):
            encode_record(replace(BubbleSettings(), text_styles=(TextStyle(0, 1),)),
                          QTransform())

    def test_unknown_metadata_does_not_leak_into_editable_values(self):
        values = self.record(future_metadata={"extra": "data"})
        settings = settings_from_dict(values, legacy=True)
        self.assertNotIn("future_metadata", settings.to_dict())
        self.assertEqual(values["future_metadata"], {"extra": "data"})
