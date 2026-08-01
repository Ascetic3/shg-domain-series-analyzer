from __future__ import annotations

from pathlib import Path

import pytest

from shg_domain_analyzer.config import (
    build_layer_table,
    load_series_config,
    natural_key,
    save_series_config,
)
from shg_domain_analyzer.models import LayerMetadata, SeriesConfig
from shg_domain_analyzer.models import SOURCE_LEGACY_IMAGES


def test_z_increasing_and_decreasing() -> None:
    increasing = SeriesConfig("input", "output", 100.0, 5.0, 2.5, direction="increasing")
    decreasing = SeriesConfig("input", "output", 100.0, 5.0, 2.5, direction="decreasing")
    assert increasing.z_for_index(3) == pytest.approx(12.5)
    assert decreasing.z_for_index(3) == pytest.approx(-2.5)


def test_natural_sort() -> None:
    names = ["frame_10.png", "frame_2.png", "frame_1.png"]
    assert sorted(names, key=natural_key) == ["frame_1.png", "frame_2.png", "frame_10.png"]


def test_gap_detection_preserves_layer_index_and_z() -> None:
    files = [Path("frame_1.png"), Path("frame_2.png"), Path("frame_4.png")]
    layers, missing, needs_confirmation, warnings = build_layer_table(files, 0.0, 10.0, "increasing")
    assert missing == [3]
    assert needs_confirmation
    assert warnings
    assert [layer.layer_index for layer in layers] == [0, 1, 3]
    assert [layer.z_um for layer in layers] == [0.0, 10.0, 30.0]


@pytest.mark.parametrize("step", [0.0, -1.0])
def test_non_positive_step_is_rejected(tmp_path: Path, step: float) -> None:
    config = SeriesConfig(str(tmp_path / "input"), str(tmp_path / "output"), 100.0, 0.0, step)
    assert any("spacing" in error.lower() for error in config.validate_basic())


def test_non_positive_frame_width_is_rejected(tmp_path: Path) -> None:
    config = SeriesConfig(str(tmp_path / "input"), str(tmp_path / "output"), 0.0, 0.0, 1.0)
    assert any("frame width" in error.lower() for error in config.validate_basic())


def test_input_output_equality_is_rejected(tmp_path: Path) -> None:
    same = tmp_path / "series"
    config = SeriesConfig(str(same), str(same), 100.0, 0.0, 1.0)
    assert any("must not be the same" in error.lower() for error in config.validate_basic())


def test_saved_config_uses_portable_paths_and_round_trips(tmp_path: Path) -> None:
    input_dir = tmp_path / "series" / "images"
    output_dir = tmp_path / "runs"
    input_dir.mkdir(parents=True)
    source = input_dir / "frame_1.png"
    source.touch()
    config = SeriesConfig(
        str(input_dir.resolve()),
        str(output_dir.resolve()),
        100.0,
        0.0,
        1.0,
        layers=[LayerMetadata("frame_1.png", str(source.resolve()), 0, 0.0, source_number=1)],
    )
    config_path = tmp_path / "config" / "series_config.json"

    save_series_config(config, config_path)
    serialized = config_path.read_text(encoding="utf-8")
    restored = load_series_config(config_path)

    assert str(tmp_path.resolve()) not in serialized
    assert restored.input_dir == str(input_dir.resolve())
    assert restored.output_dir == str(output_dir.resolve())
    assert restored.layers[0].source_path == str(source.resolve())


def test_old_image_config_infers_legacy_mode() -> None:
    old_style = {
        "input_dir": "images",
        "output_dir": "outputs",
        "frame_width_um": 100.0,
        "z_start_um": 0.0,
        "z_step_um": 1.0,
        "layers": [
            {"filename": "layer_001.png", "source_path": "images/layer_001.png", "layer_index": 0, "z_um": 0.0}
        ],
    }
    assert SeriesConfig.from_dict(old_style).source_type == SOURCE_LEGACY_IMAGES
