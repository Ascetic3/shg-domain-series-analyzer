from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCIENTIFIC_WARNING = (
    "The physical interpretation and scientific accuracy of the detector "
    "must be validated against expert annotation or an independent method."
)

SOURCE_RAW_TXT = "raw_txt"
SOURCE_LEGACY_IMAGES = "legacy_images"


@dataclass(frozen=True)
class ProcessingParameters:
    """Parameters preserved from the v6 detector.

    Defaults intentionally match analyze_domains_v6.py. Fixed preprocessing
    constants are recorded here for provenance even when they are not exposed
    by the MVP GUI.
    """

    min_period_um: float = 25.0
    boundary_frac: float = 0.50
    min_band_width_um: float = 1.0
    max_band_width_um: float = 18.0
    profile_sigma_px: float = 3.0
    min_dark_interval_width_um: float = 3.0
    denoise_sigma_px: float = 0.8
    background_sigma_px: float = 18.0
    rotation_score_crop_fraction: float = 0.72
    analysis_crop_fraction: float = 0.78
    final_profile_sigma_px: float = 1.0
    edge_ignore_fraction: float = 0.04
    status_contrast_threshold: float = 0.08

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.min_period_um <= 0:
            errors.append("Minimum band period must be greater than zero.")
        if not 0 < self.boundary_frac < 1:
            errors.append("Boundary fraction must be between zero and one.")
        if self.min_band_width_um <= 0:
            errors.append("Minimum candidate band width must be greater than zero.")
        if self.max_band_width_um <= self.min_band_width_um:
            errors.append("Maximum candidate band width must exceed the minimum.")
        if self.profile_sigma_px <= 0:
            errors.append("Profile smoothing sigma must be greater than zero.")
        if self.min_dark_interval_width_um <= 0:
            errors.append("Minimum dark interval width must be greater than zero.")
        return errors


@dataclass
class LayerMetadata:
    filename: str
    source_path: str
    layer_index: int
    z_um: float
    status: str = "Pending"
    source_number: int | None = None
    matrix_shape: tuple[int, int] | None = None
    source_min: float | None = None
    source_max: float | None = None
    import_status: str = "pending"
    import_error_type: str = ""
    import_error_message: str = ""

    @property
    def path(self) -> Path:
        return Path(self.source_path)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LayerMetadata":
        clean = dict(data)
        if clean.get("matrix_shape") is not None:
            clean["matrix_shape"] = tuple(clean["matrix_shape"])
        return cls(**clean)


@dataclass
class SeriesConfig:
    input_dir: str
    output_dir: str
    frame_width_um: float
    z_start_um: float
    z_step_um: float
    source_type: str = SOURCE_RAW_TXT
    direction: str = "increasing"
    txt_patterns: list[str] = field(default_factory=lambda: ["*.txt"])
    image_patterns: list[str] = field(
        default_factory=lambda: ["img_*.png", "img_*.tif", "img_*.tiff", "*.png", "*.tif", "*.tiff"]
    )
    export_preview_png: bool = False
    export_float_tiff: bool = False
    preview_low_percentile: float = 1.0
    preview_high_percentile: float = 99.0
    processing: ProcessingParameters = field(default_factory=ProcessingParameters)
    layers: list[LayerMetadata] = field(default_factory=list)
    order_confirmed: bool = False

    def z_for_index(self, layer_index: int) -> float:
        sign = 1.0 if self.direction == "increasing" else -1.0
        return float(self.z_start_um + sign * layer_index * self.z_step_um)

    def validate_basic(self) -> list[str]:
        errors: list[str] = []
        if self.frame_width_um <= 0:
            errors.append("Physical frame width must be greater than zero.")
        if self.z_step_um <= 0:
            errors.append("Layer spacing must be greater than zero.")
        if self.direction not in {"increasing", "decreasing"}:
            errors.append("Direction must be 'increasing' or 'decreasing'.")
        if self.source_type not in {SOURCE_RAW_TXT, SOURCE_LEGACY_IMAGES}:
            errors.append("Source type must be raw_txt or legacy_images.")
        if not 0 <= self.preview_low_percentile < self.preview_high_percentile <= 100:
            errors.append("Preview percentiles must satisfy 0 <= low < high <= 100.")
        if not self.input_dir:
            errors.append("Input directory is required.")
        if not self.output_dir:
            errors.append("Output directory is required.")
        if self.input_dir and self.output_dir:
            input_path = Path(self.input_dir).expanduser().resolve()
            output_path = Path(self.output_dir).expanduser().resolve()
            if input_path == output_path:
                errors.append("Input and output directories must not be the same.")
            elif input_path in output_path.parents:
                errors.append("Output directory must not be inside the input directory.")
        errors.extend(self.processing.validate())
        return errors

    def refresh_layer_z(self) -> None:
        for layer in self.layers:
            layer.z_um = self.z_for_index(layer.layer_index)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scientific_warning"] = SCIENTIFIC_WARNING
        data["coordinate_rule"] = {
            "increasing": "z_i = z0 + layer_index * step",
            "decreasing": "z_i = z0 - layer_index * step",
            "internal_unit": "um",
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeriesConfig":
        clean = dict(data)
        clean.pop("scientific_warning", None)
        clean.pop("coordinate_rule", None)
        if "source_type" not in clean:
            legacy_extensions = {".png", ".tif", ".tiff"}
            filenames = [str(item.get("filename", "")) for item in clean.get("layers", [])]
            clean["source_type"] = (
                SOURCE_LEGACY_IMAGES
                if filenames and all(Path(name).suffix.lower() in legacy_extensions for name in filenames)
                else SOURCE_RAW_TXT
            )
        clean["processing"] = ProcessingParameters(**clean.get("processing", {}))
        clean["layers"] = [LayerMetadata.from_dict(item) for item in clean.get("layers", [])]
        return cls(**clean)


@dataclass
class PreflightReport:
    layers: list[LayerMetadata] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_numbers: list[int] = field(default_factory=list)
    image_size: tuple[int, int] | None = None
    common_matrix_shape: tuple[int, int] | None = None
    found_files: int = 0
    valid_files: int = 0
    invalid_files: int = 0
    import_errors: list[FrameError] = field(default_factory=list)
    txt_format_description: dict[str, Any] = field(default_factory=dict)
    requires_order_confirmation: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class FrameError:
    filename: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class RunOutcome:
    run_dir: str
    summaries: list[dict[str, Any]]
    walls: list[dict[str, Any]]
    domains: list[dict[str, Any]]
    errors: list[FrameError]
    qc_paths: dict[str, str]
    plot_paths: list[str]
    cancelled: bool = False
    import_errors: list[FrameError] = field(default_factory=list)
    preview_paths: dict[str, str] = field(default_factory=dict)
    tiff_stack_path: str | None = None
    imported_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.summaries)

    @property
    def ok(self) -> int:
        return sum(row.get("status") == "OK" for row in self.summaries)

    @property
    def check(self) -> int:
        return sum(row.get("status") == "CHECK" for row in self.summaries)
