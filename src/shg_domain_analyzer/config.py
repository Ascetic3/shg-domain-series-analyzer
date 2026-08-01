from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from .models import LayerMetadata, SeriesConfig


def natural_key(value: str | Path) -> list[object]:
    """Return a natural-sort key: 1, 2, 10 instead of 1, 10, 2."""

    name = Path(value).name.lower()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def extract_frame_number(filename: str) -> int | None:
    """Use the last numeric group in the filename stem as the source number."""

    matches = re.findall(r"\d+", Path(filename).stem)
    return int(matches[-1]) if matches else None


def missing_numbers(numbers: Iterable[int]) -> list[int]:
    values = sorted(set(numbers))
    if len(values) < 2:
        return []
    return sorted(set(range(values[0], values[-1] + 1)) - set(values))


def build_layer_table(
    files: list[Path],
    z_start_um: float,
    z_step_um: float,
    direction: str,
) -> tuple[list[LayerMetadata], list[int], bool, list[str]]:
    """Build an explicit filename -> layer_index -> z table.

    Numeric filenames use a zero-based offset derived from the source number:
    layer_index = source_number - minimum_source_number. This preserves gaps
    without making the first numbered image start one step after z0.
    """

    ordered = sorted(files, key=natural_key)
    numbers = [extract_frame_number(path.name) for path in ordered]
    warnings: list[str] = []
    requires_confirmation = False

    if all(number is not None for number in numbers):
        numeric = [int(number) for number in numbers if number is not None]
        duplicates = sorted(number for number in set(numeric) if numeric.count(number) > 1)
        if duplicates:
            raise ValueError(f"Duplicate frame numbers: {duplicates}")
        base = min(numeric)
        indices = [number - base for number in numeric]
        missing = missing_numbers(numeric)
        if missing:
            warnings.append(
                "Missing frame number(s): " + ", ".join(str(number) for number in missing)
                + ". Layer indices preserve these gaps."
            )
            requires_confirmation = True
    else:
        indices = list(range(len(ordered)))
        missing = []
        requires_confirmation = True
        warnings.append(
            "Frame numbers could not be extracted from every filename. "
            "The displayed natural-sort order must be explicitly confirmed."
        )

    sign = 1.0 if direction == "increasing" else -1.0
    layers = [
        LayerMetadata(
            filename=path.name,
            source_path=str(path.resolve()),
            layer_index=index,
            z_um=float(z_start_um + sign * index * z_step_um),
            source_number=number,
        )
        for path, number, index in zip(ordered, numbers, indices)
    ]
    return layers, missing, requires_confirmation, warnings


def save_series_config(config: SeriesConfig, path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = config.to_dict()
    data["path_mode"] = "relative_to_config"

    def portable_path(value: str) -> str:
        if not value:
            return value
        absolute = Path(value).expanduser().resolve()
        try:
            return Path(os.path.relpath(absolute, output.parent)).as_posix()
        except ValueError:
            # Windows cannot express a relative path across drive letters.
            return str(absolute)

    data["input_dir"] = portable_path(config.input_dir)
    data["output_dir"] = portable_path(config.output_dir)
    for serialized, layer in zip(data["layers"], config.layers):
        serialized["source_path"] = portable_path(layer.source_path)

    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def load_series_config(path: str | Path) -> SeriesConfig:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    path_mode = data.pop("path_mode", None)
    if path_mode == "relative_to_config":
        def resolved_path(value: str) -> str:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = source.parent / candidate
            return str(candidate.resolve())

        data["input_dir"] = resolved_path(data["input_dir"])
        data["output_dir"] = resolved_path(data["output_dir"])
        for layer in data.get("layers", []):
            layer["source_path"] = resolved_path(layer["source_path"])
    return SeriesConfig.from_dict(data)
