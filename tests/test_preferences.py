from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt5.QtCore import QSettings

from krita_speech_bubble_generator.bubbles.settings import BubbleSettings, SettingsError
from krita_speech_bubble_generator.editor.preferences import QtPreferencesStore
from krita_speech_bubble_generator.editor.state import EditorPreferences


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "preferences.ini")

    def store(self):
        return QtPreferencesStore(QSettings(self.path, QSettings.IniFormat))

    def test_absent_preferences_do_not_replace_fresh_defaults(self):
        self.assertIsNone(self.store().load())

    def test_preferences_survive_a_new_store_and_preserve_all_bubble_settings(self):
        expected = EditorPreferences(replace(
            BubbleSettings(), style="Shouting", text="Remember me\nand this line",
            font="DejaVu Sans", font_size=22, padding=43, outline=7,
            tail_angle=-0.5, tail_length=83, shout_shape="Expressive",
            thought_nodes=27, shout_seed=1729, thought_seed=2718,
            tail_curve=73, tail_curve_direction="Down"),
            background_enabled=False, new_layer=False)
        self.store().save(expected)
        self.assertTrue(Path(self.path).is_file())
        self.assertEqual(self.store().load(), expected)

    def test_invalid_preferences_are_not_silently_ignored(self):
        for raw in ("invalid json", "[]", '{"version": 2}',
                    '{"version": 1, "settings": {"padding": -1}}',
                    '{"version": 1, "settings": {}, "new_layer": 1}'):
            with self.subTest(raw=raw):
                settings = QSettings(self.path, QSettings.IniFormat)
                settings.setValue("editor", raw)
                settings.sync()
                with self.assertRaises(SettingsError):
                    self.store().load()

    def test_missing_new_fields_keep_fresh_defaults(self):
        settings = QSettings(self.path, QSettings.IniFormat)
        settings.setValue("editor", json.dumps({
            "version": 1, "settings": {"text": "Older preferences"}}))
        settings.sync()
        self.assertEqual(self.store().load(), EditorPreferences(
            replace(BubbleSettings(), text="Older preferences")))
