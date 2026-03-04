from __future__ import annotations
from pathlib import Path
import json
from dataclasses import asdict, is_dataclass
from stc.io.load_excel import load_case, Paths
from stc.loop.solver import solve_case

##################################################
##               Run Model Here                 ##
##################################################

def _to_jsonable(x):
    if is_dataclass(x):
        return asdict(x)
    if hasattr(x, "__dict__"):
        return x.__dict__
    return x

def main():
    root = Path(__file__).resolve().parents[2]
    baseline = root / "Data" / "Inputs" / "baseline_inputs.xlsx"
    fluids = root / "Data" / "Inputs" / "fluids.xlsx"

    case = load_case(Paths(baseline_xlsx=baseline, fluids_xlsx=fluids), case_id="BASE")
    res = solve_case(case)

    out_dir = root / "Data" / "Outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_json = out_dir / f"{res.case_id}_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(_to_jsonable(res), f, indent=2)

    print("Done.")
    print(f"Qin_total_W = {res.Qin_total_W:.2f}")
    print(f"m_dot_kg_s  = {res.m_dot_kg_s:.6f}")
    print(f"dp_total_kPa= {res.dp_total_kPa:.3f}")
    print(f"pump_Pelec_W= {res.pump.P_elec_W:.3f}")
    print(f"rad_A_req_m2= {res.radiator.A_req_m2:.4f}")
    print(f"Wrote: {out_json}")

if __name__ == "__main__":
    main()