"""
Alignment (zip-to-territory-style): zip grain, annual cadence, 100%
coverage. Carries one always-on structural quirk - a single mid-period
realignment, at config.ALIGNMENT_REALIGNMENT_DATE - where a subset of
zips permanently move to a different territory. This is a fixed data
characteristic like the January deductible reset, not a sampled effect
from the catalog, so it isn't randomized per run.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from faker import Faker

import config as cfg


def generate(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    territories = world["territories"].set_index("territory_id")
    fake = Faker()
    Faker.seed(int(rng.integers(0, 2**31 - 1)))

    zip_assignment: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    for territory in world["territories"].itertuples(index=False):
        n_assigned = 0
        while n_assigned < cfg.N_ZIPS_PER_TERRITORY:
            z = fake.zipcode()
            if z in used:
                continue
            used.add(z)
            zip_assignment[z] = (territory.territory_id, territory.region_id)
            n_assigned += 1

    zips = list(zip_assignment.keys())
    n_realign = int(len(zips) * cfg.ALIGNMENT_REALIGNMENT_FRACTION)
    realigned_zips = rng.choice(zips, size=n_realign, replace=False)

    new_territory_for = {}
    all_territory_ids = territories.index.values
    for z in realigned_zips:
        current = zip_assignment[z][0]
        candidates = all_territory_ids[all_territory_ids != current]
        new_territory_for[z] = str(rng.choice(candidates))

    years = range(cfg.SIM_START.year, cfg.SIM_END.year + 1)
    rows = []
    for year in years:
        effective_date = date(year, 1, 1)
        realign_active = effective_date >= cfg.ALIGNMENT_REALIGNMENT_DATE
        for z, (territory_id, region_id) in zip_assignment.items():
            if realign_active and z in new_territory_for:
                territory_id = new_territory_for[z]
                region_id = territories.loc[territory_id, "region_id"]
            rows.append(
                {
                    "zip": z,
                    "territory_id": territory_id,
                    "region_id": region_id,
                    "effective_date": effective_date,
                }
            )

    return pd.DataFrame(rows)
