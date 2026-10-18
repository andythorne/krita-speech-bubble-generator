"""Values owned by an editor session, never native shape handles."""

from dataclasses import dataclass, field
from typing import Optional, Tuple

from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QImage, QTransform

from ..bubbles.settings import BubbleSettings, TransformValues


@dataclass(frozen=True)
class EditorPreferences:
    settings: BubbleSettings = field(default_factory=BubbleSettings)
    background_enabled: bool = True
    new_layer: bool = True


@dataclass(frozen=True)
class BubbleTarget:
    document: object
    layer_id: object
    shape_name: str
    baseline: TransformValues

    @property
    def identity(self) -> Tuple[object, object, str]:
        return self.document, self.layer_id, self.shape_name


@dataclass(frozen=True)
class Selection:
    document: object = None
    layer_id: object = None
    selected_names: Tuple[str, ...] = ()
    bubble_names: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedBubble:
    target: BubbleTarget
    settings: BubbleSettings
    layer_name: str


@dataclass(frozen=True)
class PendingEdit:
    target: BubbleTarget
    settings: BubbleSettings


@dataclass(frozen=True)
class CanvasContext:
    image: QImage
    rect: QRectF
    transform: QTransform


@dataclass
class EditorSession:
    draft: BubbleSettings
    target: Optional[BubbleTarget] = None
    applied: Optional[BubbleSettings] = None
    observed: Optional[Selection] = None
    pending: Optional[PendingEdit] = None
    loading: bool = False
    writing: bool = False
    background_enabled: bool = True
    context: Optional[CanvasContext] = None
    background_target: Optional[BubbleTarget] = None
