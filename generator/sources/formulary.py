"""
Formulary (MMIT-style): plan x product x quarter grain, quarterly cadence,
"major plans" only - not every regional plan in the true world shows up in
this feed, which is what "major plans" coverage means in practice. Quirk:
effective-date lags, since the vendor's recorded effective date for a
formulary change trails the payer's actual quarter change.

Formulary status is sticky by design: competitor placement is drawn once
per plan and held for the whole window (real formularies don't flicker
quarter to quarter), and Veltrana's status moves through a monotonic
post-launch ramp toward a per-plan ceiling. Applies the E1 formulary
downgrade (only when it targeted a plan, not a region - region-level
access shifts have no formulary-dataset analogue) as a persistent step
down in that ceiling from world["formulary_downgrades"], ground truth
effects.py left in the world dict, not the answer key.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg

_STATE_ORDER = ["not_covered", "pa_biosim_step", "non_preferred", "preferred"]

# Weighted pools (repeats = weight) to draw one constant lifetime state
# per plan for each non-Veltrana product.
_NON_VELTRANA_STATE_POOL = {
    "ADALIMUMAB_BIOSIM": ["preferred"] * 9 + ["non_preferred"],
    "DERMAVEX": ["preferred"] * 6 + ["non_preferred"] * 3 + ["pa_biosim_step"],
    "CLARIVO": ["preferred"] * 5 + ["non_preferred"] * 4 + ["pa_biosim_step"],
    "ORELTA": ["preferred"] * 4 + ["non_preferred"] * 4 + ["pa_biosim_step"] * 2,
}

# Per-plan ceiling stage Veltrana's ramp climbs toward (index into
# _STATE_ORDER) - not every plan ultimately grants "preferred".
_CEILING_STAGE_POOL = [3] * 5 + [2] * 4 + [1] * 1


def _major_plans(world: dict, rng: np.random.Generator) -> list[str]:
    patients = world["patients"]
    plan_ids = patients.loc[
        patients["payer_channel"].isin(["commercial", "medicare_partd"]), "plan_id"
    ].unique()
    national = [p for p in plan_ids if p.startswith("PBM_NAT_") or p == "MEDICARE_PARTD"]
    regional = [p for p in plan_ids if p.startswith("PLAN_REG_")]
    kept_regional = [p for p in regional if rng.random() < cfg.FORMULARY_REGIONAL_PLAN_COVERAGE]
    return sorted(national) + sorted(kept_regional)


def generate(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    plans = _major_plans(world, rng)
    quarters = pd.date_range(cfg.SIM_START, cfg.SIM_END, freq="QS")
    products = list(cfg.PRODUCTS.keys())

    downgrade = world.get("formulary_downgrades")
    downgrade_plan = downgrade_start = None
    if downgrade is not None and len(downgrade):
        downgrade_plan = downgrade.iloc[0]["plan_id"]
        downgrade_start = pd.Timestamp(downgrade.iloc[0]["start_date"]).to_period("Q")

    # Constant lifetime state per (plan, non-Veltrana product).
    non_veltrana_state = {
        (plan, product): rng.choice(pool)
        for plan in plans
        for product, pool in _NON_VELTRANA_STATE_POOL.items()
    }
    # Per-plan ceiling Veltrana's ramp ultimately climbs to.
    veltrana_ceiling = {plan: int(rng.choice(_CEILING_STAGE_POOL)) for plan in plans}

    rows = []
    for plan in plans:
        for quarter in quarters:
            q_period = quarter.to_period("Q")
            for product in products:
                if product == "VELTRANA":
                    months_since_launch = (
                        q_period.to_timestamp() - pd.Timestamp(cfg.LAUNCH_DATE)
                    ).days // 30
                    if months_since_launch < 0:
                        state = "not_covered"
                    else:
                        ramp = min(1.0, months_since_launch / cfg.ACCESS_RAMP_MONTHS)
                        ceiling = veltrana_ceiling[plan]
                        if (
                            plan == downgrade_plan
                            and downgrade_start is not None
                            and q_period >= downgrade_start
                        ):
                            # A downgrade permanently caps the ceiling lower,
                            # regardless of how far the ramp had climbed.
                            ceiling = min(ceiling, 1)
                        stage = min(int(ramp * (len(_STATE_ORDER) - 1)), ceiling)
                        state = _STATE_ORDER[stage]
                else:
                    state = non_veltrana_state[(plan, product)]

                lag_days = int(rng.integers(*cfg.FORMULARY_EFFECTIVE_DATE_LAG_DAYS))
                effective_date = q_period.to_timestamp() + pd.Timedelta(days=lag_days)

                rows.append(
                    {
                        "plan_id": plan,
                        "product": product,
                        "quarter": q_period.to_timestamp(),
                        "formulary_state": state,
                        "effective_date": effective_date,
                    }
                )

    return pd.DataFrame(rows)
