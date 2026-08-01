from __future__ import annotations

import csv
import json
from pathlib import Path

import tifffile

from demo.generate_synthetic_series import generate_synthetic_series
from shg_domain_analyzer.export import execute_series
from shg_domain_analyzer.image_io import preflight_series, sha256_file
from shg_domain_analyzer.models import SOURCE_RAW_TXT, SeriesConfig


def test_full_raw_txt_pipeline_and_sources_unchanged(tmp_path: Path) -> None:
    series_dir = tmp_path / "synthetic"
    truth = generate_synthetic_series(
        series_dir,
        frame_count=8,
        image_size_px=128,
        frame_width_um=128.0,
        include_invalid_examples=True,
        include_legacy_images=False,
    )
    input_dir = series_dir / "txt"
    config = SeriesConfig(
        input_dir=str(input_dir),
        output_dir=str(tmp_path / "outputs"),
        frame_width_um=float(truth["frame_width_um"]),
        z_start_um=0.0,
        z_step_um=12.5,
        source_type=SOURCE_RAW_TXT,
        direction="increasing",
        export_preview_png=True,
        export_float_tiff=True,
        order_confirmed=True,
    )
    report = preflight_series(config)
    assert report.is_valid
    assert report.valid_files == 8
    assert report.invalid_files == 2
    assert {error.error_type for error in report.import_errors} == {"non_numeric", "invalid_shape"}
    config.layers = report.layers

    hashes_before = {path.name: sha256_file(path) for path in input_dir.glob("*.txt")}
    outcome = execute_series(config)
    hashes_after = {path.name: sha256_file(path) for path in input_dir.glob("*.txt")}

    assert outcome.processed == 8
    assert len(outcome.import_errors) == 2
    assert not outcome.errors
    assert hashes_before == hashes_after

    run_dir = Path(outcome.run_dir)
    expected = {
        "summary.csv", "walls.csv", "domains.csv", "errors.csv", "imported_layers.csv",
        "import_errors.csv", "run_manifest.json", "series_config.json", "source_stack_float32.tif",
    }
    assert expected.issubset({path.name for path in run_dir.iterdir()})
    assert len(list((run_dir / "previews").glob("*.png"))) == 8
    assert len(list((run_dir / "qc").glob("*.png"))) == 8

    stack = tifffile.imread(run_dir / "source_stack_float32.tif")
    assert stack.shape == (8, 128, 128)
    assert stack.dtype.name == "float32"

    with (run_dir / "imported_layers.csv").open(encoding="utf-8-sig", newline="") as stream:
        imported = list(csv.DictReader(stream))
    assert len(imported) == 10
    assert sum(row["import_status"] == "valid" for row in imported) == 8

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_type"] == SOURCE_RAW_TXT
    assert manifest["dtype_used_for_analysis"]["source_array"] == "float64"
    assert manifest["dtype_used_for_analysis"]["uint8_or_png_intermediate"] is False
    assert manifest["float_tiff"]["axes"] == "ZYX"
    assert manifest["all_inputs_unchanged"] is True
    assert str(tmp_path.resolve()) not in (run_dir / "run_manifest.json").read_text(encoding="utf-8")
