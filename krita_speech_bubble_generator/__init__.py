"""Bootstrap only when Krita is available; library imports remain hostless."""

import importlib


def _bootstrap() -> None:
    try:
        importlib.import_module("krita")
    except ModuleNotFoundError as error:
        if error.name != "krita":
            raise
        return
    from .krita_speech_bubble_generator import SpeechBubbleDocker, register
    globals()["SpeechBubbleDocker"] = SpeechBubbleDocker
    register()


_bootstrap()
