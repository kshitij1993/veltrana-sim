"""
Sell-in (867 / ex-factory): SP x NDC x day, daily cadence, 100% coverage -
this is the manufacturer's own shipment ledger into its 3 specialty
pharmacies, so unlike the other feeds it isn't sampled or delayed. It's
still allowed to diverge from sell-out (true dispenses): each shipment
lands with its own lead-time jitter around the dispense it's ultimately
covering, and if E9 (SP inventory build) got sampled, one quarter gets an
extra lump-sum shipment on top of ordinary replenishment.

Only reports Veltrana - the manufacturer's own ledger has no visibility
into what its specialty pharmacies ship for competitor brands.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator, fills: pd.DataFrame) -> pd.DataFrame:
    patients = world["patients"][["patient_id", "dispensing_sp"]]
    veltrana_fills = fills.loc[fills["product"] == "VELTRANA"].merge(
        patients, on="patient_id", how="left"
    )
    veltrana_fills = veltrana_fills.loc[veltrana_fills["dispensing_sp"] != ""]

    daily = (
        veltrana_fills.groupby(["dispensing_sp", "fill_date"], as_index=False)
        .size()
        .rename(columns={"size": "units_dispensed", "dispensing_sp": "sp", "fill_date": "date"})
    )
    daily["date"] = pd.to_datetime(daily["date"])

    n = len(daily)
    lead_days = rng.integers(cfg.SELL_IN_LEAD_DAYS[0], cfg.SELL_IN_LEAD_DAYS[1] + 1, size=n)
    daily["ship_date"] = daily["date"] + pd.to_timedelta(lead_days, unit="D")
    daily["units"] = daily["units_dispensed"]

    inventory_build = world.get("sp_inventory_build")
    if inventory_build is not None and len(inventory_build):
        row = inventory_build.iloc[0]
        build_quarter = pd.Timestamp(row["quarter"]).to_period("Q")
        excess_weeks = int(row["excess_weeks"])

        in_quarter = daily["date"].dt.to_period("Q") == build_quarter
        weekly_avg_by_sp = (
            daily.loc[in_quarter].groupby("sp")["units_dispensed"].mean() * 7
        )
        lump_date = build_quarter.to_timestamp()
        lumps = pd.DataFrame(
            {
                "sp": weekly_avg_by_sp.index,
                "date": lump_date,
                "units_dispensed": 0,
                "ship_date": lump_date,
                "units": (weekly_avg_by_sp.values * excess_weeks).round().astype(int),
            }
        )
        daily = pd.concat([daily, lumps], ignore_index=True)

    daily["ndc"] = cfg.NDC_PREFIX["VELTRANA"]
    daily["sell_in_id"] = [f"SELLIN{i:07d}" for i in range(len(daily))]

    return daily[["sell_in_id", "ndc", "sp", "ship_date", "units"]].sort_values(
        ["ship_date", "sp"]
    ).reset_index(drop=True)
