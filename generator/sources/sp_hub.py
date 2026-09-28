"""
SP and hub status feed (852/867 + hub-style): patient status event grain,
daily cadence. ~100% coverage of Veltrana's own patient journey and 0% of
competitors - the brand's hub only ever sees its own patients, which is
exactly the asymmetry the design doc calls out. Each of the 3 specialty
pharmacies reports through its own status-code vocabulary
(config.SP_STATUS_CODE_MAPS), a built-in quirk any reconciliation has to
work through.

Requires world["patients"]["dispensing_sp"] to already be assigned
(sources/common.assign_dispensing_sp) and reads refill timing from the
shared true-fills stream so this feed's refill events land on the same
dates the claims/Rx-audit feeds would independently reconstruct.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator, fills: pd.DataFrame) -> pd.DataFrame:
    patients = world["patients"]
    veltrana = patients.loc[patients["index_product"] == "VELTRANA"].copy()
    veltrana = veltrana.loc[veltrana["dispensing_sp"] != ""]

    veltrana_fills = fills.loc[fills["product"] == "VELTRANA"]
    first_fill_dates = (
        veltrana_fills.loc[veltrana_fills["is_first_fill"]]
        .set_index("patient_id")["fill_date"]
    )
    refill_fills = veltrana_fills.loc[~veltrana_fills["is_first_fill"]]

    n = len(veltrana)
    jitter = rng.integers(1, 4, size=(n, 3))  # bv / pa-submit / pa-decision day offsets
    abandon_jitter = rng.integers(5, 20, size=n)

    events = []
    for row, (bv_j, pa_j, decision_j), aband_j in zip(
        veltrana.itertuples(index=False), jitter, abandon_jitter
    ):
        pid = row.patient_id
        sp = row.dispensing_sp
        idx_date = pd.Timestamp(row.index_start_date)

        events.append((pid, sp, "referral_received", idx_date))
        if row.bv_complete:
            events.append((pid, sp, "benefit_verification", idx_date + pd.Timedelta(days=int(bv_j))))
        if row.pa_required:
            events.append((pid, sp, "pa_pending", idx_date + pd.Timedelta(days=int(pa_j))))
            if row.pa_outcome in ("approved_first_pass", "approved_on_appeal"):
                events.append((pid, sp, "pa_approved", idx_date + pd.Timedelta(days=int(decision_j) + 2)))
            elif row.pa_outcome == "denied":
                events.append((pid, sp, "pa_denied", idx_date + pd.Timedelta(days=int(decision_j) + 2)))
        if row.abandoned:
            events.append((pid, sp, "abandoned", idx_date + pd.Timedelta(days=int(aband_j))))
        if row.reached_first_fill and pid in first_fill_dates.index:
            events.append((pid, sp, "first_fill", first_fill_dates[pid]))

    ev = pd.DataFrame(events, columns=["patient_id", "sp", "status", "event_date"])

    refill_ev = refill_fills.merge(
        veltrana[["patient_id", "dispensing_sp"]], on="patient_id", how="inner"
    )
    refill_ev = pd.DataFrame(
        {
            "patient_id": refill_ev["patient_id"],
            "sp": refill_ev["dispensing_sp"],
            "status": "refill",
            "event_date": refill_ev["fill_date"],
        }
    )
    ev = pd.concat([ev, refill_ev], ignore_index=True)

    ev["status_code"] = ""
    for sp, code_map in cfg.SP_STATUS_CODE_MAPS.items():
        mask = ev["sp"] == sp
        ev.loc[mask, "status_code"] = ev.loc[mask, "status"].map(code_map)

    lag_days = rng.integers(cfg.SP_HUB_EVENT_LAG_DAYS[0], cfg.SP_HUB_EVENT_LAG_DAYS[1] + 1, size=len(ev))
    ev["report_date"] = pd.to_datetime(ev["event_date"]) + pd.to_timedelta(lag_days, unit="D")
    ev = ev.sort_values(["patient_id", "event_date"]).reset_index(drop=True)
    ev["event_id"] = [f"SPEVT{i:08d}" for i in range(len(ev))]

    return ev[["event_id", "patient_id", "sp", "status_code", "event_date", "report_date"]]
