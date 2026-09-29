"""
Rx audit (IQVIA Xponent/NPA-style): HCP x product x payer channel x week,
weekly cadence with a 2-week reporting lag, projected national volume.

Derived from the shared true-fills stream (sources/common.py) by weekly
aggregation, then distorted with the vendor's own projection noise
(non-integer projected units) and, if E5 got sampled, a periodic
methodology restatement read from the ground truth effects.py left in the
world dict - never from answer_key.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator, fills: pd.DataFrame) -> pd.DataFrame:
    weekly = fills.copy()
    weekly["week_of"] = pd.to_datetime(weekly["fill_date"]).dt.to_period("W-SUN").dt.start_time

    agg = (
        weekly.groupby(["hcp_id", "product", "payer_channel", "week_of"], as_index=False)
        .size()
        .rename(columns={"size": "true_units"})
    )

    noise = rng.normal(cfg.RX_AUDIT_PROJECTION_FACTOR, cfg.RX_AUDIT_PROJECTION_NOISE_SD, size=len(agg))
    agg["projected_units"] = np.clip(agg["true_units"] * noise, 0, None).round(2)

    restatement = world.get("vendor_restatement")
    if restatement is not None and len(restatement):
        row = restatement.iloc[0]
        month = pd.Timestamp(row["restatement_month"]).to_period("M")
        shift = float(row["shift_pct"]) * int(row["direction"])
        month_mask = agg["week_of"].dt.to_period("M") == month
        agg.loc[month_mask, "projected_units"] = (
            agg.loc[month_mask, "projected_units"] * (1 + shift)
        ).round(2)

    agg["report_date"] = agg["week_of"] + pd.Timedelta(weeks=cfg.RX_AUDIT_LAG_WEEKS)

    return agg[
        ["hcp_id", "product", "payer_channel", "week_of", "report_date", "projected_units"]
    ].sort_values(["week_of", "hcp_id", "product"]).reset_index(drop=True)
