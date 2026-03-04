"""
load_excel.py

Read baseline_inputs.xlsx (multi-sheet) and return a nested dict for one case_id.

This version is BACKWARD COMPATIBLE:
- If newer Cold Plate columns are missing, defaults are applied.
- Keeps your existing required sheets + column checks.

Usage:
    from pathlib import Path
    from load_excel import Paths, load_case

    data = load_case(Paths(baseline_xlsx=Path("baseline_inputs.xlsx")), case_id="BASE")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_SHEETS_BASELINE = [
    "MISSION", "LOADS", "TEMP_TARGETS", "FLUID",
    "COLD_PLATE", "LINES_FITTINGS", "PUMP", "RADIATOR"
]

# --- Defaults for new Cold Plate features (safe + non-breaking) ---
COLDPLATE_DEFAULTS: dict[str, Any] = {
    # Topology / distribution
    "flow_mode": "parallel",               # "parallel" or "serpentine"
    "n_passes_serpentine": 1,              # used only for serpentine
    "flow_split_model": "ideal",           # "ideal" or "simple_maldistribution"
    "maldistribution_factor": 1.0,         # >= 1.0

    # Spreading resistance inputs (mm in Excel; conversions happen elsewhere)
    "spreading_model": "none",             # "none" or "simple"
    "source_w_mm": 0.0,
    "source_l_mm": 0.0,
    "sink_w_mm": 0.0,
    "sink_l_mm": 0.0,
    "source_to_channels_t_mm": 0.0,        # 0 => default to base_thickness_mm in your model layer

    # Recommended physics knobs (if you add them to Excel)
    # If not present, these defaults prevent crashes but may make results less meaningful.
    "K_minor_total": 0.0,                  # additional minor losses across cold plate
    "interface_h_W_m2K": 5000.0,           # rough placeholder for TIM/contact (tune this!)
    "interface_area_mm2": 0.0,             # IMPORTANT: set this in Excel for meaningful temps
    "plate_k_W_mK": float("nan"),          # can be set from material mapping elsewhere if desired
}

# Optional: define required columns for specific sheets (beyond case_id)
# Keep minimal to avoid breaking existing files.
REQUIRED_COLS_BY_SHEET: dict[str, list[str]] = {
    "LOADS": ["case_id", "Qin_W"],
    "COLD_PLATE": ["case_id"],  # we apply defaults for missing optional cols
    "MISSION": ["case_id"],
    "TEMP_TARGETS": ["case_id"],
    "FLUID": ["case_id"],
    "LINES_FITTINGS": ["case_id"],
    "PUMP": ["case_id"],
    "RADIATOR": ["case_id"],
}


@dataclass(frozen=True)
class Paths:
    baseline_xlsx: Path
    fluids_xlsx: Path | None = None


def _require_columns(df: pd.DataFrame, required: list[str], sheet: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"[{sheet}] Missing columns: {missing}")


def _apply_defaults(row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Fill missing/NaN keys in row with defaults."""
    out = dict(row)
    for k, v in defaults.items():
        if k not in out or pd.isna(out[k]):
            out[k] = v
    return out


def _norm_lower(x: Any, default: str) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return default
    return str(x).strip().lower()


def _to_int(x: Any, default: int) -> int:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return default
        return int(x)
    except Exception:
        return default


def _to_float(x: Any, default: float) -> float:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return default
        return float(x)
    except Exception:
        return default


def load_case(paths: Paths, case_id: str = "BASE") -> dict[str, Any]:
    """
    Returns a nested dict with:
      mission, loads, temp_targets, fluid, coldplate, lines, pump, radiator, accumulator(optional)

    Notes:
    - COLD_PLATE sheet is upgraded with defaults for new columns.
    - FLUID_LIBRARY merge remains optional if fluids_xlsx is provided and FLUID has fluid_id.
    """
    base = pd.read_excel(paths.baseline_xlsx, sheet_name=None, engine="openpyxl")

    # --- Check required sheets ---
    missing_sheets = [s for s in REQUIRED_SHEETS_BASELINE if s not in base]
    if missing_sheets:
        raise ValueError(f"baseline_inputs.xlsx missing sheets: {missing_sheets}")

    # --- Helper to get one row by case_id ---
    def one_row(sheet: str) -> pd.Series:
        df = base[sheet]
        # enforce minimal per-sheet required columns
        req = REQUIRED_COLS_BY_SHEET.get(sheet, ["case_id"])
        _require_columns(df, req, sheet)

        sel = df[df["case_id"] == case_id]
        if sel.empty:
            raise ValueError(f"[{sheet}] No rows found for case_id='{case_id}'")
        return sel.iloc[0]

    mission = one_row("MISSION").to_dict()
    temp_targets = one_row("TEMP_TARGETS").to_dict()
    fluid_row = one_row("FLUID").to_dict()

    # --- Cold plate: apply defaults + normalize new fields ---
    coldplate_raw = one_row("COLD_PLATE").to_dict()
    coldplate = _apply_defaults(coldplate_raw, COLDPLATE_DEFAULTS)

    # Normalize string modes
    coldplate["flow_mode"] = _norm_lower(coldplate.get("flow_mode"), "parallel")
    coldplate["flow_split_model"] = _norm_lower(coldplate.get("flow_split_model"), "ideal")
    coldplate["spreading_model"] = _norm_lower(coldplate.get("spreading_model"), "none")

    # Cast + clamp numeric fields
    coldplate["n_passes_serpentine"] = max(_to_int(coldplate.get("n_passes_serpentine"), 1), 1)
    coldplate["maldistribution_factor"] = max(_to_float(coldplate.get("maldistribution_factor"), 1.0), 1.0)

    # Optional numeric conversions / safety casting
    for k in [
        "source_w_mm", "source_l_mm", "sink_w_mm", "sink_l_mm", "source_to_channels_t_mm",
        "K_minor_total", "interface_h_W_m2K", "interface_area_mm2", "plate_k_W_mK"
    ]:
        if k in coldplate:
            coldplate[k] = _to_float(coldplate.get(k), COLDPLATE_DEFAULTS.get(k, 0.0))

    # Normalize topology keywords
    if coldplate["flow_mode"] not in ("parallel", "serpentine"):
        raise ValueError(f"[COLD_PLATE] flow_mode must be 'parallel' or 'serpentine' (got '{coldplate['flow_mode']}')")

    if coldplate["flow_split_model"] not in ("ideal", "simple_maldistribution"):
        raise ValueError(
            f"[COLD_PLATE] flow_split_model must be 'ideal' or 'simple_maldistribution' "
            f"(got '{coldplate['flow_split_model']}')"
        )

    if coldplate["spreading_model"] not in ("none", "simple"):
        raise ValueError(f"[COLD_PLATE] spreading_model must be 'none' or 'simple' (got '{coldplate['spreading_model']}')")

    lines = one_row("LINES_FITTINGS").to_dict()
    pump = one_row("PUMP").to_dict()
    radiator = one_row("RADIATOR").to_dict()

    # --- Loads: multiple rows per case_id ---
    loads_df = base["LOADS"]
    _require_columns(loads_df, REQUIRED_COLS_BY_SHEET["LOADS"], "LOADS")
    loads = loads_df[loads_df["case_id"] == case_id].copy()
    if loads.empty:
        raise ValueError(f"[LOADS] No loads found for case_id='{case_id}'")

    # --- Optional: merge fluid properties from fluids.xlsx library ---
    if paths.fluids_xlsx and "fluid_id" in fluid_row and pd.notna(fluid_row["fluid_id"]):
        lib = pd.read_excel(paths.fluids_xlsx, sheet_name="FLUID_LIBRARY", engine="openpyxl")
        _require_columns(lib, ["fluid_id"], "FLUID_LIBRARY")
        match = lib[lib["fluid_id"] == fluid_row["fluid_id"]]
        if match.empty:
            raise ValueError(f"[FLUID_LIBRARY] fluid_id='{fluid_row['fluid_id']}' not found")
        librow = match.iloc[0].to_dict()
        fluid_row = {**fluid_row, **librow}

    return {
        "case_id": case_id,
        "mission": mission,
        "temp_targets": temp_targets,
        "loads": loads.to_dict(orient="records"),
        "fluid": fluid_row,
        "coldplate": coldplate,
        "lines": lines,
        "pump": pump,
        "radiator": radiator,
        "accumulator": base.get("ACCUMULATOR", pd.DataFrame()).to_dict(orient="records"),
    }