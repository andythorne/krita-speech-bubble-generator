"""Presenter contracts with no native host or concrete editor controls."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QObject, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QImage, QTransform
from PyQt5.QtTest import QTest

from fake_krita import APP
from krita_speech_bubble_generator.bubbles.settings import BubbleSettings, SettingsError
from krita_speech_bubble_generator.editor.contracts import GatewayError, TargetMissing
from krita_speech_bubble_generator.editor.presenter import EditorPresenter
from krita_speech_bubble_generator.editor.state import (
    BubbleTarget, CanvasContext, EditorPreferences, LoadedBubble, Selection,
)


class SubstituteView(QObject):
    edited = pyqtSignal(object, tuple)
    tail_moved = pyqtSignal(object)
    tail_start_moved = pyqtSignal(object)
    page_requested = pyqtSignal(bool)
    new_requested = pyqtSignal()
    import_requested = pyqtSignal()
    recovery_requested = pyqtSignal()
    copy_style_requested = pyqtSignal()
    paste_style_requested = pyqtSignal()
    background_toggled = pyqtSignal(bool)
    refresh_requested = pyqtSignal()
    destination_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.settings = BubbleSettings()
        self.warnings = []
        self.context = None
        self.dragging = False
        self.mode = False, "New bubble"
        self.background = True, False
        self.rendered = None
        self.new_layer = True
        self.style_available = False

    def initial_settings(self):
        return self.settings

    def load_settings(self, settings):
        self.settings = settings
        return settings

    def reflect_settings(self, settings):
        self.settings = settings
        return settings

    def show_render(self, rendered):
        self.rendered = rendered

    def show_context(self, context):
        self.context = context

    def show_mode(self, editing, label):
        self.mode = editing, label

    def show_background(self, enabled, available):
        self.background = enabled, available

    def is_dragging(self):
        return self.dragging

    def warn(self, message):
        self.warnings.append(message)

    def set_new_layer(self, new_layer):
        self.new_layer = new_layer

    def set_style_available(self, available):
        self.style_available = available


class SubstituteRenderer:
    def __init__(self):
        self.calls = []
        self.tail_calls = []

    def render(self, settings, preview=False):
        self.calls.append((settings, preview))
        return SimpleNamespace(svg=settings.text, view_box=QRectF(0, 0, 20, 10),
                               tip=None, tail_start=None)

    def move_tail(self, settings, point):
        self.tail_calls.append((settings, point))
        return replace(settings, tail_angle=0.7, tail_length=23)

    def move_tail_start(self, settings, point):
        self.tail_calls.append((settings, point))
        return replace(settings, tail_start_angle=-0.4)


class SubstituteGateway:
    def __init__(self):
        self.document = object()
        self.selection = Selection(self.document)
        self.records = {}
        self.writes = []
        self.created = []
        self.snapshots = []
        self.placements = []
        self.update_error = None
        self.load_error = None
        self.context_error = None
        self.transform = QTransform()

    def active_document(self):
        return self.document

    def observe(self):
        return self.selection

    def record(self, name, settings=None, document=None):
        target = BubbleTarget(document or self.document, "layer-" + name, name,
                              (1, 0, 0, 1, 0, 0))
        loaded = LoadedBubble(target, settings or BubbleSettings(text=name), name)
        self.records[name] = loaded
        return loaded

    def select(self, loaded, selected=True):
        target = loaded.target
        self.document = target.document
        self.selection = Selection(
            target.document, target.layer_id,
            (target.shape_name,) if selected else (), (target.shape_name,))

    def load_selected(self, shape_name=None):
        if self.load_error:
            raise self.load_error
        name = shape_name or self.selection.bubble_names[0]
        return self.records[name]

    def deselect(self):
        self.selection = replace(self.selection, selected_names=())
        return self.selection

    def create(self, settings, svg, new_layer):
        self.created.append((settings, svg, new_layer))
        loaded = self.record("created", settings)
        self.select(loaded)
        return loaded

    def import_legacy(self):
        if self.load_error:
            raise self.load_error
        loaded = self.record("imported", BubbleSettings(text="Old dialogue"))
        self.select(loaded)
        return loaded

    def recover_selected(self):
        if self.load_error:
            raise self.load_error
        loaded = self.record("recovered", BubbleSettings(text="Recovered dialogue"))
        self.select(loaded)
        return loaded

    def update(self, target, settings, svg):
        self.writes.append((target, settings, svg))
        if self.update_error:
            raise self.update_error
        updated = replace(target, baseline=(1, 0, 0, 1, -20, -10))
        self.records[target.shape_name] = LoadedBubble(updated, settings, target.shape_name)
        return updated

    def placement(self, target):
        self.placements.append(target)
        if self.context_error:
            raise self.context_error
        return self.transform

    def snapshot(self, target):
        self.snapshots.append(target)
        if self.context_error:
            raise self.context_error
        return CanvasContext(QImage(2, 2, QImage.Format_ARGB32),
                             QRectF(0, 0, 100, 100), self.transform)


class PresenterTests(unittest.TestCase):
    def setUp(self):
        self.owner = QObject()
        self.view = SubstituteView()
        self.gateway = SubstituteGateway()
        self.renderer = SubstituteRenderer()
        self.seeds = MagicMock(side_effect=[17, 29, 31, 43, 59])
        self.presenter = EditorPresenter(
            self.view, self.gateway, self.renderer, self.seeds, self.owner)

    def tearDown(self):
        self.presenter.live_timer.stop()
        self.presenter.selection_timer.stop()
        self.presenter.background_timer.stop()
        self.owner.deleteLater()
        APP.processEvents()

    def bind(self, name="first", **settings):
        loaded = self.gateway.record(name, replace(self.presenter.state.draft, text=name, **settings))
        self.gateway.select(loaded)
        self.presenter.load_selected()
        return loaded

    def edit(self, **values):
        self.view.edited.emit(replace(self.presenter.state.draft, **values), tuple(values))

    def test_style_clipboard_survives_repeated_pastes_selection_and_new_bubbles(self):
        self.assertFalse(self.view.style_available)
        self.bind("source", shape="Tracing", style="Shouting", wrapping="Diamond",
                  fill="#123456", outline=7,
                  padding=95, shout_shape="Expressive", shout_nodes=37,
                  shout_irregularity=90, thought_irregularity=80,
                  thought_nodes=29, thought_size=275, shout_seed=42, thought_seed=53,
                  oval_custom=True, oval_vertical_padding=25, oval_squareness=80,
                  autocenter=False, line_length=24, optical_center=True,
                  tail_curve=75, tail_curve_direction="Down")
        source = self.presenter.state.draft
        self.view.copy_style_requested.emit()
        self.assertTrue(self.view.style_available)
        self.assertIsNone(self.presenter.state.pending)
        self.assertEqual(self.gateway.writes, [])
        self.edit(padding=200)
        for name in ("second", "third"):
            with self.subTest(name=name):
                self.bind(name, style="Thought", tail_length=70, tail_angle=-1.2,
                          lock_tail=False, shout_seed=173, thought_seed=291)
                target = self.presenter.state.target
                expected = self.presenter.state.draft.with_style_from(source)
                self.view.paste_style_requested.emit()
                self.assertEqual(self.presenter.state.draft, expected)
                self.assertEqual(
                    (expected.shout_seed, expected.thought_seed, expected.thought_size),
                    (42, 53, 275))
                self.assertEqual(
                    (expected.text, expected.tail_angle, expected.tail_length, expected.lock_tail),
                    (name, -1.2, 70, False))
                self.assertEqual(self.view.settings, expected)
                self.assertEqual(self.presenter.state.pending.target, target)
                self.assertTrue(self.presenter.apply_live_update())
                self.assertEqual(self.gateway.writes[-1][:2], (target, expected))
                self.assertEqual(self.presenter.state.copied_style, source)
                self.assertTrue(self.view.style_available)
        self.presenter.start_new()
        self.view.paste_style_requested.emit()
        self.assertEqual(self.presenter.state.draft.style, source.style)
        self.assertEqual(self.presenter.state.draft.padding, source.padding)
        self.assertIsNone(self.presenter.state.pending)
        self.assertEqual(self.seeds.call_count, 2)

    def test_deselecting_and_starting_new_preserves_the_current_bubble_type(self):
        loaded = self.bind("selected", style="Thought")
        self.gateway.select(loaded, selected=False)
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.presenter.state.draft.style, "Thought")
        self.assertEqual(self.view.settings.style, "Thought")

        self.presenter.start_new()
        self.assertEqual(self.presenter.state.draft.style, "Thought")
        self.assertEqual(self.view.settings.style, "Thought")

    def test_copying_again_replaces_style_and_paste_without_copy_warns(self):
        initial = self.presenter.state.draft
        self.view.paste_style_requested.emit()
        self.assertEqual(self.presenter.state.draft, initial)
        self.assertEqual(self.view.warnings, ["Copy a bubble style before pasting it."])
        self.view.copy_style_requested.emit()
        self.edit(style="Square", padding=25)
        self.view.copy_style_requested.emit()
        self.edit(style="Thought", padding=300)
        self.view.paste_style_requested.emit()
        self.assertEqual(self.presenter.state.draft.style, "Sharp")
        self.assertEqual(self.presenter.state.draft.shape, "Square")
        self.assertEqual(self.presenter.state.draft.padding, 25)

    def test_initial_seeds_are_injected_and_all_timers_have_gui_ownership(self):
        self.assertIs(self.presenter.parent(), self.owner)
        self.assertEqual((self.view.settings.shout_seed, self.view.settings.thought_seed), (17, 29))
        for timer, interval, single in (
            (self.presenter.live_timer, 150, True),
            (self.presenter.selection_timer, 150, False),
            (self.presenter.background_timer, 250, True),
        ):
            self.assertIs(timer.parent(), self.presenter)
            self.assertIs(timer.thread(), self.presenter.thread())
            self.assertEqual(timer.interval(), interval)
            self.assertEqual(timer.isSingleShot(), single)
            self.assertFalse(timer.isActive())
        self.assertEqual(self.gateway.writes, [])

    def test_preferences_restore_every_option_except_default_shape_and_style(self):
        saved = EditorPreferences(
            replace(BubbleSettings(), shape="Tracing", style="Thought", wrapping="Diamond",
                    text="Remember this dialogue",
                    padding=75, font_size=22, tail_length=63, lock_tail=False,
                    thought_seed=101, shout_seed=202),
            background_enabled=False, new_layer=False)
        store = MagicMock()
        store.load.return_value = saved
        presenter = EditorPresenter(
            self.view, self.gateway, self.renderer, lambda low, high: low,
            self.owner, preferences=store)
        self.assertEqual(self.view.settings, replace(saved.settings, style="Oval"))
        self.assertEqual(self.view.background, (False, False))
        self.assertFalse(self.view.new_layer)
        presenter.hidden()
        store.save.assert_called_once_with(replace(
            saved, settings=replace(saved.settings, style="Oval")))

    def test_preferences_save_edits_destination_background_and_hidden_state(self):
        store = MagicMock()
        self.presenter.preferences = store
        self.edit(text="Saved dialogue", padding=60, style="Shouting")
        self.assertEqual(store.save.call_args.args[0].settings, self.view.settings)
        self.view.destination_changed.emit(False)
        self.assertFalse(store.save.call_args.args[0].new_layer)
        self.view.background_toggled.emit(False)
        self.assertFalse(store.save.call_args.args[0].background_enabled)
        self.presenter.hidden()
        self.assertEqual(store.save.call_args.args[0], EditorPreferences(
            self.view.settings, False, False))

    def test_preferences_failures_are_reported_without_losing_the_draft(self):
        store = MagicMock()
        store.load.side_effect = SettingsError("Invalid preferences")
        store.save.side_effect = SettingsError("Read-only preferences")
        presenter = EditorPresenter(
            self.view, self.gateway, self.renderer, lambda low, high: low,
            self.owner, preferences=store)
        presenter.edit(replace(self.view.settings, text="Still editable"))
        self.assertEqual(presenter.state.draft.text, "Still editable")
        self.assertEqual(self.view.warnings, [
            "Cannot restore editor options: Invalid preferences",
            "Cannot save editor options: Read-only preferences"])

    def test_leaving_existing_bubble_keeps_current_appearance_for_new_drafts(self):
        loaded = self.bind(style="Shouting", padding=95)
        self.assertEqual(self.view.settings.style, "Shouting")
        self.gateway.selection = Selection(self.gateway.document)
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.view.settings, loaded.settings)
        self.edit(style="Thought")
        self.presenter.sync_selection(force=True)
        self.assertEqual(self.view.settings.style, "Thought")

    def test_explicit_import_binds_without_scheduling_a_redraw(self):
        self.view.import_requested.emit()
        self.assertEqual(self.presenter.state.target.shape_name, "imported")
        self.assertEqual(self.view.settings.text, "Old dialogue")
        self.assertEqual(self.presenter.state.applied, self.view.settings)
        self.assertIsNone(self.presenter.state.pending)
        self.assertEqual(self.gateway.writes, [])
        self.edit(text="Edited old dialogue")
        self.presenter.flush_live_update()
        self.assertEqual(self.gateway.writes[0][0].shape_name, "imported")

    def test_failed_import_reports_the_error_without_rebinding(self):
        loaded = self.bind()
        self.gateway.load_error = SettingsError("Unsupported old artwork")
        self.view.import_requested.emit()
        self.assertEqual(self.view.warnings[-1], "Unsupported old artwork")
        self.assertEqual(self.presenter.state.target, loaded.target)
        self.assertFalse(self.presenter.state.writing)

    def test_explicit_recovery_binds_without_scheduling_a_redraw(self):
        self.view.recovery_requested.emit()
        self.assertEqual(self.presenter.state.target.shape_name, "recovered")
        self.assertEqual(self.view.settings.text, "Recovered dialogue")
        self.assertEqual(self.presenter.state.applied, self.view.settings)
        self.assertIsNone(self.presenter.state.pending)
        self.assertFalse(self.presenter.live_timer.isActive())
        self.assertEqual(self.gateway.writes, [])
        self.assertIn("Recovered:", self.view.mode[1])
        self.edit(text="Edited recovered dialogue")
        self.presenter.flush_live_update()
        self.assertEqual(self.gateway.writes[0][0].shape_name, "recovered")

    def test_failed_recovery_reports_the_error_without_rebinding(self):
        loaded = self.bind()
        self.gateway.load_error = GatewayError("No unique match")
        self.view.recovery_requested.emit()
        self.assertEqual(self.view.warnings[-1], "No unique match")
        self.assertEqual(self.presenter.state.target, loaded.target)
        self.assertFalse(self.presenter.state.writing)

    def test_recovery_flushes_pending_edits_to_their_original_target(self):
        original = self.bind()
        self.edit(text="Pending original dialogue")
        self.view.recovery_requested.emit()
        self.assertEqual(self.gateway.writes[0][0], original.target)
        self.assertEqual(self.gateway.writes[0][1].text, "Pending original dialogue")
        self.assertEqual(self.presenter.state.target.shape_name, "recovered")
        self.assertIsNone(self.presenter.state.pending)

    def test_only_irregularity_intents_regenerate_the_corresponding_seed(self):
        self.edit(text="Typing", tail_angle=0.9, shout_nodes=32, shout_shape="Angular",
                  style="Thought")
        self.assertEqual(self.seeds.call_count, 2)
        self.edit(shout_irregularity=80)
        self.assertEqual(self.presenter.state.draft.shout_seed, 48)
        self.assertEqual(self.presenter.state.draft.thought_seed, 29)
        self.edit(thought_irregularity=90)
        self.assertEqual(self.presenter.state.draft.thought_seed, 72)
        self.assertEqual(self.seeds.call_args.args, (1, 2 ** 31))

    def test_pattern_seed_wraps_and_loading_never_reseeds_or_schedules_a_write(self):
        loaded = self.bind(shout_seed=2 ** 31 - 1, thought_seed=123)
        self.assertEqual(self.seeds.call_count, 2)
        self.assertIsNone(self.presenter.state.pending)
        self.assertFalse(self.presenter.live_timer.isActive())
        self.assertEqual(self.presenter.state.applied, loaded.settings)
        self.edit(shout_irregularity=70)
        self.assertEqual(self.presenter.state.draft.shout_seed, 30)
        self.assertEqual(self.presenter.state.draft.thought_seed, 123)

    def test_reverting_to_applied_snapshot_cancels_pending_work(self):
        self.bind()
        original = self.presenter.state.applied
        self.edit(text="changed")
        self.assertIsNotNone(self.presenter.state.pending)
        self.view.edited.emit(original, ("text",))
        self.assertIsNone(self.presenter.state.pending)
        QTest.qWait(180)
        self.assertEqual(self.gateway.writes, [])

    def test_ordinary_edits_reflect_only_draft_changes_without_reloading_the_form(self):
        self.bind()
        self.view.load_settings = MagicMock(side_effect=AssertionError("Unexpected form reload"))
        self.edit(text="keep cursor and focus")
        self.edit(shout_irregularity=80)
        self.view.tail_moved.emit(QPointF(10, 20))
        self.view.load_settings.assert_not_called()
        self.assertEqual(self.view.settings.tail_length, 23)

    def test_tail_start_edits_follow_the_same_targeted_pending_write_path(self):
        loaded = self.bind(tail_advanced=True)
        seeds = (self.view.settings.shout_seed, self.view.settings.thought_seed)
        self.view.tail_start_moved.emit(QPointF(100, 20))
        self.assertEqual(self.view.settings.tail_start_angle, -0.4)
        self.assertEqual(self.presenter.state.pending.target, loaded.target)
        self.assertEqual((self.view.settings.shout_seed, self.view.settings.thought_seed), seeds)
        self.presenter.flush_live_update()
        self.assertEqual(self.gateway.writes[-1][1], self.view.settings)

    def test_real_timer_coalesces_edits_into_one_latest_snapshot(self):
        self.bind()
        self.edit(text="intermediate")
        self.edit(text="final")
        QTest.qWait(190)
        self.assertEqual(len(self.gateway.writes), 1)
        target, settings, svg = self.gateway.writes[0]
        self.assertEqual((target.shape_name, settings.text, svg), ("first", "final", "final"))
        self.assertIsNone(self.presenter.state.pending)

    def test_live_timeout_reconciles_new_selection_before_writing(self):
        first = self.bind()
        second = self.gateway.record("second")
        self.edit(text="old target edit")
        pending = self.presenter.state.pending
        self.gateway.select(second)
        self.presenter.live_timer.stop()
        self.presenter.apply_live_update()
        self.assertEqual(self.gateway.writes[0][:2], (first.target, pending.settings))
        self.assertEqual(len(self.gateway.writes), 1)
        self.assertEqual(self.presenter.state.target.identity, second.target.identity)
        self.assertEqual(self.view.settings.text, "second")

    def test_selection_poll_ignores_ambiguous_bubble_names_without_a_warning(self):
        loaded = self.gateway.record("duplicated")
        self.gateway.select(loaded)
        self.gateway.selection = replace(
            self.gateway.selection, bubble_names=("duplicated", "duplicated"))
        self.gateway.load_selected = MagicMock(
            side_effect=GatewayError("Ambiguous bubble"))
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.view.warnings, [])
        self.gateway.load_selected.assert_not_called()

    def test_document_switch_discards_pending_write_instead_of_cross_document_flush(self):
        first = self.bind()
        self.edit(text="not flushed across documents")
        second = self.gateway.record("second", document=object())
        self.gateway.select(second)
        self.presenter.apply_live_update()
        self.assertEqual(self.gateway.writes, [])
        self.assertNotEqual(first.target.document, self.presenter.state.target.document)
        self.assertEqual(self.view.settings.text, "second")
        self.assertIsNone(self.presenter.state.pending)

    def test_deselection_flushes_then_unbinds_without_automatically_reselecting(self):
        first = self.bind()
        self.edit(text="finish")
        self.gateway.selection = replace(self.gateway.selection, selected_names=())
        self.presenter.sync_selection()
        self.assertEqual(self.gateway.writes[0][0], first.target)
        self.assertIsNone(self.presenter.state.target)
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.edit(text="draft")
        self.assertIsNone(self.presenter.state.pending)

    def test_multiple_or_unrelated_selected_shapes_never_choose_a_bubble(self):
        self.bind()
        for names in (("first", "other"), ("unrelated",)):
            self.gateway.selection = replace(self.gateway.selection, selected_names=names)
            self.presenter.sync_selection()
            self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.view.warnings, [])

    def test_new_mode_flushes_and_keeps_the_draft_without_rebinding_one_bubble(self):
        self.bind()
        self.edit(text="finish and reuse")
        self.view.new_requested.emit()
        self.assertEqual(len(self.gateway.writes), 1)
        self.assertEqual(self.gateway.selection.selected_names, ())
        self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.view.settings.text, "finish and reuse")
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.view.page_requested.emit(False)
        self.assertEqual(self.gateway.created[0][2], False)
        self.assertEqual(self.presenter.state.target.shape_name, "created")

    def test_primary_action_updates_a_bound_target_even_when_destination_says_new(self):
        self.bind()
        self.edit(text="changed")
        self.view.page_requested.emit(True)
        self.assertEqual(len(self.gateway.writes), 1)
        self.assertEqual(self.gateway.created, [])

    def test_failure_keeps_draft_and_baseline_and_only_a_new_attempt_retries(self):
        loaded = self.bind()
        self.gateway.update_error = GatewayError("Cannot import")
        self.edit(text="failed draft")
        self.presenter.apply_live_update()
        self.assertEqual(self.presenter.state.target, loaded.target)
        self.assertEqual(self.presenter.state.applied, loaded.settings)
        self.assertEqual(self.presenter.state.draft.text, "failed draft")
        self.assertIsNone(self.presenter.state.pending)
        self.presenter.sync_selection()
        self.presenter.apply_live_update()
        self.assertEqual(len(self.gateway.writes), 1)
        self.assertEqual(self.view.warnings, ["Cannot import"])
        self.gateway.update_error = None
        self.edit(text="retry")
        self.presenter.apply_live_update()
        self.assertEqual(self.presenter.state.applied.text, "retry")
        self.assertNotEqual(self.presenter.state.target.baseline, loaded.target.baseline)

    def test_failed_flush_does_not_disable_a_new_selection(self):
        self.bind()
        self.gateway.update_error = GatewayError("Failed old target")
        self.edit(text="failed")
        second = self.gateway.record("second")
        self.gateway.select(second)
        self.presenter.sync_selection()
        self.gateway.update_error = None
        self.edit(text="new target edit")
        self.presenter.apply_live_update()
        self.assertEqual([write[0].shape_name for write in self.gateway.writes],
                         ["first", "second"])
        self.assertEqual(self.presenter.state.applied.text, "new target edit")
        self.assertEqual(self.view.warnings, ["Failed old target"])

    def test_malformed_record_clears_previous_target_without_partially_loading(self):
        self.bind()
        second = self.gateway.record("second")
        self.gateway.select(second)
        self.gateway.load_error = SettingsError("Invalid text")
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.assertEqual(self.view.settings.text, "first")
        self.assertEqual(self.view.warnings, ["Cannot read this bubble's settings: Invalid text"])

    def test_unexpected_errors_are_not_hidden_as_successful_host_operations(self):
        self.bind()
        self.gateway.update_error = RuntimeError("Programming error")
        with self.assertRaisesRegex(RuntimeError, "Programming error"):
            self.presenter.update()
        self.assertFalse(self.presenter.state.writing)
        self.assertEqual(self.view.warnings, [])

    def test_tail_move_dispatches_through_renderer_without_reseeding(self):
        self.bind()
        point = QPointF(42, 13)
        self.view.tail_moved.emit(point)
        self.assertEqual(self.renderer.tail_calls[-1][1], point)
        self.assertEqual((self.view.settings.tail_angle, self.view.settings.tail_length), (0.7, 23))
        self.assertEqual(self.seeds.call_count, 2)
        self.assertIsNotNone(self.presenter.state.pending)

    def test_movement_updates_transform_immediately_and_debounces_snapshot(self):
        loaded = self.bind()
        self.gateway.snapshots.clear()
        for x in (10, 20, 30):
            self.gateway.transform = QTransform.fromTranslate(x, 20)
            self.presenter.sync_selection()
            self.assertEqual(self.view.context.transform, self.gateway.transform)
        self.assertEqual(self.gateway.snapshots, [])
        self.assertEqual(self.presenter.state.background_target, loaded.target)
        QTest.qWait(290)
        self.assertEqual(self.gateway.snapshots, [loaded.target])
        self.assertFalse(self.presenter.background_timer.isActive())

    def test_dragging_prevents_native_movement_from_reframing_active_drag(self):
        self.bind()
        self.gateway.placements.clear()
        original = self.view.context
        self.view.dragging = True
        self.gateway.transform = QTransform.fromTranslate(200, 80)
        self.presenter.sync_selection()
        self.assertIs(self.view.context, original)
        self.assertEqual(self.gateway.placements, [])

    def test_movement_timeout_that_loads_new_target_does_not_snapshot_twice(self):
        self.bind()
        self.gateway.transform = QTransform.fromTranslate(30, 40)
        self.presenter.sync_selection()
        second = self.gateway.record("second")
        self.gateway.select(second)
        self.gateway.snapshots.clear()
        self.presenter.refresh_moved_background()
        self.assertEqual(self.gateway.snapshots, [second.target])
        self.assertFalse(self.presenter.background_timer.isActive())

    def test_background_toggle_cancels_pending_movement_and_snapshot_errors_disable(self):
        self.bind()
        self.gateway.transform = QTransform.fromTranslate(30, 40)
        self.presenter.sync_selection()
        self.gateway.snapshots.clear()
        self.view.background_toggled.emit(False)
        QTest.qWait(290)
        self.assertEqual(self.gateway.snapshots, [])
        self.assertIsNone(self.view.context)
        self.assertFalse(self.presenter.background_timer.isActive())
        self.gateway.context_error = GatewayError("Snapshot failed")
        self.view.background_toggled.emit(True)
        self.assertEqual(self.view.background, (False, True))
        self.assertIsNone(self.view.context)
        self.assertEqual(self.view.warnings,
                         ["Cannot show the canvas background: Snapshot failed"])

    def test_deleted_group_stops_editing_instead_of_reusing_a_native_shape(self):
        self.bind()
        self.gateway.context_error = TargetMissing("Deleted")
        self.presenter.sync_selection()
        self.assertIsNone(self.presenter.state.target)
        self.assertIsNone(self.view.context)
        self.assertEqual(self.view.warnings, [])

    def test_writes_refresh_context_transform_without_taking_another_snapshot(self):
        self.bind()
        self.gateway.snapshots.clear()
        self.gateway.transform = QTransform.fromTranslate(40, 70)
        self.edit(text="change")
        self.presenter.apply_live_update()
        self.assertEqual(self.gateway.snapshots, [])
        self.assertEqual(self.view.context.transform, self.gateway.transform)

    def test_background_refresh_defers_while_writing(self):
        loaded = self.bind()
        self.gateway.snapshots.clear()
        self.presenter.state.writing = True
        self.presenter.refresh_moved_background()
        self.assertEqual(self.gateway.snapshots, [])
        self.assertTrue(self.presenter.background_timer.isActive())
        self.presenter.state.writing = False
        self.presenter.refresh_moved_background()
        self.assertEqual(self.gateway.snapshots, [loaded.target])

    def test_hide_flushes_pending_edit_and_stops_all_timers(self):
        self.bind()
        self.presenter.shown()
        self.gateway.transform = QTransform.fromTranslate(20, 30)
        self.presenter.sync_selection()
        self.edit(text="hide flush")
        self.presenter.hidden()
        self.assertEqual(self.gateway.writes[-1][1].text, "hide flush")
        self.assertFalse(any(timer.isActive() for timer in (
            self.presenter.live_timer, self.presenter.selection_timer,
            self.presenter.background_timer)))

    def test_destroying_owner_destroys_presenter_and_every_running_timer(self):
        owner = QObject()
        presenter = EditorPresenter(
            SubstituteView(), SubstituteGateway(), SubstituteRenderer(),
            lambda minimum, maximum: minimum, owner)
        timers = presenter.live_timer, presenter.selection_timer, presenter.background_timer
        for timer in timers:
            timer.start()
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(presenter))
        self.assertTrue(all(sip.isdeleted(timer) for timer in timers))
