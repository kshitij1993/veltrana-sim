"""
CRM calls (Veeva-style): call x rep x HCP grain, daily cadence, near-
complete coverage. Two things are baked in here rather than left to the
analysis to discover the hard way:

- Targeting selection bias (always-on, per the design doc): reps call
  higher-potential-decile HCPs more, which is exactly what makes a naive
  "calls vs. Rx" correlation misleading later in the promotional-response
  module.
- Call saturation (E3, if sampled): on top of the baseline targeting skew,
  reps keep piling calls onto their favorite top-decile accounts past the
  point of usefulness, read from world["call_response_curve"] - ground
  truth effects.py left in the world, not the answer key.

Quirks: duplicate logs and late entry (calls logged days after they
happened).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    hcps = world["hcps"]
    n_hcps = len(hcps)

    potential = hcps["potential_decile"].values.astype(float)
    targeting_multiplier = 1 + cfg.CALLS_TARGETING_SELECTION_STRENGTH * (
        potential - potential.mean()
    ) / potential.std()

    saturation_boost = np.ones(n_hcps)
    call_curve = world.get("call_response_curve")
    if call_curve is not None and len(call_curve):
        top_deciles = {int(d) for d in call_curve.iloc[0]["top_deciles"].split(",")}
        boosted = hcps["potential_decile"].isin(top_deciles).values
        saturation_boost[boosted] = 1.5

    mean_calls_per_quarter = np.clip(
        cfg.CALLS_PER_HCP_PER_QUARTER_BASE * targeting_multiplier * saturation_boost, 0.05, None
    )

    quarter_starts = pd.date_range(cfg.SIM_START, cfg.SIM_END, freq="QS")
    hcp_ids = hcps["hcp_id"].values
    rep_ids = hcps["rep_id"].values
    territory_ids = hcps["territory_id"].values

    chunks = []
    for q_start in quarter_starts:
        q_end = min(q_start + pd.DateOffset(months=3), pd.Timestamp(cfg.SIM_END) + pd.Timedelta(days=1))
        q_days = max(1, (q_end - q_start).days)

        n_calls = rng.poisson(mean_calls_per_quarter)
        total = int(n_calls.sum())
        if total == 0:
            continue

        hcp_idx = np.repeat(np.arange(n_hcps), n_calls)
        offsets = rng.integers(0, q_days, size=total)
        call_dates = q_start + pd.to_timedelta(offsets, unit="D")

        chunks.append(
            pd.DataFrame(
                {
                    "hcp_id": hcp_ids[hcp_idx],
                    "rep_id": rep_ids[hcp_idx],
                    "territory_id": territory_ids[hcp_idx],
                    "call_date": call_dates,
                }
            )
        )

    calls = pd.concat(chunks, ignore_index=True)
    n = len(calls)
    calls["call_id"] = [f"CALL{i:08d}" for i in range(n)]

    late_mask = rng.random(n) < cfg.CALLS_LATE_ENTRY_RATE
    late_days = np.zeros(n, dtype=int)
    if late_mask.any():
        late_days[late_mask] = rng.integers(*cfg.CALLS_LATE_ENTRY_DAYS, size=int(late_mask.sum()))
    calls["logged_date"] = pd.to_datetime(calls["call_date"]) + pd.to_timedelta(late_days, unit="D")

    n_dupes = int(n * cfg.CALLS_DUPLICATE_LOG_RATE)
    if n_dupes:
        dupe_idx = rng.choice(calls.index, size=n_dupes, replace=False)
        dupes = calls.loc[dupe_idx].copy()
        dupes["call_id"] = [f"CALL{n + i:08d}" for i in range(n_dupes)]
        calls = pd.concat([calls, dupes], ignore_index=True)

    return calls[["call_id", "hcp_id", "rep_id", "territory_id", "call_date", "logged_date"]]
