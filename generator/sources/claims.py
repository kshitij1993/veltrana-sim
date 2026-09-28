"""
Patient claims (LAAD/Symphony-style): patient x claim grain, delivered
monthly with a 4-6 week adjudication lag, covering ~65% of patients
(worse for Medicaid, which is systematically undercaptured by commercial
claims clearinghouses).

Derived from the shared true-fills stream (sources/common.py): sample the
covered population, tokenize the patient ID (the vendor never sees the
brand's own patient identifiers), carve out a temporary eligibility gap
for a subset of covered patients, and add adjudication lag with an
occasional late-adjudication tail.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg
from sources.common import tokenize_id


def generate(world: dict, rng: np.random.Generator, fills: pd.DataFrame) -> pd.DataFrame:
    patients = world["patients"][["patient_id", "payer_channel"]].drop_duplicates("patient_id")

    coverage_prob = np.where(
        patients["payer_channel"] == "medicaid",
        cfg.CLAIMS_PATIENT_COVERAGE * (1 - cfg.CLAIMS_MEDICAID_UNDERCAPTURE),
        cfg.CLAIMS_PATIENT_COVERAGE,
    )
    covered_mask = rng.random(len(patients)) < coverage_prob
    covered_ids = patients.loc[covered_mask, "patient_id"].values

    claims = fills[fills["patient_id"].isin(set(covered_ids))].copy()

    # Eligibility gaps: a random window per affected patient, independent of
    # their own fill timing, during which any claim is invisible to this feed.
    n_gap = int(len(covered_ids) * cfg.CLAIMS_ELIGIBILITY_GAP_RATE)
    if n_gap:
        gap_patient_ids = rng.choice(covered_ids, size=n_gap, replace=False)
        gap_days = rng.integers(*cfg.CLAIMS_ELIGIBILITY_GAP_DAYS, size=n_gap)
        total_span = (cfg.SIM_END - cfg.SIM_START).days
        gap_offset = rng.integers(0, np.maximum(total_span - gap_days, 1))
        gap_start = pd.Timestamp(cfg.SIM_START) + pd.to_timedelta(gap_offset, unit="D")
        gap_end = gap_start + pd.to_timedelta(gap_days, unit="D")
        gap_windows = pd.DataFrame(
            {"patient_id": gap_patient_ids, "gap_start": gap_start, "gap_end": gap_end}
        )

        claims = claims.merge(gap_windows, on="patient_id", how="left")
        in_gap = (
            claims["gap_start"].notna()
            & (claims["fill_date"] >= claims["gap_start"])
            & (claims["fill_date"] < claims["gap_end"])
        )
        claims = claims.loc[~in_gap].drop(columns=["gap_start", "gap_end"])

    n = len(claims)
    base_lag_weeks = rng.integers(cfg.CLAIMS_LAG_WEEKS[0], cfg.CLAIMS_LAG_WEEKS[1] + 1, size=n)
    late_mask = rng.random(n) < cfg.CLAIMS_LATE_ADJUDICATION_RATE
    extra_weeks = np.zeros(n, dtype=int)
    if late_mask.any():
        extra_weeks[late_mask] = rng.integers(
            *cfg.CLAIMS_LATE_ADJUDICATION_EXTRA_WEEKS, size=int(late_mask.sum())
        )
    lag_days = (base_lag_weeks + extra_weeks) * 7

    claims["adjudication_date"] = pd.to_datetime(claims["fill_date"]) + pd.to_timedelta(
        lag_days, unit="D"
    )
    claims["is_late_adjudication"] = late_mask
    claims["patient_token"] = claims["patient_id"].map(tokenize_id)
    claims = claims.rename(columns={"fill_date": "service_date"})
    claims["claim_id"] = [f"CLM{i:08d}" for i in range(len(claims))]

    return claims[
        [
            "claim_id",
            "patient_token",
            "product",
            "hcp_id",
            "payer_channel",
            "plan_id",
            "region_id",
            "territory_id",
            "service_date",
            "adjudication_date",
            "is_late_adjudication",
            "fill_number",
        ]
    ].sort_values(["service_date", "claim_id"]).reset_index(drop=True)
