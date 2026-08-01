from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
from PIL import Image

from .models import SCIENTIFIC_WARNING


def preview_to_uint8(
    matrix: np.ndarray,
    low_percentile: float = 1.0,
    high_percentile: float = 99.0,
) -> np.ndarray:
    """Create an 8-bit display copy without modifying the raw matrix."""

    source = np.asarray(matrix)
    if source.ndim != 2 or not np.isfinite(source).all():
        raise ValueError("Display preview requires a finite two-dimensional matrix.")
    low, high = np.percentile(source, [low_percentile, high_percentile])
    if high - low < np.finfo(float).eps:
        return np.zeros(source.shape, dtype=np.uint8)
    normalized = np.clip((source.astype(np.float64, copy=False) - low) / (high - low), 0.0, 1.0)
    return np.round(normalized * 255.0).astype(np.uint8)


def save_preview_png(
    output_path: str | Path,
    matrix: np.ndarray,
    low_percentile: float = 1.0,
    high_percentile: float = 99.0,
) -> Path:
    """Save an 8-bit percentile-normalized preview that is never used for analysis."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(preview_to_uint8(matrix, low_percentile, high_percentile)).save(output)
    return output


def add_dense_grid(axis, x_major: float | None = None, y_major: float | None = None) -> None:
    if x_major:
        axis.xaxis.set_major_locator(MultipleLocator(x_major))
    axis.xaxis.set_minor_locator(AutoMinorLocator(5))
    if y_major:
        axis.yaxis.set_major_locator(MultipleLocator(y_major))
    axis.yaxis.set_minor_locator(AutoMinorLocator(5))
    axis.grid(True, which="major", alpha=0.35, linewidth=0.8)
    axis.grid(True, which="minor", alpha=0.18, linewidth=0.5)


def save_qc_plot(
    output_path: str | Path,
    filename: str,
    layer_index: int,
    z_um: float,
    rotated_crop: np.ndarray,
    profile: np.ndarray,
    summary: dict[str, Any],
    walls: list[dict[str, Any]],
    black_domains: list[dict[str, Any]],
    um_per_px: float,
) -> Path:
    """Save the v6 QC layout with scientifically neutral labels."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    x_um = np.arange(profile.size) * um_per_px

    figure = plt.figure(figsize=(11.5, 7.8))
    image_axis = figure.add_axes([0.08, 0.57, 0.86, 0.35])
    image_axis.imshow(rotated_crop, cmap="gray", aspect="auto")
    image_axis.set_title(f"{filename} | layer {layer_index} | z={z_um:.3f} µm | rotated analysis crop")
    image_axis.set_xlabel("x, px")
    image_axis.set_ylabel("y, px")

    for row in walls:
        image_axis.axvline(row["x_start_px"], color="tab:blue", linestyle="--", linewidth=1.0)
        image_axis.axvline(row["x_end_px"], color="tab:blue", linestyle="--", linewidth=1.0)
        image_axis.axvline(row["center_px"], color="tab:red", linestyle=":", linewidth=1.0)
        image_axis.text(
            row["center_px"],
            8,
            f"W{row['band_index']}",
            color="tab:red",
            fontsize=8,
            ha="center",
            va="top",
            bbox=dict(facecolor="white", alpha=0.58, edgecolor="none", pad=1.0),
        )

    for row in black_domains:
        image_axis.text(
            row["center_px"],
            rotated_crop.shape[0] - 10,
            f"B{row['interval_index']}",
            color="black",
            fontsize=8,
            ha="center",
            va="bottom",
            bbox=dict(facecolor="white", alpha=0.58, edgecolor="none", pad=1.0),
        )

    profile_axis = figure.add_axes([0.08, 0.11, 0.86, 0.35])
    profile_axis.plot(x_um, profile, linewidth=1.8, label="normalized brightness profile")

    first_interval = True
    for row in black_domains:
        profile_axis.axvspan(
            row["x_start_um"],
            row["x_end_um"],
            color="black",
            alpha=0.10,
            label="dark interval B (within-frame order)" if first_interval else None,
        )
        profile_axis.text(row["center_um"], 0.04, f"B{row['interval_index']}", ha="center", fontsize=8)
        first_interval = False

    first_band = True
    first_center = True
    for row in walls:
        profile_axis.axvspan(
            row["x_start_um"],
            row["x_end_um"],
            color="tab:blue",
            alpha=0.22,
            label="detected bright band W" if first_band else None,
        )
        first_band = False
        profile_axis.axvline(
            row["center_um"],
            color="tab:red",
            linestyle=":",
            linewidth=1.0,
            label="detected band center" if first_center else None,
        )
        first_center = False
        if math.isfinite(row["boundary_level"]):
            profile_axis.hlines(
                row["boundary_level"],
                row["x_start_um"],
                row["x_end_um"],
                color="tab:blue",
                linestyle="--",
                linewidth=1.1,
            )

    profile_axis.set_xlabel("coordinate across detected bands, µm")
    profile_axis.set_ylabel("normalized brightness")
    profile_axis.set_title(
        f"candidate band={summary['candidate_band_mean_um']:.2f} µm, "
        f"candidate dark interval={summary['candidate_dark_interval_mean_um']:.2f} µm, "
        f"period={summary['period_band_centers_um']:.2f} µm, status={summary['status']}"
    )
    add_dense_grid(profile_axis, x_major=10.0, y_major=0.1)
    profile_axis.legend(loc="best", fontsize=8)
    figure.text(0.08, 0.015, SCIENTIFIC_WARNING, fontsize=7.5, color="darkred")
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def dark_interval_distribution_by_depth(domains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group every detected interval by z without assigning inter-layer identity."""

    grouped: dict[float, list[float]] = {}
    for row in domains:
        z_um = float(row["z_um"])
        grouped.setdefault(z_um, []).append(float(row["candidate_domain_width_um"]))
    result: list[dict[str, Any]] = []
    for z_um in sorted(grouped):
        widths = np.asarray(grouped[z_um], dtype=float)
        result.append(
            {
                "z_um": z_um,
                "widths_um": widths.tolist(),
                "median_um": float(np.median(widths)),
                "q1_um": float(np.percentile(widths, 25)),
                "q3_um": float(np.percentile(widths, 75)),
                "n": int(widths.size),
            }
        )
    return result


def _plot_status_aware_series(axis, rows: list[dict[str, Any]], field: str, label: str, color: str) -> None:
    z = np.asarray([float(row["z_um"]) for row in rows], dtype=float)
    values = np.asarray([float(row[field]) for row in rows], dtype=float)
    ok = np.asarray([row.get("status") == "OK" for row in rows], dtype=bool)
    finite = np.isfinite(values)
    reliable_line = np.where(ok & finite, values, np.nan)
    axis.plot(z, reliable_line, marker="o", linewidth=1.8, color=color, label=label)
    check = (~ok) & finite
    if np.any(check):
        axis.scatter(
            z[check], values[check], marker="X", s=70, color=color,
            edgecolors="#7f1d1d", linewidths=0.7, zorder=5, label=f"{label} — CHECK",
        )


def plot_depth_summary(axis_sizes, axis_counts, rows: list[dict[str, Any]]) -> None:
    """Draw aggregate layer statistics; CHECK layers break every connecting line."""

    _plot_status_aware_series(
        axis_sizes, rows, "candidate_band_mean_um", "mean candidate bright-band width", "#1976d2"
    )
    _plot_status_aware_series(
        axis_sizes, rows, "candidate_dark_interval_mean_um", "mean candidate dark-interval width", "#111827"
    )
    _plot_status_aware_series(
        axis_sizes, rows, "period_band_centers_um", "mean period", "#7c3aed"
    )
    _plot_status_aware_series(
        axis_counts, rows, "n_detected_bright_bands", "bright bands", "#0284c7"
    )
    _plot_status_aware_series(axis_counts, rows, "n_dark_intervals", "dark intervals", "#c2410c")

    axis_sizes.set_ylabel("candidate width / period, µm")
    axis_sizes.set_title("Exploratory depth summary of candidate detections")
    axis_counts.set_xlabel("z, µm")
    axis_counts.set_ylabel("detections per layer, n")
    add_dense_grid(axis_sizes, y_major=5.0)
    add_dense_grid(axis_counts, y_major=1.0)
    axis_sizes.legend(loc="best", fontsize=8, ncols=2)
    axis_counts.legend(loc="best", fontsize=8, ncols=2)


def plot_dark_interval_distribution(
    axis,
    domains: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Plot per-depth observations and robust summaries without cross-layer lines."""

    status_by_filename = {str(row["filename"]): str(row.get("status", "CHECK")) for row in summaries}
    ok_rows = [row for row in domains if status_by_filename.get(str(row["filename"])) == "OK"]
    check_rows = [row for row in domains if status_by_filename.get(str(row["filename"])) != "OK"]
    if ok_rows:
        axis.scatter(
            [float(row["z_um"]) for row in ok_rows],
            [float(row["candidate_domain_width_um"]) for row in ok_rows],
            s=38, marker="o", color="#16784b", alpha=0.72, label="intervals in OK layers", zorder=3,
        )
    if check_rows:
        axis.scatter(
            [float(row["z_um"]) for row in check_rows],
            [float(row["candidate_domain_width_um"]) for row in check_rows],
            s=64, marker="X", color="#c2413b", label="intervals in CHECK layers", zorder=4,
        )

    grouped = dark_interval_distribution_by_depth(domains)
    z_values = np.asarray([row["z_um"] for row in grouped], dtype=float)
    if z_values.size > 1:
        differences = np.diff(np.unique(z_values))
        half_width = 0.08 * float(np.min(differences[differences > 0])) if np.any(differences > 0) else 0.35
    else:
        half_width = 0.35
    for group in grouped:
        z_um = float(group["z_um"])
        axis.vlines(z_um, group["q1_um"], group["q3_um"], color="#0f172a", linewidth=4.0, alpha=0.72)
        axis.hlines(
            group["median_um"], z_um - half_width, z_um + half_width,
            color="#f59e0b", linewidth=3.0, zorder=5,
        )
        axis.annotate(
            f"n={group['n']}", (z_um, group["q3_um"]), xytext=(0, 7),
            textcoords="offset points", ha="center", va="bottom", fontsize=8, color="#334155",
        )

    axis.plot([], [], color="#0f172a", linewidth=4.0, label="interquartile range")
    axis.plot([], [], color="#f59e0b", linewidth=3.0, label="median")
    axis.set_xlabel("z, µm")
    axis.set_ylabel("candidate dark-interval width, µm")
    axis.set_title(
        "Candidate dark-interval width distribution at each depth.\n"
        "Intervals are not tracked between layers."
    )
    add_dense_grid(axis, y_major=5.0)
    axis.legend(loc="best", fontsize=8)
    return grouped


def save_depth_plots(
    output_dir: str | Path,
    summaries: list[dict[str, Any]],
    domains: list[dict[str, Any]],
) -> list[Path]:
    if not summaries:
        return []
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    rows = sorted(summaries, key=lambda row: float(row["z_um"]))

    figure, (axis_sizes, axis_counts) = plt.subplots(
        2, 1, figsize=(10.4, 7.8), sharex=True, gridspec_kw={"height_ratios": [1.65, 1.0]}
    )
    plot_depth_summary(axis_sizes, axis_counts, rows)
    figure.text(
        0.075,
        0.012,
        "CHECK markers are shown separately and break connecting lines.\n"
        "The physical interpretation and scientific accuracy of the detector must be validated\n"
        "against expert annotation or an independent method.",
        fontsize=7.3,
        color="darkred",
        va="bottom",
    )
    figure.tight_layout(rect=[0, 0.105, 1, 1])
    summary_path = root / "depth_summary.png"
    figure.savefig(summary_path, dpi=220)
    plt.close(figure)

    figure2, axis2 = plt.subplots(figsize=(10.2, 6.4))
    plot_dark_interval_distribution(axis2, domains, rows)
    figure2.text(0.075, 0.012, SCIENTIFIC_WARNING, fontsize=7.5, color="darkred")
    figure2.tight_layout(rect=[0, 0.05, 1, 1])
    intervals_path = root / "dark_interval_distribution_by_depth.png"
    figure2.savefig(intervals_path, dpi=220)
    plt.close(figure2)
    return [summary_path, intervals_path]
