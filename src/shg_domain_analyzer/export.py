from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import tifffile

from . import __version__
from .config import save_series_config
from .image_io import MatrixImportError, preflight_series, read_source_array, sha256_file
from .measurements import analyze_array
from .models import (
    FrameError,
    RunOutcome,
    SCIENTIFIC_WARNING,
    SOURCE_RAW_TXT,
    SeriesConfig,
)
from .visualization import save_depth_plots, save_preview_png, save_qc_plot


ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]


def create_run_directory(output_base: str | Path) -> Path:
    base = Path(output_base).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    run_dir = base / f"run_{stamp}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=False, exist_ok=False)
    return run_dir


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def write_json(path: str | Path, data: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def save_float32_tiff_stack(output_path: str | Path, matrices: Iterable[np.ndarray]) -> Path:
    """Write same-shaped source matrices as an unscaled float32 ZYX TIFF stack."""

    arrays = [np.asarray(matrix) for matrix in matrices]
    if not arrays:
        raise ValueError("At least one matrix is required for TIFF stack export.")
    shape = arrays[0].shape
    if any(array.ndim != 2 or array.shape != shape for array in arrays):
        raise ValueError("TIFF stack layers must be same-shaped two-dimensional matrices.")
    stack = np.stack(arrays, axis=0).astype(np.float32, copy=False)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(output, stack, metadata={"axes": "ZYX"}, photometric="minisblack")
    return output


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _portable_source_path(path: Path, run_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), run_dir)).as_posix()
    except ValueError:
        return path.name


def execute_series(
    config: SeriesConfig,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> RunOutcome:
    """Import, validate, and process an explicit layer table into a unique run."""

    report = preflight_series(config)
    if not report.is_valid:
        raise ValueError("Preflight failed: " + " | ".join(report.errors))
    if not config.layers:
        raise ValueError("SeriesConfig must contain an explicit filename -> layer_index -> z table.")
    if report.requires_order_confirmation and not config.order_confirmed:
        raise ValueError("The detected order or numeric gaps require explicit confirmation.")

    discovered_names = {layer.filename for layer in report.layers}
    configured_names = {layer.filename for layer in config.layers}
    if discovered_names != configured_names:
        raise ValueError("Saved layer table does not match the current input source set.")
    if len(configured_names) != len(config.layers):
        raise ValueError("Saved layer table contains duplicate filenames.")

    current_by_name = {layer.filename: layer for layer in report.layers}
    for layer in config.layers:
        current = current_by_name[layer.filename]
        layer.matrix_shape = current.matrix_shape
        layer.source_min = current.source_min
        layer.source_max = current.source_max
        layer.import_status = current.import_status
        layer.import_error_type = current.import_error_type
        layer.import_error_message = current.import_error_message

    config.refresh_layer_z()
    all_layers = sorted(config.layers, key=lambda layer: (layer.layer_index, layer.filename.casefold()))
    valid_layers = [layer for layer in all_layers if layer.import_status == "valid"]
    if not valid_layers:
        raise ValueError("No valid source layers remain after import validation.")
    for layer in all_layers:
        if not layer.path.is_file():
            raise ValueError(f"Configured source file is missing: {layer.filename}")

    hashes_before = {layer.filename: sha256_file(layer.path) for layer in all_layers}
    run_dir = create_run_directory(config.output_dir)
    qc_dir = run_dir / "qc"
    plot_dir = run_dir / "plots"
    preview_dir = run_dir / "previews"

    summaries: list[dict[str, Any]] = []
    walls: list[dict[str, Any]] = []
    domains: list[dict[str, Any]] = []
    errors: list[FrameError] = []
    import_errors = list(report.import_errors)
    import_error_names = {error.filename for error in import_errors}
    qc_paths: dict[str, str] = {}
    preview_paths: dict[str, str] = {}
    stack_matrices: list[np.ndarray] = []
    cancelled = False

    total = len(valid_layers)
    for current_index, layer in enumerate(valid_layers, start=1):
        if cancel_check and cancel_check():
            cancelled = True
            break
        if progress_callback:
            progress_callback(current_index, total, layer.filename)

        try:
            source_array = read_source_array(layer, config.source_type)
            if layer.matrix_shape is not None and source_array.shape != layer.matrix_shape:
                raise MatrixImportError("invalid_shape", "Source shape changed after preflight validation.")
        except Exception as exc:
            layer.import_status = "invalid_data"
            layer.import_error_type = getattr(exc, "error_type", type(exc).__name__)
            layer.import_error_message = str(exc)
            if layer.filename not in import_error_names:
                import_errors.append(
                    FrameError(layer.filename, layer.import_error_type, layer.import_error_message)
                )
                import_error_names.add(layer.filename)
            continue

        if config.export_float_tiff:
            stack_matrices.append(source_array)
        if config.export_preview_png:
            try:
                preview_path = preview_dir / f"{Path(layer.filename).stem}.png"
                save_preview_png(
                    preview_path,
                    source_array,
                    config.preview_low_percentile,
                    config.preview_high_percentile,
                )
                preview_paths[layer.filename] = str(preview_path)
            except Exception as exc:
                errors.append(FrameError(layer.filename, "PreviewExportError", str(exc)))

        try:
            analysis = analyze_array(source_array, layer, config.frame_width_um, config.processing)
            analysis.summary["source_type"] = config.source_type
            qc_path = qc_dir / f"{Path(layer.filename).stem}_qc.png"
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
            layer.status = analysis.summary["status"]
            summaries.append(analysis.summary)
            walls.extend(analysis.wall_rows)
            domains.extend(analysis.domain_rows)
            qc_paths[layer.filename] = str(qc_path)
        except Exception as exc:
            layer.status = "ERROR"
            errors.append(FrameError(layer.filename, type(exc).__name__, str(exc)))

    tiff_stack_path: str | None = None
    if config.export_float_tiff and stack_matrices:
        tiff_stack_path = str(save_float32_tiff_stack(run_dir / "source_stack_float32.tif", stack_matrices))

    plot_paths = [str(path) for path in save_depth_plots(plot_dir, summaries, domains)]

    summary_fields = [
        "filename", "source_type", "source_array_dtype", "layer_index", "source_number", "z_um",
        "frame_width_um", "image_width_px", "image_height_px", "um_per_px_x", "um_per_px_y",
        "rotation_to_vertical_deg", "n_detected_bright_bands", "n_dark_intervals",
        "candidate_band_mean_um", "candidate_band_std_um",
        "candidate_dark_interval_mean_um", "candidate_dark_interval_std_um",
        "period_band_centers_um", "period_band_centers_std_um",
        "dark_fraction_of_period", "bright_fraction_of_period", "profile_contrast",
        "status", "interpretation", "scientific_warning",
    ]
    wall_fields = [
        "filename", "layer_index", "z_um", "type", "band_index", "x_start_px",
        "x_end_px", "center_px", "width_px", "x_start_um", "x_end_um", "center_um",
        "candidate_wall_width_um", "boundary_level", "extreme_level",
    ]
    domain_fields = [
        "filename", "layer_index", "z_um", "type", "interval_index", "left_band_index",
        "right_band_index", "x_start_px", "x_end_px", "center_px", "width_px",
        "x_start_um", "x_end_um", "center_um", "candidate_domain_width_um", "index_scope",
    ]
    error_fields = ["filename", "error_type", "message"]
    imported_fields = [
        "source_filename", "source_number", "layer_index", "z_um", "rows", "columns",
        "source_min", "source_max", "source_sha256", "import_status",
    ]

    hashes_after = {layer.filename: sha256_file(layer.path) for layer in all_layers}
    imported_rows = [
        {
            "source_filename": layer.filename,
            "source_number": layer.source_number if layer.source_number is not None else "",
            "layer_index": layer.layer_index,
            "z_um": layer.z_um,
            "rows": layer.matrix_shape[0] if layer.matrix_shape else "",
            "columns": layer.matrix_shape[1] if layer.matrix_shape else "",
            "source_min": layer.source_min if layer.source_min is not None else "",
            "source_max": layer.source_max if layer.source_max is not None else "",
            "source_sha256": hashes_before[layer.filename],
            "import_status": layer.import_status,
        }
        for layer in all_layers
    ]

    write_csv(run_dir / "summary.csv", summaries, summary_fields)
    write_csv(run_dir / "walls.csv", walls, wall_fields)
    write_csv(run_dir / "domains.csv", domains, domain_fields)
    write_csv(run_dir / "errors.csv", [error.to_dict() for error in errors], error_fields)
    write_csv(run_dir / "imported_layers.csv", imported_rows, imported_fields)
    write_csv(run_dir / "import_errors.csv", [error.to_dict() for error in import_errors], error_fields)
    save_series_config(config, run_dir / "series_config.json")

    input_files = [
        {
            "filename": layer.filename,
            "source_path": _portable_source_path(layer.path, run_dir),
            "layer_index": layer.layer_index,
            "z_um": layer.z_um,
            "import_status": layer.import_status,
            "sha256_before": hashes_before[layer.filename],
            "sha256_after": hashes_after[layer.filename],
            "unchanged": hashes_before[layer.filename] == hashes_after[layer.filename],
        }
        for layer in all_layers
    ]
    dtype_description = (
        {
            "source_array": "float64",
            "normalize_for_analysis_working_copy": "float32 (preserved v6 behavior)",
            "uint8_or_png_intermediate": False,
        }
        if config.source_type == SOURCE_RAW_TXT
        else {
            "source_array": "float32 grayscale loaded from the already converted image",
            "normalize_for_analysis_working_copy": "float32",
            "uint8_or_png_intermediate": "legacy source file itself may already be 8-bit",
        }
    )
    manifest = {
        "application": "shg-domain-analyzer",
        "application_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "run_directory": ".",
        "source_type": config.source_type,
        "txt_format_description": report.txt_format_description if config.source_type == SOURCE_RAW_TXT else None,
        "dtype_used_for_analysis": dtype_description,
        "matrix_shape_rows_columns": list(report.common_matrix_shape) if report.common_matrix_shape else None,
        "preview_normalization": {
            "method": "linear percentile scaling with clipping",
            "low_percentile": config.preview_low_percentile,
            "high_percentile": config.preview_high_percentile,
            "output_dtype": "uint8",
            "used_as_analysis_input": False,
            "exported": config.export_preview_png,
        },
        "float_tiff": {
            "dtype": "float32",
            "axes": "ZYX",
            "contrast_or_quantization": "none",
            "exported": bool(tiff_stack_path),
        },
        "algorithm_origin": "analyze_domains_v6.py formulas and thresholds, modularized without detector changes",
        "terminology": {
            "W": "detected bright band; candidate wall width only",
            "B": "dark interval ordered left-to-right within one frame; not physical tracking",
        },
        "scientific_warning": SCIENTIFIC_WARNING,
        "processing_parameters": config.processing.__dict__,
        "counts": {
            "configured": len(all_layers),
            "valid_imports": sum(layer.import_status == "valid" for layer in all_layers),
            "invalid_imports": sum(layer.import_status != "valid" for layer in all_layers),
            "processed": len(summaries),
            "ok": sum(row["status"] == "OK" for row in summaries),
            "check": sum(row["status"] == "CHECK" for row in summaries),
            "analysis_or_export_errors": len(errors),
            "cancelled": cancelled,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": _version("numpy"),
            "scipy": _version("scipy"),
            "Pillow": _version("Pillow"),
            "matplotlib": _version("matplotlib"),
            "PySide6": _version("PySide6"),
            "tifffile": _version("tifffile"),
        },
        "preflight_warnings": report.warnings,
        "input_files": input_files,
        "all_inputs_unchanged": all(item["unchanged"] for item in input_files),
        "outputs": {
            "summary": "summary.csv",
            "walls": "walls.csv",
            "domains": "domains.csv",
            "errors": "errors.csv",
            "imported_layers": "imported_layers.csv",
            "import_errors": "import_errors.csv",
            "series_config": "series_config.json",
            "qc_directory": "qc",
            "plots_directory": "plots",
            "previews_directory": "previews" if config.export_preview_png else None,
            "float_tiff_stack": "source_stack_float32.tif" if tiff_stack_path else None,
        },
    }
    write_json(run_dir / "run_manifest.json", manifest)

    return RunOutcome(
        run_dir=str(run_dir),
        summaries=summaries,
        walls=walls,
        domains=domains,
        errors=errors,
        qc_paths=qc_paths,
        plot_paths=plot_paths,
        cancelled=cancelled,
        import_errors=import_errors,
        preview_paths=preview_paths,
        tiff_stack_path=tiff_stack_path,
        imported_rows=imported_rows,
    )
