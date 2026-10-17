"""Development declarations for the Krita API used by this plugin."""

from typing import Type

from PyQt5.QtWidgets import QDockWidget

from krita_speech_bubble_generator.krita_host.contracts import Host


class DockWidget(QDockWidget):
    def canvasChanged(self, canvas: object) -> None: ...


class DockWidgetFactoryBase:
    DockRight: int


class DockWidgetFactory:
    def __init__(self, identifier: str, position: int,
                 widget_type: Type[DockWidget]) -> None: ...


class Krita:
    @staticmethod
    def instance() -> Host: ...
