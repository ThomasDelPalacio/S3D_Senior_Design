# src/stc/components/pump.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PumpInputs:
    efficiency: float          # electrical-to-hydraulic (0-1)
    power_limit_W: float | None = None

@dataclass(frozen=True)
class PumpResult:
    dp_kPa_required: float
    V_dot_m3_s: float
    P_hyd_W: float
    P_elec_W: float
    within_power_limit: bool

class Pump:
    """
    First-pass pump sizing:
    - Hydraulic power: P_hyd = Δp * Vdot
    - Electrical power: P_elec = P_hyd / η
    """

    def __init__(self, inp: PumpInputs):
        self.inp = inp

    def evaluate(self, dp_total_kPa: float, V_dot_m3_s: float) -> PumpResult:
        i = self.inp
        dp_Pa = dp_total_kPa * 1000.0
        P_hyd = dp_Pa * V_dot_m3_s
        eta = max(min(i.efficiency, 1.0), 1e-6)
        P_elec = P_hyd / eta

        ok = True
        if i.power_limit_W is not None:
            ok = P_elec <= i.power_limit_W

        return PumpResult(
            dp_kPa_required=dp_total_kPa,
            V_dot_m3_s=V_dot_m3_s,
            P_hyd_W=P_hyd,
            P_elec_W=P_elec,
            within_power_limit=ok,
        )