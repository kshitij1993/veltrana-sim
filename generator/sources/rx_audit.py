"""
Rx audit (IQVIA Xponent/NPA-style): HCP x product x payer channel x week,
weekly cadence with a 2-week reporting lag, projected national volume.

Reports NRx (new-patient starts) and TRx (total dispenses, new + refill)
separately, projected and noised independently - matching how a real
Xponent-style panel actually reports both, not just a combined count.
Both are derived from the shared true-fills stream (sources/common.py):
TRx from every fill, NRx from the subset where is_first_fill is true.
Distorted with the vendor's own projection noise (non-integer projected
units) and, if E5 got sampled, a periodic methodology restatement read
from the ground truth effects.py left in the world dict - never from
answer_key.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator, fills: pd.DataFrame) -> pd.DataFrame:
    weekly = fills.copy()
    weekly["week_of"] = pd.to_datetime(weekly["fill_date"]).dt.to_period("W-SUN").dt.start_time

    group_keys = ["hcp_id", "product", "payer_channel", "week_of"]
    trx = weekly.groupby(group_keys, as_index=False).size().rename(columns={"size": "true_trx"})
    nrx = (
        weekly.loc[weekly["is_first_fill"]]
        .groupby(group_keys, as_index=False)
        .size()
        .rename(columns={"size": "true_nrx"})
    )
    agg = trx.merge(nrx, on=group_keys, how="left")
    agg["true_nrx"] = agg["true_nrx"].fillna(0).astype(int)

    noise_trx = rng.normal(cfg.RX_AUDIT_PROJECTION_FACTOR, cfg.RX_AUDIT_PROJECTION_NOISE_SD, size=len(agg))
    noise_nrx = rng.normal(cfg.RX_AUDIT_PROJECTION_FACTOR, cfg.RX_AUDIT_PROJECTION_NOISE_SD, size=len(agg))
    agg["projected_trx"] = np.clip(agg["true_trx"] * noise_trx, 0, None).round(2)
    agg["projected_nrx"] = np.clip(agg["true_nrx"] * noise_nrx, 0, None).round(2)

    restatement = world.get("vendor_restatement")
    if restatement is not None and len(restatement):
        row = restatement.iloc[0]
        month = pd.Timestamp(row["restatement_month"]).to_period("M")
        shift = float(row["shift_pct"]) * int(row["direction"])
        month_mask = agg["week_of"].dt.to_period("M") == month
        agg.loc[month_mask, "projected_trx"] = (
            agg.loc[month_mask, "projected_trx"] * (1 + shift)
        ).round(2)
        agg.loc[month_mask, "projected_nrx"] = (
            agg.loc[month_mask, "projected_nrx"] * (1 + shift)
        ).round(2)

    agg["report_date"] = agg["week_of"] + pd.Timedelta(weeks=cfg.RX_AUDIT_LAG_WEEKS)

    return agg[
        ["hcp_id", "product", "payer_channel", "week_of", "report_date", "projected_nrx", "projected_trx"]
    ].sort_values(["week_of", "hcp_id", "product"]).reset_index(drop=True)
