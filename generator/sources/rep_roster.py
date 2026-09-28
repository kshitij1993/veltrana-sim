"""
Rep roster (HR/field ops-style): rep x territory x month grain, monthly
cadence, 100% coverage. Vacancies (E2, if sampled) appear only in this
feed - no other dataset directly says "this territory had no rep" - which
is exactly the point per the design doc, and is read from
world["rep_vacancies"], not the answer key.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def generate(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    territories = world["territories"]
    months = pd.date_range(cfg.SIM_START, cfg.SIM_END, freq="MS")
    vacancy = world.get("rep_vacancies")
    vacant_territory = None
    vacancy_start = vacancy_end = None
    if vacancy is not None and len(vacancy):
        row = vacancy.iloc[0]
        vacant_territory = row["territory_id"]
        vacancy_start = pd.Timestamp(row["start_date"])
        vacancy_end = pd.Timestamp(row["end_date"])

    rows = []
    for territory in territories.itertuples(index=False):
        for month in months:
            is_vacant = (
                vacant_territory == territory.territory_id
                and vacancy_start <= month < vacancy_end
            )
            rows.append(
                {
                    "territory_id": territory.territory_id,
                    "region_id": territory.region_id,
                    "month": month,
                    "rep_id": None if is_vacant else territory.rep_id,
                    "status": "vacant" if is_vacant else "active",
                }
            )

    return pd.DataFrame(rows)
