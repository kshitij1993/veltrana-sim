"""
Builds the single "true world": every HCP, territory, patient, and clinical/
access event, undistorted. This is ground truth. Nothing here knows about
claims coverage gaps, Rx audit projection noise, or SP status-code quirks -
that distortion happens later, per source, in sources/*.py, reading from
this world.

Effects (effects.py) get applied to the *outputs* of this module before
per-source derivation runs, so world.py itself has no knowledge of the
effect catalog either.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

import config as cfg


def _daterange_days(start, end) -> int:
    return (end - start).days


def generate_territories(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    rep_n = 0
    for region_id in range(1, cfg.N_REGIONS + 1):
        for t in range(1, cfg.TERRITORIES_PER_REGION + 1):
            rep_n += 1
            territory_id = f"T{region_id:02d}{t:02d}"
            rows.append(
                {
                    "territory_id": territory_id,
                    "region_id": f"R{region_id:02d}",
                    "rep_id": f"REP{rep_n:04d}",
                }
            )
    return pd.DataFrame(rows)


def generate_hcps(rng: np.random.Generator, territories: pd.DataFrame) -> pd.DataFrame:
    fake = Faker()
    Faker.seed(int(rng.integers(0, 2**31 - 1)))

    n = cfg.N_HCPS
    specialties = rng.choice(
        list(cfg.HCP_SPECIALTY_MIX.keys()),
        size=n,
        p=list(cfg.HCP_SPECIALTY_MIX.values()),
    )
    territory_ids = rng.choice(territories["territory_id"].values, size=n)

    # Group HCPs into HCOs (practices), roughly 3 HCPs per HCO on average.
    n_hcos = max(1, n // 3)
    hco_ids = rng.integers(0, n_hcos, size=n)

    # Potential decile: dermatologists skew higher-potential.
    base_decile = rng.integers(1, 11, size=n)
    derm_boost = (specialties == "dermatologist") * rng.integers(0, 2, size=n)
    potential_decile = np.clip(base_decile + derm_boost, 1, 10)

    npi_base = 1_000_000_000
    hcps = pd.DataFrame(
        {
            "hcp_id": [f"HCP{i:06d}" for i in range(n)],
            "npi": [str(npi_base + i) for i in range(n)],
            "first_name": [fake.first_name() for _ in range(n)],
            "last_name": [fake.last_name() for _ in range(n)],
            "specialty": specialties,
            "hco_id": [f"HCO{h:05d}" for h in hco_ids],
            "territory_id": territory_ids,
            "potential_decile": potential_decile,
        }
    )
    hcps = hcps.merge(territories, on="territory_id", how="left")
    return hcps


def _sample_payer(rng: np.random.Generator, n: int) -> pd.DataFrame:
    channel = rng.choice(
        list(cfg.CHANNEL_MIX.keys()), size=n, p=list(cfg.CHANNEL_MIX.values())
    )
    plan_id = np.empty(n, dtype=object)

    commercial_mask = channel == "commercial"
    n_comm = commercial_mask.sum()
    is_national = rng.random(n_comm) < cfg.NATIONAL_PBM_SHARE_OF_COMMERCIAL
    national_ids = rng.integers(1, cfg.N_NATIONAL_PBMS + 1, size=n_comm)
    regional_ids = rng.integers(1, cfg.N_REGIONAL_PLANS + 1, size=n_comm)
    comm_plan_ids = np.where(
        is_national,
        [f"PBM_NAT_{i}" for i in national_ids],
        [f"PLAN_REG_{i}" for i in regional_ids],
    )
    plan_id[commercial_mask] = comm_plan_ids

    for chan in ("medicare_partd", "medicaid", "cash_other"):
        mask = channel == chan
        plan_id[mask] = chan.upper()

    return pd.DataFrame({"payer_channel": channel, "plan_id": plan_id})


def _sample_index_dates(rng: np.random.Generator, n: int) -> np.ndarray:
    """
    Index therapy start dates across the full window. A mild upward drift
    in incidence over time (more diagnosed/treated patients later) rather
    than a flat uniform distribution, since that's how an expanding
    biologic-eligible population actually looks.
    """
    total_days = _daterange_days(cfg.SIM_START, cfg.SIM_END)
    # Linear drift: weight ~1.0 at start, ~1.6 at end.
    u = rng.random(n)
    # Inverse-CDF sample for a linearly increasing density on [0, total_days].
    a, b = 1.0, 1.6
    # CDF(x) = (a*x + (b-a)*x^2/(2*total_days)) / (a*total_days + (b-a)*total_days/2)
    # Solve via numeric search using np.interp against a precomputed grid.
    grid = np.linspace(0, total_days, 2000)
    density = a + (b - a) * (grid / total_days)
    cdf = np.cumsum(density)
    cdf = cdf / cdf[-1]
    days_offset = np.interp(u, cdf, grid).astype(int)
    return pd.Timestamp(cfg.SIM_START) + pd.to_timedelta(days_offset, unit="D")


def _choose_product(rng: np.random.Generator, index_dates: np.ndarray) -> np.ndarray:
    """
    Baseline (no planted-effect) product choice at each index date. Veltrana
    is unavailable before launch and ramps in afterward; effects.py will
    later perturb this ramp, formulary-driven shares, and switch behavior.
    """
    n = len(index_dates)
    products = np.empty(n, dtype=object)
    pre_launch_mask = index_dates < np.datetime64(cfg.LAUNCH_DATE)

    pre_products = list(cfg.BASELINE_SOURCE_SHARE.keys())
    pre_probs = list(cfg.BASELINE_SOURCE_SHARE.values())
    n_pre = pre_launch_mask.sum()
    products[pre_launch_mask] = rng.choice(pre_products, size=n_pre, p=pre_probs)

    post_mask = ~pre_launch_mask
    n_post = post_mask.sum()
    months_since_launch = np.array(
        [
            max(0, (pd.Timestamp(d).to_period("M") - pd.Timestamp(cfg.LAUNCH_DATE).to_period("M")).n)
            for d in index_dates[post_mask]
        ]
    )
    ramp = np.clip(months_since_launch / cfg.ACCESS_RAMP_MONTHS, 0, 1)
    veltrana_share = 0.12 * ramp  # true steady-state baseline share, pre-effect

    post_products = np.empty(n_post, dtype=object)
    draws = rng.random(n_post)
    is_veltrana = draws < veltrana_share
    post_products[is_veltrana] = "VELTRANA"

    remaining_mask = ~is_veltrana
    n_remaining = remaining_mask.sum()
    resid_probs = np.array(pre_probs)
    resid_probs = resid_probs / resid_probs.sum()
    post_products[remaining_mask] = rng.choice(pre_products, size=n_remaining, p=resid_probs)

    products[post_mask] = post_products
    return products


def generate_patients(rng: np.random.Generator, hcps: pd.DataFrame) -> pd.DataFrame:
    n = cfg.N_PATIENTS

    age = np.clip(rng.normal(48, 14, size=n), 18, 90).astype(int)
    sex = rng.choice(["F", "M"], size=n, p=[0.52, 0.48])

    payer = _sample_payer(rng, n)
    index_dates = _sample_index_dates(rng, n)
    products = _choose_product(rng, index_dates)

    # Prescriber: weighted toward higher-potential HCPs (not uniform), which
    # is what makes call-targeting selection bias real later on.
    weights = hcps["potential_decile"].values.astype(float)
    weights = weights / weights.sum()
    prescriber_idx = rng.choice(len(hcps), size=n, p=weights)
    prescriber_hcp_id = hcps["hcp_id"].values[prescriber_idx]
    region_id = hcps["region_id"].values[prescriber_idx]
    territory_id = hcps["territory_id"].values[prescriber_idx]

    patients = pd.DataFrame(
        {
            "patient_id": [f"PT{i:07d}" for i in range(n)],
            "age": age,
            "sex": sex,
            "payer_channel": payer["payer_channel"].values,
            "plan_id": payer["plan_id"].values,
            "prescriber_hcp_id": prescriber_hcp_id,
            "region_id": region_id,
            "territory_id": territory_id,
            "index_product": products,
            "index_start_date": index_dates,
        }
    )
    return patients


def simulate_journey(rng: np.random.Generator, patients: pd.DataFrame) -> pd.DataFrame:
    """
    Attaches the referral -> BV -> PA -> first fill -> persistence/
    discontinuation/switch outcome to every patient, using the baseline
    rates in config. Only meaningful for Veltrana starts (the SP/hub
    journey is Veltrana-specific per the data source design), but
    persistence and discontinuation are simulated for all products since
    claims-derived persistence applies market-wide.
    """
    n = len(patients)
    is_veltrana = (patients["index_product"] == "VELTRANA").values
    is_commercial = (patients["payer_channel"] == "commercial").values

    bv_complete = rng.random(n) < cfg.BASELINE_RATES["hub_referral_to_bv_complete"]

    pa_required = np.where(
        is_commercial, rng.random(n) < cfg.BASELINE_RATES["pa_required_commercial"], False
    )
    pa_approved_first = rng.random(n) < cfg.BASELINE_RATES["pa_approved_first_submission"]
    appeal_overturned = rng.random(n) < cfg.BASELINE_RATES["denial_appeal_overturn_rate"]

    pa_outcome = np.where(
        ~pa_required,
        "not_required",
        np.where(
            pa_approved_first,
            "approved_first_pass",
            np.where(appeal_overturned, "approved_on_appeal", "denied"),
        ),
    )

    abandoned = (pa_outcome != "denied") & (rng.random(n) < cfg.BASELINE_RATES["sp_abandonment_rate"])
    reached_first_fill = bv_complete & (pa_outcome != "denied") & ~abandoned

    referral_to_fill_days = np.clip(
        rng.normal(cfg.BASELINE_RATES["median_days_referral_to_fill"], 6, size=n), 3, 90
    ).astype(int)

    # Persistence: exponential hazard calibrated so ~70% survive 12 months
    # for the class baseline; Clarivo persists a bit better, adalimumab a
    # bit worse, reflecting real-world class dynamics (not a planted effect).
    persistence_multiplier = np.select(
        [
            patients["index_product"].values == "CLARIVO",
            patients["index_product"].values == "ADALIMUMAB_BIOSIM",
        ],
        [1.15, 0.85],
        default=1.0,
    )
    monthly_hazard_base = 1 - cfg.BASELINE_RATES["persistence_12mo"] ** (1 / 12)
    monthly_hazard = monthly_hazard_base / persistence_multiplier
    persistence_months = rng.geometric(np.clip(monthly_hazard, 0.001, 0.999), size=n)

    journey = pd.DataFrame(
        {
            "patient_id": patients["patient_id"].values,
            "bv_complete": bv_complete,
            "pa_required": pa_required,
            "pa_outcome": pa_outcome,
            "abandoned": abandoned,
            "reached_first_fill": reached_first_fill,
            "referral_to_fill_days": referral_to_fill_days,
            "persistence_months": persistence_months,
        }
    )
    return journey


def build_true_world(seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    territories = generate_territories(rng)
    hcps = generate_hcps(rng, territories)
    patients = generate_patients(rng, hcps)
    journey = simulate_journey(rng, patients)
    patients = patients.merge(journey, on="patient_id", how="left")

    return {
        "territories": territories,
        "hcps": hcps,
        "patients": patients,
    }


if __name__ == "__main__":
    world = build_true_world(seed=42)
    for name, df in world.items():
        print(f"\n=== {name} ({len(df):,} rows) ===")
        print(df.head(3).to_string())
        print(df.dtypes if name == "patients" else "")
