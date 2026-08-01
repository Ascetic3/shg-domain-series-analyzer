from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _save_txt_matrix(path: Path, matrix: np.ndarray) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        np.savetxt(stream, matrix, fmt="%.10f", delimiter=" ", newline="\r\n")


def generate_synthetic_series(
    output_dir: str | Path,
    frame_count: int = 10,
    image_size_px: int = 192,
    frame_width_um: float = 192.0,
    z_start_um: float = 0.0,
    z_step_um: float = 12.5,
    seed: int = 20260801,
    omit_source_numbers: set[int] | None = None,
    include_invalid_examples: bool = True,
    include_legacy_images: bool = True,
) -> dict:
    """Create deterministic float TXT matrices unrelated to experimental data."""

    root = Path(output_dir)
    txt_dir = root / "txt"
    legacy_dir = root / "legacy_images"
    txt_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir.mkdir(parents=True, exist_ok=True)
    for old in txt_dir.glob("*.txt"):
        old.unlink()
    for old in legacy_dir.glob("*.png"):
        old.unlink()

    omit = omit_source_numbers or set()
    rng = np.random.default_rng(seed)
    y_grid, x_grid = np.mgrid[0:image_size_px, 0:image_size_px]
    um_per_px = frame_width_um / image_size_px

    frames: list[dict] = []
    for source_number in range(1, frame_count + 1):
        if source_number in omit:
            continue
        layer_index = source_number - 1
        z_um = z_start_um + layer_index * z_step_um
        period_um = 36.0 + 0.28 * layer_index
        fwhm_um = 6.0 + 0.22 * layer_index
        period_px = period_um / um_per_px
        fwhm_px = fwhm_um / um_per_px
        sigma_px = fwhm_px / 2.354820045
        tilt_deg = -6.0 + 1.2 * layer_index
        offset_px = 14.0 + 0.35 * layer_index

        coordinate = x_grid + np.tan(np.deg2rad(tilt_deg)) * (y_grid - image_size_px / 2)
        distance = np.abs((coordinate - offset_px + period_px / 2) % period_px - period_px / 2)
        bright_bands = np.exp(-0.5 * (distance / sigma_px) ** 2)
        slow_background = 0.04 * np.sin(2 * np.pi * y_grid / image_size_px)
        slow_background += 0.025 * (x_grid / image_size_px - 0.5)
        texture = 0.018 * np.sin(2 * np.pi * y_grid / 17.0 + layer_index * 0.25)
        noise = rng.normal(0.0, 0.028, size=(image_size_px, image_size_px))
        matrix = np.clip(0.18 + 0.72 * bright_bands + slow_background + texture + noise, 0.0, 1.0)

        txt_filename = f"layer_{source_number:03d}.txt"
        _save_txt_matrix(txt_dir / txt_filename, matrix)
        legacy_filename = f"layer_{source_number:03d}.png"
        if include_legacy_images:
            legacy = np.round(matrix * 255.0).astype(np.uint8)
            Image.fromarray(legacy).save(legacy_dir / legacy_filename)

        frames.append(
            {
                "filename": txt_filename,
                "legacy_filename": legacy_filename if include_legacy_images else None,
                "source_number": source_number,
                "layer_index": layer_index,
                "z_um": z_um,
                "generated_period_um": period_um,
                "generated_bright_band_fwhm_um": fwhm_um,
                "generated_dark_gap_approx_um": period_um - fwhm_um,
                "tilt_deg": tilt_deg,
                "noise_std_normalized": 0.028,
            }
        )

    invalid_examples: list[dict[str, object]] = []
    if include_invalid_examples:
        invalid_number = frame_count + 1
        invalid_name = f"layer_{invalid_number:03d}_invalid.txt"
        with (txt_dir / invalid_name).open("w", encoding="ascii", newline="") as stream:
            stream.write("synthetic invalid token\r\n")
        invalid_examples.append({"filename": invalid_name, "expected_status": "invalid_data"})

        wrong_shape_number = frame_count + 2
        wrong_shape_name = f"layer_{wrong_shape_number:03d}_wrong_shape.txt"
        wrong_shape = np.arange(9, dtype=np.float64).reshape(3, 3) / 10.0
        _save_txt_matrix(txt_dir / wrong_shape_name, wrong_shape)
        invalid_examples.append({"filename": wrong_shape_name, "expected_status": "invalid_shape"})

    truth = {
        "dataset": "fully synthetic periodic bright-band TXT demo",
        "safe_for_portfolio": True,
        "not_based_on_real_experimental_data": True,
        "primary_source_type": "raw_txt",
        "scientific_note": (
            "Generator parameters are known by construction. Agreement is useful for software "
            "regression but does not validate a physical interpretation."
        ),
        "txt_format": {
            "encoding": "ASCII-compatible UTF-8 without BOM",
            "column_separator": "single space",
            "row_separator": "CRLF",
            "decimal_separator": "dot",
            "header": "none",
            "dtype_when_loaded": "float64",
        },
        "image_size_px": [image_size_px, image_size_px],
        "frame_width_um": frame_width_um,
        "z_start_um": z_start_um,
        "z_step_um": z_step_um,
        "direction": "increasing",
        "seed": seed,
        "omitted_source_numbers": sorted(omit),
        "invalid_examples": invalid_examples,
        "legacy_images_note": (
            "Optional PNG files are simple synthetic 8-bit compatibility inputs, not an ImageJ-equivalent conversion."
        ),
        "frames": frames,
    }
    (root / "ground_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return truth


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a safe synthetic float TXT matrix series.")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "synthetic_series")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--with-gap", action="store_true", help="Omit source frame 4 for preflight demonstrations.")
    args = parser.parse_args()
    omit = {4} if args.with_gap else set()
    truth = generate_synthetic_series(args.output, frame_count=args.frames, omit_source_numbers=omit)
    print(f"Generated {len(truth['frames'])} synthetic TXT matrices in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
