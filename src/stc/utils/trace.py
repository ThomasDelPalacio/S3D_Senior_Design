# src/stc/utils/trace.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import math

@dataclass
class TraceLog:
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def info(self, msg: str) -> None:
        self.messages.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def summarize(self) -> str:
        out = []
        if self.errors:
            out.append("ERRORS:")
            out += [f"  - {e}" for e in self.errors]
        if self.warnings:
            out.append("WARNINGS:")
            out += [f"  - {w}" for w in self.warnings]
        if self.messages:
            out.append("INFO:")
            out += [f"  - {m}" for m in self.messages]
        return "\n".join(out) if out else "No trace messages."

def is_bad(x: Any) -> bool:
    try:
        return x is None or (isinstance(x, float) and math.isnan(x))
    except Exception:
        return True

def require_number(x: Any, name: str, trace: TraceLog) -> float:
    if is_bad(x):
        trace.error(f"Missing/NaN required value: {name}")
        return float("nan")
    try:
        v = float(x)
        if math.isnan(v):
            trace.error(f"Value became NaN after casting: {name} = {x}")
        return v
    except Exception:
        trace.error(f"Could not convert to float: {name} = {x}")
        return float("nan")