"""
HCP master (OneKey-style MDM): HCP grain, quarterly snapshot cadence,
100% coverage. Quirks: ~8% duplicate records (same NPI, a different MDM
key and slightly mangled name - exactly what golden-record matching in
Phase 2 is for), address moves between snapshots, and a small rate of
specialty mislabeling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

import config as cfg


def generate(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    hcps = world["hcps"]
    fake = Faker()
    Faker.seed(int(rng.integers(0, 2**31 - 1)))

    addresses = {
        hid: (fake.street_address(), fake.city(), fake.state_abbr(), fake.zipcode())
        for hid in hcps["hcp_id"]
    }

    quarters = pd.date_range(cfg.SIM_START, cfg.SIM_END, freq="QS")
    other_specialties = list(cfg.HCP_SPECIALTY_MIX.keys())

    snapshots = []
    for quarter in quarters:
        movers = hcps["hcp_id"].sample(
            frac=cfg.HCP_MASTER_ADDRESS_MOVE_RATE_PER_QUARTER,
            random_state=int(rng.integers(0, 2**31 - 1)),
        )
        for hid in movers:
            addresses[hid] = (fake.street_address(), fake.city(), fake.state_abbr(), fake.zipcode())

        snap = hcps.copy()
        snap["quarter"] = quarter
        snap["address"] = snap["hcp_id"].map(lambda h: addresses[h][0])
        snap["city"] = snap["hcp_id"].map(lambda h: addresses[h][1])
        snap["state"] = snap["hcp_id"].map(lambda h: addresses[h][2])
        snap["zip"] = snap["hcp_id"].map(lambda h: addresses[h][3])

        mismatched = snap.sample(
            frac=cfg.HCP_MASTER_SPECIALTY_MISMATCH_RATE,
            random_state=int(rng.integers(0, 2**31 - 1)),
        ).index
        if len(mismatched):
            snap.loc[mismatched, "specialty"] = rng.choice(other_specialties, size=len(mismatched))

        snapshots.append(snap)

    master = pd.concat(snapshots, ignore_index=True)

    dupe_source_ids = hcps["hcp_id"].sample(
        frac=cfg.HCP_MASTER_DUPLICATE_RATE, random_state=int(rng.integers(0, 2**31 - 1))
    ).values
    dup_id_map = {hid: f"HCPD{1_000_000 + i:07d}" for i, hid in enumerate(dupe_source_ids)}

    dupes = master.loc[master["hcp_id"].isin(dupe_source_ids)].copy()
    dupes["hcp_id"] = dupes["hcp_id"].map(dup_id_map)
    variant = rng.integers(0, 2, size=len(dupes))
    dupes["last_name"] = np.where(variant == 0, dupes["last_name"].str.upper(), dupes["last_name"])

    master = pd.concat([master, dupes], ignore_index=True)

    return master[
        [
            "hcp_id",
            "npi",
            "first_name",
            "last_name",
            "specialty",
            "hco_id",
            "territory_id",
            "region_id",
            "address",
            "city",
            "state",
            "zip",
            "quarter",
        ]
    ].sort_values(["quarter", "hcp_id"]).reset_index(drop=True)
