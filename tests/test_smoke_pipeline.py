from __future__ import annotations

import csv
import json
from pathlib import Path

from demo.generate_synthetic_series import generate_synthetic_series
from shg_domain_analyzer.export import execute_series
from shg_domain_analyzer.image_io import preflight_series, sha256_file
from shg_domain_analyzer.models import SOURCE_LEGACY_IMAGES, SeriesConfig


def test_full_pipeline_smoke_and_sources_unchanged(tmp_path: Path) -> None:
    series_dir = tmp_path / "synthetic"
    truth = generate_synthetic_series(series_dir, frame_count=8, image_size_px=128, frame_width_um=128.0)
    input_dir = series_dir / "legacy_images"
    config = SeriesConfig(
        input_dir=str(input_dir),
        output_dir=str(tmp_path / "outputs"),
        frame_width_um=float(truth["frame_width_um"]),
        z_start_um=0.0,
        z_step_um=12.5,
        source_type=SOURCE_LEGACY_IMAGES,
        direction="increasing",
        order_confirmed=True,
    )
    report = preflight_series(config)
    assert report.is_valid
    config.layers = report.layers

    hashes_before = {path.name: sha256_file(path) for path in input_dir.glob("*.png")}
    outcome = execute_series(config)
    hashes_after = {path.name: sha256_file(path) for path in input_dir.glob("*.png")}

    assert outcome.processed == 8
    assert not outcome.cancelled
    assert not outcome.errors
    assert hashes_before == hashes_after

    run_dir = Path(outcome.run_dir)
    expected = {
        "summary.csv", "walls.csv", "domains.csv", "errors.csv",
        "run_manifest.json", "series_config.json",
    }
    assert expected.issubset({path.name for path in run_dir.iterdir()})
    assert len(list((run_dir / "qc").glob("*.png"))) == 8
    assert list((run_dir / "plots").glob("*.png"))

    with (run_dir / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8
    assert "candidate_band_mean_um" in rows[0]
    truth_by_filename = {frame["legacy_filename"]: frame for frame in truth["frames"]}
    for row in rows:
        expected_period = truth_by_filename[row["filename"]]["generated_period_um"]
        detected_period = float(row["period_band_centers_um"])
        assert abs(detected_period - expected_period) < 2.5

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["all_inputs_unchanged"] is True
    assert manifest["counts"]["processed"] == 8
    assert "scientific_warning" in manifest
    assert str(tmp_path.resolve()) not in (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in (run_dir / "series_config.json").read_text(encoding="utf-8")
