from __future__ import annotations
from dataclasses import dataclass
import math

##################################################
##              Data Containers                 ##
##################################################

@dataclass(frozen=True)
class AccumulatorInputs:
    # Liquid inventory in the loop; used for expansion sizing
    V_liquid_cc: float

    # Fluid volumetric thermal expansion coefficient (1/K)
    beta_1_K: float

    # Temperature swing for sizing (K)
    dT_K: float

    # Gas side assumptions
    P_precharge_kPa: float
    P_min_kPa: float
    P_max_kPa: float
    polytropic_n: float = 1.2  # 1.0 isothermal, ~1.2-1.4 closer to adiabatic-ish

@dataclass(frozen=True)
class AccumulatorResult:
    dV_expand_cc: float
    V_gas_min_cc: float
    V_gas_max_cc: float
    V_accumulator_cc: float
    notes: str

##################################################
##              Accumulator Model               ##
##################################################

class Accumulator:
    """
    First-pass accumulator sizing:
        1) Liquid expansion: ΔV = V_liq * beta * ΔT
        2) Gas compression: P*V^n = constant (polytropic)
    Need enough gas volume swing to absorb ΔV while keeping P within [Pmin, Pmax].

    This is a prelim model; once picked accumulator architecture (bladder/bellows),
    add dead volumes, gas solubility, and dynamic effects.
    """

    def __init__(self, inp: AccumulatorInputs):
        self.inp = inp

    def size(self):
        i = self.inp
        Vliq = max(i.V_liquid_cc, 1e-9)
        beta = max(i.beta_1_K, 0.0)
        dT = max(i.dT_K, 0.0)

        dV = Vliq * beta * dT  # cc (since proportional)

        # Gas law (polytropic): P1*V1^n = P2*V2^n
        n = max(i.polytropic_n, 1e-6)

        # Define:
            # At minimum system pressure P_min, gas volume is maximum: V_gas_max
            # At maximum system pressure P_max, gas volume is minimum: V_gas_min
            # And: V_gas_max - V_gas_min >= dV (must absorb expansion)
        Pmin = max(i.P_min_kPa, 1e-9)
        Pmax = max(i.P_max_kPa, Pmin + 1e-6)
        P0 = max(i.P_precharge_kPa, 1e-9)

        # Choose V_gas_max based on precharge and minimum pressure:
            # P0 * V0^n = Pmin * V_gas_max^n
        # Without V0 known, we solve by selecting V_gas_max such that volume swing equals dV.
        # Use relation between V_gas_min and V_gas_max:
            # Pmin*Vmax^n = Pmax*Vmin^n => Vmin = Vmax*(Pmin/Pmax)^(1/n)
        ratio = (Pmin / Pmax) ** (1.0 / n)
        # Vmax - Vmin = Vmax*(1 - ratio) >= dV  => Vmax >= dV/(1-ratio)
        denom = max(1.0 - ratio, 1e-9)
        Vgas_max = dV / denom
        Vgas_min = Vgas_max * ratio

        # Total accumulator volume (gas + a little margin). Add 20% margin for prelim.
        Vacc = 1.2 * Vgas_max

        notes = "Prelim: Vacc includes 20% margin; refine with dead volume + architecture specifics."

        return AccumulatorResult(
            dV_expand_cc=dV,
            V_gas_min_cc=Vgas_min,
            V_gas_max_cc=Vgas_max,
            V_accumulator_cc=Vacc,
            notes=notes,
        )