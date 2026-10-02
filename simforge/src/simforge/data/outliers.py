"""Outlier DETECTION. Detection never removes anything: it produces candidates; the engineer acts
(KEEP / EXCLUDE_FROM_FIT / MARK_INVALID, and RESTORED to undo), each action logged with reason, method, who and when.

Methods:
  IQR  value < Q1 - k*IQR or > Q3 + k*IQR (k = 1.5 "mild", 3.0 "extreme")
  MAD  modified z = 0.6745 * |x - median| / MAD > 3.5 (Iglewicz & Hoaglin)
Industrial data are often right-skewed: an "outlier" in the right tail can be a real long cycle (a jam, a rework).
Excluding it makes the simulation optimistic. That is why nothing is excluded automatically.
"""

from __future__ import annotations

from typing import Any

import numpy as np

METHODS = {"IQR": "Q1 - k·IQR / Q3 + k·IQR (k = 1.5 leve, 3.0 extremo)", "MAD": "z modificado = 0.6745·|x − mediana| / MAD > 3.5"}


def detect(values: list[float], indexes: list[int], iqr_k: float = 1.5, mad_z: float = 3.5) -> dict[str, Any]:
    a = np.asarray(values, dtype=float)
    if a.size < 5:
        return {"evaluated": False, "reason": "n < 5", "candidates": []}
    q1, q3 = np.percentile(a, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - iqr_k * iqr, q3 + iqr_k * iqr
    elo, ehi = q1 - 3.0 * iqr, q3 + 3.0 * iqr
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    cands = []
    for v, i in zip(a, indexes):
        methods = []
        if v < lo or v > hi:
            methods.append("IQR_EXTREME" if (v < elo or v > ehi) else "IQR_MILD")
        if mad > 0:
            z = 0.6745 * abs(v - med) / mad
            if z > mad_z:
                methods.append(f"MAD(z={z:.1f})")
        if methods:
            cands.append({"index": int(i), "value": float(v), "side": "high" if v > med else "low", "methods": methods})
    return {"evaluated": True, "iqr_fences": [float(lo), float(hi)], "iqr_k": iqr_k, "mad": mad, "mad_z": mad_z,
            "median": med, "candidates": cands,
            "note": "Candidatos, no errores: revisa cada uno (¿atasco real? ¿error de registro? ¿otro producto?) y decide."}
