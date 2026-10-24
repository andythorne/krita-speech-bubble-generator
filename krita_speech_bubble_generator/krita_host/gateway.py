"""Native document operations, with explicit targets for every write."""

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple, Union, cast
import uuid

from PyQt5.QtCore import QByteArray, QRectF, QUuid
from PyQt5.QtGui import QTransform

from ..bubbles.settings import (
    ANNOTATION_PREFIX, INTEGER_RANGES, SHAPE_NAME, BubbleSettings, TransformValues,
    decode_record, encode_record, transform_values,
)
from .canvas_context import canvas_snapshot, canvas_transform
from .contracts import Document, Host, Node, Shape
from .legacy import read_legacy_bubble
from .recovery import (
    detached_group, generated_name, group_settings, matching_records, stable_name,
    store_group_settings,
)
from ..editor.contracts import BubbleRendering, GatewayError, TargetMissing
from ..editor.state import BubbleTarget, CanvasContext, LoadedBubble, Selection


class KritaGateway:
    def __init__(self, host: Optional[Host] = None,
                 renderer: Optional[BubbleRendering] = None) -> None:
        if host is None:
            from krita import Krita  # pyright: ignore[reportMissingModuleSource]
            host = Krita.instance()
        self.host = host
        self.renderer = renderer

    def active_document(self) -> Optional[Document]:
        return self.host.activeDocument()

    @staticmethod
    def annotation_key(layer: Node, shape_name: str = SHAPE_NAME) -> str:
        key = ANNOTATION_PREFIX + layer.uniqueId().toString()
        return key if shape_name == SHAPE_NAME else key + "-" + shape_name

    @classmethod
    def shape_selected(cls, shape: Shape) -> bool:
        return shape.isSelected() or (
            shape.type() == "groupshape"
            and any(cls.shape_selected(child) for child in shape.children()))

    @classmethod
    def deselect_shape(cls, shape: Shape) -> None:
        if shape.type() == "groupshape":
            for child in shape.children():
                cls.deselect_shape(child)
        if shape.isSelected():
            shape.deselect()

    @classmethod
    def selected_names(cls, shapes: Sequence[Shape]) -> Tuple[str, ...]:
        return tuple(sorted(shape.name() for shape in shapes if cls.shape_selected(shape)))

    def bubble_shapes(self, document: Document, layer: Node) -> List[Shape]:
        return [
            shape for shape in layer.shapes()
            if shape.type() == "groupshape"
            and generated_name(shape.name())
        ]

    @staticmethod
    def shape_by_name(layer: Node, name: str) -> Optional[Shape]:
        matches = [shape for shape in layer.shapes() if shape.name() == name]
        return matches[0] if len(matches) == 1 and matches[0].type() == "groupshape" else None

    def resolve_bubble(self, document: Document, layer: Node,
                       name: Optional[str] = None) -> Optional[Shape]:
        bubbles = self.bubble_shapes(document, layer)
        selected = [shape for shape in layer.shapes() if self.shape_selected(shape)]
        if len(selected) == 1:
            shape = selected[0]
            if shape in bubbles and (name is None or shape.name() == name):
                return shape
        if name is not None:
            matches = [shape for shape in bubbles if shape.name() == name]
            return matches[0] if len(matches) == 1 else None
        return bubbles[0] if not selected and len(bubbles) == 1 else None

    @staticmethod
    def named_groups(document: Document, name: str) -> List[Tuple[Node, Shape]]:
        matches: List[Tuple[Node, Shape]] = []

        def find(node: Node) -> None:
            if node.type() == "vectorlayer":
                matches.extend((node, shape) for shape in node.shapes()
                               if shape.name() == name and shape.type() == "groupshape")
            for child in node.childNodes():
                find(child)

        for child in document.rootNode().childNodes():
            find(child)
        return matches

    def observe(self) -> Selection:
        document = self.active_document()
        layer = document.activeNode() if document else None
        bubbles = (self.bubble_shapes(document, layer)
                   if document is not None and layer is not None
                   and layer.type() == "vectorlayer" else [])
        return Selection(
            document, layer.uniqueId() if layer else None,
            self.selected_names(layer.shapes()) if layer is not None and bubbles else (),
            tuple(shape.name() for shape in bubbles))

    def deselect(self) -> Selection:
        document = self.active_document()
        layer = document.activeNode() if document else None
        if layer is not None and layer.type() == "vectorlayer":
            for shape in layer.shapes():
                self.deselect_shape(shape)
        return self.observe()

    def load_selected(self, shape_name: Optional[str] = None) -> LoadedBubble:
        document = self.active_document()
        layer = document.activeNode() if document else None
        if document is None or layer is None or layer.type() != "vectorlayer":
            raise GatewayError("Select a bubble vector layer made with this version of the plugin.")
        shape = self.resolve_bubble(document, layer, shape_name)
        if shape is None:
            raise GatewayError("Select one generated bubble on this vector layer to edit it.")
        if (sum(item.name() == shape.name() for item in layer.shapes()) > 1
                or (stable_name(shape.name())
                    and len(self.named_groups(document, shape.name())) > 1)):
            return self._restore_shape(document, layer, shape)
        data = document.annotation(self.annotation_key(layer, shape.name()))
        if not data:
            return self._restore_shape(document, layer, shape)
        record = decode_record(bytes(data))
        embedded = group_settings(shape)
        if embedded is not None and embedded != record.settings:
            return self._restore_shape(document, layer, shape)
        independent = document.annotation(shape.name()) if stable_name(shape.name()) else QByteArray()
        if independent:
            saved = decode_record(bytes(independent))
            if saved.layer_id and saved.layer_id != layer.uniqueId().toString():
                return self._restore_shape(document, layer, shape)
        if not layer.locked():
            name = shape.name() if stable_name(shape.name()) else SHAPE_NAME + "-" + uuid.uuid4().hex
            if name != shape.name() or independent != data:
                self.save_settings(document, layer, record.settings, record.baseline, name)
                shape.setName(name)
            store_group_settings(shape, record.settings)
        return LoadedBubble(
            BubbleTarget(document, layer.uniqueId(), shape.name(), record.baseline),
            record.settings, layer.name())

    @staticmethod
    def bubble_group(layer: Node, shapes: Sequence[Shape],
                     name: str = SHAPE_NAME) -> Optional[Shape]:
        if len(shapes) == 1 and shapes[0].type() == "groupshape":
            group = shapes[0]
        else:
            group = layer.createGroupShape(name, shapes)
        if group is not None:
            group.setName(name)
        return group

    @staticmethod
    def place_shape(group: Shape, transform: QTransform,
                    old_bounds: Optional[QRectF] = None) -> None:
        dirty = group.boundingBox()
        if old_bounds is not None:
            dirty = dirty.united(old_bounds)
        group.setTransformation(transform)
        group.updateAbsolute(dirty.united(group.boundingBox()))
        group.update()

    @staticmethod
    def refresh_canvas(document: Document) -> None:
        document.waitForDone()
        document.refreshProjection()

    def save_settings(self, document: Document, layer: Node,
                      settings: BubbleSettings,
                      baseline: Union[TransformValues, QTransform],
                      name: str = SHAPE_NAME) -> None:
        data = QByteArray(encode_record(
            settings, baseline, layer.uniqueId().toString() if stable_name(name) else ""))
        document.setAnnotation(self.annotation_key(layer, name), "Speech bubble settings",
                               data)
        if stable_name(name):
            document.setAnnotation(name, "Speech bubble settings", data)

    def recover_selected(self) -> LoadedBubble:
        document = self.active_document()
        layer = document.activeNode() if document is not None else None
        if document is None or layer is None or layer.type() != "vectorlayer":
            raise GatewayError("Select one generated bubble on a vector layer to recover it.")
        if layer.locked():
            raise GatewayError("Unlock the bubble layer before recovering it.")
        selected = [shape for shape in layer.shapes() if self.shape_selected(shape)]
        if (len(selected) != 1 or selected[0].type() != "groupshape"
                or not generated_name(selected[0].name())):
            raise GatewayError("Select exactly one intact generated bubble group to recover it.")
        shape = selected[0]
        if (document.annotation(self.annotation_key(layer, shape.name()))
                and len(self.named_groups(document, shape.name())) == 1):
            raise GatewayError("This bubble is already editable. Select it to edit.")
        return self._restore_shape(document, layer, shape)

    def _restore_shape(self, document: Document, layer: Node, shape: Shape) -> LoadedBubble:
        if layer.locked():
            raise GatewayError("Unlock the bubble layer before restoring its editing settings.")
        embedded = group_settings(shape)
        data = document.annotation(shape.name()) if stable_name(shape.name()) else QByteArray()
        recovered = detached_group(
            shape.toSvg(), shape.name(), require_text=embedded is None and not bool(data),
            fragment=True)
        if embedded is not None:
            settings = embedded
        else:
            records = ([decode_record(bytes(data))] if data
                       else matching_records(document, shape.name(), recovered.text))
            if len(records) != 1:
                raise GatewayError(
                    "Recovery requires embedded settings or one uniquely matching saved settings "
                    "record from a removed layer. No unique match was found; the artwork has not "
                    "been changed. For an older copied bubble, select it in the original document "
                    "with this version of the plugin, then copy the intact group again.")
            settings = records[0].settings
        if self.renderer is None:
            raise GatewayError("The bubble recovery renderer is not configured.")
        if document.xRes() <= 0 or document.yRes() <= 0:
            raise GatewayError("The document resolution is invalid.")
        # Reparenting can bake the old group transform into its children. Fit
        # the regenerated outline in local coordinates, retaining the new parent.
        placement = recovered.placement(self.renderer.render(settings).svg)
        delta = (QTransform.fromScale(document.xRes() / 72, document.xRes() / 72)
                 * placement * shape.transformation())
        inverse, invertible = delta.inverted()
        if not invertible:
            raise GatewayError("The recovered bubble placement is not invertible.")
        baseline = shape.transformation() * inverse
        name = shape.name()
        if (not stable_name(name)
                or len(self.named_groups(document, name)) > 1):
            name = SHAPE_NAME + "-" + uuid.uuid4().hex
        self.save_settings(document, layer, settings, baseline, name)
        shape.setName(name)
        store_group_settings(shape, settings)
        return LoadedBubble(
            BubbleTarget(document, layer.uniqueId(), name, transform_values(baseline)),
            settings, layer.name())

    def import_legacy(self) -> LoadedBubble:
        document = self.active_document()
        layer = document.activeNode() if document is not None else None
        if document is None or layer is None or layer.type() != "vectorlayer":
            raise GatewayError("Select the old bubble's vector layer before importing it.")
        if layer.locked():
            raise GatewayError("Unlock the old bubble layer before importing it.")
        if self.bubble_shapes(document, layer):
            raise GatewayError(
                "This layer already contains a generated bubble group. Import requires one "
                "ungrouped old bubble. Select a generated bubble to edit or recover it.")
        if self.renderer is None:
            raise GatewayError("The legacy bubble renderer is not configured.")
        legacy = read_legacy_bubble(layer.toSvg())
        shapes = layer.shapes()
        if len(shapes) != legacy.shape_count or any(
                shape.type() == "groupshape" for shape in shapes):
            raise GatewayError("Import requires one ungrouped old bubble and no other artwork.")
        if (any(shape.name() == SHAPE_NAME for shape in shapes)
                or document.annotation(self.annotation_key(layer))):
            raise GatewayError("This layer already has bubble editing data; it cannot be imported.")
        # Fit extra padding to the recovered body, including the new style's
        # enclosure allowance rather than counting that allowance twice.
        low, high = INTEGER_RANGES["padding"]
        while low < high:
            middle = (low + high + 1) // 2
            candidate = replace(legacy.settings, padding=middle)
            bounds = self.renderer.render(candidate).view_box
            if (bounds.width() <= legacy.body.width()
                    and bounds.height() <= legacy.body.height()):
                low = middle
            else:
                high = middle - 1
        settings = replace(legacy.settings, padding=low)
        generated = self.renderer.render(settings).view_box
        if generated.isEmpty() or document.xRes() <= 0 or document.yRes() <= 0:
            raise GatewayError("The bubble size or document resolution is invalid.")
        if legacy.tip is not None:
            # Fit before placement scaling so the first redraw keeps the old tip.
            inverse_placement, invertible = legacy.placement(generated).inverted()
            if not invertible:
                raise GatewayError("The old bubble placement is not invertible.")
            point = inverse_placement.map(legacy.transform.map(legacy.tip))
            fitted = self.renderer.move_tail(replace(settings, lock_tail=False), point)
            settings = replace(fitted, lock_tail=settings.lock_tail)
        delta = QTransform.fromScale(document.xRes() / 72, document.xRes() / 72) * (
            legacy.placement(generated))
        inverse, invertible = delta.inverted()
        if not invertible:
            raise GatewayError("The old bubble placement is not invertible.")
        name = SHAPE_NAME + "-" + uuid.uuid4().hex
        group = self.bubble_group(layer, shapes, name)
        if group is None:
            raise GatewayError("Krita could not group the old bubble shapes.")
        # A synthetic import baseline lets the first redraw retain the old body's
        # canvas placement even though its original shapes used unrelated origins.
        baseline = group.transformation() * inverse
        self.save_settings(document, layer, settings, baseline, name)
        for shape in shapes:
            self.deselect_shape(shape)
        group.select()
        self.refresh_canvas(document)
        return LoadedBubble(
            BubbleTarget(document, layer.uniqueId(), name, transform_values(baseline)),
            settings, layer.name())

    def create(self, settings: BubbleSettings, svg: str,
               new_layer: bool) -> LoadedBubble:
        document = self.active_document()
        if document is None:
            raise GatewayError("Open a document before adding a bubble.")
        if new_layer:
            layer = document.createVectorLayer(settings.text[:16] or "Speech bubble")
            if layer is None:
                raise GatewayError("Krita could not create a vector layer.")
            if not document.rootNode().addChildNode(layer, None):
                self._discard_import(layer, [], remove_layer=True)
                raise GatewayError("Krita could not add the bubble layer.")
        else:
            layer = document.activeNode()
            if layer is None or layer.type() != "vectorlayer":
                raise GatewayError("Select a vector layer before adding a bubble to an existing layer.")
            if layer.locked():
                raise GatewayError("Unlock the selected vector layer before adding a bubble.")
        previous = layer.shapes()
        name = SHAPE_NAME + "-" + uuid.uuid4().hex
        shapes = layer.addShapesFromSvg(svg)
        if not shapes:
            if new_layer:
                self._discard_import(layer, [], remove_layer=True)
            raise GatewayError("Krita could not import the bubble SVG.")
        group = self.bubble_group(layer, shapes, name)
        if group is None:
            self._discard_import(layer, shapes, new_layer)
            raise GatewayError("Krita could not group the bubble shapes.")
        baseline = group.transformation()
        group.setZIndex(max((shape.zIndex() for shape in previous), default=-1) + 1)
        bounds = group.boundingBox()
        margin = settings.font_size
        x, y = margin, margin
        if not new_layer and previous:
            previous_bounds = previous[-1].boundingBox()
            x = max(margin, previous_bounds.left() + margin)
            y = max(margin, previous_bounds.top() + margin)
        placement = QTransform.fromTranslate(x - bounds.left(), y - bounds.top())
        self.place_shape(group, baseline * placement)
        store_group_settings(group, settings)
        self.save_settings(document, layer, settings, baseline, name)
        document.setActiveNode(layer)
        for shape in previous:
            if self.shape_selected(shape):
                self.deselect_shape(shape)
        group.select()
        self.refresh_canvas(document)
        return LoadedBubble(
            BubbleTarget(document, layer.uniqueId(), name, transform_values(baseline)),
            settings, layer.name())

    @staticmethod
    def _discard_import(layer: Node, shapes: Sequence[Shape],
                        remove_layer: bool = False) -> None:
        removed = layer.remove() if remove_layer else all([shape.remove() for shape in shapes])
        if not removed:
            raise GatewayError("Krita could not remove the failed bubble import.")

    def _target_shape(self, target: BubbleTarget) -> Tuple[Document, Node, Shape]:
        document = self.active_document()
        if document is None or document != target.document:
            raise GatewayError("Return to the document containing the bubble being edited.")
        # Session identities stay opaque until they return to their owning gateway.
        layer = document.nodeByUniqueID(cast(QUuid, target.layer_id))
        if layer is None or layer.type() != "vectorlayer":
            raise TargetMissing("The bubble layer no longer exists. Select a bubble and reopen it.")
        shape = self.shape_by_name(layer, target.shape_name)
        if shape is None:
            raise TargetMissing(
                "The bubble's vector structure has changed. Updating would overwrite manual edits.")
        return document, layer, shape

    def update(self, target: BubbleTarget, settings: BubbleSettings,
               svg: str) -> BubbleTarget:
        try:
            document, layer, old = self._target_shape(target)
        except TargetMissing:
            document = self.active_document()
            if document is None or not stable_name(target.shape_name):
                raise
            original_layer = document.nodeByUniqueID(cast(QUuid, target.layer_id))
            if (original_layer is not None and original_layer.type() == "vectorlayer"
                    and any(shape.name() == target.shape_name for shape in original_layer.shapes())):
                raise
            matches = self.named_groups(document, target.shape_name)
            if len(matches) != 1:
                raise
            layer, old = matches[0]
            target = self._restore_shape(document, layer, old).target
        if layer.locked():
            raise GatewayError("Unlock the bubble layer before updating it.")
        selected = self.shape_selected(old)
        inverse, invertible = QTransform(*target.baseline).inverted()
        if not invertible:
            raise GatewayError("The saved bubble transform is not invertible.")
        delta = inverse * old.transformation()
        shapes = layer.addShapesFromSvg(svg)
        if not shapes:
            raise GatewayError("Krita could not import the updated bubble SVG.")
        group = self.bubble_group(layer, shapes, target.shape_name)
        if group is None:
            self._discard_import(layer, shapes)
            raise GatewayError("Krita could not group the updated bubble shapes.")
        baseline = group.transformation()
        self.place_shape(group, baseline * delta, old.boundingBox())
        group.setZIndex(old.zIndex())
        if not old.remove():
            if not group.remove():
                raise GatewayError("Krita could not replace or remove the imported bubble.")
            raise GatewayError("Krita could not replace the original bubble.")
        if selected:
            group.select()
        store_group_settings(group, settings)
        self.save_settings(document, layer, settings, baseline, target.shape_name)
        self.refresh_canvas(document)
        return replace(target, baseline=transform_values(baseline))

    def placement(self, target: BubbleTarget) -> QTransform:
        document, _, shape = self._target_shape(target)
        try:
            return canvas_transform(document, QTransform(*target.baseline), shape)
        except ValueError as error:
            raise GatewayError(str(error)) from error

    def snapshot(self, target: BubbleTarget) -> CanvasContext:
        document, layer, shape = self._target_shape(target)
        try:
            transform = canvas_transform(document, QTransform(*target.baseline), shape)
            image, rect = canvas_snapshot(document, layer, target.shape_name)
        except ValueError as error:
            raise GatewayError(str(error)) from error
        return CanvasContext(image, rect, transform)
