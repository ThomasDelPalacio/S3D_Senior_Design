# src/stc/components/radiator.py
from __future__ import annotations
from dataclasses import dataclass
import math

SIGMA = 5.670374419e-8  # W/m^2/K^4 | Stefan–Boltzmann Constant

##################################################
##              Data Containers                 ##
##################################################

@dataclass(frozen=True)
class RadiatorInputs:
    epsilon: float
    alpha: float
    view_factor: float          # 0-1 effective view to space
    A_max_m2: float | None      # geometric constraint

    # Environment flux assumptions for the case 
    q_solar_W_m2: float         # incident solar on radiator
    q_albedo_W_m2: float        # reflected solar component
    q_ir_W_m2: float            # Earth IR on radiator

@dataclass(frozen=True)
class RadiatorResult:
    A_req_m2: float
    A_used_m2: float
    Q_reject_W: float
    T_rad_K: float
    feasible_with_Amax: bool

##################################################
##               Radiator Model                 ##
##################################################

class Radiator:
    """
    First-pass radiator sizing using steady radiation balance:
      Q_reject = ε σ A F_view (T_rad^4 - T_sink^4) - A α (q_solar + q_albedo) - A (q_ir)
    Rearranged for A given Q and T_rad.
    """

    def __init__(self, inp: RadiatorInputs):
        self.inp = inp

    def area_required(self, Q_W: float, T_rad_C: float, T_sink_K: float):
        i = self.inp
        eps = max(min(i.epsilon, 1.0), 1e-6)
        alp = max(min(i.alpha, 1.0), 0.0)
        F = max(min(i.view_factor, 1.0), 0.0)

        T_rad_K = T_rad_C + 273.15

        # Net radiative capability per area (W/m^2)
        rad_term = eps * SIGMA * F * (T_rad_K**4 - T_sink_K**4)

        # Absorbed environmental loads per area (W/m^2)
        absorbed = alp * (i.q_solar_W_m2 + i.q_albedo_W_m2) + i.q_ir_W_m2

        net_per_area = rad_term - absorbed

        if net_per_area <= 0:
            # Cannot reject heat at this temperature/conditions
            A_req = float("inf")
        else:
            A_req = Q_W / net_per_area

        A_used = A_req
        feasible = True
        if i.A_max_m2 is not None:
            A_used = min(A_req, i.A_max_m2)
            feasible = A_req <= i.A_max_m2

        Q_reject = 0.0
        if math.isfinite(A_used):
            Q_reject = A_used * net_per_area

        return RadiatorResult(
            A_req_m2=A_req,
            A_used_m2=A_used,
            Q_reject_W=Q_reject,
            T_rad_K=T_rad_K,
            feasible_with_Amax=feasible,
        )