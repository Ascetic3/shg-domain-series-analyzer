from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import load_series_config, save_series_config
from ..image_io import preflight_series, read_source_array
from ..models import (
    LayerMetadata,
    PreflightReport,
    RunOutcome,
    SCIENTIFIC_WARNING,
    SOURCE_LEGACY_IMAGES,
    SOURCE_RAW_TXT,
    SeriesConfig,
)
from ..visualization import preview_to_uint8
from .image_viewer import FullSizeImageDialog, ImageViewer, ZoomControls
from .localization import install_application_language, load_application_language
from .worker import AnalysisWorker


SUMMARY_COLUMNS = [
    ("filename", "filename"),
    ("layer_index", "layer_index"),
    ("z_um", "z, µm"),
    ("status", "status"),
    ("n_detected_bright_bands", "bright bands"),
    ("n_dark_intervals", "dark intervals"),
    ("candidate_band_mean_um", "candidate wall width, µm"),
    ("candidate_dark_interval_mean_um", "candidate domain width, µm"),
    ("period_band_centers_um", "period, µm"),
    ("rotation_to_vertical_deg", "rotation, °"),
]


class MainWindow(QMainWindow):
    processing_started = Signal()
    processing_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bright-band series analyzer — Raw TXT portfolio MVP")
        self.resize(1480, 920)
        self._layers: list[LayerMetadata] = []
        self._preflight_report = PreflightReport()
        self._outcome: RunOutcome | None = None
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._completion_dialog: QMessageBox | None = None
        self._full_size_qc_window: FullSizeImageDialog | None = None
        self._syncing_layer_selection = False
        self._preview_shortcuts: list[QShortcut] = []
        self._last_unit = "µm"
        self._build_ui()
        self._apply_style()
        self._source_type_changed()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 13, 16, 13)
        root.setSpacing(8)

        title = QLabel("Periodic bright-band series analyzer")
        title.setObjectName("title")
        subtitle = QLabel("Raw floating-point matrices and legacy images share one detector through analyze_array().")
        subtitle.setObjectName("subtitle")
        warning = QLabel(SCIENTIFIC_WARNING)
        warning.setObjectName("warningBanner")
        warning.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(warning)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_setup_tab()
        self._build_source_preview_tab()
        self._build_summary_tab()
        self._build_qc_tab()
        self._build_plots_tab()
        self._build_errors_tab()
        self.setCentralWidget(central)

    def _build_setup_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        selection_group = QGroupBox("A. Source series")
        selection_layout = QVBoxLayout(selection_group)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source type"))
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItem("Raw TXT matrices", SOURCE_RAW_TXT)
        self.source_type_combo.addItem("PNG/TIFF images", SOURCE_LEGACY_IMAGES)
        self.source_type_combo.currentIndexChanged.connect(self._source_type_changed)
        self.source_explanation = QLabel()
        self.source_explanation.setObjectName("sourceExplanation")
        source_row.addWidget(self.source_type_combo)
        source_row.addWidget(self.source_explanation, 1)
        selection_layout.addLayout(source_row)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Source folder"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Folder containing safe TXT matrices")
        choose_input = QPushButton("Browse…")
        choose_input.clicked.connect(self.choose_input_directory)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(choose_input)
        selection_layout.addLayout(input_row)

        stats = QGridLayout()
        self.found_label = QLabel("Found files: 0")
        self.valid_label = QLabel("Valid matrices: 0")
        self.invalid_label = QLabel("Invalid files: 0")
        self.shape_label = QLabel("Common shape: —")
        self.first_label = QLabel("First: —")
        self.last_label = QLabel("Last: —")
        self.gaps_label = QLabel("Detected gaps: —")
        self.numbering_label = QLabel("Numbering: —")
        for position, widget in enumerate(
            (
                self.found_label, self.valid_label, self.invalid_label, self.shape_label,
                self.first_label, self.last_label, self.gaps_label, self.numbering_label,
            )
        ):
            stats.addWidget(widget, position // 4, position % 4)
        selection_layout.addLayout(stats)

        columns = [
            "filename", "source_number", "layer_index", "z", "matrix_shape",
            "minimum", "maximum", "import_status",
        ]
        self.layer_table = QTableWidget(0, len(columns))
        self.layer_table.setHorizontalHeaderLabels(columns)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.layer_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.layer_table.currentCellChanged.connect(self._table_selection_changed)
        header = self.layer_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        selection_layout.addWidget(self.layer_table, 1)
        layout.addWidget(selection_group, 3)

        lower = QSplitter(Qt.Horizontal)
        parameter_group = QGroupBox("B. Series parameters and optional exports")
        form = QFormLayout(parameter_group)
        self.frame_width_spin = self._double_spin(200.0, 0.0, 1_000_000.0, 3)
        self.z_start_spin = self._double_spin(0.0, -1_000_000.0, 1_000_000.0, 3)
        self.z_step_spin = self._double_spin(10.0, 0.0, 1_000_000.0, 3)
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["increasing z", "decreasing z"])
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["µm", "mm"])
        self.unit_combo.currentTextChanged.connect(self._unit_changed)
        form.addRow("Physical frame width", self.frame_width_spin)
        form.addRow("First layer position z₀", self.z_start_spin)
        form.addRow("Layer spacing Δz", self.z_step_spin)
        form.addRow("Direction", self.direction_combo)
        form.addRow("Display unit", self.unit_combo)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Base folder; every run creates a new run_* directory")
        choose_output = QPushButton("Browse…")
        choose_output.clicked.connect(self.choose_output_directory)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(choose_output)
        form.addRow("Results base folder", output_row)
        self.export_preview_checkbox = QCheckBox("Export preview PNG files (display only; percentiles 1/99)")
        self.export_tiff_checkbox = QCheckBox("Export float32 TIFF stack (ZYX; no contrast or quantization)")
        form.addRow(self.export_preview_checkbox)
        form.addRow(self.export_tiff_checkbox)

        config_row = QHBoxLayout()
        save_config_button = QPushButton("Save config JSON…")
        load_config_button = QPushButton("Load config JSON…")
        save_config_button.clicked.connect(self.save_config_dialog)
        load_config_button.clicked.connect(self.load_config_dialog)
        config_row.addWidget(save_config_button)
        config_row.addWidget(load_config_button)
        form.addRow(config_row)

        validation_group = QGroupBox("C. Import and preflight validation")
        validation_layout = QVBoxLayout(validation_group)
        self.preflight_text = QTextEdit()
        self.preflight_text.setReadOnly(True)
        self.preflight_text.setMinimumHeight(145)
        self.preflight_text.setPlaceholderText("Choose an input folder to inspect the source series.")
        self.confirm_order_checkbox = QCheckBox("I confirm the displayed order and any numeric gaps")
        validation_layout.addWidget(self.preflight_text)
        validation_layout.addWidget(self.confirm_order_checkbox)

        lower.addWidget(parameter_group)
        lower.addWidget(validation_group)
        lower.setStretchFactor(0, 1)
        lower.setStretchFactor(1, 1)
        layout.addWidget(lower, 2)

        run_group = QGroupBox("D. Run")
        run_layout = QHBoxLayout(run_group)
        self.run_button = QPushButton("Run analysis")
        self.run_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.current_file_label = QLabel("Current file: —")
        self.result_counts_label = QLabel("processed 0  •  OK 0  •  CHECK 0  •  errors 0")
        self.run_button.clicked.connect(self.run_analysis)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        run_layout.addWidget(self.run_button)
        run_layout.addWidget(self.cancel_button)
        run_layout.addWidget(self.progress_bar, 1)
        run_layout.addWidget(self.current_file_label, 1)
        run_layout.addWidget(self.result_counts_label)
        layout.addWidget(run_group)

        for widget in (self.frame_width_spin, self.z_start_spin, self.z_step_spin):
            widget.editingFinished.connect(self.refresh_preflight)
        self.direction_combo.currentIndexChanged.connect(self.refresh_preflight)
        self.input_edit.editingFinished.connect(self.refresh_preflight)
        self.output_edit.editingFinished.connect(self.refresh_preflight)
        self.tabs.addTab(page, "Setup")

    def _build_source_preview_tab(self) -> None:
        page = QWidget()
        self.source_preview_page = page
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Source layer"))
        self.source_preview_combo = QComboBox()
        self.source_preview_combo.currentIndexChanged.connect(self._source_layer_changed)
        self.source_preview_metadata = QLabel("filename: — | layer_index: — | z: — | status: —")
        row.addWidget(self.source_preview_combo)
        row.addWidget(self.source_preview_metadata, 1)
        layout.addLayout(row)

        controls = QHBoxLayout()
        self.source_previous_button = QPushButton("← Previous")
        self.source_next_button = QPushButton("Next →")
        self.source_layer_indicator = QLabel("Layer 0 of 0")
        self.source_layer_indicator.setObjectName("layerIndicator")
        self.source_previous_button.clicked.connect(lambda: self._navigate_combo(self.source_preview_combo, -1))
        self.source_next_button.clicked.connect(lambda: self._navigate_combo(self.source_preview_combo, 1))
        controls.addWidget(self.source_previous_button)
        controls.addWidget(self.source_next_button)
        controls.addWidget(self.source_layer_indicator)
        controls.addSpacing(16)
        self.source_preview_viewer = ImageViewer("Choose and validate a source folder.")
        self.source_preview_viewer.setObjectName("imagePreview")
        self.source_preview = self.source_preview_viewer
        self.source_zoom_controls = ZoomControls(self.source_preview_viewer)
        controls.addWidget(self.source_zoom_controls, 1)
        layout.addLayout(controls)
        layout.addWidget(self.source_preview_viewer, 1)
        note = QLabel(
            "Display preview uses percentile normalization on a copy. The raw float matrix remains unchanged and is the analysis input."
        )
        note.setObjectName("inlineWarning")
        layout.addWidget(note)
        self.tabs.addTab(page, "Source preview")
        self._install_preview_shortcuts(page, self.source_preview_combo)

    def _build_summary_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel("Candidate measurements only. CHECK rows are not validated physical results.")
        note.setObjectName("inlineWarning")
        self.summary_table = QTableWidget(0, len(SUMMARY_COLUMNS))
        self.summary_table.setHorizontalHeaderLabels([label for _key, label in SUMMARY_COLUMNS])
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(note)
        layout.addWidget(self.summary_table, 1)
        self.tabs.addTab(page, "Summary")

    def _build_qc_tab(self) -> None:
        page = QWidget()
        self.qc_preview_page = page
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        top.addWidget(QLabel("Layer"))
        self.qc_combo = QComboBox()
        self.qc_combo.currentIndexChanged.connect(self._qc_layer_changed)
        self.qc_metadata = QLabel("filename: — | layer_index: — | z: —")
        top.addWidget(self.qc_combo)
        top.addWidget(self.qc_metadata, 1)
        layout.addLayout(top)

        navigation = QHBoxLayout()
        self.qc_previous_button = QPushButton("← Previous")
        self.qc_next_button = QPushButton("Next →")
        self.qc_layer_indicator = QLabel("Layer 0 of 0")
        self.qc_layer_indicator.setObjectName("layerIndicator")
        self.qc_previous_button.clicked.connect(lambda: self._navigate_combo(self.qc_combo, -1))
        self.qc_next_button.clicked.connect(lambda: self._navigate_combo(self.qc_combo, 1))
        navigation.addWidget(self.qc_previous_button)
        navigation.addWidget(self.qc_next_button)
        navigation.addWidget(self.qc_layer_indicator)
        navigation.addStretch(1)
        layout.addLayout(navigation)

        images = QSplitter(Qt.Horizontal)
        self.original_panel, self.original_preview, self.original_zoom_controls = self._preview_panel(
            "Display preview of source"
        )
        self.qc_panel, self.qc_preview, self.qc_zoom_controls = self._preview_panel("Full QC visualization")
        self.open_full_size_button = QPushButton("Open full size")
        self.open_full_size_button.clicked.connect(self.open_full_size_qc)
        self.qc_zoom_controls.layout().insertWidget(4, self.open_full_size_button)
        images.addWidget(self.original_panel)
        images.addWidget(self.qc_panel)
        layout.addWidget(images, 1)
        note = QLabel("B1, B2… are left-to-right interval order within this frame; intervals are not tracked between layers.")
        note.setObjectName("inlineWarning")
        layout.addWidget(note)
        self.tabs.addTab(page, "QC preview")
        self._install_preview_shortcuts(page, self.qc_combo)

    def _build_plots_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        warning = QLabel(
            "These plots summarize detections across depth. They do not track individual physical domains "
            "between layers and require scientific validation."
        )
        warning.setObjectName("warningBanner")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        row = QHBoxLayout()
        row.addWidget(QLabel("Exploratory plot"))
        self.plot_combo = QComboBox()
        self.plot_combo.currentIndexChanged.connect(self._update_plot_preview)
        row.addWidget(self.plot_combo)
        row.addStretch(1)
        layout.addLayout(row)
        self.plot_preview = QLabel("Run the analysis to generate depth plots.")
        self.plot_preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.plot_preview, 1)
        self.tabs.addTab(page, "Exploratory depth analysis")

    def _build_errors_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.errors_table = QTableWidget(0, 4)
        self.errors_table.setHorizontalHeaderLabels(["stage", "file", "error type", "message"])
        self.errors_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.errors_table)
        self.tabs.addTab(page, "Errors")

    @staticmethod
    def _double_spin(value: float, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        return widget

    @staticmethod
    def _preview_panel(title: str) -> tuple[QGroupBox, ImageViewer, ZoomControls]:
        container = QGroupBox(title)
        layout = QVBoxLayout(container)
        viewer = ImageViewer()
        viewer.setObjectName("imagePreview")
        controls = ZoomControls(viewer)
        layout.addWidget(controls)
        layout.addWidget(viewer, 1)
        return container, viewer, controls

    def _install_preview_shortcuts(self, page: QWidget, combo: QComboBox) -> None:
        actions = {
            "Left": lambda: self._navigate_combo(combo, -1),
            "Right": lambda: self._navigate_combo(combo, 1),
            "Home": lambda: self._set_combo_index(combo, 0),
            "End": lambda: self._set_combo_index(combo, combo.count() - 1),
        }
        for sequence, action in actions.items():
            shortcut = QShortcut(QKeySequence(sequence), page)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
            self._preview_shortcuts.append(shortcut)

    def _set_combo_index(self, combo: QComboBox, index: int) -> None:
        if combo.count() > 0:
            combo.setCurrentIndex(min(combo.count() - 1, max(0, index)))

    def _navigate_combo(self, combo: QComboBox, offset: int) -> None:
        if combo.count() > 0:
            self._set_combo_index(combo, combo.currentIndex() + offset)

    def _source_layer_changed(self, _index: int = -1) -> None:
        if self._syncing_layer_selection:
            return
        self._synchronize_layer_selection(self.source_preview_combo.currentData())

    def _qc_layer_changed(self, _index: int = -1) -> None:
        if self._syncing_layer_selection:
            return
        self._synchronize_layer_selection(self.qc_combo.currentData())

    def _synchronize_layer_selection(self, filename: object) -> None:
        self._syncing_layer_selection = True
        try:
            for combo in (self.source_preview_combo, self.qc_combo):
                target = combo.findData(filename) if filename is not None else -1
                if combo.currentIndex() != target:
                    combo.setCurrentIndex(target)
        finally:
            self._syncing_layer_selection = False
        self._update_source_preview()
        self._update_qc_preview()
        self._update_navigation_state()

    def _update_navigation_state(self) -> None:
        for combo, previous, next_button, indicator in (
            (
                self.source_preview_combo,
                self.source_previous_button,
                self.source_next_button,
                self.source_layer_indicator,
            ),
            (self.qc_combo, self.qc_previous_button, self.qc_next_button, self.qc_layer_indicator),
        ):
            index = combo.currentIndex()
            count = combo.count()
            previous.setEnabled(count > 0 and index > 0)
            next_button.setEnabled(count > 0 and 0 <= index < count - 1)
            indicator.setText(f"Layer {index + 1} of {count}" if index >= 0 else f"Layer 0 of {count}")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f7fb; }
            QWidget { font-family: "Segoe UI"; font-size: 10pt; color: #1e293b; }
            QLabel#title { font-size: 21pt; font-weight: 700; color: #0f2747; }
            QLabel#subtitle { color: #52647a; font-size: 10.5pt; }
            QLabel#warningBanner, QLabel#inlineWarning {
                background: #fff4d6; color: #784b00; border: 1px solid #e7c567;
                border-radius: 6px; padding: 7px;
            }
            QLabel#sourceExplanation { color: #28547a; padding-left: 8px; }
            QGroupBox {
                background: white; border: 1px solid #d8e0ea; border-radius: 8px;
                margin-top: 11px; padding-top: 10px; font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QPushButton { background: #e8eef7; border: 1px solid #b9c7d8; border-radius: 5px; padding: 6px 11px; }
            QPushButton#primaryButton { background: #1769aa; color: white; border-color: #1769aa; font-weight: 600; }
            QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {
                background: white; border: 1px solid #bec9d6; border-radius: 4px; padding: 4px;
            }
            QTableWidget { background: white; alternate-background-color: #f3f7fc; gridline-color: #d9e1ea; }
            QHeaderView::section { background: #e6edf6; padding: 5px; border: 0; border-right: 1px solid #c9d4e1; font-weight: 600; }
            QTabWidget::pane { border: 1px solid #cad5e2; background: #f9fbfd; }
            QTabBar::tab { background: #dfe8f2; padding: 8px 14px; margin-right: 2px; }
            QTabBar::tab:selected { background: white; color: #145b91; font-weight: 600; }
            QGraphicsView#imagePreview { background: #eef2f7; border: 1px solid #d4dce6; }
            QLabel#layerIndicator {
                background: #edf4fb; color: #174f7d; border: 1px solid #b8ccdf;
                border-radius: 4px; padding: 5px 10px; font-weight: 600;
            }
            """
        )

    def _source_type(self) -> str:
        return str(self.source_type_combo.currentData())

    def _source_type_changed(self) -> None:
        raw = self._source_type() == SOURCE_RAW_TXT
        self.source_explanation.setText(
            "Raw TXT mode analyzes the original floating-point matrices."
            if raw
            else "Legacy image mode analyzes already converted image files."
        )
        self.input_edit.setPlaceholderText(
            "Folder containing numeric TXT matrices" if raw else "Folder containing PNG/TIFF images"
        )
        self.refresh_preflight()

    def _unit_factor(self) -> float:
        return 1.0 if self.unit_combo.currentText() == "µm" else 1000.0

    def _values_um(self) -> tuple[float, float, float]:
        factor = self._unit_factor()
        return (
            self.frame_width_spin.value() * factor,
            self.z_start_spin.value() * factor,
            self.z_step_spin.value() * factor,
        )

    def _unit_changed(self, unit: str) -> None:
        old_factor = 1.0 if self._last_unit == "µm" else 1000.0
        new_factor = 1.0 if unit == "µm" else 1000.0
        for spin in (self.frame_width_spin, self.z_start_spin, self.z_step_spin):
            value_um = spin.value() * old_factor
            spin.blockSignals(True)
            spin.setValue(value_um / new_factor)
            spin.blockSignals(False)
        self._last_unit = unit
        self.refresh_preflight()

    def choose_input_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose source series")
        if folder:
            self.input_edit.setText(folder)
            if not self.output_edit.text().strip():
                self.output_edit.setText(str(Path(folder).resolve().parent / "analysis_results"))
            self.refresh_preflight()

    def choose_output_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose results base folder")
        if folder:
            self.output_edit.setText(folder)
            self.refresh_preflight()

    def _base_config(self) -> SeriesConfig:
        frame_width_um, z_start_um, z_step_um = self._values_um()
        return SeriesConfig(
            input_dir=self.input_edit.text().strip(),
            output_dir=self.output_edit.text().strip(),
            frame_width_um=frame_width_um,
            z_start_um=z_start_um,
            z_step_um=z_step_um,
            source_type=self._source_type(),
            direction="increasing" if self.direction_combo.currentIndex() == 0 else "decreasing",
            export_preview_png=self.export_preview_checkbox.isChecked(),
            export_float_tiff=self.export_tiff_checkbox.isChecked(),
            layers=list(self._layers),
            order_confirmed=self.confirm_order_checkbox.isChecked(),
        )

    def refresh_preflight(self) -> None:
        self._invalidate_results()
        if not self.input_edit.text().strip():
            self._layers = []
            self._preflight_report = PreflightReport()
            self._populate_layer_table()
            self._populate_source_preview_choices()
            self.preflight_text.clear()
            return
        report = preflight_series(self._base_config())
        self._preflight_report = report
        self._layers = report.layers
        self._populate_layer_table()
        self._show_preflight_report(report)
        self._populate_source_preview_choices()

    def _invalidate_results(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._outcome = None
        self.progress_bar.setValue(0)
        self.current_file_label.setText("Current file: —")
        self.result_counts_label.setText("processed 0  •  OK 0  •  CHECK 0  •  errors 0")
        self.summary_table.setRowCount(0)
        self.qc_combo.clear()
        self.qc_metadata.setText("filename: — | layer_index: — | z: —")
        self.original_preview.set_message("No result available")
        self.qc_preview.set_message("No result available")
        self.open_full_size_button.setEnabled(False)
        self.plot_preview.clear()
        self.plot_preview.setText("No result available")
        self.plot_combo.clear()
        self.errors_table.setRowCount(0)
        self._update_navigation_state()

    def _populate_layer_table(self) -> None:
        self.layer_table.setRowCount(len(self._layers))
        unit = self.unit_combo.currentText()
        factor = self._unit_factor()
        for row_index, layer in enumerate(self._layers):
            shape = f"{layer.matrix_shape[0]} × {layer.matrix_shape[1]}" if layer.matrix_shape else "—"
            values = [
                layer.filename,
                str(layer.source_number) if layer.source_number is not None else "—",
                str(layer.layer_index),
                f"{layer.z_um / factor:.3f} {unit}",
                shape,
                f"{layer.source_min:.5g}" if layer.source_min is not None else "—",
                f"{layer.source_max:.5g}" if layer.source_max is not None else "—",
                layer.import_status.replace("_", " "),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 7:
                    item.setForeground(QColor("#16784b" if layer.import_status == "valid" else "#a63b2b"))
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self.layer_table.setItem(row_index, column, item)
        report = self._preflight_report
        self.found_label.setText(f"Found files: {report.found_files}")
        valid_label = "Valid matrices" if self._source_type() == SOURCE_RAW_TXT else "Valid images"
        self.valid_label.setText(f"{valid_label}: {report.valid_files}")
        self.invalid_label.setText(f"Invalid files: {report.invalid_files}")
        self.invalid_label.setStyleSheet("color: #a63b2b;" if report.invalid_files else "")
        shape = report.common_matrix_shape
        self.shape_label.setText(f"Common shape: {shape[0]} × {shape[1]}" if shape else "Common shape: —")
        self.first_label.setText(f"First: {self._layers[0].filename if self._layers else '—'}")
        self.last_label.setText(f"Last: {self._layers[-1].filename if self._layers else '—'}")
        gaps = ", ".join(str(value) for value in report.missing_numbers) or "none"
        self.gaps_label.setText(f"Detected gaps: {gaps}")
        extracted = sum(layer.source_number is not None for layer in self._layers)
        self.numbering_label.setText(f"Extracted numbering: {extracted}/{len(self._layers)}")

    def _show_preflight_report(self, report: PreflightReport) -> None:
        lines: list[str] = []
        lines.extend(f"ERROR — {message}" for message in report.errors)
        lines.extend(f"WARNING — {message}" for message in report.warnings)
        lines.extend(
            f"IMPORT ERROR — {error.filename}: {error.error_type}: {error.message}"
            for error in report.import_errors
        )
        if report.common_matrix_shape:
            rows, columns = report.common_matrix_shape
            lines.append(f"Common matrix shape — {rows} × {columns}")
        if report.is_valid:
            lines.append(f"READY — {report.valid_files} valid source layer(s) can be analyzed")
        self.preflight_text.setPlainText("\n".join(lines))
        self.confirm_order_checkbox.setEnabled(report.requires_order_confirmation)
        if not report.requires_order_confirmation:
            self.confirm_order_checkbox.setChecked(True)

    def _populate_source_preview_choices(self) -> None:
        self.source_preview_combo.blockSignals(True)
        self.source_preview_combo.clear()
        for layer in self._layers:
            if layer.import_status == "valid":
                self.source_preview_combo.addItem(layer.filename, layer.filename)
        self.source_preview_combo.blockSignals(False)
        self._source_layer_changed()

    def _table_selection_changed(self, row: int, _column: int, _old_row: int, _old_column: int) -> None:
        if 0 <= row < len(self._layers):
            index = self.source_preview_combo.findData(self._layers[row].filename)
            if index >= 0:
                self.source_preview_combo.setCurrentIndex(index)

    def save_config_dialog(self) -> None:
        if not self._layers:
            QMessageBox.warning(self, "No series", "Choose and validate a source series first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save series configuration", "series_config.json", "JSON (*.json)")
        if path:
            save_series_config(self._base_config(), path)

    def load_config_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load series configuration", "", "JSON (*.json)")
        if path:
            self.load_config_file(path)

    def load_config_file(self, path: str | Path) -> None:
        self._invalidate_results()
        config = load_series_config(path)
        self.source_type_combo.setCurrentIndex(0 if config.source_type == SOURCE_RAW_TXT else 1)
        self.input_edit.setText(config.input_dir)
        self.output_edit.setText(config.output_dir)
        self.unit_combo.setCurrentText("µm")
        self.frame_width_spin.setValue(config.frame_width_um)
        self.z_start_spin.setValue(config.z_start_um)
        self.z_step_spin.setValue(config.z_step_um)
        self.direction_combo.setCurrentIndex(0 if config.direction == "increasing" else 1)
        self.export_preview_checkbox.setChecked(config.export_preview_png)
        self.export_tiff_checkbox.setChecked(config.export_float_tiff)
        self.confirm_order_checkbox.setChecked(config.order_confirmed)
        self.refresh_preflight()

    def run_analysis(self) -> None:
        config = self._base_config()
        report = preflight_series(config)
        if report.errors:
            QMessageBox.critical(self, "Preflight failed", "\n".join(report.errors))
            return
        if report.requires_order_confirmation and not config.order_confirmed:
            QMessageBox.warning(
                self,
                "Order confirmation required",
                "Review filename → source_number → layer_index → z and explicitly confirm the order or gaps.",
            )
            return
        if not config.layers:
            QMessageBox.critical(self, "No layer table", "The explicit layer table is empty.")
            return

        self._outcome = None
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.current_file_label.setText("Current file: starting…")
        self.result_counts_label.setText("processed 0  •  OK 0  •  CHECK 0  •  errors 0")

        self._thread = QThread(self)
        self._worker = AnalysisWorker(config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self.processing_started.emit()
        self._thread.start()

    def cancel_analysis(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.current_file_label.setText("Cancellation requested; finishing current layer…")

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        self.progress_bar.setValue(int(round((current - 1) * 100 / max(total, 1))))
        self.current_file_label.setText(f"Current file: {filename} ({current}/{total})")

    def _on_finished(self, outcome: RunOutcome) -> None:
        self._outcome = outcome
        self.progress_bar.setValue(100 if not outcome.cancelled else self.progress_bar.value())
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.current_file_label.setText("Cancelled" if outcome.cancelled else "Completed")
        total_errors = len(outcome.errors) + len(outcome.import_errors)
        self.result_counts_label.setText(
            f"processed {outcome.processed}  •  OK {outcome.ok}  •  CHECK {outcome.check}  •  errors {total_errors}"
        )
        self._populate_results(outcome)
        self.processing_finished.emit(outcome)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("Analysis and export complete")
        dialog.setText(f"Processed {outcome.processed} layer(s); OK {outcome.ok}; CHECK {outcome.check}.")
        details = f"Results folder: {Path(outcome.run_dir).name}"
        if outcome.tiff_stack_path:
            details += "\n\nFloat32 TIFF export succeeded. Axes: ZYX. No contrast or 8-bit quantization applied."
        dialog.setInformativeText(details)
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.setModal(False)
        dialog.setStyleSheet(
            "QMessageBox { background: #f7f9fc; } "
            "QMessageBox QLabel { color: #172b4d; min-width: 560px; padding: 4px; } "
            "QMessageBox QPushButton { color: #172b4d; background: #e8eef7; "
            "border: 1px solid #9fb0c4; border-radius: 4px; padding: 6px 18px; }"
        )
        self._completion_dialog = dialog
        dialog.show()

    def _on_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.current_file_label.setText("Run failed")
        QMessageBox.critical(self, "Analysis failed", message)

    def _on_thread_finished(self) -> None:
        self._worker = None
        self._thread = None

    def _populate_results(self, outcome: RunOutcome) -> None:
        self.summary_table.setRowCount(len(outcome.summaries))
        for row_index, row in enumerate(sorted(outcome.summaries, key=lambda item: int(item["layer_index"]))):
            for column, (key, _label) in enumerate(SUMMARY_COLUMNS):
                value = row.get(key, "")
                text = "NaN" if isinstance(value, float) and math.isnan(value) else f"{value:.3f}" if isinstance(value, float) else str(value)
                item = QTableWidgetItem(text)
                if key == "status":
                    item.setForeground(QColor("#16784b" if value == "OK" else "#a63b2b"))
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self.summary_table.setItem(row_index, column, item)

        self.qc_combo.blockSignals(True)
        self.qc_combo.clear()
        for row in sorted(outcome.summaries, key=lambda item: int(item["layer_index"])):
            self.qc_combo.addItem(f"{row['filename']} — z={row['z_um']:.3f} µm", row["filename"])
        self.qc_combo.blockSignals(False)
        self._qc_layer_changed()

        self.plot_combo.blockSignals(True)
        self.plot_combo.clear()
        for path in outcome.plot_paths:
            labels = {
                "depth_summary": "Depth summary",
                "dark_interval_distribution_by_depth": "Dark-interval distribution by depth",
            }
            self.plot_combo.addItem(labels.get(Path(path).stem, Path(path).name), path)
        self.plot_combo.blockSignals(False)
        self._update_plot_preview()

        error_rows = [("import", error) for error in outcome.import_errors] + [("analysis/export", error) for error in outcome.errors]
        self.errors_table.setRowCount(len(error_rows))
        for row_index, (stage, error) in enumerate(error_rows):
            for column, value in enumerate((stage, error.filename, error.error_type, error.message)):
                self.errors_table.setItem(row_index, column, QTableWidgetItem(value))

    def _set_pixmap(self, target: QLabel | ImageViewer, pixmap: QPixmap, max_size: tuple[int, int]) -> None:
        if isinstance(target, ImageViewer):
            target.set_pixmap(pixmap)
        else:
            target.setPixmap(pixmap.scaled(*max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _set_array_preview(self, target: QLabel | ImageViewer, array, max_size: tuple[int, int]) -> None:
        preview = preview_to_uint8(array)
        height, width = preview.shape
        image = QImage(preview.data, width, height, preview.strides[0], QImage.Format_Grayscale8).copy()
        self._set_pixmap(target, QPixmap.fromImage(image), max_size)

    def _set_file_preview(
        self, target: QLabel | ImageViewer, path: str | Path | None, max_size: tuple[int, int]
    ) -> None:
        if not path or not Path(path).is_file():
            if isinstance(target, ImageViewer):
                target.set_message("Image unavailable")
            else:
                target.setText("Image unavailable")
                target.setPixmap(QPixmap())
            return
        self._set_pixmap(target, QPixmap(str(path)), max_size)

    def _current_layer(self, combo: QComboBox) -> LayerMetadata | None:
        filename = combo.currentData()
        return next((layer for layer in self._layers if layer.filename == filename), None)

    def _update_source_preview(self) -> None:
        layer = self._current_layer(self.source_preview_combo)
        if layer is None:
            self.source_preview.set_message("Choose and validate a source folder.")
            self.source_preview_metadata.setText("filename: — | layer_index: — | z: — | status: —")
            self._update_navigation_state()
            return
        try:
            array = read_source_array(layer, self._source_type())
            self._set_array_preview(self.source_preview, array, (1050, 650))
            status = "—"
            if self._outcome:
                summary = next(
                    (item for item in self._outcome.summaries if item["filename"] == layer.filename), None
                )
                if summary:
                    status = str(summary["status"])
            self.source_preview_metadata.setText(
                f"filename: {layer.filename}  |  layer_index: {layer.layer_index}  |  "
                f"z: {layer.z_um:.3f} µm  |  status: {status}  |  shape: {array.shape[0]} × {array.shape[1]}"
            )
            self._style_status_label(self.source_preview_metadata, status)
        except Exception as exc:
            self.source_preview.set_message(f"Preview unavailable: {type(exc).__name__}")
        self._update_navigation_state()

    def _update_qc_preview(self) -> None:
        if not self._outcome:
            self.open_full_size_button.setEnabled(False)
            self._update_navigation_state()
            return
        layer = self._current_layer(self.qc_combo)
        if layer is None:
            self.original_preview.set_message("No source preview for the selected layer")
            self.qc_preview.set_message("No QC result for the selected layer")
            self.open_full_size_button.setEnabled(False)
            self._update_navigation_state()
            return
        row = next((item for item in self._outcome.summaries if item["filename"] == layer.filename), None)
        if row is None:
            return
        self.qc_metadata.setText(
            f"filename: {layer.filename}  |  layer_index: {row['layer_index']}  |  z: {row['z_um']:.3f} µm  |  status: {row['status']}"
        )
        self._style_status_label(self.qc_metadata, str(row["status"]))
        if self._source_type() == SOURCE_RAW_TXT:
            self.original_panel.setTitle("Display preview — raw float64 source, normalized only for display")
            self._set_array_preview(self.original_preview, read_source_array(layer, self._source_type()), (560, 530))
        else:
            self.original_panel.setTitle("Legacy input image")
            self._set_file_preview(self.original_preview, layer.source_path, (560, 530))
        qc_path = self._outcome.qc_paths.get(layer.filename)
        self._set_file_preview(self.qc_preview, qc_path, (690, 530))
        self.open_full_size_button.setEnabled(bool(qc_path and Path(qc_path).is_file()))
        self._update_navigation_state()

    def open_full_size_qc(self) -> None:
        if not self._outcome:
            return
        layer = self._current_layer(self.qc_combo)
        path = self._outcome.qc_paths.get(layer.filename) if layer else None
        if not path or not Path(path).is_file():
            return
        dialog = FullSizeImageDialog(path, f"Full-size QC — {layer.filename}", self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda: setattr(self, "_full_size_qc_window", None))
        self._full_size_qc_window = dialog
        dialog.show()

    @staticmethod
    def _style_status_label(label: QLabel, status: str) -> None:
        if status == "OK":
            label.setStyleSheet("color: #166534; background: #dcfce7; border-radius: 4px; padding: 4px;")
        elif status == "CHECK":
            label.setStyleSheet("color: #991b1b; background: #fee2e2; border-radius: 4px; padding: 4px; font-weight: 600;")
        else:
            label.setStyleSheet("")

    def _update_plot_preview(self) -> None:
        if self.plot_combo.currentIndex() >= 0:
            self._set_file_preview(self.plot_preview, self.plot_combo.currentData(), (1120, 680))


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    smoke_test = "--smoke-test" in arguments
    qt_arguments = [sys.argv[0], *(argument for argument in arguments if argument != "--smoke-test")]
    app = QApplication.instance() or QApplication(qt_arguments)
    app.setApplicationName("Bright-band series analyzer")
    install_application_language(app, load_application_language())
    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(250, app.quit)
    exit_code = app.exec()
    if smoke_test:
        window.close()
        app.processEvents()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
