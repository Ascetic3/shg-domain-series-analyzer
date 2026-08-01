from __future__ import annotations

import numpy as np

from shg_domain_analyzer.processing import build_black_domains, detect_bright_walls


def test_detect_bright_walls_on_synthetic_profile() -> None:
    x = np.arange(180, dtype=float)
    profile = np.full_like(x, 0.08)
    for center in (20, 60, 100, 140):
        profile += 0.9 * np.exp(-0.5 * ((x - center) / 3.0) ** 2)
    profile = np.clip(profile, 0, 1)

    bands, centers, _prominences = detect_bright_walls(
        profile,
        um_per_px=1.0,
        min_period_um=25.0,
        boundary_frac=0.50,
        min_wall_width_um=1.0,
        max_wall_width_um=18.0,
    )
    assert len(centers) == 4
    assert len(bands) == 4
    assert all(5.0 <= band["width_um"] <= 9.0 for band in bands)

    intervals = build_black_domains(bands, um_per_px=1.0, min_domain_width_um=3.0)
    assert len(intervals) == 3
    assert [row["interval_index"] for row in intervals] == [1, 2, 3]

