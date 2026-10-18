"""Krita registration and the editor composition/lifetime root."""

import random
from typing import Optional

from PyQt5.QtGui import QHideEvent, QShowEvent

from krita import (  # pyright: ignore[reportMissingModuleSource]
    DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita,
)

from .bubbles.renderer import BubbleRenderer
from .editor.presenter import EditorPresenter
from .editor.preferences import QtPreferencesStore
from .editor.view import BubbleEditorView
from .krita_host.gateway import KritaGateway


class SpeechBubbleDocker(DockWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Krita Speech Bubble Generator")
        self.view = BubbleEditorView(self)
        self.renderer = BubbleRenderer()
        self.gateway = KritaGateway(renderer=self.renderer)
        self.presenter = EditorPresenter(
            self.view, self.gateway, self.renderer, random.randrange, self,
            preferences=QtPreferencesStore())
        self.setWidget(self.view)

    def canvasChanged(self, canvas: object) -> None:
        self.presenter.canvas_changed()

    def showEvent(self, a0: Optional[QShowEvent]) -> None:
        super().showEvent(a0)
        self.presenter.shown()

    def hideEvent(self, a0: Optional[QHideEvent]) -> None:
        self.presenter.hidden()
        super().hideEvent(a0)


_registered = False


def register() -> None:
    global _registered
    if not _registered:
        Krita.instance().addDockWidgetFactory(DockWidgetFactory(
            "Krita Speech Bubble Generator", DockWidgetFactoryBase.DockRight, SpeechBubbleDocker))
        _registered = True
