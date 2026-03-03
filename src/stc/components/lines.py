# src/stc/components/lines.py
from __future__ import annotations
from dataclasses import dataclass
import math

def friction_factor_turbulent(Re: float, rel_rough: float) -> float:
    Re = max(Re, 1e-9)
    rr = max(rel_rough, 1e-12)
    return 0.25 / (math.log10(rr/3.7 + 5.74/(Re**0.9)))**2

@dataclass(frozen=True)
class LinesInputs:
    length_m: float
    ID_m: float
    roughness_m: float
    K_minor_total: float  # sum of fittings K
    allow_dp_kPa: float = 1e9

@dataclass(frozen=True)
class LinesResult:
    v_m_s: float
    Re: float
    f: float
    dp_kPa: float
    dp_fric_kPa: float
    dp_minor_kPa: float

class Lines:
    """
    First-pass line model:
    - Darcy–Weisbach + minor losses
    - Assumes single diameter for entire run
    """

    def __init__(self, inp: LinesInputs):
        self.inp = inp

    def evaluate(self, V_dot_m3_s: float, rho: float, mu: float) -> LinesResult:
        i = self.inp
        A = math.pi * (i.ID_m**2) / 4.0
        v = V_dot_m3_s / max(A, 1e-12)
        Re = rho * v * i.ID_m / max(mu, 1e-12)

        # Laminar vs turbulent friction factor
        if Re < 2300:
            f = 64.0 / max(Re, 1e-9)
        else:
            rel_rough = i.roughness_m / max(i.ID_m, 1e-12)
            f = friction_factor_turbulent(Re, rel_rough)

        dp_fric = f * (i.length_m / max(i.ID_m, 1e-12)) * (rho * v*v / 2.0)  # Pa
        dp_minor = i.K_minor_total * (rho * v*v / 2.0)                       # Pa
        dp = dp_fric + dp_minor

        return LinesResult(
            v_m_s=v,
            Re=Re,
            f=f,
            dp_kPa=dp / 1000.0,
            dp_fric_kPa=dp_fric / 1000.0,
            dp_minor_kPa=dp_minor / 1000.0,
        )