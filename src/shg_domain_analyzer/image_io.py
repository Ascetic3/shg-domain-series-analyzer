from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from .config import build_layer_table, natural_key
from .models import (
    FrameError,
    LayerMetadata,
    PreflightReport,
    SOURCE_LEGACY_IMAGES,
    SOURCE_RAW_TXT,
    SeriesConfig,
)


class MatrixImportError(ValueError):
    """Structured TXT import failure safe to expose without matrix contents."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class TxtSeriesInspection:
    details: dict[Path, dict[str, Any]]
    common_shape: tuple[int, int] | None
    errors: list[FrameError]
    format_description: dict[str, Any]


def read_gray(path: Path) -> np.ndarray:
    """Read a legacy PNG/TIFF as float32 grayscale; formula preserved from v6."""

    with Image.open(path) as image:
        gray = image.convert("L")
        return np.asarray(gray, dtype=np.float32)


def _decode_txt(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise MatrixImportError("empty_file", "TXT file is empty.")
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig"), "UTF-8 with BOM"
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MatrixImportError("encoding_error", "TXT file is not valid UTF-8 text.") from exc
    encoding = "ASCII-compatible UTF-8 without BOM" if raw.isascii() else "UTF-8 without BOM"
    return text, encoding


def validate_matrix(
    matrix: np.ndarray,
    expected_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    """Validate a complete numeric matrix without changing its values or dtype."""

    if not isinstance(matrix, np.ndarray) or matrix.ndim != 2:
        raise MatrixImportError("invalid_dimensions", "Data must form a two-dimensional matrix.")
    rows, columns = matrix.shape
    if rows < 2 or columns < 2:
        raise MatrixImportError("invalid_shape", "Matrix must contain at least two rows and two columns.")
    if not np.isfinite(matrix).all():
        raise MatrixImportError("non_finite", "Matrix contains NaN or infinity.")
    if expected_shape is not None and matrix.shape != expected_shape:
        raise MatrixImportError(
            "invalid_shape",
            f"Matrix shape {matrix.shape[0]} x {matrix.shape[1]} differs from the common series shape "
            f"{expected_shape[0]} x {expected_shape[1]}.",
        )
    return matrix


def read_txt_matrix(path: str | Path) -> np.ndarray:
    """Read an entire headerless whitespace-delimited TXT matrix as float64."""

    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise MatrixImportError("read_error", "TXT file could not be read completely.") from exc
    text, _encoding = _decode_txt(raw)
    lines = text.splitlines()
    if not lines or not any(line.strip() for line in lines):
        raise MatrixImportError("empty_file", "TXT file contains no matrix values.")
    if any(not line.strip() for line in lines):
        raise MatrixImportError("blank_row", "TXT matrix contains an empty row.")

    rows = [line.split() for line in lines]
    widths = [len(row) for row in rows]
    if not widths or widths[0] == 0:
        raise MatrixImportError("empty_file", "TXT file contains no matrix values.")
    if len(set(widths)) != 1:
        raise MatrixImportError("ragged_rows", "TXT matrix rows do not contain the same number of columns.")

    matrix = np.empty((len(rows), widths[0]), dtype=np.float64)
    for row_index, row in enumerate(rows):
        for column_index, token in enumerate(row):
            try:
                matrix[row_index, column_index] = float(token)
            except ValueError as exc:
                raise MatrixImportError(
                    "non_numeric",
                    f"TXT matrix contains a nonnumeric token at row {row_index + 1}, "
                    f"column {column_index + 1}.",
                ) from exc
    return validate_matrix(matrix)


def _describe_txt_format(path: Path, shape: tuple[int, int]) -> dict[str, Any]:
    raw = path.read_bytes()
    text, encoding = _decode_txt(raw)
    line_ending = "CRLF" if b"\r\n" in raw else "LF" if b"\n" in raw else "CR"
    lines = text.splitlines()
    whitespace_runs = [match.group(0) for line in lines[: min(5, len(lines))] for match in re.finditer(r"\s+", line)]
    single_space = bool(whitespace_runs) and all(run == " " for run in whitespace_runs)
    return {
        "encoding": encoding,
        "column_separator": "single space" if single_space else "whitespace",
        "row_separator": line_ending,
        "decimal_separator": "dot",
        "header": "none; every parsed token is numeric",
        "extra_whitespace": "none detected" if all(line == line.strip() for line in lines) else "present",
        "parser": "complete-file UTF-8 decode; every whitespace-delimited token is parsed",
        "matrix_shape_rows_columns": list(shape),
    }


def inspect_txt_series(paths: Iterable[str | Path]) -> TxtSeriesInspection:
    """Inspect all TXT files, identify the common shape, and retain no matrix contents."""

    ordered = [Path(path) for path in paths]
    details: dict[Path, dict[str, Any]] = {}
    shape_counts: Counter[tuple[int, int]] = Counter()
    format_source: Path | None = None

    for path in ordered:
        try:
            matrix = read_txt_matrix(path)
            shape = tuple(int(value) for value in matrix.shape)
            shape_counts[shape] += 1
            details[path] = {
                "shape": shape,
                "minimum": float(np.min(matrix)),
                "maximum": float(np.max(matrix)),
                "status": "valid",
                "error_type": "",
                "message": "",
            }
            if format_source is None:
                format_source = path
        except MatrixImportError as exc:
            details[path] = {
                "shape": None,
                "minimum": None,
                "maximum": None,
                "status": "invalid_data",
                "error_type": exc.error_type,
                "message": str(exc),
            }

    common_shape = (
        max(shape_counts, key=lambda shape: (shape_counts[shape], shape[0] * shape[1]))
        if shape_counts
        else None
    )
    if common_shape is not None:
        for path, detail in details.items():
            if detail["status"] == "valid" and detail["shape"] != common_shape:
                rows, columns = detail["shape"]
                detail.update(
                    status="invalid_shape",
                    error_type="invalid_shape",
                    message=(
                        f"Matrix shape {rows} x {columns} differs from the common series shape "
                        f"{common_shape[0]} x {common_shape[1]}; no resizing was applied."
                    ),
                )

    errors = [
        FrameError(path.name, detail["error_type"], detail["message"])
        for path, detail in details.items()
        if detail["status"] != "valid"
    ]
    description = (
        _describe_txt_format(format_source, common_shape)
        if format_source is not None and common_shape is not None
        else {}
    )
    return TxtSeriesInspection(details, common_shape, errors, description)


def load_txt_series(layer_metadata: Iterable[LayerMetadata]) -> list[tuple[LayerMetadata, np.ndarray]]:
    """Load valid TXT layers as float64 arrays in explicit layer order."""

    loaded: list[tuple[LayerMetadata, np.ndarray]] = []
    for layer in sorted(layer_metadata, key=lambda item: (item.layer_index, item.filename.casefold())):
        if layer.import_status != "valid":
            continue
        matrix = read_txt_matrix(layer.path)
        validate_matrix(matrix, layer.matrix_shape)
        loaded.append((layer, matrix))
    return loaded


def discover_images(folder: str | Path, patterns: list[str]) -> list[Path]:
    root = Path(folder)
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.glob(pattern) if path.is_file())
    unique = sorted(set(files), key=natural_key)
    return [path for path in unique if "full_stack" not in path.name.lower()]


def discover_txt_matrices(folder: str | Path, patterns: list[str]) -> list[Path]:
    root = Path(folder)
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.glob(pattern) if path.is_file())
    return sorted(set(files), key=natural_key)


def discover_source_files(config: SeriesConfig) -> list[Path]:
    if config.source_type == SOURCE_RAW_TXT:
        return discover_txt_matrices(config.input_dir, config.txt_patterns)
    return discover_images(config.input_dir, config.image_patterns)


def read_source_array(layer: LayerMetadata, source_type: str) -> np.ndarray:
    if source_type == SOURCE_RAW_TXT:
        return read_txt_matrix(layer.path)
    if source_type == SOURCE_LEGACY_IMAGES:
        return read_gray(layer.path)
    raise ValueError(f"Unsupported source type: {source_type}")


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attach_layer_order(config: SeriesConfig, files: list[Path], report: PreflightReport) -> None:
    try:
        layers, missing, needs_confirmation, warnings = build_layer_table(
            files,
            z_start_um=config.z_start_um,
            z_step_um=config.z_step_um,
            direction=config.direction,
        )
        report.layers = layers
        report.missing_numbers = missing
        report.requires_order_confirmation = needs_confirmation
        report.warnings.extend(warnings)
    except ValueError as exc:
        report.errors.append(str(exc))


def preflight_series(config: SeriesConfig) -> PreflightReport:
    report = PreflightReport()
    report.errors.extend(config.validate_basic())

    input_dir = Path(config.input_dir).expanduser()
    if not input_dir.is_dir():
        report.errors.append("Input directory does not exist or is not a directory.")
        return report

    files = discover_source_files(config)
    report.found_files = len(files)
    if not files:
        label = "TXT matrices" if config.source_type == SOURCE_RAW_TXT else "PNG/TIFF images"
        report.errors.append(f"Input directory contains no supported {label}.")
        return report

    lowered = [path.name.casefold() for path in files]
    duplicate_names = sorted(name for name in set(lowered) if lowered.count(name) > 1)
    if duplicate_names:
        report.errors.append("Source filenames are not unique: " + ", ".join(duplicate_names))

    _attach_layer_order(config, files, report)
    layers_by_path = {layer.path.resolve(): layer for layer in report.layers}

    if config.source_type == SOURCE_RAW_TXT:
        inspection = inspect_txt_series(files)
        report.common_matrix_shape = inspection.common_shape
        report.txt_format_description = inspection.format_description
        report.import_errors = inspection.errors
        for path, detail in inspection.details.items():
            layer = layers_by_path.get(path.resolve())
            if layer is None:
                continue
            layer.matrix_shape = detail["shape"]
            layer.source_min = detail["minimum"]
            layer.source_max = detail["maximum"]
            layer.import_status = detail["status"]
            layer.import_error_type = detail["error_type"]
            layer.import_error_message = detail["message"]
        report.valid_files = sum(layer.import_status == "valid" for layer in report.layers)
        report.invalid_files = len(report.layers) - report.valid_files
        if report.invalid_files:
            report.warnings.append(
                f"{report.invalid_files} TXT file(s) are invalid and will be excluded from analysis; "
                "details will be exported to import_errors.csv."
            )
        if report.valid_files == 0:
            report.errors.append("No valid TXT matrices remain after import validation.")
    else:
        dimensions: dict[tuple[int, int], list[str]] = {}
        for layer in report.layers:
            try:
                width, height = image_dimensions(layer.path)
                array = read_gray(layer.path)
                layer.matrix_shape = (height, width)
                layer.source_min = float(np.min(array))
                layer.source_max = float(np.max(array))
                layer.import_status = "valid"
                dimensions.setdefault((width, height), []).append(layer.filename)
            except Exception as exc:
                layer.import_status = "invalid_data"
                layer.import_error_type = type(exc).__name__
                layer.import_error_message = str(exc)
                report.import_errors.append(FrameError(layer.filename, type(exc).__name__, str(exc)))
        if len(dimensions) > 1:
            details = "; ".join(f"{size}: {len(names)} file(s)" for size, names in dimensions.items())
            report.errors.append("Images do not all have the same size: " + details)
        elif dimensions:
            report.image_size = next(iter(dimensions))
            width, height = report.image_size
            report.common_matrix_shape = (height, width)
        report.valid_files = sum(layer.import_status == "valid" for layer in report.layers)
        report.invalid_files = len(report.layers) - report.valid_files
        if report.invalid_files:
            report.errors.append(f"Cannot read {report.invalid_files} legacy image file(s).")

    return report
