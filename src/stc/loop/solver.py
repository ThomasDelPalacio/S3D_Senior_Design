# src/stc/loop/solver.py
from __future__ import annotations
import math
from dataclasses import dataclass
from stc.components import (
    ColdPlate, ColdPlateInputs,
    Lines, LinesInputs,
    Pump, PumpInputs,
    Radiator, RadiatorInputs,
    Accumulator, AccumulatorInputs,
)

##################################################
##              Data Containers                 ##
##################################################

@dataclass(frozen=True)
class SolveResult:
    case_id: str
    Qin_total_W: float
    m_dot_kg_s: float
    dp_total_kPa: float
    coldplate: object
    lines: object
    pump: object
    radiator: object
    accumulator: object | None = None

##################################################
##              Solver Function                 ##
##################################################

def solve_case(case: dict):
    """
    Solve one steady-state mechanically pumped single-phase loop case.
    `case` is the dict produced by stc.io.load_excel.load_case().
    """
    cid = str(case["case_id"])

    # Total heat input (sum loads * duty_cycle)
    Qin_total = 0.0
    for r in case["loads"]:
        Qin_total += float(r["Qin_W"]) * float(r.get("duty_cycle", 1.0))

    # Fluid properties (constants for prelim sizing)
    f = case["fluid"]
    rho = float(f["rho_kg_m3"])
    cp = float(f["cp_J_kgK"])
    mu = float(f["mu_Pa_s"])
    k  = float(f["k_W_mK"])
    beta = float(f.get("beta_1_K", 0.0))

    # Temperature targets 
    tt = case["temp_targets"]
    dT_loop = float(tt["dT_loop_C"])  # K increment
    T_rad_C = float(tt.get("T_radiator_guess_C", 35.0))
    T_sink_K = float(case["mission"].get("sink_temp_K", 3.0))

    # Mass flow from energy balance: m_dot = Q/(cp*dT)
    m_dot = Qin_total / max(cp * dT_loop, 1e-12)

    # Cold plate inputs
    cp_row = case["coldplate"]

    # Choose channel size (mm -> m). Default uses min bounds unless explicit fields exist.
    if "channel_w_mm" in cp_row and cp_row["channel_w_mm"] == cp_row["channel_w_mm"]:
        w_mm = float(cp_row["channel_w_mm"])
    else:
        w_mm = float(cp_row["w_mm_min"])

    if "channel_h_mm" in cp_row and cp_row["channel_h_mm"] == cp_row["channel_h_mm"]:
        h_mm = float(cp_row["channel_h_mm"])
    else:
        h_mm = float(cp_row["h_mm_min"])

    w_m = w_mm / 1000.0
    h_m = h_mm / 1000.0

    # Interface area (prefer cold plate sheet)
    if (
        "interface_area_mm2" in cp_row
        and cp_row["interface_area_mm2"] == cp_row["interface_area_mm2"]
        and float(cp_row["interface_area_mm2"]) > 0
    ):
        interface_area_m2 = float(cp_row["interface_area_mm2"]) * 1e-6
    else:
        # fallback: sum all load interface areas if present
        interface_area_m2 = 0.0
        for r in case["loads"]:
            interface_area_m2 += float(r.get("interface_area_m2", 0.0))
        if interface_area_m2 <= 0:
            interface_area_m2 = 0.0025

    # Fotprint-driven channel count and channel length
    gpu_count = int(cp_row.get("gpu_count", 0) or 0)
    gpu_w_mm = float(cp_row.get("gpu_w_mm", 0.0) or 0.0)
    gpu_l_mm = float(cp_row.get("gpu_l_mm", 0.0) or 0.0)
    gpu_gap_mm = float(cp_row.get("gpu_gap_mm", 0.0) or 0.0)
    arrangement = str(cp_row.get("gpu_arrangement", "side_by_side")).strip().lower()

    edge_margin_mm = float(cp_row.get("edge_margin_mm", 0.0) or 0.0)
    manifold_len_mm = float(cp_row.get("manifold_length_mm", 0.0) or 0.0)
    pitch_mm = float(cp_row.get("channel_pitch_mm", 0.0) or 0.0)
    channels_per_gpu_override = int(cp_row.get("channels_per_gpu", 0) or 0)

    # Defaults from sheet if footprint model not active
    channel_count = int(cp_row.get("channel_count", 1))
    channel_length_mm = float(cp_row.get("channel_length_mm", 0.0))

    # Activate footprint sizing only when gpu_count and gpu dims are provided
    if gpu_count > 0 and gpu_w_mm > 0 and gpu_l_mm > 0:
        # Channel run length tied to GPU length + margins (no manifolds inside channel length)
        channel_length_mm = gpu_l_mm + 2.0 * edge_margin_mm

        # Compute channels_per_gpu
        if channels_per_gpu_override > 0:
            channels_per_gpu = channels_per_gpu_override
        else:
            # If pitch is provided, compute based on usable width
            if pitch_mm > 0:
                usable_w_mm = max(gpu_w_mm - 2.0 * edge_margin_mm, 0.0)
                channels_per_gpu = int(math.floor(usable_w_mm / pitch_mm)) if usable_w_mm > 0 else 0
            else:
                channels_per_gpu = 0

        # Total channel count depends on arrangement:
        # - side_by_side: two banks in parallel under each GPU => N_total = gpu_count * channels_per_gpu
        # - end_to_end: still typically two banks; keep same count model (banks repeat along length)
        if channels_per_gpu > 0:
            channel_count = max(gpu_count * channels_per_gpu, 1)

    # Convert channel length to meters for the ColdPlateInputs
    channel_length_m = channel_length_mm / 1000.0

    # New topology/distribution/spreading fields
    flow_mode = str(cp_row.get("flow_mode", "parallel")).strip().lower()
    flow_split_model = str(cp_row.get("flow_split_model", "ideal")).strip().lower()
    spreading_model = str(cp_row.get("spreading_model", "none")).strip().lower()

    n_passes_serpentine = max(int(cp_row.get("n_passes_serpentine", 1)), 1)
    maldistribution_factor = max(float(cp_row.get("maldistribution_factor", 1.0)), 1.0)

    # Spreading dims (mm -> m)
    source_w_m = float(cp_row.get("source_w_mm", 0.0)) / 1000.0
    source_l_m = float(cp_row.get("source_l_mm", 0.0)) / 1000.0
    sink_w_m   = float(cp_row.get("sink_w_mm", 0.0)) / 1000.0
    sink_l_m   = float(cp_row.get("sink_l_mm", 0.0)) / 1000.0
    source_to_channels_t_m = float(cp_row.get("source_to_channels_t_mm", 0.0)) / 1000.0

    coldplate_in = ColdPlateInputs(
        channel_w_m=w_m,
        channel_h_m=h_m,
        channel_length_m=channel_length_m,
        n_channels=channel_count,

        K_minor_total=float(cp_row.get("K_minor_total", 3.0)),
        roughness_m=float(cp_row["roughness_um"]) * 1e-6,

        base_thickness_m=float(cp_row["base_thickness_mm"]) / 1000.0,
        plate_k_W_mK=float(cp_row.get("plate_k_W_mK", 150.0)),
        interface_h_W_m2K=float(cp_row.get("interface_h_W_m2K", 5000.0)),
        interface_area_m2=interface_area_m2,

        flow_mode=flow_mode,
        n_passes_serpentine=n_passes_serpentine,
        flow_split_model=flow_split_model,
        maldistribution_factor=maldistribution_factor,

        spreading_model=spreading_model,
        source_w_m=source_w_m,
        source_l_m=source_l_m,
        sink_w_m=sink_w_m,
        sink_l_m=sink_l_m,
        source_to_channels_t_m=source_to_channels_t_m,
    )

    # Lines inputs
    ln = case["lines"]
    ID_mm = float(ln.get("line_ID_mm", ln.get("line_ID_mm_min", 4.0)))
    lines_in = LinesInputs(
        length_m=float(ln["line_length_m"]),
        ID_m=ID_mm / 1000.0,
        roughness_m=float(ln.get("roughness_m", 1e-6)),
        K_minor_total=float(ln.get("fitting_K_total", 8.0)),
        allow_dp_kPa=float(ln.get("allow_dp_kPa", 1e9)),
    )

    # Pump inputs
    pp = case["pump"]
    pump_in = PumpInputs(
        efficiency=float(pp.get("pump_efficiency", 0.25)),
        power_limit_W=float(pp["pump_power_limit_W"])
        if "pump_power_limit_W" in pp and pp["pump_power_limit_W"] == pp["pump_power_limit_W"]
        else None,
    )

    # Radiator inputs
    rd = case["radiator"]
    rad_in = RadiatorInputs(
        epsilon=float(rd["epsilon"]),
        alpha=float(rd["alpha"]),
        view_factor=float(rd.get("view_factor", 1.0)),
        A_max_m2=float(rd["A_max_m2"])
        if "A_max_m2" in rd and rd["A_max_m2"] == rd["A_max_m2"]
        else None,
        q_solar_W_m2=float(rd.get("q_solar_W_m2", 1361.0)),
        q_albedo_W_m2=float(rd.get("q_albedo_W_m2", 200.0)),
        q_ir_W_m2=float(rd.get("q_ir_W_m2", 240.0)),
    )

    # Evaluate components
    cp_model = ColdPlate(coldplate_in)
    cp_res = cp_model.evaluate(Qin_W=Qin_total, m_dot_kg_s=m_dot, rho=rho, cp=cp, mu=mu, k=k)

    lines_model = Lines(lines_in)
    ln_res = lines_model.evaluate(V_dot_m3_s=cp_res.V_dot_m3_s, rho=rho, mu=mu)

    dp_total_kPa = cp_res.dp_kPa + ln_res.dp_kPa

    pump_model = Pump(pump_in)
    pump_res = pump_model.evaluate(dp_total_kPa=dp_total_kPa, V_dot_m3_s=cp_res.V_dot_m3_s)

    rad_model = Radiator(rad_in)
    rad_res = rad_model.area_required(Q_W=Qin_total, T_rad_C=T_rad_C, T_sink_K=T_sink_K)

    # Acumulator 
    acc_res = None
    acc_list = case.get("accumulator", [])
    if isinstance(acc_list, list) and len(acc_list) > 0:
        a = acc_list[0]
        acc_in = AccumulatorInputs(
            V_liquid_cc=float(a.get("V_liquid_cc", 50.0)),
            beta_1_K=beta,
            dT_K=float(a.get("dT_K", dT_loop)),
            P_precharge_kPa=float(a.get("P_precharge_kPa", 150.0)),
            P_min_kPa=float(a.get("P_min_kPa", 120.0)),
            P_max_kPa=float(a.get("P_max_kPa", 400.0)),
            polytropic_n=float(a.get("polytropic_n", 1.2)),
        )
        acc_model = Accumulator(acc_in)
        acc_res = acc_model.size()

    return SolveResult(
        case_id=cid,
        Qin_total_W=Qin_total,
        m_dot_kg_s=m_dot,
        dp_total_kPa=dp_total_kPa,
        coldplate=cp_res,
        lines=ln_res,
        pump=pump_res,
        radiator=rad_res,
        accumulator=acc_res,
    )