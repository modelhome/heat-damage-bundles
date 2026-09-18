"""Exposure-response functions: WBGT (degC) -> physical work capacity lost (%).

Each function is implemented from its published equation, with the citation
beside it. Nothing here is vendored from third-party analysis code, and nothing
here touches the network.

Both implemented curves describe *heavy outdoor work* - the construction and
agriculture workforce this bundle's BLS table counts. Neither is parameterised
by metabolic rate, which is why `work_intensity_class` accepts only "heavy";
see the bundle README.

The two curves disagree sharply above 30 degC, and that is the point: one is a
lab-derived empirical sigmoid, the other a power law fitted to occupational
safety thresholds. Being able to swap them, and to see the swap in the output's
sampled curve, is what makes the damage function auditable.
"""
from __future__ import annotations

# --- Foster et al. (2021) ----------------------------------------------------
# Foster J, Smallcombe JW, Hodder S, Jay O, Flouris AD, Nybo L, Havenith G.
# "An advanced empirical model for quantifying the impact of heat and climate
# change on human physical work capacity." Int J Biometeorol 65:1215-1229 (2021).
# doi:10.1007/s00484-021-02105-0
#
# Table 3, WBGT row. The paper's general form is the sigmoid
#     PWC% = 100 / (1 + (x / PWC50) ** HillSlope)
# with plateaus fixed at 0 and 100; for WBGT, PWC50 = 33.63 and HillSlope = 6.33
# (R2 = .94, RMSE = 5.94, fitted over 12-40 degC WBGT).
#
# PWC is relative to a cool reference condition (15 degC, 50% RH). The underlying
# protocol is fixed cardiovascular strain at a heart-rate ceiling of 130 b/min,
# which the paper characterises as moderate-to-heavy occupational work.
FOSTER_PWC50 = 33.63
FOSTER_HILL_SLOPE = 6.33

# --- Dunne, Stouffer and John (2013) -----------------------------------------
# Dunne JP, Stouffer RJ, John JG. "Reductions in labour capacity from heat stress
# under climate warming." Nature Climate Change 3:563-566 (2013).
# doi:10.1038/nclimate1827
#
#     labour capacity = 100 - 25 * max(0, WBGT - 25) ** (2/3),  bounded to [0, 100]
#
# Derived from occupational health and safety thresholds for heavy work rather
# than from a laboratory fit: full capacity up to WBGT 25 degC, no safe outdoor
# work at or above 33 degC.
DUNNE_THRESHOLD_C = 25.0
DUNNE_COEFFICIENT = 25.0
DUNNE_EXPONENT = 2.0 / 3.0


def foster2021(wbgt_c: float) -> float:
    """Capacity lost (%) at *wbgt_c* under Foster et al. (2021)."""
    pwc_pct = 100.0 / (1.0 + (wbgt_c / FOSTER_PWC50) ** FOSTER_HILL_SLOPE)
    return 100.0 - pwc_pct


def dunne2013(wbgt_c: float) -> float:
    """Capacity lost (%) at *wbgt_c* under Dunne, Stouffer and John (2013)."""
    excess = max(0.0, wbgt_c - DUNNE_THRESHOLD_C)
    capacity_pct = 100.0 - DUNNE_COEFFICIENT * excess**DUNNE_EXPONENT
    return 100.0 - max(0.0, min(100.0, capacity_pct))


ERFS: dict[str, dict[str, object]] = {
    "foster2021": {
        "function": foster2021,
        "citation": (
            "Foster J, Smallcombe JW, Hodder S, Jay O, Flouris AD, Nybo L, Havenith G (2021). "
            "An advanced empirical model for quantifying the impact of heat and climate change "
            "on human physical work capacity. Int J Biometeorol 65:1215-1229. "
            "doi:10.1007/s00484-021-02105-0"
        ),
        "summary": (
            "Lab-derived sigmoid fitted to 338 work sessions in climatic chambers, at a "
            "fixed cardiovascular strain of 130 beats/min (moderate-to-heavy work)."
        ),
        "valid_range_c": (12.0, 40.0),
        "work_intensity_class": "heavy",
    },
    "dunne2013": {
        "function": dunne2013,
        "citation": (
            "Dunne JP, Stouffer RJ, John JG (2013). Reductions in labour capacity from heat "
            "stress under climate warming. Nature Climate Change 3:563-566. "
            "doi:10.1038/nclimate1827"
        ),
        "summary": (
            "Power law fitted to occupational safety thresholds for heavy work: full capacity "
            "to WBGT 25 degC, none at or above 33 degC."
        ),
        # No fitted range to extrapolate beyond: the function is bounded by
        # construction, at full capacity below 25 degC and none at or above 33.
        "valid_range_c": None,
        "work_intensity_class": "heavy",
    },
}

DEFAULT_ERF = "foster2021"

# The only work-intensity class either implemented curve describes. The runner
# rejects the others rather than accepting a value it cannot honour.
SUPPORTED_WORK_INTENSITY_CLASSES = ("heavy",)
WORK_INTENSITY_METABOLIC_RATE_W = 400

CURVE_START_C = 15.0
CURVE_STOP_C = 45.0
CURVE_STEP_C = 0.5


def capacity_loss_pct(wbgt_c: float, erf: str = DEFAULT_ERF) -> float:
    """Capacity lost (%) at *wbgt_c* under the named exposure-response function."""
    try:
        entry = ERFS[erf]
    except KeyError:
        raise ValueError(f"unknown erf {erf!r}; choose one of {sorted(ERFS)}") from None
    return entry["function"](wbgt_c)  # type: ignore[operator]


def sample_curve(erf: str = DEFAULT_ERF) -> list[dict[str, float]]:
    """The named curve sampled across CURVE_START_C..CURVE_STOP_C, for plotting."""
    steps = round((CURVE_STOP_C - CURVE_START_C) / CURVE_STEP_C)
    points = []
    for step in range(steps + 1):
        wbgt = round(CURVE_START_C + step * CURVE_STEP_C, 2)
        points.append(
            {"wbgt_c": wbgt, "capacity_loss_pct": round(capacity_loss_pct(wbgt, erf), 3)}
        )
    return points
