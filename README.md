# Periodic bright-band series analyzer

This directory is a standalone, synthetic-data-only portfolio MVP. Its primary
input is a folder of numeric TXT matrices. A legacy PNG/TIFF mode remains for
already converted images. Both modes feed the same `analyze_array()` detector.

> **Scientific warning:** The physical interpretation and scientific accuracy
> of the detector must be validated against expert annotation or an independent
> method.

The application uses neutral terminology: detected bright bands, dark
intervals between detected bands, candidate wall width, and candidate domain
width. B1, B2, ... are left-to-right interval order inside one frame; they are
not identities of physical objects between frames.

No real matrices, images, measurements, sample identifiers, experimental
conditions, or legacy results are included in `portfolio_app`.

## Source modes

### Raw TXT matrices (default)

Raw TXT mode analyzes the original floating-point matrices. Each complete file
is decoded and every token is parsed to a rectangular NumPy `float64` array.
That array is passed directly to `analyze_array()`. It is never converted to
PNG or `uint8` before analysis. The preserved v6 `normalize_for_analysis()`
function creates its existing float32 working copy internally.

The inspected legacy data format is:

- ASCII-compatible UTF-8 text without BOM;
- CRLF row endings;
- one space between columns;
- decimal point;
- no header or blank rows;
- no leading or trailing whitespace;
- numeric basenames, with both zero-padded and non-padded forms;
- typical matrices are 300 × 300;
- isolated 3 × 3 matrices occur and are treated as `invalid_shape`, without
  resizing.

Because the inspected files contain only ASCII numeric syntax, a more specific
national text encoding cannot be inferred from their bytes.

### PNG/TIFF images

Legacy image mode analyzes already converted image files. Pillow loads the
image through the existing grayscale `float32` path. This mode exists for
compatibility and is not the primary workflow.

ImageJ/Fiji is not required by either mode.

## Architecture

```text
portfolio_app/
├── src/shg_domain_analyzer/
│   ├── models.py           configuration and result dataclasses
│   ├── config.py           portable JSON and filename → layer → z mapping
│   ├── image_io.py         strict TXT import, image import, preflight, hashing
│   ├── processing.py       detector formulas modularized from v6
│   ├── measurements.py     shared analyze_array() measurement core
│   ├── visualization.py    display preview, QC, and depth plots
│   ├── export.py           CSV, manifest, preview PNG, and float TIFF stack
│   └── gui/
│       ├── main_window.py  PySide6 source/import/result workflow
│       └── worker.py       background execution and cancellation
├── demo/
│   ├── generate_synthetic_series.py
│   ├── run_demo.py
│   └── capture_gui_screenshots.py
├── tests/
├── screenshots/
├── pyproject.toml
└── run_gui.py
```

## Shared analysis pipeline

```text
TXT file ── read_txt_matrix() ── float64 array ─┐
                                                ├─ analyze_array()
PNG/TIFF ── read_gray() ───────── float32 array ┘
```

`analyze_array()` applies the unchanged detector stages:

1. `normalize_for_analysis()`;
2. `find_best_rotation()`;
3. `crop_center()` and `rotate_and_build_profile()`;
4. `robust_profile_normalize()`;
5. `detect_bright_walls()`;
6. `build_black_domains()`;
7. neutral measurements and `save_qc_plot()`.

The formulas and default thresholds from v6 were not intentionally changed.
Software-level additions include source validation, explicit metadata, portable
configuration, error isolation, exports, and the worker-thread GUI.

## Raw data, display preview, and QC

Three representations are deliberately separate:

1. **Raw data** — the source `float64` TXT matrix used by `analyze_array()`.
2. **Display preview** — a new `uint8` copy made by linear 1st/99th percentile
   scaling and clipping. It is used only for GUI display or optional PNG export.
3. **QC visualization** — the rotated analysis crop, normalized profile,
   detected candidates, and annotations produced after analysis.

Preview generation does not mutate the raw array and preview PNG files are
never read back into the Raw TXT analysis pipeline.

The Source preview and QC preview tabs provide synchronized layer navigation
with Previous/Next, Left/Right, Home/End, and a current-layer indicator. Their
viewers preserve aspect ratio and support bounded 10–800% zoom, mouse-wheel
zooming, panning while enlarged, Fit to window, 100%, and double-click Fit.
The full QC PNG can also be opened in a separate scalable window. These display
operations do not resave or modify source images.

## Exploratory depth analysis

Depth analysis is an **exploratory feature**, not a validated reconstruction of
the evolution of individual physical domains. It summarizes independent
detections at each configured layer position and requires scientific
validation.

The depth summary shows mean candidate bright-band width, mean candidate dark-
interval width, mean period, detection counts, and OK/CHECK status. CHECK
layers use separate markers and break connecting lines. The distribution plot
shows every candidate dark-interval width at each z together with its median,
interquartile range, and observation count. Intervals from different layers
are never joined into B1(z), B2(z), or B3(z) series.

## Layer coordinates and preflight

Natural sorting gives `1, 2, 10`. When numbers are available, the last numeric
group in each basename is extracted and:

```text
layer_index = source_number - minimum_source_number
```

For increasing z, `z_i = z0 + layer_index × step`; for decreasing z,
`z_i = z0 - layer_index × step`. Internal coordinates are micrometres.
Therefore a missing source number reserves its coordinate rather than silently
shifting later layers. Missing or unextractable numbering requires explicit GUI
confirmation, and the confirmed table is stored in `series_config.json`.

TXT validation rejects empty files, nonnumeric or ragged content, matrices
smaller than 2 × 2, NaN/infinity, and shapes that differ from the series mode.
Invalid files are displayed in the GUI, excluded from analysis, and recorded in
`import_errors.csv`. A small outlier is never resized to the common shape.

## Optional conversion exports

The two options are disabled by default:

- **Preview PNG:** 8-bit grayscale, linear 1st/99th percentile normalization,
  display only.
- **Float TIFF stack:** valid layers in explicit layer order, `float32`, axes
  `ZYX`, no contrast enhancement and no 8-bit quantization.

`imported_layers.csv` preserves filename, source number, layer index, z, shape,
source minimum/maximum, SHA-256, and import status.

## Legacy ImageJ workflow

The old workflow converted TXT data into contrast-enhanced 8-bit PNG/TIFF using
ImageJ Enhance Contrast. Raw TXT mode instead analyzes the original
floating-point matrices. Results from the two workflows may differ, and their
equivalence has not been verified.

The preview PNG implementation is not claimed to be bitwise or scientifically
equivalent to ImageJ. This project does not approximate ImageJ Enhance Contrast
in the primary analysis mode. A separate experimental compatibility converter
could be evaluated later, but it is outside this version.

## Installation and GUI

- Python 3.10 or newer
- NumPy, Pillow, SciPy, Matplotlib, PySide6, tifffile
- pytest for tests

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python run_gui.py
```

Dependencies are installed into the environment once. Application startup does
not run pip.

## Results

Every run creates a new `run_timestamp_uuid` directory containing:

```text
summary.csv
walls.csv
domains.csv
errors.csv
imported_layers.csv
import_errors.csv
series_config.json
run_manifest.json
qc/*.png
plots/*.png
previews/*.png                 optional
source_stack_float32.tif       optional
```

The manifest records source type, detected TXT format, source and working
dtypes, common matrix shape, preview settings, TIFF dtype/axes, dependency
versions, processing parameters, portable source paths, and before/after source
hashes.

## Synthetic demos and tests

The generator creates ten deterministic float TXT layers with periodic bright
features, depth-dependent parameters, noise, fixed seed, and
`ground_truth.json`. It also creates a nonnumeric file, a 3 × 3 wrong-shape
file, a gap variant, and optional synthetic PNG files for legacy tests. None are
derived from experimental data.

```powershell
python demo/run_demo.py --mode raw
python demo/run_demo.py --mode legacy
python -m pytest
```

Synthetic comparisons test software regression, not physical accuracy.

## Current limitations

- Bright-band identity and physical meaning are not validated.
- `OK` is an internal structural check, not an accuracy guarantee.
- B indices identify left-to-right order only within one frame.
- Exploratory depth plots are not a confirmed reconstruction of individual
  domain evolution.
- There is no inter-layer registration, uncertainty propagation, confidence
  interval, or expert-agreement metric.
- Mean transverse profiles can lose curved, branching, or heterogeneous detail.
- Fixed preprocessing and detection thresholds can bias results.
- TXT import currently targets the inspected headerless, dot-decimal,
  whitespace-delimited format; locale decimal commas and headers are rejected.
- Cancellation occurs between layers, not inside rotation search for one layer.
- A filename's last numeric group may be ambiguous and must be reviewed.
- Saved paths can only remain relative across locations on the same drive.
- No license is included at this stage.
