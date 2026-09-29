"""
Generator-side QA for data/bronze/: sanity-checks that each per-source
distortion function actually did what config.py says it should, by
comparing the exported Parquet files against a freshly rebuilt true world
for the same seed.

This is a build tool, not an analysis module - it lives in generator/
alongside export.py, not in dbt/sql/notebooks, and it only ever uses the
seed to reproduce ground truth counts for comparison. It never inspects
or prints which effects got activated; nothing about the answer key's
*content* leaks into these checks or their output.

Usage: python validate_bronze.py --seed 42
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import config as cfg
import effects
from export import ALL_MODULE_NAMES
from sources import common

pd.set_option("display.width", 160)
pd.set_option("display.max_colwidth", 60)


def load_bronze() -> dict[str, pd.DataFrame]:
    names = [
        "rx_audit",
        "claims",
        "sp_hub",
        "sell_in",
        "crm_calls",
        "rep_roster",
        "hcp_master",
        "formulary",
        "alignment",
    ]
    tables = {}
    for name in names:
        path = cfg.BRONZE_DIR / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run export.py first")
        tables[name] = pd.read_parquet(path)
    return tables


def rebuild_ground_truth(seed: int) -> tuple[dict, pd.DataFrame]:
    """Reproduces exactly what export.py built for this seed: the effect-
    perturbed world, SP assignment, and the shared true-fills stream."""
    world = effects.build_and_seal(seed)
    rngs = common.spawn_rngs(seed, "sources", ALL_MODULE_NAMES + ["dispensing_sp", "fills"])
    common.assign_dispensing_sp(world, rngs["dispensing_sp"])
    fills = common.build_true_fills(world, rngs["fills"])
    return world, fills


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_claims_coverage(world: dict, claims: pd.DataFrame) -> list[dict]:
    """
    (1) claims.parquet should carry ~CLAIMS_PATIENT_COVERAGE of the true
    fill-generating patient population per channel, further reduced for
    Medicaid per CLAIMS_MEDICAID_UNDERCAPTURE. "True patient count" here is
    patients who actually reached first fill - claims can only ever cover
    someone who has a fill to be sampled from in the first place.
    """
    fillers = world["patients"].loc[world["patients"]["reached_first_fill"]]
    true_by_channel = fillers["payer_channel"].value_counts()
    actual_by_channel = claims.groupby("payer_channel")["patient_token"].nunique()

    rows = []
    for channel, true_n in true_by_channel.items():
        true_n = int(true_n)
        actual_n = int(actual_by_channel.get(channel, 0))
        expected_rate = cfg.CLAIMS_PATIENT_COVERAGE * (
            1 - cfg.CLAIMS_MEDICAID_UNDERCAPTURE if channel == "medicaid" else 1
        )
        actual_rate = actual_n / true_n if true_n else float("nan")
        rows.append(
            {
                "check": "1. claims coverage",
                "metric": f"distinct patients w/ claims ({channel})",
                "expected": f"~{expected_rate:.1%} of {true_n:,} fillers",
                "actual": f"{actual_n:,} ({actual_rate:.1%})",
                "status": "PASS" if abs(actual_rate - expected_rate) < 0.05 else "FAIL",
            }
        )
    return rows


def check_hcp_duplicates(hcp_master: pd.DataFrame) -> dict:
    """(2) hcp_master.parquet should have ~HCP_MASTER_DUPLICATE_RATE more
    distinct HCP records than the true 4,000-HCP roster."""
    true_n = cfg.N_HCPS
    actual_n = hcp_master["hcp_id"].nunique()
    expected_n = int(round(true_n * (1 + cfg.HCP_MASTER_DUPLICATE_RATE)))
    actual_extra_pct = actual_n / true_n - 1
    return {
        "check": "2. HCP duplicates",
        "metric": "distinct hcp_id count",
        "expected": f"~{expected_n:,} ({true_n:,} + {cfg.HCP_MASTER_DUPLICATE_RATE:.0%})",
        "actual": f"{actual_n:,} ({actual_extra_pct:+.1%} vs. true)",
        "status": "PASS" if abs(actual_extra_pct - cfg.HCP_MASTER_DUPLICATE_RATE) < 0.02 else "FAIL",
    }


def check_sp_hub(world: dict, sp_hub: pd.DataFrame) -> list[dict]:
    """
    (3) sp_hub.parquet should contain only Veltrana patients, and every
    row's status_code should belong to the vocabulary of the SP named in
    that same row - never another SP's code for the same status.
    """
    patients = world["patients"]
    veltrana_ids = set(patients.loc[patients["index_product"] == "VELTRANA", "patient_id"])
    non_veltrana_rows = int((~sp_hub["patient_id"].isin(veltrana_ids)).sum())

    code_to_sp = {
        code: sp for sp, code_map in cfg.SP_STATUS_CODE_MAPS.items() for code in code_map.values()
    }
    expected_sp = sp_hub["status_code"].map(code_to_sp)
    vocab_mismatches = int((expected_sp != sp_hub["sp"]).sum())

    return [
        {
            "check": "3. sp_hub scope",
            "metric": "rows for non-Veltrana patients",
            "expected": "0",
            "actual": f"{non_veltrana_rows:,} of {len(sp_hub):,}",
            "status": "PASS" if non_veltrana_rows == 0 else "FAIL",
        },
        {
            "check": "3. sp_hub vocab",
            "metric": "status_code not matching its own row's SP vocabulary",
            "expected": "0",
            "actual": f"{vocab_mismatches:,} of {len(sp_hub):,}",
            "status": "PASS" if vocab_mismatches == 0 else "FAIL",
        },
    ]


def check_rx_audit_noninteger(rx_audit: pd.DataFrame) -> dict:
    """(4) rx_audit.parquet's projected_units should be non-integer for the
    overwhelming majority of rows (the vendor projection noise)."""
    values = rx_audit["projected_units"].to_numpy()
    is_integer = np.isclose(values, np.round(values))
    pct_noninteger = 1 - is_integer.mean()
    return {
        "check": "4. rx_audit noise",
        "metric": "% of projected_units that are non-integer",
        "expected": "> 90%",
        "actual": f"{pct_noninteger:.1%}",
        "status": "PASS" if pct_noninteger > 0.90 else "FAIL",
    }


def check_sell_in_vs_claims(sell_in: pd.DataFrame, claims: pd.DataFrame) -> dict:
    """(5) sell-in and claims should NOT reconcile - different coverage,
    different timing, different lead/lag - so their Veltrana totals should
    visibly diverge rather than matching up."""
    sell_in_units = int(sell_in["units"].sum())
    veltrana_claims_rows = int((claims["product"] == "VELTRANA").sum())
    pct_diff = (sell_in_units - veltrana_claims_rows) / veltrana_claims_rows
    return {
        "check": "5. sell-in vs. claims",
        "metric": "sell-in units vs. Veltrana claim rows",
        "expected": "visibly divergent (not reconciled)",
        "actual": f"{sell_in_units:,} vs. {veltrana_claims_rows:,} ({pct_diff:+.1%})",
        "status": "PASS" if abs(pct_diff) > 0.02 else "FAIL",
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main(seed: int) -> None:
    print(f"Rebuilding ground truth for seed={seed} to validate against...")
    world, fills = rebuild_ground_truth(seed)
    tables = load_bronze()

    results = []
    results += check_claims_coverage(world, tables["claims"])
    results.append(check_hcp_duplicates(tables["hcp_master"]))
    results += check_sp_hub(world, tables["sp_hub"])
    results.append(check_rx_audit_noninteger(tables["rx_audit"]))
    results.append(check_sell_in_vs_claims(tables["sell_in"], tables["claims"]))

    summary = pd.DataFrame(results)[["check", "metric", "expected", "actual", "status"]]
    print()
    print(summary.to_string(index=False))

    n_fail = (summary["status"] == "FAIL").sum()
    print()
    print(f"{len(summary) - n_fail}/{len(summary)} checks passed" + (f", {n_fail} FAILED" if n_fail else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.seed)
