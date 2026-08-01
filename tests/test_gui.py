from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import shg_domain_analyzer.gui.main_window as main_window_module
from shg_domain_analyzer.gui.image_viewer import ImageViewer
from shg_domain_analyzer.gui.main_window import MainWindow
from shg_domain_analyzer.models import LayerMetadata, RunOutcome


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def preview_window(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    monkeypatch.setattr(
        main_window_module,
        "read_source_array",
        lambda _layer, _source_type: np.arange(200, dtype=float).reshape(10, 20),
    )
    window = MainWindow()
    window._layers = [
        LayerMetadata(f"layer_{index + 1:03d}.txt", str(Path("unused") / f"{index}.txt"), index, index * 12.5)
        for index in range(3)
    ]
    rows = [
        {
            "filename": layer.filename,
            "layer_index": layer.layer_index,
            "z_um": layer.z_um,
            "status": "CHECK" if layer.layer_index == 1 else "OK",
        }
        for layer in window._layers
    ]
    window._outcome = RunOutcome("unused", rows, [], [], [], {}, [])
    for combo in (window.source_preview_combo, window.qc_combo):
        combo.blockSignals(True)
        combo.clear()
        for layer in window._layers:
            combo.addItem(layer.filename, layer.filename)
        combo.blockSignals(False)
    window._source_layer_changed()
    window.show()
    app.processEvents()
    yield window
    window.close()


def test_previous_next_and_boundary_buttons(preview_window: MainWindow) -> None:
    window = preview_window
    assert window.source_preview_combo.currentIndex() == 0
    assert not window.source_previous_button.isEnabled()
    assert window.source_next_button.isEnabled()

    window.source_next_button.click()
    assert window.source_preview_combo.currentIndex() == 1
    assert window.qc_combo.currentIndex() == 1
    assert window.source_layer_indicator.text() == "Layer 2 of 3"

    window.source_next_button.click()
    assert window.source_preview_combo.currentIndex() == 2
    assert not window.source_next_button.isEnabled()
    window.source_next_button.click()
    assert window.source_preview_combo.currentIndex() == 2

    window.source_previous_button.click()
    assert window.source_preview_combo.currentIndex() == 1


def test_preview_shortcuts_and_setup_isolation(preview_window: MainWindow, app: QApplication) -> None:
    window = preview_window
    window.tabs.setCurrentWidget(window.source_preview_page)
    window.source_preview_viewer.setFocus()
    window.source_preview_combo.setCurrentIndex(0)
    QTest.keyClick(window.source_preview_viewer, Qt.Key_Right)
    app.processEvents()
    assert window.source_preview_combo.currentIndex() == 1
    QTest.keyClick(window.source_preview_viewer, Qt.Key_End)
    assert window.source_preview_combo.currentIndex() == 2
    QTest.keyClick(window.source_preview_viewer, Qt.Key_Home)
    assert window.source_preview_combo.currentIndex() == 0

    window.tabs.setCurrentWidget(window.qc_preview_page)
    window.qc_preview.setFocus()
    QTest.keyClick(window.qc_preview, Qt.Key_Right)
    app.processEvents()
    assert window.qc_combo.currentIndex() == 1
    QTest.keyClick(window.qc_preview, Qt.Key_Left)
    assert window.qc_combo.currentIndex() == 0

    window.tabs.setCurrentIndex(0)
    window.frame_width_spin.setFocus()
    QTest.keyClick(window.frame_width_spin, Qt.Key_Right)
    app.processEvents()
    assert window.source_preview_combo.currentIndex() == 0


def test_layer_change_synchronizes_filename_z_and_status(preview_window: MainWindow) -> None:
    window = preview_window
    window.qc_combo.setCurrentIndex(1)
    assert window.source_preview_combo.currentData() == "layer_002.txt"
    assert "filename: layer_002.txt" in window.source_preview_metadata.text()
    assert "layer_index: 1" in window.source_preview_metadata.text()
    assert "z: 12.500 µm" in window.source_preview_metadata.text()
    assert "status: CHECK" in window.qc_metadata.text()
    assert "#fee2e2" in window.qc_metadata.styleSheet()


def test_viewer_preserves_aspect_ratio_and_fit_actual_are_safe(app: QApplication) -> None:
    viewer = ImageViewer()
    viewer.resize(600, 400)
    viewer.show()
    pixmap = QPixmap(400, 200)
    pixmap.fill(Qt.white)
    viewer.set_pixmap(pixmap)
    app.processEvents()

    viewer.fit_to_window()
    assert viewer.transform().m11() == pytest.approx(viewer.transform().m22())
    assert viewer.pixmap_size() == (400, 200)
    assert ImageViewer.MIN_SCALE <= viewer.scale_factor <= ImageViewer.MAX_SCALE

    viewer.actual_size()
    assert viewer.scale_factor == pytest.approx(1.0)
    viewer.zoom_in()
    viewer.zoom_out()
    viewer.fit_to_window()
    assert viewer.transform().m11() == pytest.approx(viewer.transform().m22())
    viewer.close()
