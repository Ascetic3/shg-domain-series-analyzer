from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .image_io import read_gray, validate_matrix
from .models import LayerMetadata, ProcessingParameters, SCIENTIFIC_WARNING
from .processing import (
    build_black_domains,
    detect_bright_walls,
    find_best_rotation,
    normalize_for_analysis,
    rotate_and_build_profile,
)


@dataclass
class FrameAnalysis:
    summary: dict[str, Any]
    wall_rows: list[dict[str, Any]]
    domain_rows: list[dict[str, Any]]
    cropped_image: np.ndarray
    profile: np.ndarray
    bands: list[dict[str, Any]]
    dark_intervals: list[dict[str, Any]]
    um_per_px: float


def analyze_array(
    array: np.ndarray,
    layer: LayerMetadata,
    frame_width_um: float,
    params: ProcessingParameters,
) -> FrameAnalysis:
    """Analyze a two-dimensional floating-point source through the shared detector.

    Raw TXT matrices arrive here as float64. No PNG or uint8 conversion occurs;
    the preserved v6 normalize_for_analysis function creates its float32 working
    copy internally.
    """

    arr = np.asarray(array)
    validate_matrix(arr)
    height, width = arr.shape
    um_per_px_x = frame_width_um / float(width)
    um_per_px_y = frame_width_um / float(height)
    um_per_px = 0.5 * (um_per_px_x + um_per_px_y)

    arr_norm = normalize_for_analysis(arr)
    best_rotation = find_best_rotation(arr_norm)
    cropped, profile = rotate_and_build_profile(
        arr_norm,
        rotation_deg=best_rotation,
        profile_sigma_px=params.profile_sigma_px,
    )

    bands, _centers_px, _prominences = detect_bright_walls(
        profile,
        um_per_px=um_per_px,
        min_period_um=params.min_period_um,
        boundary_frac=params.boundary_frac,
        min_wall_width_um=params.min_band_width_um,
        max_wall_width_um=params.max_band_width_um,
        edge_ignore_frac=params.edge_ignore_fraction,
    )
    dark_intervals = build_black_domains(
        bands,
        um_per_px=um_per_px,
        min_domain_width_um=params.min_dark_interval_width_um,
    )

    band_widths = np.array([row["width_um"] for row in bands], dtype=float)
    interval_widths = np.array([row["width_um"] for row in dark_intervals], dtype=float)
    centers_um = np.array([row["center_um"] for row in bands], dtype=float)

    if centers_um.size >= 2:
        periods = np.diff(centers_um)
        period_centers_um = float(np.mean(periods))
        period_centers_std_um = float(np.std(periods, ddof=1)) if periods.size > 1 else float("nan")
    else:
        period_centers_um = float("nan")
        period_centers_std_um = float("nan")

    contrast_profile = float(np.percentile(profile, 95) - np.percentile(profile, 5))
    n_bands = int(band_widths.size)
    n_intervals = int(interval_widths.size)
    status = (
        "OK"
        if n_bands >= 2 and n_intervals >= 1 and contrast_profile > params.status_contrast_threshold
        else "CHECK"
    )

    summary: dict[str, Any] = {
        "filename": layer.filename,
        "source_array_dtype": str(arr.dtype),
        "layer_index": layer.layer_index,
        "source_number": layer.source_number if layer.source_number is not None else "",
        "z_um": layer.z_um,
        "frame_width_um": frame_width_um,
        "image_width_px": width,
        "image_height_px": height,
        "um_per_px_x": um_per_px_x,
        "um_per_px_y": um_per_px_y,
        "rotation_to_vertical_deg": best_rotation,
        "n_detected_bright_bands": n_bands,
        "n_dark_intervals": n_intervals,
        "candidate_band_mean_um": float(np.mean(band_widths)) if n_bands else float("nan"),
        "candidate_band_std_um": float(np.std(band_widths, ddof=1)) if n_bands > 1 else float("nan"),
        "candidate_dark_interval_mean_um": float(np.mean(interval_widths)) if n_intervals else float("nan"),
        "candidate_dark_interval_std_um": (
            float(np.std(interval_widths, ddof=1)) if n_intervals > 1 else float("nan")
        ),
        "period_band_centers_um": period_centers_um,
        "period_band_centers_std_um": period_centers_std_um,
        "dark_fraction_of_period": (
            float(np.mean(interval_widths) / period_centers_um)
            if n_intervals and math.isfinite(period_centers_um) and period_centers_um > 0
            else float("nan")
        ),
        "bright_fraction_of_period": (
            float(np.mean(band_widths) / period_centers_um)
            if n_bands and math.isfinite(period_centers_um) and period_centers_um > 0
            else float("nan")
        ),
        "profile_contrast": contrast_profile,
        "status": status,
        "interpretation": "candidate measurements; physical interpretation is not validated",
    }

    common = {
        "filename": layer.filename,
        "layer_index": layer.layer_index,
        "z_um": layer.z_um,
    }
    wall_rows: list[dict[str, Any]] = []
    for row in bands:
        wall_rows.append(
            {
                **common,
                "type": row["kind"],
                "band_index": row["band_index"],
                "x_start_px": row["x_start_px"],
                "x_end_px": row["x_end_px"],
                "center_px": row["center_px"],
                "width_px": row["width_px"],
                "x_start_um": row["x_start_um"],
                "x_end_um": row["x_end_um"],
                "center_um": row["center_um"],
                "candidate_wall_width_um": row["width_um"],
                "boundary_level": row["boundary_level"],
                "extreme_level": row["extreme_level"],
            }
        )

    domain_rows: list[dict[str, Any]] = []
    for row in dark_intervals:
        domain_rows.append(
            {
                **common,
                "type": row["kind"],
                "interval_index": row["interval_index"],
                "left_band_index": row["left_band_index"],
                "right_band_index": row["right_band_index"],
                "x_start_px": row["x_start_px"],
                "x_end_px": row["x_end_px"],
                "center_px": row["center_px"],
                "width_px": row["width_px"],
                "x_start_um": row["x_start_um"],
                "x_end_um": row["x_end_um"],
                "center_um": row["center_um"],
                "candidate_domain_width_um": row["width_um"],
                "index_scope": "left-to-right order within this frame only; not physical tracking",
            }
        )

    summary["scientific_warning"] = SCIENTIFIC_WARNING
    return FrameAnalysis(
        summary=summary,
        wall_rows=wall_rows,
        domain_rows=domain_rows,
        cropped_image=cropped,
        profile=profile,
        bands=bands,
        dark_intervals=dark_intervals,
        um_per_px=um_per_px,
    )


def analyze_image(
    layer: LayerMetadata,
    frame_width_um: float,
    params: ProcessingParameters,
) -> FrameAnalysis:
    """Legacy compatibility wrapper for already converted PNG/TIFF input."""

    return analyze_array(read_gray(layer.path), layer, frame_width_um, params)
