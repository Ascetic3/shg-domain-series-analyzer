from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PathCollection

from shg_domain_analyzer.visualization import (
    dark_interval_distribution_by_depth,
    plot_dark_interval_distribution,
    plot_depth_summary,
    save_depth_plots,
)


def _summary(filename: str, z_um: float, status: str) -> dict:
    return {
        "filename": filename,
        "z_um": z_um,
        "status": status,
        "candidate_band_mean_um": 3.0 + z_um / 100,
        "candidate_dark_interval_mean_um": 20.0 + z_um / 100,
        "period_band_centers_um": 25.0 + z_um / 100,
        "n_detected_bright_bands": 4,
        "n_dark_intervals": 3,
    }


def _domain(filename: str, z_um: float, width: float, interval_index: int) -> dict:
    return {
        "filename": filename,
        "z_um": z_um,
        "candidate_domain_width_um": width,
        "interval_index": interval_index,
    }


def test_distribution_contains_every_interval_at_each_z() -> None:
    domains = [
        _domain("a.txt", 0.0, 10.0, 1),
        _domain("a.txt", 0.0, 12.0, 2),
        _domain("b.txt", 10.0, 14.0, 1),
        _domain("b.txt", 10.0, 16.0, 2),
        _domain("b.txt", 10.0, 18.0, 3),
    ]
    grouped = dark_interval_distribution_by_depth(domains)
    assert grouped == [
        {"z_um": 0.0, "widths_um": [10.0, 12.0], "median_um": 11.0, "q1_um": 10.5, "q3_um": 11.5, "n": 2},
        {"z_um": 10.0, "widths_um": [14.0, 16.0, 18.0], "median_um": 16.0, "q1_um": 15.0, "q3_um": 17.0, "n": 3},
    ]

    figure, axis = plt.subplots()
    plot_dark_interval_distribution(axis, domains, [_summary("a.txt", 0.0, "OK"), _summary("b.txt", 10.0, "CHECK")])
    plotted_observations = sum(
        len(collection.get_offsets())
        for collection in axis.collections
        if isinstance(collection, PathCollection)
    )
    assert plotted_observations == len(domains)
    assert not any(line.get_label().startswith(("B1", "B2", "B3")) for line in axis.lines)
    assert "Intervals are not tracked between layers." in axis.get_title()
    plt.close(figure)


def test_check_is_distinct_and_breaks_depth_lines() -> None:
    rows = [_summary("a.txt", 0.0, "OK"), _summary("b.txt", 10.0, "CHECK"), _summary("c.txt", 20.0, "OK")]
    figure, (axis_sizes, axis_counts) = plt.subplots(2, 1)
    plot_depth_summary(axis_sizes, axis_counts, rows)

    for line in axis_sizes.lines[:3]:
        assert np.isnan(np.asarray(line.get_ydata(), dtype=float)[1])
    assert any("CHECK" in collection.get_label() for collection in axis_sizes.collections)
    assert any("CHECK" in collection.get_label() for collection in axis_counts.collections)
    plt.close(figure)


def test_saved_plots_use_distribution_not_interval_index_series(tmp_path: Path) -> None:
    summaries = [_summary("a.txt", 0.0, "OK"), _summary("b.txt", 10.0, "CHECK")]
    domains = [_domain("a.txt", 0.0, 10.0, 1), _domain("b.txt", 10.0, 12.0, 1)]
    paths = save_depth_plots(tmp_path, summaries, domains)
    assert [path.name for path in paths] == ["depth_summary.png", "dark_interval_distribution_by_depth.png"]
    assert all(path.is_file() for path in paths)
    assert not (tmp_path / "dark_intervals_by_index.png").exists()

