# path | src/stc/components/coldplate.py
from __future__ import annotations
from dataclasses import dataclass
import math

##################################################
##      Helper Functions for Coldplate Cals     ##
##################################################

def hydraulic_diameter_rect(w_m: float, h_m: float):
    A = w_m * h_m
    P = 2.0 * (w_m + h_m)
    return 4.0 * A / max(P, 1e-12)

def reynolds(rho: float, v: float, Dh: float, mu: float):
    return rho * v * Dh / max(mu, 1e-12)

def prandtl(cp: float, mu: float, k: float):
    return cp * mu / max(k, 1e-12)

def nusselt_laminar_rect(aspect: float) -> float:
    a = max(min(aspect, 1.0), 1e-6)
    return 8.235 * (1 - 2.0421*a + 3.0853*a*a - 2.4765*a**3 + 1.0578*a**4 - 0.1861*a**5)

def friction_factor_laminar(Re: float, aspect: float):
    a = max(min(aspect, 1.0), 1e-6)
    Po = 24.0 * (1 - 1.3553*a + 1.9467*a*a - 1.7012*a**3 + 0.9564*a**4 - 0.2537*a**5)
    return Po / max(Re, 1e-12)

def friction_factor_turbulent(Re: float, rel_rough: float):
    Re = max(Re, 1e-12)
    rr = max(rel_rough, 1e-12)
    return 0.25 / (math.log10(rr/3.7 + 5.74/(Re**0.9)))**2

def nusselt_turbulent_dittus_boelter(Re: float, Pr: float, heating: bool = True):
    n = 0.4 if heating else 0.3
    return 0.023 * (Re**0.8) * (Pr**n)

def spreading_resistance_simple(
    k_W_mK: float,
    t_m: float,
    source_w_m: float,
    source_l_m: float,
    sink_w_m: float,
    sink_l_m: float,            ):
    """
    Simple spreading-resistance approximation.

    NOT a high-fidelity Yovanovich model.
    It's a conservative estimate that increases resistance when
    the heat source area is much smaller than the sink area.

    R_spread ≈ (t / (k * A_source)) * (phi - 1)
    where phi = sqrt(A_sink / A_source), phi >= 1.

    If A_sink == A_source => R_spread = 0.
    """
    A_src = max(source_w_m * source_l_m, 1e-12)
    A_snk = max(sink_w_m * sink_l_m, 1e-12)

    phi = math.sqrt(max(A_snk / A_src, 1.0))
    if phi <= 1.0:
        return 0.0

    R_1D_src = t_m / max(k_W_mK * A_src, 1e-12)
    return R_1D_src * (phi - 1.0)

##################################################
##              Data Containers                 ##
##################################################

@dataclass(frozen=True)
class ColdPlateInputs:
    # Channel geometry (meters)
    channel_w_m: float
    channel_h_m: float
    channel_length_m: float
    n_channels: int

    # Losses
    K_minor_total: float   # across cold plate path: entries, turns, manifolds, etc.
    roughness_m: float

    # Thermal conduction/contact (prelim)
    base_thickness_m: float
    plate_k_W_mK: float
    interface_h_W_m2K: float
    interface_area_m2: float

    # Topology + distribution
    flow_mode: str = "parallel"  # "parallel" or "serpentine"
    n_passes_serpentine: int = 1 # used only in serpentine mode
    flow_split_model: str = "ideal"  # "ideal" or "simple_maldistribution"
    maldistribution_factor: float = 1.0  # >= 1.0, only used in parallel mode

    # Spreading resistance
    spreading_model: str = "none"  # "none" or "simple"
    source_w_m: float = 0.0
    source_l_m: float = 0.0
    sink_w_m: float = 0.0
    sink_l_m: float = 0.0
    source_to_channels_t_m: float = 0.0  # if 0, assume = base_thickness_m

@dataclass(frozen=True)
class ColdPlateResult:
    m_dot_kg_s: float
    V_dot_m3_s: float

    # Limiting path/channel values
    v_m_s: float
    Re: float
    Pr: float
    Nu: float
    h_W_m2K: float

    dp_kPa: float
    dT_coolant_K: float

    # Thermal resistances
    R_conv_K_W: float
    R_plate_1D_K_W: float
    R_spread_K_W: float
    R_contact_K_W: float
    R_total_K_W: float

    # Helpful debug
    effective_n_channels: int
    limiting_m_dot_channel_kg_s: float
    topology: str

##################################################
##              ColdPlate Model                 ##
##################################################

class ColdPlate:
    """
    Cold plate model:
    - flow_mode: parallel channels OR serpentine single-path
    - flow_split_model: ideal OR simple maldistribution penalty (parallel only)
    - optional spreading resistance (simple) to penalize small heat source area

    Note:
    - dp and h are computed based on the "limiting" channel/path (conservative for parallel
      when maldistribution is enabled).
    - dT_coolant is computed on total m_dot (overall energy balance).
    """

    def __init__(self, inp: ColdPlateInputs):
        self.inp = inp

    def evaluate(self, Qin_W: float, m_dot_kg_s: float, rho: float, cp: float, mu: float, k: float):
        i = self.inp

        # Determine topology behavior
        flow_mode = (i.flow_mode or "parallel").strip().lower()
        if flow_mode not in ("parallel", "serpentine"):
            raise ValueError(f"flow_mode must be 'parallel' or 'serpentine', got: {i.flow_mode}")

        # Effective channels and total flow path length
        if flow_mode == "parallel":
            n_eff = max(int(i.n_channels), 1)
            L_eff = i.channel_length_m
        else:
            n_eff = 1
            L_eff = i.channel_length_m * max(int(i.n_passes_serpentine), 1)

        # Flow split / limiting channel logic
        if flow_mode == "parallel":
            split_model = (i.flow_split_model or "ideal").strip().lower()
            if split_model not in ("ideal", "simple_maldistribution"):
                raise ValueError(f"flow_split_model must be 'ideal' or 'simple_maldistribution', got: {i.flow_split_model}")

            if split_model == "ideal":
                m_dot_ch_lim = m_dot_kg_s / n_eff
            else:
                fmd = max(i.maldistribution_factor, 1.0)
                m_dot_ch_lim = m_dot_kg_s / (n_eff * fmd)
        else:
            m_dot_ch_lim = m_dot_kg_s

        V_dot = m_dot_kg_s / max(rho, 1e-12)
        V_dot_ch_lim = m_dot_ch_lim / max(rho, 1e-12)

        A_ch = i.channel_w_m * i.channel_h_m
        v_lim = V_dot_ch_lim / max(A_ch, 1e-12)

        Dh = hydraulic_diameter_rect(i.channel_w_m, i.channel_h_m)
        Re = reynolds(rho, v_lim, Dh, mu)
        Pr = prandtl(cp, mu, k)

        aspect = min(i.channel_w_m, i.channel_h_m) / max(i.channel_w_m, i.channel_h_m)

        # Heat transfer + friction
        if Re < 2300:
            Nu = nusselt_laminar_rect(aspect)
            f = friction_factor_laminar(Re, aspect)
        else:
            Nu = nusselt_turbulent_dittus_boelter(Re, Pr, heating=True)
            rel_rough = i.roughness_m / max(Dh, 1e-12)
            f = friction_factor_turbulent(Re, rel_rough)

        h = Nu * k / max(Dh, 1e-12)

        # Pressure drop based on limiting path velocity
        dp_fric = f * (L_eff / max(Dh, 1e-12)) * (rho * v_lim * v_lim / 2.0)
        dp_minor = i.K_minor_total * (rho * v_lim * v_lim / 2.0)
        dp_total = dp_fric + dp_minor  # Pa

        # Coolant bulk deltaT across the cold plate
        dT_coolant = Qin_W / max(m_dot_kg_s * cp, 1e-12)

        # Convective area
        P_wet = 2.0 * (i.channel_w_m + i.channel_h_m)
        if flow_mode == "parallel":
            A_conv = P_wet * i.channel_length_m * max(int(i.n_channels), 1)
        else:
            A_conv = P_wet * L_eff

        R_conv = 1.0 / max(h * A_conv, 1e-12)

        # Plate conduction (1D through thickness under interface area)
        R_plate_1D = i.base_thickness_m / max(i.plate_k_W_mK * i.interface_area_m2, 1e-12)

        # Spreading resistance 
        spread_model = (i.spreading_model or "none").strip().lower()
        if spread_model == "simple":
            t_spread = i.source_to_channels_t_m if i.source_to_channels_t_m > 0 else i.base_thickness_m
            if min(i.source_w_m, i.source_l_m, i.sink_w_m, i.sink_l_m) > 0:
                R_spread = spreading_resistance_simple(
                    k_W_mK=i.plate_k_W_mK,
                    t_m=t_spread,
                    source_w_m=i.source_w_m,
                    source_l_m=i.source_l_m,
                    sink_w_m=i.sink_w_m,
                    sink_l_m=i.sink_l_m,
                )
            else:
                R_spread = 0.0
        else:
            R_spread = 0.0

        # Contact/TIM resistance
        R_contact = 1.0 / max(i.interface_h_W_m2K * i.interface_area_m2, 1e-12)

        R_total = R_contact + R_plate_1D + R_spread + R_conv

        return ColdPlateResult(
            m_dot_kg_s=m_dot_kg_s,
            V_dot_m3_s=V_dot,
            v_m_s=v_lim,
            Re=Re,
            Pr=Pr,
            Nu=Nu,
            h_W_m2K=h,
            dp_kPa=dp_total / 1000.0,
            dT_coolant_K=dT_coolant,
            R_conv_K_W=R_conv,
            R_plate_1D_K_W=R_plate_1D,
            R_spread_K_W=R_spread,
            R_contact_K_W=R_contact,
            R_total_K_W=R_total,
            effective_n_channels=n_eff,
            limiting_m_dot_channel_kg_s=m_dot_ch_lim,
            topology=flow_mode,
        )