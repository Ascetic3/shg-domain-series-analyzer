from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from matplotlib import get_data_path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

import shg_domain_analyzer.gui.main_window as main_window_module
from shg_domain_analyzer.export import execute_series
from shg_domain_analyzer.image_io import preflight_series
from shg_domain_analyzer.measurements import analyze_array
from shg_domain_analyzer.models import LayerMetadata, ProcessingParameters, SOURCE_RAW_TXT, SeriesConfig
from shg_domain_analyzer.visualization import save_depth_plots, save_qc_plot
from shg_domain_analyzer.gui.main_window import MainWindow


CHECK_FILENAME = "synthetic_check_in_memory.txt"


def process_events(app: QApplication, seconds: float = 0.25) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def save_widget(widget: QWidget, path: Path, app: QApplication) -> None:
    process_events(app)
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"Could not save screenshot: {path}")


def add_real_check_example(window: MainWindow, outcome, run_dir: Path) -> np.ndarray:
    check_array = np.zeros((192, 192), dtype=np.float64)
    check_array[:, 92:100] = 1.0
    layer = LayerMetadata(
        filename=CHECK_FILENAME,
        source_path="in-memory synthetic screenshot fixture",
        layer_index=10,
        z_um=125.0,
        status="CHECK",
        source_number=11,
        matrix_shape=check_array.shape,
        source_min=0.0,
        source_max=1.0,
        import_status="valid",
    )
    analysis = analyze_array(check_array, layer, 192.0, ProcessingParameters())
    if analysis.summary["status"] != "CHECK":
        raise RuntimeError("The screenshot fixture must produce a real CHECK result with default parameters.")
    analysis.summary["source_type"] = SOURCE_RAW_TXT
    qc_path = run_dir / "qc" / "synthetic_check_in_memory_qc.png"
    save_qc_plot(
        qc_path,
        filename=layer.filename,
        layer_index=layer.layer_index,
        z_um=layer.z_um,
        rotated_crop=analysis.cropped_image,
        profile=analysis.profile,
        summary=analysis.summary,
        walls=analysis.bands,
        black_domains=analysis.dark_intervals,
        um_per_px=analysis.um_per_px,
    )
    window._layers.append(layer)
    outcome.summaries.append(analysis.summary)
    outcome.walls.extend(analysis.wall_rows)
    outcome.domains.extend(analysis.domain_rows)
    outcome.qc_paths[layer.filename] = str(qc_path)
    outcome.plot_paths = [
        str(path)
        for path in save_depth_plots(run_dir / "plots", outcome.summaries, outcome.domains)
    ]
    return check_array


def main() -> int:
    screenshot_dir = ROOT / "screenshots" / "gui_enhancements"
    docs_dir = ROOT / "docs" / "images"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    names = [
        "01_source_navigation.png",
        "02_qc_fit.png",
        "03_qc_zoomed.png",
        "04_qc_full_size_window.png",
        "05_depth_summary.png",
        "06_dark_interval_distribution.png",
        "07_check_layer_qc.png",
    ]
    for name in names:
        path = screenshot_dir / name
        if path.exists():
            path.unlink()
    docs_names = [
        "series_setup.png",
        "source_preview.png",
        "qc_preview.png",
        "qc_zoom.png",
        "depth_distribution.png",
    ]
    for name in docs_names:
        path = docs_dir / name
        if path.exists():
            path.unlink()

    app = QApplication.instance() or QApplication(sys.argv)
    font_path = Path(get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
    if QFontDatabase.addApplicationFont(str(font_path)) < 0:
        raise RuntimeError(f"Could not register screenshot font: {font_path}")
    app.setFont(QFont("DejaVu Sans", 10))
    input_dir = ROOT / "demo" / "synthetic_series" / "txt"
    temporary = ROOT / "demo" / "gui_enhancement_capture"
    temporary.mkdir(parents=True, exist_ok=True)
    original_read_source_array = main_window_module.read_source_array
    try:
        config = SeriesConfig(
            input_dir=str(input_dir),
            output_dir=str(temporary / "results"),
            frame_width_um=192.0,
            z_start_um=0.0,
            z_step_um=12.5,
            source_type=SOURCE_RAW_TXT,
            direction="increasing",
            order_confirmed=True,
        )
        report = preflight_series(config)
        if not report.is_valid:
            raise RuntimeError("Screenshot preflight failed: " + " | ".join(report.errors))
        config.layers = report.layers
        outcome = execute_series(config)

        window = MainWindow()
        window.setStyleSheet(window.styleSheet().replace('"Segoe UI"', '"DejaVu Sans"'))
        window.resize(1540, 960)

        window.input_edit.setText("demo/synthetic_series/txt")
        window.output_edit.setText("analysis_results")
        window.frame_width_spin.setValue(192.0)
        window.z_start_spin.setValue(0.0)
        window.z_step_spin.setValue(12.5)
        window.direction_combo.setCurrentIndex(0)
        window.refresh_preflight()
        window.show()
        window.tabs.setCurrentIndex(0)
        window.layer_table.clearSelection()
        save_widget(window, docs_dir / docs_names[0], app)

        window._layers = [layer for layer in config.layers if layer.import_status == "valid"]
        check_array: np.ndarray | None = None

        def screenshot_read_source_array(layer, source_type):
            if layer.filename == CHECK_FILENAME:
                if check_array is None:
                    raise RuntimeError("CHECK screenshot array is unavailable.")
                return check_array.copy()
            return original_read_source_array(layer, source_type)

        main_window_module.read_source_array = screenshot_read_source_array
        window._outcome = outcome
        window._populate_source_preview_choices()
        window._populate_results(outcome)
        process_events(app, 0.4)

        window.tabs.setCurrentWidget(window.source_preview_page)
        window.source_preview_combo.setCurrentIndex(5)
        window.source_preview.fit_to_window()
        save_widget(window, screenshot_dir / names[0], app)
        save_widget(window, docs_dir / docs_names[1], app)

        window.tabs.setCurrentWidget(window.qc_preview_page)
        window.qc_combo.setCurrentIndex(5)
        window.original_preview.fit_to_window()
        window.qc_preview.fit_to_window()
        save_widget(window, screenshot_dir / names[1], app)
        save_widget(window, docs_dir / docs_names[2], app)

        window.qc_preview.actual_size()
        width, height = window.qc_preview.pixmap_size()
        window.qc_preview.centerOn(width * 0.52, height * 0.70)
        save_widget(window, screenshot_dir / names[2], app)
        save_widget(window, docs_dir / docs_names[3], app)

        window.open_full_size_qc()
        if window._full_size_qc_window is None:
            raise RuntimeError("Full-size QC window did not open.")
        window._full_size_qc_window.viewer.fit_to_window()
        save_widget(window._full_size_qc_window, screenshot_dir / names[3], app)
        window._full_size_qc_window.close()

        window.tabs.setCurrentIndex(window.tabs.indexOf(window.plot_preview.parentWidget()))
        distribution_index = window.plot_combo.findText("Dark-interval distribution by depth")
        window.plot_combo.setCurrentIndex(distribution_index)
        save_widget(window, docs_dir / docs_names[4], app)

        check_array = add_real_check_example(window, outcome, Path(outcome.run_dir))
        window._populate_source_preview_choices()
        window._populate_results(outcome)
        window.tabs.setCurrentIndex(window.tabs.indexOf(window.plot_preview.parentWidget()))
        summary_index = window.plot_combo.findText("Depth summary")
        window.plot_combo.setCurrentIndex(summary_index)
        save_widget(window, screenshot_dir / names[4], app)

        distribution_index = window.plot_combo.findText("Dark-interval distribution by depth")
        window.plot_combo.setCurrentIndex(distribution_index)
        save_widget(window, screenshot_dir / names[5], app)

        window.tabs.setCurrentWidget(window.qc_preview_page)
        window.qc_combo.setCurrentIndex(window.qc_combo.findData(CHECK_FILENAME))
        window.original_preview.fit_to_window()
        window.qc_preview.fit_to_window()
        save_widget(window, screenshot_dir / names[6], app)
        window.close()
    finally:
        main_window_module.read_source_array = original_read_source_array
        shutil.rmtree(temporary, ignore_errors=False)

    for name in names:
        print((screenshot_dir / name).resolve())
    for name in docs_names:
        print((docs_dir / name).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
