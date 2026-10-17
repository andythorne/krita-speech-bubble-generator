from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QTransform


def canvas_transform(document, baseline, shape):
    inverse, invertible = baseline.inverted()
    if not invertible:
        raise ValueError("The saved bubble transform is not invertible")
    x_res, y_res = document.xRes(), document.yRes()
    if x_res <= 0 or y_res <= 0:
        raise ValueError("The document resolution is invalid")
    # Krita imports unitless SVG at one image pixel per unit, but exposes shapes in points.
    transform = (
        QTransform.fromScale(72 / x_res, 72 / x_res)
        * inverse * shape.absoluteTransformation()
        * QTransform.fromScale(x_res / 72, y_res / 72)
    )
    if not transform.isInvertible():
        raise ValueError("The bubble's canvas transform is not invertible")
    return transform


def canvas_snapshot(document, layer, shape_name=None):
    path = []
    node = layer
    parent = node.parentNode()
    while parent is not None:
        siblings = parent.childNodes()
        index = next((index for index, sibling in enumerate(siblings)
                      if sibling.uniqueId() == node.uniqueId()), None)
        if index is None:
            raise ValueError("The bubble could not be located in the layer tree")
        path.append(index)
        node = parent
        parent = node.parentNode()

    document.waitForDone()
    snapshot = document.clone()
    if snapshot is None:
        raise ValueError("Krita could not create a canvas snapshot")
    try:
        node = snapshot.rootNode()
        for index in reversed(path):
            children = node.childNodes()
            if index >= len(children):
                raise ValueError("The bubble could not be located in the canvas snapshot")
            node = children[index]
        # Hide only the edited group; other bubbles on a shared layer stay visible.
        if shape_name is not None:
            shapes = [shape for shape in node.shapes() if shape.name() == shape_name]
            if len(shapes) != 1:
                raise ValueError("The bubble could not be located in the canvas snapshot")
            shapes[0].setVisible(False)
            shapes[0].update()
        else:
            node.setVisible(False)
        snapshot.waitForDone()
        snapshot.refreshProjection()
        width, height = document.width(), document.height()
        if width <= 0 or height <= 0:
            raise ValueError("The document has no canvas area")
        scale = min(1, 2048 / max(width, height))
        image = snapshot.thumbnail(max(1, round(width * scale)),
                                   max(1, round(height * scale)))
        if image.isNull():
            raise ValueError("Krita could not render the canvas snapshot")
        return image, QRectF(0, 0, width, height)
    finally:
        snapshot.close()
