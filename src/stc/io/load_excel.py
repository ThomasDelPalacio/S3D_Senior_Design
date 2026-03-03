from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd

REQUIRED_SHEETS_BASELINE = [
    "MISSION", "LOADS", "TEMP_TARGETS", "FLUID",
    "COLD_PLATE", "LINES_FITTINGS", "PUMP", "RADIATOR"
]

@dataclass(frozen=True)
class Paths:
    baseline_xlsx: Path
    fluids_xlsx: Path | None = None

def _require_columns(df: pd.DataFrame, required: list[str], sheet: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"[{sheet}] Missing columns: {missing}")

def load_case(paths: Paths, case_id: str = "BASE") -> dict:
    """
    Returns a nested dict with:
      mission, loads, temp_targets, fluid, coldplate, lines, pump, radiator, accumulator(optional)
    """
    base = pd.read_excel(paths.baseline_xlsx, sheet_name=None, engine="openpyxl")

    # --- Check required sheets ---
    missing_sheets = [s for s in REQUIRED_SHEETS_BASELINE if s not in base]
    if missing_sheets:
        raise ValueError(f"baseline_inputs.xlsx missing sheets: {missing_sheets}")

    # --- Read and filter by case_id ---
    def one_row(sheet: str) -> pd.Series:
        df = base[sheet]
        _require_columns(df, ["case_id"], sheet)
        sel = df[df["case_id"] == case_id]
        if sel.empty:
            raise ValueError(f"[{sheet}] No rows found for case_id='{case_id}'")
        return sel.iloc[0]

    mission = one_row("MISSION").to_dict()
    temp_targets = one_row("TEMP_TARGETS").to_dict()
    fluid_row = one_row("FLUID").to_dict()
    coldplate = one_row("COLD_PLATE").to_dict()
    lines = one_row("LINES_FITTINGS").to_dict()
    pump = one_row("PUMP").to_dict()
    radiator = one_row("RADIATOR").to_dict()

    loads_df = base["LOADS"]
    _require_columns(loads_df, ["case_id", "Qin_W"], "LOADS")
    loads = loads_df[loads_df["case_id"] == case_id].copy()
    if loads.empty:
        raise ValueError(f"[LOADS] No loads found for case_id='{case_id}'")

    # --- If you want fluids.xlsx as a library, merge here (optional) ---
    # If baseline FLUID has 'fluid_id', you can look it up in fluids.xlsx
    if paths.fluids_xlsx and "fluid_id" in fluid_row and pd.notna(fluid_row["fluid_id"]):
        lib = pd.read_excel(paths.fluids_xlsx, sheet_name="FLUID_LIBRARY", engine="openpyxl")
        _require_columns(lib, ["fluid_id"], "FLUID_LIBRARY")
        match = lib[lib["fluid_id"] == fluid_row["fluid_id"]]
        if match.empty:
            raise ValueError(f"[FLUID_LIBRARY] fluid_id='{fluid_row['fluid_id']}' not found")
        # overwrite/augment constants
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
        # optional:
        "accumulator": base.get("ACCUMULATOR", pd.DataFrame()).to_dict(orient="records"),
    }