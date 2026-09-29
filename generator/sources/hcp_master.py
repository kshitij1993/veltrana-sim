"""
HCP master (OneKey-style MDM): HCP grain, quarterly snapshot cadence,
100% coverage. Quirks: ~8% duplicate records - the same real person
entered as a second MDM record because intake never cross-referenced the
existing one, so NPI comes through blank or mistyped and name/address get
independently reformatted (initials, suffixes, street abbreviations).
That's what makes golden-record matching in Phase 2 a fuzzy-match problem
on name + address + specialty rather than a trivial `GROUP BY npi` - and
exactly why it's worth practicing. Also: address moves between snapshots,
and a small rate of specialty mislabeling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

import config as cfg

_STREET_ABBREV = {
    "Street": "St",
    "Avenue": "Ave",
    "Suite": "Ste",
    "Road": "Rd",
    "Drive": "Dr",
    "Boulevard": "Blvd",
}


def _corrupt_npi(npi: str, rng: np.random.Generator, used_npis: set[str]) -> str:
    """
    Half the time the duplicate's NPI is just missing; the rest of the
    time it's a transposed-digit typo - either way, not a usable join
    key. Real NPIs here are dense and sequential (they only vary in the
    last few digits), so a random adjacent-digit transposition has a
    real chance of landing on some *other* HCP's actual NPI by pure
    accident. That would silently merge this duplicate into a
    completely unrelated person at the exact-NPI collapse step, with no
    fuzzy-match evidence trail - worse than not deduping at all. Retry
    until the typo lands somewhere unused, or give up and go blank.
    """
    if rng.random() < 0.5:
        return ""
    for _ in range(20):
        digits = list(npi)
        pos = int(rng.integers(0, len(digits) - 1))
        digits[pos], digits[pos + 1] = digits[pos + 1], digits[pos]
        candidate = "".join(digits)
        if candidate not in used_npis:
            used_npis.add(candidate)
            return candidate
    return ""


def _mangle_name(first: str, last: str, rng: np.random.Generator) -> tuple[str, str]:
    variant = int(rng.integers(0, 3))
    if variant == 0:
        return f"{first[0]}.", last.upper()
    if variant == 1:
        suffix = rng.choice(["JR", "MD", "II"])
        return first, f"{last} {suffix}"
    return first, last


def _maybe_abbreviate(address: str, abbreviate: bool) -> str:
    if not abbreviate:
        return address
    for full, short in _STREET_ABBREV.items():
        address = address.replace(full, short)
    return address


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

    # One mangled identity per duplicate HCP, held constant across all of
    # its quarterly rows - a bogus MDM record still describes one person
    # consistently over time, just like a real one does.
    source_hcps = hcps.set_index("hcp_id")
    name_map = {
        hid: _mangle_name(source_hcps.loc[hid, "first_name"], source_hcps.loc[hid, "last_name"], rng)
        for hid in dupe_source_ids
    }
    used_npis = set(hcps["npi"])
    npi_map = {hid: _corrupt_npi(source_hcps.loc[hid, "npi"], rng, used_npis) for hid in dupe_source_ids}
    abbreviate_map = {hid: bool(rng.random() < 0.5) for hid in dupe_source_ids}

    dupes = master.loc[master["hcp_id"].isin(dupe_source_ids)].copy()
    source_id = dupes["hcp_id"]
    dupes["first_name"] = source_id.map(lambda h: name_map[h][0])
    dupes["last_name"] = source_id.map(lambda h: name_map[h][1])
    dupes["npi"] = source_id.map(npi_map)
    dupes["address"] = [
        _maybe_abbreviate(addr, abbreviate_map[h]) for addr, h in zip(dupes["address"], source_id)
    ]
    dupes["hcp_id"] = source_id.map(dup_id_map)

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
