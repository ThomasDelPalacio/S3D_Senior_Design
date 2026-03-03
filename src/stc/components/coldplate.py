from __future__ import annotations
from dataclasses import dataclass
import math

# --- Helpers Functions for Coldplate Cals---

def hydraulic_diameter_rect(w_m: float, h_m: float) -> float:
    """Hydraulic diameter for rectangular duct: Dh = 4A/P."""
    A = w_m * h_m
    P = 2.0 * (w_m + h_m)
    return 4.0 * A / P

def reynolds(rho: float, v: float, Dh: float, mu: float) -> float:
    return rho * v * Dh / mu

def prandtl(cp: float, mu: float, k: float) -> float:
    return cp * mu / k

def nusselt_laminar_rect(aspect: float) -> float:
    """
    Fully-developed laminar, constant wall temperature, rectangular duct.
    Uses a common approximation for Nu based on aspect ratio (0 < aspect <= 1).
    aspect = min(w,h)/max(w,h).
    """
    # A widely used fit; good for prelim sizing
    # Nu ~ 8.235 for circular; varies with aspect ratio.
    # This polynomial fit is commonly used in heat transfer handbooks.
    a = max(min(aspect, 1.0), 1e-6)
    return 8.235 * (1 - 2.0421*a + 3.0853*a*a - 2.4765*a**3 + 1.0578*a**4 - 0.1861*a**5)

def friction_factor_laminar(Re: float, aspect: float) -> float:
    """
    Laminar f for non-circular ducts is often expressed as f = Po/Re,
    where Po (Poiseuille number) depends on aspect ratio.
    Use a common approximation for rectangular ducts.
    """
    a = max(min(aspect, 1.0), 1e-6)  # a = min/max
    # Approx Poiseuille number for rectangular ducts (fully developed laminar):
    # Po ≈ 24*(1 - 1.3553a + 1.9467a^2 - 1.7012a^3 + 0.9564a^4 - 0.2537a^5)
    Po = 24.0 * (1 - 1.3553*a + 1.9467*a*a - 1.7012*a**3 + 0.9564*a**4 - 0.2537*a**5)
    return Po / max(Re, 1e-9)

def friction_factor_turbulent(Re: float, rel_rough: float) -> float:
    """
    Turbulent friction factor using Swamee-Jain explicit approximation to Colebrook.
    Valid for turbulent flow. Good for preliminary sizing.
    """
    Re = max(Re, 1e-9)
    rr = max(rel_rough, 1e-12)
    return 0.25 / (math.log10(rr/3.7 + 5.74/(Re**0.9)))**2

def nusselt_turbulent_dittus_boelter(Re: float, Pr: float, heating: bool = True) -> float:
    """
    Dittus–Boelter for turbulent internal flow:
    Nu = 0.023 Re^0.8 Pr^n, n=0.4 (heating) or 0.3 (cooling)
    """
    n = 0.4 if heating else 0.3
    return 0.023 * (Re**0.8) * (Pr**n)

# --- Data containers ---

@dataclass(frozen=True)
class ColdPlateInputs:
    # Geometry (meters)
    channel_w_m: float
    channel_h_m: float
    channel_length_m: float
    n_channels: int

    # Losses
    K_minor_total: float  # across cold plate: manifolds, turns, entries, etc.
    roughness_m: float    # absolute roughness

    # Thermal conduction (optional, prelim)
    base_thickness_m: float
    plate_k_W_mK: float       # cold-plate solid conductivity
    interface_h_W_m2K: float  # effective contact conductance (TIM + contact), can be very rough early
    interface_area_m2: float  # contact area from electronics to plate

@dataclass(frozen=True)
class ColdPlateResult:
    m_dot_kg_s: float
    V_dot_m3_s: float
    v_channel_m_s: float
    Re: float
    Pr: float
    Nu: float
    h_W_m2K: float
    dp_kPa: float
    dT_coolant_K: float

    # Simple thermal resistances (for quick temp estimate)
    R_conv_K_W: float
    R_plate_K_W: float
    R_contact_K_W: float
    R_total_K_W: float

class ColdPlate:
    """
    First-pass cold plate model:
    - Splits flow evenly across channels
    - Darcy–Weisbach pressure drop + minor losses
    - Internal convection coefficient (laminar/turbulent)
    - Optional simple conduction/contact resistance chain for quick T estimates
    """

    def __init__(self, inp: ColdPlateInputs):
        self.inp = inp

    def evaluate(self, Qin_W: float, m_dot_kg_s: float, rho: float, cp: float, mu: float, k: float) -> ColdPlateResult:
        i = self.inp
        n = max(int(i.n_channels), 1)

        # Flow split
        m_dot_ch = m_dot_kg_s / n
        V_dot = m_dot_kg_s / rho
        V_dot_ch = V_dot / n

        A_ch = i.channel_w_m * i.channel_h_m
        v = V_dot_ch / max(A_ch, 1e-12)

        Dh = hydraulic_diameter_rect(i.channel_w_m, i.channel_h_m)
        Re = reynolds(rho, v, Dh, mu)
        Pr = prandtl(cp, mu, k)

        aspect = min(i.channel_w_m, i.channel_h_m) / max(i.channel_w_m, i.channel_h_m)

        # Heat transfer correlation choice
        if Re < 2300:
            Nu = nusselt_laminar_rect(aspect)
            f = friction_factor_laminar(Re, aspect)
        else:
            Nu = nusselt_turbulent_dittus_boelter(Re, Pr, heating=True)
            rel_rough = i.roughness_m / max(Dh, 1e-12)
            f = friction_factor_turbulent(Re, rel_rough)

        h = Nu * k / max(Dh, 1e-12)

        # Pressure drop per channel
        dp_fric = f * (i.channel_length_m / max(Dh, 1e-12)) * (rho * v*v / 2.0)
        dp_minor = i.K_minor_total * (rho * v*v / 2.0)
        dp_total = dp_fric + dp_minor  # Pa

        # Coolant temperature rise across cold plate (single heat input)
        dT_coolant = Qin_W / max(m_dot_kg_s * cp, 1e-12)

        # Quick thermal resistances:
        # Convective area: use wetted perimeter * length * n_channels
        P_wet = 2.0 * (i.channel_w_m + i.channel_h_m)
        A_conv = P_wet * i.channel_length_m * n
        R_conv = 1.0 / max(h * A_conv, 1e-12)

        # Simple 1D conduction through base thickness under interface area
        R_plate = i.base_thickness_m / max(i.plate_k_W_mK * i.interface_area_m2, 1e-12)

        # Contact/TIM modeled as h_contact over interface area
        R_contact = 1.0 / max(i.interface_h_W_m2K * i.interface_area_m2, 1e-12)

        R_total = R_contact + R_plate + R_conv

        return ColdPlateResult(
            m_dot_kg_s=m_dot_kg_s,
            V_dot_m3_s=V_dot,
            v_channel_m_s=v,
            Re=Re,
            Pr=Pr,
            Nu=Nu,
            h_W_m2K=h,
            dp_kPa=dp_total / 1000.0,
            dT_coolant_K=dT_coolant,
            R_conv_K_W=R_conv,
            R_plate_K_W=R_plate,
            R_contact_K_W=R_contact,
            R_total_K_W=R_total,
        )