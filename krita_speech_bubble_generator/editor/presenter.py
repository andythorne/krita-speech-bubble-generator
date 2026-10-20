"""Selection-safe editing transitions and GUI-thread timer orchestration."""

from dataclasses import replace
from typing import Callable, Optional, Tuple, cast

from PyQt5.QtCore import QObject, QPointF, QTimer

from ..bubbles.settings import BubbleSettings, SettingsError
from .contracts import (
    BubbleGateway, BubbleRendering, EditorView, GatewayError, PreviewContext, SeedSupplier,
    PreferencesStore, TargetMissing,
)
from .state import (
    BubbleTarget, CanvasContext, EditorPreferences, EditorSession, LoadedBubble, PendingEdit,
)


class EditorPresenter(QObject):
    def __init__(self, view: EditorView, gateway: BubbleGateway,
                 renderer: BubbleRendering, seed_supplier: SeedSupplier,
                 parent: Optional[QObject] = None,
                 preferences: Optional[PreferencesStore] = None) -> None:
        super().__init__(parent)
        self.view = view
        self.gateway = gateway
        self.renderer = renderer
        self.seed_supplier = seed_supplier
        self.preferences = preferences
        self._new_layer = True
        saved = None
        if preferences is not None:
            try:
                saved = preferences.load()
            except SettingsError as error:
                view.warn("Cannot restore editor options: " + str(error))
        initial = replace(view.initial_settings(),
                          shout_seed=seed_supplier(0, 2 ** 31),
                          thought_seed=seed_supplier(0, 2 ** 31))
        if saved is not None:
            initial = saved.settings
            self._new_layer = saved.new_layer
        initial = replace(initial, style=BubbleSettings().style)
        self.state = EditorSession(view.load_settings(initial))
        if saved is not None:
            self.state.background_enabled = saved.background_enabled
        view.set_new_layer(self._new_layer)
        view.set_style_available(False)
        view.show_background(self.state.background_enabled, False)
        self.live_timer = self._timer(150, self.apply_live_update, single=True)
        self.selection_timer = self._timer(150, self.sync_selection)
        self.background_timer = self._timer(250, self.refresh_moved_background, single=True)
        view.edited.connect(self.edit)
        view.tail_moved.connect(self.move_tail)
        def request_page(new_layer: bool) -> None:
            self.page_action(new_layer)
        view.page_requested.connect(request_page)
        view.new_requested.connect(self.start_new)
        view.import_requested.connect(self.import_legacy)
        view.recovery_requested.connect(self.recover_selected)
        view.copy_style_requested.connect(self.copy_style)
        view.paste_style_requested.connect(self.paste_style)
        view.background_toggled.connect(self.toggle_background)
        view.refresh_requested.connect(self.refresh_background)
        view.destination_changed.connect(self.set_destination)
        self.render()

    def _save_preferences(self) -> None:
        if self.preferences is not None:
            try:
                self.preferences.save(EditorPreferences(
                    self.state.draft, self.state.background_enabled, self._new_layer))
            except SettingsError as error:
                self.view.warn("Cannot save editor options: " + str(error))

    def set_destination(self, new_layer: bool) -> None:
        self._new_layer = new_layer
        self._save_preferences()

    def _timer(self, interval: int, callback: Callable[[], object],
               single: bool = False) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(interval)
        timer.setSingleShot(single)
        def invoke() -> None:
            callback()
        timer.timeout.connect(invoke)
        return timer

    def render(self) -> None:
        self.view.show_render(self.renderer.render(self.state.draft, preview=True))

    def edit(self, settings: BubbleSettings, fields: Tuple[str, ...] = ()) -> None:
        if self.state.loading:
            return
        for field, seed, current in (
                ("shout_irregularity", "shout_seed", self.state.draft.shout_seed),
                ("thought_irregularity", "thought_seed", self.state.draft.thought_seed)):
            if field in fields:
                settings = replace(
                    settings, **{seed: (current
                                       + self.seed_supplier(1, 2 ** 31)) % (2 ** 31)})
        self.state.draft = self.view.reflect_settings(settings)
        self._save_preferences()
        self.render()
        if self.state.writing:
            return
        if self.state.target is not None and self.state.draft != self.state.applied:
            self.state.pending = PendingEdit(self.state.target, self.state.draft)
            self.live_timer.start()
        else:
            self._cancel_live()

    def move_tail(self, point: QPointF) -> None:
        self.edit(self.renderer.move_tail(self.state.draft, point))

    def copy_style(self) -> None:
        self.state.copied_style = self.state.draft
        self.view.set_style_available(True)

    def paste_style(self) -> None:
        if self.state.copied_style is None:
            self.view.warn("Copy a bubble style before pasting it.")
            return
        self.edit(self.state.draft.with_style_from(self.state.copied_style))

    def _cancel_live(self) -> None:
        self.live_timer.stop()
        self.state.pending = None

    def _cancel_background(self) -> None:
        self.background_timer.stop()
        self.state.background_target = None

    def flush_live_update(self) -> bool:
        pending = self.state.pending
        self._cancel_live()
        if pending is not None and self.gateway.active_document() == pending.target.document:
            return self._write(pending.target, pending.settings)
        return False

    def apply_live_update(self) -> Optional[bool]:
        if self.state.loading or self.state.writing:
            return
        # The pending snapshot belongs to its original target, even if selection
        # polling has not yet noticed a native selection change.
        self.sync_selection()
        if self.state.pending is not None:
            return self.flush_live_update()
        return False

    def update(self) -> bool:
        if self.state.loading or self.state.writing or self.state.target is None:
            return False
        self._cancel_live()
        return self._write(self.state.target, self.state.draft)

    def _write(self, target: BubbleTarget, settings: BubbleSettings) -> bool:
        self.state.writing = True
        try:
            updated = self.gateway.update(target, settings, self.renderer.render(settings).svg)
        except (GatewayError, SettingsError) as error:
            self.view.warn(str(error))
            return False
        finally:
            self.state.writing = False
        if self.state.target is not None and self.state.target.identity == target.identity:
            self.state.target = updated
            self.state.applied = settings
            if self.state.background_enabled:
                try:
                    transform = self.gateway.placement(updated)
                except GatewayError as error:
                    self.disable_background(error)
                else:
                    if self.state.context is not None:
                        self._set_context(replace(self.state.context, transform=transform))
                        self.render()
        return True

    def page_action(self, new_layer: bool = True) -> Optional[bool]:
        if self.state.loading or self.state.writing:
            return
        if self.state.target is not None:
            return self.update()
        self.flush_live_update()
        self.state.writing = True
        try:
            loaded = self.gateway.create(
                self.state.draft, self.renderer.render(self.state.draft).svg, new_layer)
        except (GatewayError, SettingsError) as error:
            self.view.warn(str(error))
            return False
        finally:
            self.state.writing = False
        self.bind(loaded)
        return True

    def start_new(self) -> None:
        self.flush_live_update()
        selection = self.gateway.deselect()
        self.stop_editing()
        self.state.observed = selection
        self.view.show_mode(False, "New bubble")

    def recover_selected(self) -> None:
        self._recover(self.gateway.recover_selected, "Recovered: ",
                      " - save as .kra to keep the restored editing settings.")

    def import_legacy(self) -> None:
        self._recover(
            self.gateway.import_legacy, "Imported: ",
            " - first update redraws the bubble; layout and per-word formatting may change.")

    def _recover(self, recover: Callable[[], LoadedBubble], prefix: str, suffix: str) -> None:
        if self.state.loading or self.state.writing:
            return
        self.flush_live_update()
        self.state.writing = True
        try:
            loaded = recover()
        except (GatewayError, SettingsError) as error:
            self.view.warn(str(error))
            return
        finally:
            self.state.writing = False
        self.bind(loaded)
        self.view.show_mode(True, prefix + loaded.layer_name + suffix)

    def stop_editing(self) -> None:
        self._cancel_live()
        self._cancel_background()
        self.state.target = None
        self.state.applied = None
        self.view.show_mode(False, "New bubble - select a bubble to edit")
        self.view.show_background(self.state.background_enabled, False)
        self._set_context(None)
        self.render()

    def bind(self, loaded: LoadedBubble) -> None:
        self._cancel_live()
        self._cancel_background()
        self.state.loading = True
        try:
            draft = self.view.load_settings(loaded.settings)
        finally:
            self.state.loading = False
        self.state.draft = draft
        self.state.target = loaded.target
        self.state.applied = draft
        self.state.observed = self.gateway.observe()
        self.view.show_mode(True, "Editing: " + loaded.layer_name)
        self.view.show_background(self.state.background_enabled, True)
        self._set_context(None)
        if self.state.background_enabled:
            self.refresh_background()
        self.render()

    def load_selected(self, shape_name: Optional[str] = None) -> None:
        if self.state.loading or self.state.writing:
            return
        self.flush_live_update()
        try:
            loaded = self.gateway.load_selected(shape_name)
        except SettingsError as error:
            self.stop_editing()
            self.view.warn("Cannot read this bubble's settings: " + str(error))
            return
        except GatewayError as error:
            self.stop_editing()
            self.view.warn(str(error))
            return
        self.bind(loaded)

    def sync_selection(self, force: bool = False) -> None:
        if self.state.loading or self.state.writing:
            return
        selection = self.gateway.observe()
        previous = self.state.observed
        layer_changed = (previous is None or selection.document != previous.document
                         or selection.layer_id != previous.layer_id)
        if (not force and not layer_changed and previous is not None
                and selection.selected_names == previous.selected_names):
            self.sync_placement()
            return
        self.state.observed = selection
        name = None
        if len(selection.selected_names) == 1:
            selected = selection.selected_names[0]
            if selection.bubble_names.count(selected) == 1:
                name = selected
        elif not selection.selected_names and len(selection.bubble_names) == 1:
            only = selection.bubble_names[0]
            if layer_changed or (force and self.state.target is not None
                                 and self.state.target.shape_name == only):
                name = only
        identity = selection.document, selection.layer_id, name
        same = self.state.target is not None and self.state.target.identity == identity
        if not same:
            self.flush_live_update()
        if name is None:
            self.stop_editing()
        elif not same:
            self.load_selected(name)
        else:
            self.sync_placement()

    def _set_context(self, context: Optional[CanvasContext]) -> None:
        self.state.context = context
        self.view.show_context(context)

    def sync_placement(self) -> None:
        state = self.state
        if (state.target is None or not state.background_enabled or state.context is None
                or self.view.is_dragging()
                or self.gateway.active_document() != state.target.document):
            return
        try:
            transform = self.gateway.placement(state.target)
        except TargetMissing:
            self.stop_editing()
            return
        except GatewayError as error:
            self.disable_background(error)
            return
        context = cast(PreviewContext, state.context)
        if transform != context.transform:
            self._set_context(replace(state.context, transform=transform))
            self.render()
            state.background_target = state.target
            self.background_timer.start()

    def refresh_moved_background(self) -> None:
        if self.state.loading or self.state.writing:
            self.background_timer.start()
            return
        target = self.state.background_target or self.state.target
        self.sync_selection()
        if (target is not None and self.state.target is not None
                and target.identity == self.state.target.identity
                and self.state.background_enabled
                and self.gateway.active_document() == target.document):
            self.refresh_background()

    def toggle_background(self, enabled: bool) -> None:
        self._cancel_background()
        self.state.background_enabled = enabled
        self._save_preferences()
        self.view.show_background(enabled, self.state.target is not None)
        if enabled:
            self.refresh_background()
        else:
            self._set_context(None)
            self.render()

    def disable_background(self, error: GatewayError) -> None:
        self._cancel_background()
        self.state.background_enabled = False
        self._set_context(None)
        self.view.show_background(False, self.state.target is not None)
        self.render()
        self.view.warn("Cannot show the canvas background: " + str(error))

    def refresh_background(self) -> None:
        self._cancel_background()
        if self.state.loading or self.state.writing:
            return
        try:
            if self.state.target is None:
                raise GatewayError("Open the document containing the bubble being edited")
            context = self.gateway.snapshot(self.state.target)
        except GatewayError as error:
            self.disable_background(error)
            return
        self._set_context(context)
        self.view.show_background(self.state.background_enabled, True)
        self.render()

    def canvas_changed(self) -> None:
        self.sync_selection()
        if self.state.target is not None and self.state.background_enabled:
            self.refresh_background()

    def shown(self) -> None:
        self.selection_timer.start()

    def hidden(self) -> None:
        self.flush_live_update()
        self._save_preferences()
        self.selection_timer.stop()
        self._cancel_background()
