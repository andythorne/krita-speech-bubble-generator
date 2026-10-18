"""Local editor preferences, separate from saved document records."""

import json
from typing import Mapping, Optional, cast

from PyQt5.QtCore import QSettings

from ..bubbles.settings import SettingsError, settings_from_dict
from .state import EditorPreferences


class QtPreferencesStore:
    def __init__(self, settings: Optional[QSettings] = None) -> None:
        self._settings = (settings if settings is not None else
                          QSettings("krita", "krita_speech_bubble_generator"))

    def load(self) -> Optional[EditorPreferences]:
        raw: object = self._settings.value("editor")
        self._check_status()
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise SettingsError("Invalid editor preferences")
        try:
            decoded: object = json.loads(raw)
        except ValueError as error:
            raise SettingsError("Invalid editor preferences: " + str(error)) from error
        if not isinstance(decoded, Mapping):
            raise SettingsError("Invalid editor preferences")
        values = cast(Mapping[str, object], decoded)
        if type(values.get("version")) is not int or values["version"] != 1:
            raise SettingsError("Unsupported editor preferences format")
        background = values.get("background_enabled", True)
        new_layer = values.get("new_layer", True)
        if type(background) is not bool or type(new_layer) is not bool:
            raise SettingsError("Invalid editor preferences options")
        return EditorPreferences(
            settings_from_dict(values.get("settings")), background, new_layer)

    def save(self, preferences: EditorPreferences) -> None:
        self._settings.setValue("editor", json.dumps({
            "version": 1,
            "settings": preferences.settings.to_dict(),
            "background_enabled": preferences.background_enabled,
            "new_layer": preferences.new_layer,
        }, allow_nan=False))
        self._settings.sync()
        self._check_status()

    def _check_status(self) -> None:
        if self._settings.status() != QSettings.Status.NoError:
            raise SettingsError("Cannot access the saved editor preferences")
