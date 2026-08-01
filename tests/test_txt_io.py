from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from demo.generate_synthetic_series import generate_synthetic_series
from shg_domain_analyzer.config import build_layer_table
from shg_domain_analyzer.export import save_float32_tiff_stack
from shg_domain_analyzer.image_io import (
    MatrixImportError,
    discover_txt_matrices,
    inspect_txt_series,
    read_txt_matrix,
)
from shg_domain_analyzer.measurements import analyze_array
from shg_domain_analyzer.models import LayerMetadata, ProcessingParameters
from shg_domain_analyzer.visualization import preview_to_uint8


def _write_matrix(path: Path, matrix: np.ndarray) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        np.savetxt(stream, matrix, fmt="%.9f", delimiter=" ", newline="\r\n")


def test_read_txt_matrix_returns_float64(tmp_path: Path) -> None:
    expected = np.arange(12, dtype=np.float64).reshape(3, 4) / 7.0
    path = tmp_path / "layer_001.txt"
    _write_matrix(path, expected)
    actual = read_txt_matrix(path)
    assert actual.dtype == np.float64
    np.testing.assert_allclose(actual, expected)


def test_empty_txt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with pytest.raises(MatrixImportError, match="empty"):
        read_txt_matrix(path)


def test_nonnumeric_txt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_text("1 2\n3 invalid\n", encoding="utf-8")
    with pytest.raises(MatrixImportError) as error:
        read_txt_matrix(path)
    assert error.value.error_type == "non_numeric"


def test_ragged_txt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ragged.txt"
    path.write_text("1 2 3\n4 5\n", encoding="utf-8")
    with pytest.raises(MatrixImportError) as error:
        read_txt_matrix(path)
    assert error.value.error_type == "ragged_rows"


@pytest.mark.parametrize("token", ["NaN", "inf", "-inf"])
def test_nonfinite_txt_is_rejected(tmp_path: Path, token: str) -> None:
    path = tmp_path / "nonfinite.txt"
    path.write_text(f"1 2\n3 {token}\n", encoding="utf-8")
    with pytest.raises(MatrixImportError) as error:
        read_txt_matrix(path)
    assert error.value.error_type == "non_finite"


def test_wrong_and_mismatched_shapes_are_invalid(tmp_path: Path) -> None:
    paths: list[Path] = []
    for index in range(3):
        path = tmp_path / f"layer_{index + 1:03d}.txt"
        _write_matrix(path, np.ones((20, 20), dtype=float) * index)
        paths.append(path)
    wrong = tmp_path / "layer_004.txt"
    _write_matrix(wrong, np.ones((3, 3), dtype=float))
    paths.append(wrong)
    mismatch = tmp_path / "layer_005.txt"
    _write_matrix(mismatch, np.ones((19, 20), dtype=float))
    paths.append(mismatch)

    inspection = inspect_txt_series(paths)
    assert inspection.common_shape == (20, 20)
    assert inspection.details[wrong]["status"] == "invalid_shape"
    assert inspection.details[mismatch]["status"] == "invalid_shape"


def test_txt_natural_sort_and_gap_preserve_z(tmp_path: Path) -> None:
    for name in ("layer_10.txt", "layer_2.txt", "layer_1.txt", "layer_4.txt"):
        _write_matrix(tmp_path / name, np.ones((4, 4), dtype=float))
    files = discover_txt_matrices(tmp_path, ["*.txt"])
    assert [path.name for path in files] == ["layer_1.txt", "layer_2.txt", "layer_4.txt", "layer_10.txt"]
    layers, missing, needs_confirmation, _warnings = build_layer_table(files, 0.0, 5.0, "increasing")
    assert needs_confirmation
    assert 3 in missing
    assert [layer.layer_index for layer in layers] == [0, 1, 3, 9]
    assert [layer.z_um for layer in layers] == [0.0, 5.0, 15.0, 45.0]


def test_analyze_array_receives_float64_without_uint8_conversion(tmp_path: Path, monkeypatch) -> None:
    truth = generate_synthetic_series(
        tmp_path / "series", frame_count=1, image_size_px=96, frame_width_um=96.0,
        include_invalid_examples=False, include_legacy_images=False,
    )
    source = tmp_path / "series" / "txt" / truth["frames"][0]["filename"]
    matrix = read_txt_matrix(source)
    original = matrix.copy()
    observed: list[np.dtype] = []

    import shg_domain_analyzer.measurements as measurements

    real_normalize = measurements.normalize_for_analysis

    def spy(array: np.ndarray) -> np.ndarray:
        observed.append(array.dtype)
        return real_normalize(array)

    monkeypatch.setattr(measurements, "normalize_for_analysis", spy)
    layer = LayerMetadata(source.name, str(source), 0, 0.0, source_number=1, matrix_shape=matrix.shape, import_status="valid")
    result = analyze_array(matrix, layer, 96.0, ProcessingParameters())
    assert result.summary["source_array_dtype"] == "float64"
    assert observed == [np.dtype("float64")]
    np.testing.assert_array_equal(matrix, original)


def test_display_preview_does_not_modify_raw_array() -> None:
    raw = np.linspace(-4.0, 9.0, 100, dtype=np.float64).reshape(10, 10)
    before = raw.copy()
    preview = preview_to_uint8(raw)
    assert preview.dtype == np.uint8
    np.testing.assert_array_equal(raw, before)


def test_float_tiff_stack_is_float32_zyx(tmp_path: Path) -> None:
    matrices = [np.full((4, 5), value, dtype=np.float64) for value in (0.25, 1.5, -2.0)]
    path = save_float32_tiff_stack(tmp_path / "stack.tif", matrices)
    loaded = tifffile.imread(path)
    assert loaded.shape == (3, 4, 5)
    assert loaded.dtype == np.float32
    with tifffile.TiffFile(path) as tif:
        assert tif.series[0].axes == "ZYX"
    np.testing.assert_allclose(loaded, np.stack(matrices).astype(np.float32))
