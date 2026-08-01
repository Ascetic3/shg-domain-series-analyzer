from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ImageViewer(QGraphicsView):
    """Aspect-preserving image viewer with bounded zoom and mouse panning."""

    zoom_changed = Signal(int)
    MIN_SCALE = 0.10
    MAX_SCALE = 8.00
    ZOOM_STEP = 1.25

    def __init__(self, message: str = "No image selected", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._message_item: QGraphicsTextItem | None = None
        self._fit_mode = True
        self._fit_scale = 1.0
        self.setAlignment(Qt.AlignCenter)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.set_message(message)

    @property
    def scale_factor(self) -> float:
        return float(self.transform().m11())

    @property
    def has_image(self) -> bool:
        return not self._pixmap_item.pixmap().isNull()

    def pixmap_size(self) -> tuple[int, int]:
        pixmap = self._pixmap_item.pixmap()
        return pixmap.width(), pixmap.height()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._remove_message()
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if pixmap.isNull():
            self.set_message("Image unavailable")
        else:
            self.fit_to_window()

    def set_image_path(self, path: str | Path | None) -> bool:
        if not path or not Path(path).is_file():
            self.set_message("Image unavailable")
            return False
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.set_message("Image unavailable")
            return False
        self.set_pixmap(pixmap)
        return True

    def set_message(self, message: str) -> None:
        self._pixmap_item.setPixmap(QPixmap())
        self._remove_message()
        self._message_item = self._scene.addText(message)
        self._message_item.setDefaultTextColor(Qt.darkGray)
        self._scene.setSceneRect(self._message_item.boundingRect())
        self.resetTransform()
        self._fit_mode = True
        self._emit_zoom()

    def clear(self) -> None:
        self.set_message("No image selected")

    def fit_to_window(self) -> None:
        if not self.has_image:
            return
        bounds = self._pixmap_item.boundingRect()
        viewport = self.viewport().size()
        if bounds.width() <= 0 or bounds.height() <= 0 or viewport.width() <= 1 or viewport.height() <= 1:
            return
        scale = min(viewport.width() / bounds.width(), viewport.height() / bounds.height())
        self._fit_scale = self._bounded_scale(scale)
        self._set_absolute_scale(self._fit_scale)
        self.centerOn(self._pixmap_item)
        self._fit_mode = True

    def actual_size(self) -> None:
        if not self.has_image:
            return
        self._fit_mode = False
        self._set_absolute_scale(1.0)
        self.centerOn(self._pixmap_item)

    def zoom_in(self) -> None:
        self._zoom_to(self.scale_factor * self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom_to(self.scale_factor / self.ZOOM_STEP)

    def _zoom_to(self, requested_scale: float) -> None:
        if not self.has_image:
            return
        target = self._bounded_scale(requested_scale)
        current = self.scale_factor or 1.0
        self._fit_mode = False
        self.scale(target / current, target / current)
        self._update_drag_mode()
        self._emit_zoom()

    def _set_absolute_scale(self, scale: float) -> None:
        bounded = self._bounded_scale(scale)
        self.resetTransform()
        self.scale(bounded, bounded)
        self._update_drag_mode()
        self._emit_zoom()

    @classmethod
    def _bounded_scale(cls, value: float) -> float:
        return min(cls.MAX_SCALE, max(cls.MIN_SCALE, float(value)))

    def _update_drag_mode(self) -> None:
        pannable = self.has_image and self.scale_factor > self._fit_scale + 1e-6
        self.setDragMode(QGraphicsView.ScrollHandDrag if pannable else QGraphicsView.NoDrag)

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(int(round(self.scale_factor * 100)))

    def _remove_message(self) -> None:
        if self._message_item is not None:
            self._scene.removeItem(self._message_item)
            self._message_item = None

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        if not self.has_image or event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return
        self._zoom_to(self.scale_factor * (self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP))
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton and self.has_image:
            self.fit_to_window()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_to_window()


class ZoomControls(QWidget):
    def __init__(self, viewer: ImageViewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewer = viewer
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.zoom_out_button = QPushButton("Zoom out")
        self.zoom_in_button = QPushButton("Zoom in")
        self.fit_button = QPushButton("Fit to window")
        self.actual_button = QPushButton("100%")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(45)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_out_button.clicked.connect(viewer.zoom_out)
        self.zoom_in_button.clicked.connect(viewer.zoom_in)
        self.fit_button.clicked.connect(viewer.fit_to_window)
        self.actual_button.clicked.connect(viewer.actual_size)
        viewer.zoom_changed.connect(lambda percent: self.zoom_label.setText(f"{percent}%"))
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button, self.actual_button):
            layout.addWidget(button)
        layout.addWidget(self.zoom_label)
        layout.addStretch(1)


class FullSizeImageDialog(QDialog):
    def __init__(self, path: str | Path, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1280, 820)
        layout = QVBoxLayout(self)
        self.viewer = ImageViewer()
        self.controls = ZoomControls(self.viewer)
        layout.addWidget(self.controls)
        layout.addWidget(self.viewer, 1)
        self.viewer.set_image_path(path)

