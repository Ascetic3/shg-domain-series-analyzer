from __future__ import annotations

from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d, rotate as nd_rotate
from scipy.signal import find_peaks


def normalize_for_analysis(arr: np.ndarray) -> np.ndarray:
    """Denoise, remove slow background, and robustly normalize to 0..1.

    This is the v6 formula: sigma 0.8 denoising, sigma 18 background,
    followed by 1st/99th percentile scaling.
    """

    a = arr.astype(np.float32)
    a = gaussian_filter(a, sigma=0.8)
    bg = gaussian_filter(a, sigma=18.0)
    hp = a - bg
    p1, p99 = np.percentile(hp, [1, 99])
    if p99 - p1 < 1e-6:
        return hp
    return np.clip((hp - p1) / (p99 - p1), 0, 1)


def crop_center(arr: np.ndarray, frac: float = 0.80) -> np.ndarray:
    h, w = arr.shape
    ch, cw = int(h * frac), int(w * frac)
    y0 = max(0, (h - ch) // 2)
    x0 = max(0, (w - cw) // 2)
    return arr[y0 : y0 + ch, x0 : x0 + cw]


def score_rotation_to_vertical(arr_norm: np.ndarray, angle_deg: float) -> float:
    rot = nd_rotate(arr_norm, angle_deg, reshape=False, order=1, mode="nearest")
    central = crop_center(rot, 0.72)
    profile = np.mean(central, axis=0)
    profile = gaussian_filter1d(profile, sigma=2.0)
    return float(np.var(profile))


def find_best_rotation(arr_norm: np.ndarray) -> float:
    coarse_angles = np.arange(-90.0, 90.01, 2.0)
    scores = [score_rotation_to_vertical(arr_norm, angle) for angle in coarse_angles]
    best = float(coarse_angles[int(np.argmax(scores))])

    fine_angles = np.arange(best - 3.0, best + 3.001, 0.25)
    fine_scores = [score_rotation_to_vertical(arr_norm, angle) for angle in fine_angles]
    return float(fine_angles[int(np.argmax(fine_scores))])


def robust_profile_normalize(profile: np.ndarray) -> np.ndarray:
    p2, p98 = np.percentile(profile, [2, 98])
    if p98 - p2 < 1e-9:
        return profile.copy()
    return np.clip((profile - p2) / (p98 - p2), 0, 1)


def detect_bright_walls(
    profile: np.ndarray,
    um_per_px: float,
    min_period_um: float = 25.0,
    boundary_frac: float = 0.50,
    min_wall_width_um: float = 1.0,
    max_wall_width_um: float = 20.0,
    edge_ignore_frac: float = 0.04,
) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    """Detect bright bands using the unchanged v6 local-maximum method.

    The historical function name is retained for traceability. Returned
    features use neutral labels and are not asserted to be physical walls.
    """

    n = profile.size
    if n < 5:
        return [], np.array([], dtype=int), np.array([], dtype=float)

    min_distance_px = max(3, int(round(min_period_um / um_per_px)))
    value_range = float(np.percentile(profile, 95) - np.percentile(profile, 5))
    prominence = max(0.06, 0.20 * value_range)

    lo = int(edge_ignore_frac * n)
    hi = int((1.0 - edge_ignore_frac) * n)
    median_level = float(np.median(profile))
    search_win = max(min_distance_px, int(round(30.0 / um_per_px)))

    centers, props = find_peaks(profile, distance=min_distance_px, prominence=prominence)
    centers = np.array(
        [position for position in centers if lo <= position <= hi and profile[position] > median_level],
        dtype=int,
    )

    intervals: list[dict[str, Any]] = []
    for position in centers:
        left_limit = max(0, position - search_win)
        right_limit = min(n, position + search_win + 1)
        if position <= left_limit or position + 1 >= right_limit:
            continue

        left_valley = float(np.min(profile[left_limit:position]))
        right_valley = float(np.min(profile[position + 1 : right_limit]))
        reference_valley = max(left_valley, right_valley)
        peak = float(profile[position])
        if peak <= reference_valley:
            continue

        level = reference_valley + boundary_frac * (peak - reference_valley)

        start = int(position)
        while start > 0 and profile[start] >= level:
            start -= 1
        end = int(position)
        while end < n - 1 and profile[end] >= level:
            end += 1

        start = max(0, start + 1)
        end = min(n, end)
        width_px = end - start
        width_um = width_px * um_per_px
        if width_um < min_wall_width_um or width_um > max_wall_width_um:
            continue

        intervals.append(
            {
                "kind": "detected_bright_band",
                "x_start_px": start,
                "x_end_px": end,
                "center_px": int(position),
                "x_start_um": start * um_per_px,
                "x_end_um": end * um_per_px,
                "center_um": position * um_per_px,
                "width_px": width_px,
                "width_um": width_um,
                "boundary_level": level,
                "extreme_level": peak,
            }
        )

    intervals = sorted(intervals, key=lambda row: row["center_px"])
    for index, row in enumerate(intervals, start=1):
        row["band_index"] = index
        row["feature_index"] = index
    return intervals, centers, props.get("prominences", np.array([], dtype=float))


def build_black_domains(
    walls: list[dict[str, Any]],
    um_per_px: float,
    min_domain_width_um: float = 3.0,
) -> list[dict[str, Any]]:
    """Build dark intervals between adjacent detected bright bands.

    Indices are left-to-right order within this frame only. They do not track
    a physical object between frames.
    """

    domains: list[dict[str, Any]] = []
    for left, right in zip(walls[:-1], walls[1:]):
        start = int(left["x_end_px"])
        end = int(right["x_start_px"])
        if end <= start:
            continue
        width_um = (end - start) * um_per_px
        if width_um < min_domain_width_um:
            continue
        index = len(domains) + 1
        domains.append(
            {
                "kind": "dark_interval_between_detected_bands",
                "x_start_px": start,
                "x_end_px": end,
                "center_px": 0.5 * (start + end),
                "x_start_um": start * um_per_px,
                "x_end_um": end * um_per_px,
                "center_um": 0.5 * (start + end) * um_per_px,
                "width_px": end - start,
                "width_um": width_um,
                "interval_index": index,
                "left_band_index": index,
                "right_band_index": index + 1,
                "feature_index": index,
            }
        )
    return domains


def rotate_and_build_profile(
    arr_norm: np.ndarray,
    rotation_deg: float,
    profile_sigma_px: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the unchanged v6 rotation, crop, and profile operations."""

    rotated = nd_rotate(arr_norm, rotation_deg, reshape=False, order=1, mode="nearest")
    cropped = crop_center(rotated, 0.78)
    raw_profile = np.mean(cropped, axis=0)
    smooth_profile = gaussian_filter1d(raw_profile, sigma=profile_sigma_px)
    profile = robust_profile_normalize(smooth_profile)
    profile = gaussian_filter1d(profile, sigma=1.0)
    return cropped, profile

