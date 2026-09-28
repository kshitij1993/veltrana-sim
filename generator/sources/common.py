"""
Shared helpers for the per-source derivation modules (build-order step 3).

The most important thing here is `build_true_fills`: the single true
dispense-event stream that rx_audit.py, claims.py, sp_hub.py, and
sell_in.py all derive their own imperfect view from. Building it once and
sharing it is what makes source reconciliation meaningful instead of
cosmetic - the same underlying fill shows up (differently distorted) in
every one of those four datasets, instead of each module inventing its own
disconnected event stream.

`assign_dispensing_sp` is the other piece of shared ground truth: which of
the 3 specialty pharmacies dispensed a given Veltrana patient's therapy.
E10 (SP-level persistence gap) may have already assigned it for Veltrana
patients who reached first fill; this fills in the rest so every Veltrana
patient - fillers and non-fillers alike, since referral/BV/PA all happen
before the fill outcome is known - has one.

None of this module, or anything in sources/, reads answer_key.json.
"""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg


# ---------------------------------------------------------------------------
# RNG derivation
# ---------------------------------------------------------------------------


def spawn_rngs(seed: int, salt: str, names: list[str]) -> dict[str, np.random.Generator]:
    """
    One independent RNG per name, all deterministic from (seed, salt), and
    decoupled from world.py's and effects.py's own draw sequences so
    per-source randomness doesn't depend on module call order.
    """
    base = np.random.SeedSequence([seed, zlib.crc32(salt.encode())])
    children = base.spawn(len(names))
    return {name: np.random.default_rng(child) for name, child in zip(names, children)}


# ---------------------------------------------------------------------------
# Shared true-world derivations
# ---------------------------------------------------------------------------


def assign_dispensing_sp(world: dict, rng: np.random.Generator) -> None:
    patients = world["patients"]
    veltrana_mask = (patients["index_product"] == "VELTRANA").values

    if "dispensing_sp" not in patients.columns:
        patients["dispensing_sp"] = ""
    else:
        patients["dispensing_sp"] = patients["dispensing_sp"].fillna("")

    unassigned = veltrana_mask & (patients["dispensing_sp"].values == "")
    idx = np.where(unassigned)[0]
    if len(idx):
        sp_names = list(cfg.SP_SHARE.keys())
        sp_probs = np.array(list(cfg.SP_SHARE.values()))
        sp_probs = sp_probs / sp_probs.sum()
        patients.loc[patients.index[idx], "dispensing_sp"] = rng.choice(
            sp_names, size=len(idx), p=sp_probs
        )


def _veltrana_fill_offsets(k: np.ndarray) -> np.ndarray:
    """Day offset of the k-th fill (0-indexed) from the first fill."""
    steady = cfg.PRODUCT_FILL_INTERVAL_DAYS["VELTRANA"]
    induction = cfg.VELTRANA_INDUCTION_INTERVAL_DAYS
    return np.where(k == 0, 0, np.where(k == 1, induction, induction + steady * (k - 1)))


def build_true_fills(world: dict, rng: np.random.Generator) -> pd.DataFrame:
    """
    Every actual dispense event for every patient who reached first fill:
    the first fill (offset by their referral-to-fill delay) plus refills at
    each product's dosing cadence, until persistence runs out or the data
    window (SIM_END) ends, whichever comes first.
    """
    patients = world["patients"]
    fillers = patients.loc[patients["reached_first_fill"]].reset_index(drop=True)

    sim_end = np.datetime64(cfg.SIM_END)
    index_start = pd.to_datetime(fillers["index_start_date"]).values
    first_fill_date = index_start + fillers["referral_to_fill_days"].values.astype("timedelta64[D]")
    discontinuation_date = index_start + (
        fillers["persistence_months"].values.astype(int) * 30
    ).astype("timedelta64[D]")
    cutoff = np.minimum(discontinuation_date, sim_end)

    keep = first_fill_date <= cutoff
    fillers = fillers.loc[keep].reset_index(drop=True)
    first_fill_date = first_fill_date[keep]
    cutoff = cutoff[keep]

    chunks = []
    for product in fillers["index_product"].unique():
        group_mask = (fillers["index_product"] == product).values
        group = fillers.loc[group_mask]
        start = first_fill_date[group_mask]
        end = cutoff[group_mask]
        days_available = ((end - start) / np.timedelta64(1, "D")).astype(int)

        if product == "VELTRANA":
            steady = cfg.PRODUCT_FILL_INTERVAL_DAYS["VELTRANA"]
            max_k = int(np.ceil(days_available.max() / steady)) + 2 if len(days_available) else 0
            k_arr = np.arange(max_k + 1)
            offsets = _veltrana_fill_offsets(k_arr)
        else:
            interval = cfg.PRODUCT_FILL_INTERVAL_DAYS[product]
            max_k = int(np.ceil(days_available.max() / interval)) if len(days_available) else 0
            k_arr = np.arange(max_k + 1)
            offsets = k_arr * interval

        mask = offsets[None, :] <= days_available[:, None]
        row_idx, col_idx = np.where(mask)
        if len(row_idx) == 0:
            continue

        fill_dates = start[row_idx] + offsets[col_idx].astype("timedelta64[D]")
        chunks.append(
            pd.DataFrame(
                {
                    "patient_id": group["patient_id"].values[row_idx],
                    "product": product,
                    "hcp_id": group["prescriber_hcp_id"].values[row_idx],
                    "payer_channel": group["payer_channel"].values[row_idx],
                    "plan_id": group["plan_id"].values[row_idx],
                    "region_id": group["region_id"].values[row_idx],
                    "territory_id": group["territory_id"].values[row_idx],
                    "fill_date": fill_dates,
                    "fill_number": col_idx + 1,
                }
            )
        )

    fills = pd.concat(chunks, ignore_index=True)
    fills["is_first_fill"] = fills["fill_number"] == 1
    fills = fills.sort_values(["patient_id", "fill_date"]).reset_index(drop=True)
    return fills


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def tokenize_id(patient_id: str, salt: str = "laad") -> str:
    return hashlib.sha1(f"{salt}:{patient_id}".encode()).hexdigest()[:16]


def write_bronze(df: pd.DataFrame, name: str) -> Path:
    cfg.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    if cfg.EXPORT_FORMAT == "parquet":
        path = cfg.BRONZE_DIR / f"{name}.parquet"
        df.to_parquet(path, index=False)
    else:
        path = cfg.BRONZE_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
    return path
