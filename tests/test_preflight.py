from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from shg_domain_analyzer.image_io import preflight_series
from shg_domain_analyzer.models import SOURCE_LEGACY_IMAGES, SeriesConfig


def _write_image(path: Path, shape: tuple[int, int]) -> None:
    Image.fromarray(np.zeros(shape, dtype=np.uint8)).save(path)


def test_preflight_detects_missing_frame_number(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for number in (1, 2, 4):
        _write_image(input_dir / f"layer_{number:03d}.png", (32, 32))
    config = SeriesConfig(
        str(input_dir), str(tmp_path / "output"), 32.0, 0.0, 5.0,
        source_type=SOURCE_LEGACY_IMAGES,
    )
    report = preflight_series(config)
    assert report.is_valid
    assert report.missing_numbers == [3]
    assert report.requires_order_confirmation
    assert [layer.layer_index for layer in report.layers] == [0, 1, 3]


def test_preflight_rejects_mixed_image_sizes(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_image(input_dir / "layer_001.png", (32, 32))
    _write_image(input_dir / "layer_002.png", (31, 32))
    config = SeriesConfig(
        str(input_dir), str(tmp_path / "output"), 32.0, 0.0, 5.0,
        source_type=SOURCE_LEGACY_IMAGES,
    )
    report = preflight_series(config)
    assert not report.is_valid
    assert any("same size" in error.lower() for error in report.errors)


def test_preflight_rejects_output_inside_input(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_image(input_dir / "layer_001.png", (32, 32))
    config = SeriesConfig(
        str(input_dir), str(input_dir / "results"), 32.0, 0.0, 5.0,
        source_type=SOURCE_LEGACY_IMAGES,
    )
    report = preflight_series(config)
    assert not report.is_valid
    assert any("inside the input" in error.lower() for error in report.errors)
