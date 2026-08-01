from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from demo.generate_synthetic_series import generate_synthetic_series
from shg_domain_analyzer.config import save_series_config
from shg_domain_analyzer.export import execute_series
from shg_domain_analyzer.image_io import preflight_series
from shg_domain_analyzer.models import SOURCE_LEGACY_IMAGES, SOURCE_RAW_TXT, SeriesConfig


def _run(source_type: str) -> dict:
    series_dir = ROOT / "demo" / "synthetic_series"
    output_name = "run_outputs_raw" if source_type == SOURCE_RAW_TXT else "run_outputs_legacy"
    output_base = ROOT / "demo" / output_name
    truth = generate_synthetic_series(series_dir, frame_count=10)
    source_dir = series_dir / ("txt" if source_type == SOURCE_RAW_TXT else "legacy_images")
    config = SeriesConfig(
        input_dir=str(source_dir.resolve()),
        output_dir=str(output_base.resolve()),
        frame_width_um=float(truth["frame_width_um"]),
        z_start_um=float(truth["z_start_um"]),
        z_step_um=float(truth["z_step_um"]),
        source_type=source_type,
        direction="increasing",
        export_preview_png=source_type == SOURCE_RAW_TXT,
        export_float_tiff=source_type == SOURCE_RAW_TXT,
        order_confirmed=True,
    )
    report = preflight_series(config)
    if not report.is_valid:
        raise RuntimeError("Demo preflight failed: " + " | ".join(report.errors))
    config.layers = report.layers
    save_series_config(config, series_dir / f"series_config_{source_type}.json")
    outcome = execute_series(config)
    result = {
        "source_type": source_type,
        "run_dir": outcome.run_dir,
        "configured": len(config.layers),
        "valid_imports": sum(layer.import_status == "valid" for layer in config.layers),
        "invalid_imports": len(outcome.import_errors),
        "processed": outcome.processed,
        "ok": outcome.ok,
        "check": outcome.check,
        "errors": len(outcome.errors),
        "cancelled": outcome.cancelled,
        "float_tiff": outcome.tiff_stack_path,
    }
    print(json.dumps(result, indent=2))
    return result


def run_raw_demo() -> dict:
    return _run(SOURCE_RAW_TXT)


def run_legacy_demo() -> dict:
    return _run(SOURCE_LEGACY_IMAGES)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the safe synthetic portfolio pipeline.")
    parser.add_argument("--mode", choices=["raw", "legacy"], default="raw")
    args = parser.parse_args()
    run_raw_demo() if args.mode == "raw" else run_legacy_demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
