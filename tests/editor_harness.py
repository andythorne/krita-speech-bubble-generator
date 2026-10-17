"""Test-only aggregate for the original cross-boundary regression workflows.

Widget assertions still exercise the real view, rendering assertions exercise
the renderer, and transition assertions exercise the presenter. The production
dock deliberately has no compatibility methods or widget forwarding.
"""

from dataclasses import replace

from PyQt5.QtGui import QTransform

from krita_speech_bubble_generator.bubbles.renderer import get_speech_lines
from krita_speech_bubble_generator.bubbles.settings import (
    SHAPE_NAME, transform_values, validate_settings,
)
from krita_speech_bubble_generator.editor.state import BubbleTarget, LoadedBubble


class EditorHarness:
    transitions = {
        "applyLiveUpdate": "apply_live_update", "flushLiveUpdate": "flush_live_update",
        "stopEditing": "stop_editing", "syncSelection": "sync_selection",
        "syncCanvasPlacement": "sync_placement", "refreshMovedBackground": "refresh_moved_background",
        "loadSelectedBubble": "load_selected", "startNewBubble": "start_new",
        "updateBubble": "update", "refreshCanvasBackground": "refresh_background",
    }
    timers = {"selectionTimer": "selection_timer", "liveTimer": "live_timer",
              "backgroundTimer": "background_timer"}
    editable = {"tailAngle": "tail_angle", "shoutSeed": "shout_seed",
                "thoughtSeed": "thought_seed"}

    def __init__(self, dock):
        self.dock = dock
        self.view = dock.view
        self.presenter = dock.presenter
        self.gateway = dock.gateway
        self.renderer = dock.renderer

    def __getattr__(self, name):
        if name in self.transitions:
            return getattr(self.presenter, self.transitions[name])
        if name in self.timers:
            return getattr(self.presenter, self.timers[name])
        state = self.presenter.state
        if name in self.editable:
            return getattr(state.draft, self.editable[name])
        if name == "pendingLiveUpdate":
            return state.pending is not None
        if name == "updating":
            return state.writing
        if name == "editBaseline":
            return QTransform(*state.target.baseline) if state.target else None
        target_fields = {"editDocument": "document", "editLayerId": "layer_id",
                         "editShapeName": "shape_name"}
        if name in target_fields:
            return getattr(state.target, target_fields[name]) if state.target else None
        if name == "annotationKey":
            return self.gateway.annotation_key
        if name == "shapeByName":
            return self.gateway.shape_by_name
        if name == "validateSettings":
            return validate_settings
        if name == "getSpeechLines":
            return get_speech_lines
        if name in self.view.__dict__:
            return getattr(self.view, name)
        return getattr(self.dock, name)

    def __setattr__(self, name, value):
        if name in self.editable:
            self.presenter.state.draft = replace(
                self.presenter.state.draft, **{self.editable[name]: value})
            self.view.load_settings(self.presenter.state.draft)
        elif name == "updating":
            self.presenter.state.writing = value
        else:
            object.__setattr__(self, name, value)

    def widget(self):
        return self.view

    def geometry(self):
        return self.renderer.geometry(self.presenter.state.draft)

    def renderBubble(self, preview=False):
        return self.renderer.render(self.presenter.state.draft, preview)

    def getPreview(self):
        return self.renderBubble(preview=True).svg

    def settings(self):
        return self.presenter.state.draft.to_dict()

    def saveSettings(self, document, layer, baseline, shape_name=SHAPE_NAME):
        self.gateway.save_settings(document, layer, self.presenter.state.draft, baseline, shape_name)

    def setEditTarget(self, document, layer, baseline, shape_name=SHAPE_NAME):
        self.presenter.bind(LoadedBubble(
            BubbleTarget(document, layer.uniqueId(), shape_name, transform_values(baseline)),
            self.presenter.state.draft, layer.name()))

    def addOnPageShape(self):
        return self.presenter.page_action(self.view.addDestination.currentIndex() == 0)

    def moveTail(self, point):
        return self.presenter.move_tail(point)

    def updatePreview(self):
        return self.presenter.edit(self.view.initial_settings())
