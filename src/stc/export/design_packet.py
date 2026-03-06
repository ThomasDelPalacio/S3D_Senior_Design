# src/stc/export/design_packet.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import json
import math


def _to_builtin(x: Any) -> Any:
    """Convert dataclasses + nested objects to JSON-friendly builtins."""
    if is_dataclass(x):
        return asdict(x)
    if isinstance(x, dict):
        return {str(k): _to_builtin(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_to_builtin(v) for v in x]
    if hasattr(x, "__dict__"):
        return _to_builtin(vars(x))
    # handle numpy/pandas scalar-like
    try:
        if hasattr(x, "item"):
            return x.item()
    except Exception:
        pass
    return x


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isfinite(v):
            return f"{v:.{nd}f}"
        return str(v)
    return str(v)


def _md_table(rows: list[tuple[str, Any]], nd: int = 3) -> str:
    out = ["| Parameter | Value |", "|---|---:|"]
    for k, v in rows:
        out.append(f"| {k} | {_fmt(v, nd)} |")
    return "\n".join(out)


def build_design_packet(
    *,
    case: Dict[str, Any],
    res: Any,
    source_inputs_path: str | None = None,
    version: str = "stc-dev",
) -> Dict[str, Any]:
    """
    case: dict from load_case(...) (already post-defaults for coldplate)
    res: SolveResult dataclass from solve_case(...)
    """
    cid = str(case.get("case_id", getattr(res, "case_id", "CASE")))

    # Pull common numbers (robust)
    Qin = float(getattr(res, "Qin_total_W", float("nan")))
    m_dot = float(getattr(res, "m_dot_kg_s", float("nan")))
    dp_total_kPa = float(getattr(res, "dp_total_kPa", float("nan")))

    fluid = case.get("fluid", {})
    rho = float(fluid.get("rho_kg_m3", float("nan")))
    cp = float(fluid.get("cp_J_kgK", float("nan")))

    # Flow conversions
    V_dot_m3_s = float(getattr(getattr(res, "coldplate", object()), "V_dot_m3_s", float("nan")))
    V_dot_L_min = V_dot_m3_s * 60000.0 if math.isfinite(V_dot_m3_s) else float("nan")

    # Coolant deltaT from energy balance
    coolant_dT_C = Qin / (m_dot * cp) if (m_dot > 0 and cp > 0 and math.isfinite(Qin)) else float("nan")

    # Pump head estimate
    g = 9.80665
    pump_head_m = (dp_total_kPa * 1000.0) / (rho * g) if (rho > 0 and math.isfinite(dp_total_kPa)) else float("nan")

    # Coldplate “CAD-ish” geometry (from your coldplate inputs inside solver)
    cp_case = case.get("coldplate", {})
    # these are in mm in Excel for your case dict
    base_thickness_mm = float(cp_case.get("base_thickness_mm", float("nan")))
    channel_count = int(cp_case.get("channel_count", cp_case.get("channel_count", 0)) or 0)
    channel_length_mm = float(cp_case.get("channel_length_mm", float("nan")))
    w_mm_used = float(cp_case.get("channel_w_mm", cp_case.get("w_mm_min", float("nan"))))
    h_mm_used = float(cp_case.get("channel_h_mm", cp_case.get("h_mm_min", float("nan"))))

    # Hydraulic diameter (mm) using your chosen w/h
    Dh_mm = float("nan")
    if w_mm_used > 0 and h_mm_used > 0:
        Dh_mm = (2.0 * w_mm_used * h_mm_used) / (w_mm_used + h_mm_used)

    # Radiator results
    rad = getattr(res, "radiator", None)
    A_req = float(getattr(rad, "A_req_m2", float("nan"))) if rad else float("nan")
    A_used = float(getattr(rad, "A_used_m2", float("nan"))) if rad else float("nan")
    Q_rej = float(getattr(rad, "Q_reject_W", float("nan"))) if rad else float("nan")
    T_rad_K = float(getattr(rad, "T_rad_K", float("nan"))) if rad else float("nan")
    feasible = bool(getattr(rad, "feasible_with_Amax", False)) if rad else False

    # Simple packaging suggestion: square panel with area = A_used (or A_req if used missing)
    A_for_dims = A_used if (math.isfinite(A_used) and A_used > 0) else A_req
    side_m = math.sqrt(A_for_dims) if (math.isfinite(A_for_dims) and A_for_dims > 0) else float("nan")

    # Checks
    pump = getattr(res, "pump", None)
    pump_ok = bool(getattr(pump, "within_power_limit", False)) if pump else False

    packet = {
        "meta": {
            "case_id": cid,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "source_inputs": source_inputs_path,
        },
        "inputs_used": _to_builtin(case),
        "outputs": _to_builtin(res),
        "derived_design_params": {
            "Qin_total_W": Qin,
            "m_dot_kg_s": m_dot,
            "V_dot_L_min": V_dot_L_min,
            "dp_total_kPa": dp_total_kPa,
            "coolant_dT_C": coolant_dT_C,
            "pump_required_head_m": pump_head_m,
            "coldplate_geometry": {
                "base_thickness_mm": base_thickness_mm,
                "channel_count": channel_count,
                "channel_length_mm": channel_length_mm,
                "channel_w_mm_used": w_mm_used,
                "channel_h_mm_used": h_mm_used,
                "Dh_mm": Dh_mm,
            },
            "radiator_sizing": {
                "T_rad_K": T_rad_K,
                "A_req_m2": A_req,
                "A_used_m2": A_used,
                "Q_reject_W": Q_rej,
                "suggested_panel_dims_m": {"w": side_m, "h": side_m},
            },
        },
        "checks": {
            "radiator_feasible": feasible,
            "pump_within_power_limit": pump_ok,
        },
    }
    return packet


def write_design_packet(packet: Dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cid = packet["meta"]["case_id"]

    json_path = out_dir / f"{cid}_design_packet.json"
    md_path = out_dir / f"{cid}_design_packet.md"

    json_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")

    d = packet["derived_design_params"]
    chk = packet["checks"]
    cp = packet["outputs"].get("coldplate", {})
    ln = packet["outputs"].get("lines", {})
    pump = packet["outputs"].get("pump", {})
    rad = packet["outputs"].get("radiator", {})

    md = []
    md.append(f"# Design Packet — {cid}\n")

    md.append("## Key Outputs\n")
    md.append(_md_table([
        ("Qin_total (W)", d.get("Qin_total_W")),
        ("m_dot (kg/s)", d.get("m_dot_kg_s")),
        ("V_dot (L/min)", d.get("V_dot_L_min")),
        ("dp_total (kPa)", d.get("dp_total_kPa")),
        ("coolant ΔT (°C)", d.get("coolant_dT_C")),
        ("pump head (m)", d.get("pump_required_head_m")),
    ], nd=3))

    md.append("\n## Cold Plate (limiting channel)\n")
    md.append(_md_table([
        ("v (m/s)", cp.get("v_m_s")),
        ("Re", cp.get("Re")),
        ("Nu", cp.get("Nu")),
        ("h (W/m²-K)", cp.get("h_W_m2K")),
        ("dp (kPa)", cp.get("dp_kPa")),
        ("R_total (K/W)", cp.get("R_total_K_W")),
    ], nd=3))

    md.append("\n## Lines\n")
    md.append(_md_table([
        ("v (m/s)", ln.get("v_m_s")),
        ("Re", ln.get("Re")),
        ("f", ln.get("f")),
        ("dp_fric (kPa)", ln.get("dp_fric_kPa")),
        ("dp_minor (kPa)", ln.get("dp_minor_kPa")),
        ("dp_total (kPa)", ln.get("dp_kPa")),
    ], nd=3))

    md.append("\n## Pump\n")
    md.append(_md_table([
        ("dp required (kPa)", pump.get("dp_kPa_required")),
        ("P_hyd (W)", pump.get("P_hyd_W")),
        ("P_elec (W)", pump.get("P_elec_W")),
        ("within power limit?", chk.get("pump_within_power_limit")),
    ], nd=3))

    md.append("\n## Radiator\n")
    md.append(_md_table([
        ("T_rad (K)", rad.get("T_rad_K")),
        ("A required (m²)", rad.get("A_req_m2")),
        ("A used (m²)", rad.get("A_used_m2")),
        ("Q rejected (W)", rad.get("Q_reject_W")),
        ("feasible with Amax?", chk.get("radiator_feasible")),
        ("suggested panel dims (m)", d.get("radiator_sizing", {}).get("suggested_panel_dims_m")),
    ], nd=3))

    md.append("\n## CAD-driving geometry (from inputs)\n")
    md.append(_md_table([
        ("base thickness (mm)", d.get("coldplate_geometry", {}).get("base_thickness_mm")),
        ("channel count", d.get("coldplate_geometry", {}).get("channel_count")),
        ("channel length (mm)", d.get("coldplate_geometry", {}).get("channel_length_mm")),
        ("channel w used (mm)", d.get("coldplate_geometry", {}).get("channel_w_mm_used")),
        ("channel h used (mm)", d.get("coldplate_geometry", {}).get("channel_h_mm_used")),
        ("Dh (mm)", d.get("coldplate_geometry", {}).get("Dh_mm")),
    ], nd=3))

    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path, md_path