"""
Effect injection: Phase 0 build-order step 2. Samples 5-7 candidates from
the effect catalog in the README, randomizes their location, timing, and
magnitude, and perturbs the true world's outputs accordingly (e.g. flips
some patients' index product, shortens some patients' persistence, or
records a ground-truth parameter table for a per-source module that
doesn't exist yet, like the Rx audit restatement or the SP inventory
build).

This module writes `answer_key.json` and nothing else does. No per-source
derivation module (sources/*.py), dbt model, SQL script, or notebook is
allowed to read that file before Phase 5 - the point of the sealed key is
that the analysis has to rediscover what got planted, not confirm it.

Always-on traps (targeting selection bias, the January deductible reset,
channel-mix Simpson's paradox) are NOT part of this module. Per the design
doc they're applied unconditionally in per-source derivation (build-order
step 4), regardless of which candidates get sampled here.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
from world import build_true_world

ANSWER_KEY_PATH = Path(__file__).parent / "answer_key.json"

N_EFFECTS_MIN = 5
N_EFFECTS_MAX = 7

NON_VELTRANA_PRODUCTS = list(cfg.BASELINE_SOURCE_SHARE.keys())
NON_VELTRANA_PROBS = np.array(list(cfg.BASELINE_SOURCE_SHARE.values()))
NON_VELTRANA_PROBS = NON_VELTRANA_PROBS / NON_VELTRANA_PROBS.sum()


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _add_months(d, n: int) -> pd.Timestamp:
    return (pd.Timestamp(d).to_period("M") + n).to_timestamp()


def _random_month_start(rng: np.random.Generator, earliest, latest) -> pd.Timestamp:
    earliest_p = pd.Timestamp(earliest).to_period("M")
    latest_p = pd.Timestamp(latest).to_period("M")
    span = (latest_p - earliest_p).n
    offset = int(rng.integers(0, max(span, 0) + 1))
    return (earliest_p + offset).to_timestamp()


def _random_quarter_start(rng: np.random.Generator, earliest, latest) -> pd.Timestamp:
    month = _random_month_start(rng, earliest, latest)
    return month.to_period("Q").to_timestamp()


def _fmt(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _reassign_to_non_veltrana(rng: np.random.Generator, n: int) -> np.ndarray:
    return rng.choice(NON_VELTRANA_PRODUCTS, size=n, p=NON_VELTRANA_PROBS)


# ---------------------------------------------------------------------------
# E1: payer formulary downgrade
# ---------------------------------------------------------------------------


def _sample_e1(rng: np.random.Generator, world: dict) -> dict:
    patients = world["patients"]
    dimension = str(rng.choice(["plan", "region"]))
    if dimension == "plan":
        candidates = patients.loc[
            patients["payer_channel"].isin(["commercial", "medicare_partd"]), "plan_id"
        ].unique()
    else:
        candidates = world["territories"]["region_id"].unique()
    target = str(rng.choice(candidates))

    start = _random_quarter_start(rng, _add_months(cfg.LAUNCH_DATE, 2), _add_months(cfg.SIM_END, -3))
    return {
        "dimension": dimension,
        "target": target,
        "start_date": start,
        "nbrx_impact": round(float(rng.uniform(0.15, 0.40)), 4),
    }


def _apply_e1(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    col = "plan_id" if params["dimension"] == "plan" else "region_id"
    mask = (
        (patients[col] == params["target"])
        & (patients["index_product"] == "VELTRANA")
        & (patients["index_start_date"] >= params["start_date"])
    )
    idx = patients.index[mask].to_numpy()
    n_flip = int(round(len(idx) * params["nbrx_impact"]))
    if n_flip:
        flip_idx = rng.choice(idx, size=n_flip, replace=False)
        patients.loc[flip_idx, "index_product"] = _reassign_to_non_veltrana(rng, n_flip)
    params["n_patients_affected"] = n_flip

    if params["dimension"] == "plan":
        # Ground truth for the future formulary source module - a plan-grain
        # decision, unlike the region-dimension case, which has no formulary
        # analogue and is left for that module to leave alone.
        world["formulary_downgrades"] = pd.DataFrame(
            [{"plan_id": params["target"], "start_date": params["start_date"]}]
        )


def _describe_e1(params: dict) -> str:
    return (
        f"Formulary downgrade for {params['dimension']} '{params['target']}' starting "
        f"{_fmt(params['start_date'])}, cutting Veltrana NBRx there by "
        f"{params['nbrx_impact']:.0%} ({params['n_patients_affected']} patients flipped)."
    )


# ---------------------------------------------------------------------------
# E2: rep vacancy
# ---------------------------------------------------------------------------


def _sample_e2(rng: np.random.Generator, world: dict) -> dict:
    territory = str(rng.choice(world["territories"]["territory_id"].unique()))
    duration_months = int(rng.integers(2, 7))
    start = _random_month_start(rng, _add_months(cfg.LAUNCH_DATE, 1), _add_months(cfg.SIM_END, -duration_months))
    return {
        "territory_id": territory,
        "start_date": start,
        "duration_months": duration_months,
        "end_date": _add_months(start, duration_months),
        "nbrx_impact": round(float(rng.uniform(0.20, 0.40)), 4),
    }


def _apply_e2(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    mask = (
        (patients["territory_id"] == params["territory_id"])
        & (patients["index_product"] == "VELTRANA")
        & (patients["index_start_date"] >= params["start_date"])
        & (patients["index_start_date"] < params["end_date"])
    )
    idx = patients.index[mask].to_numpy()
    n_flip = int(round(len(idx) * params["nbrx_impact"]))
    if n_flip:
        flip_idx = rng.choice(idx, size=n_flip, replace=False)
        patients.loc[flip_idx, "index_product"] = _reassign_to_non_veltrana(rng, n_flip)
    params["n_patients_affected"] = n_flip

    world["rep_vacancies"] = pd.DataFrame(
        [{"territory_id": params["territory_id"], "start_date": params["start_date"], "end_date": params["end_date"]}]
    )


def _describe_e2(params: dict) -> str:
    return (
        f"Rep vacancy in territory {params['territory_id']} from {_fmt(params['start_date'])} "
        f"for {params['duration_months']} months ({params['n_patients_affected']} patients affected)."
    )


# ---------------------------------------------------------------------------
# E3: call saturation
# ---------------------------------------------------------------------------


def _sample_e3(rng: np.random.Generator, world: dict) -> dict:
    top_n = int(rng.integers(1, 4))
    return {
        "calls_per_quarter_threshold": int(rng.integers(4, 9)),
        "top_deciles": list(range(11 - top_n, 11)),
        "negative_return_factor": round(float(rng.uniform(0.10, 0.35)), 4),
    }


def _apply_e3(rng: np.random.Generator, world: dict, params: dict) -> None:
    # No CRM call events exist yet in the true world (sources/ hasn't built
    # that module) - this effect is pure ground truth for the future CRM
    # calls generator and promotional-response module to read, not a
    # direct mutation of patients/hcps.
    world["call_response_curve"] = pd.DataFrame(
        [
            {
                "calls_per_quarter_threshold": params["calls_per_quarter_threshold"],
                "top_deciles": ",".join(map(str, params["top_deciles"])),
                "negative_return_factor": params["negative_return_factor"],
            }
        ]
    )


def _describe_e3(params: dict) -> str:
    deciles = ", ".join(map(str, params["top_deciles"]))
    return (
        f"Call saturation above {params['calls_per_quarter_threshold']} calls/quarter for "
        f"potential deciles [{deciles}]: {params['negative_return_factor']:.0%} negative "
        f"marginal return past the threshold."
    )


# ---------------------------------------------------------------------------
# E4: copay-driven abandonment
# ---------------------------------------------------------------------------

_COPAY_DIST = {
    "commercial": (75, 40, 0, 300),
    "medicare_partd": (45, 20, 0, 200),
    "medicaid": (5, 5, 0, 30),
    "cash_other": (500, 150, 100, 2000),
}


def _sample_e4(rng: np.random.Generator, world: dict) -> dict:
    return {
        "copay_threshold": int(rng.integers(50, 151)),
        "abandonment_uplift": round(float(rng.uniform(0.10, 0.30)), 4),
    }


def _apply_e4(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    n = len(patients)
    channel = patients["payer_channel"].values
    copay = np.zeros(n)
    for chan, (mean, sd, lo, hi) in _COPAY_DIST.items():
        chan_mask = channel == chan
        n_chan = int(chan_mask.sum())
        if n_chan:
            copay[chan_mask] = np.clip(rng.normal(mean, sd, size=n_chan), lo, hi)
    patients["estimated_copay"] = copay

    eligible = (
        (copay > params["copay_threshold"])
        & (patients["index_product"] == "VELTRANA").values
        & ~patients["abandoned"].values
    )
    idx = patients.index[eligible].to_numpy()
    n_flip = int(round(len(idx) * params["abandonment_uplift"]))
    if n_flip:
        flip_idx = rng.choice(idx, size=n_flip, replace=False)
        patients.loc[flip_idx, "abandoned"] = True
        patients.loc[flip_idx, "reached_first_fill"] = False
    params["n_patients_affected"] = n_flip


def _describe_e4(params: dict) -> str:
    return (
        f"Copay-driven abandonment above ${params['copay_threshold']}: "
        f"+{params['abandonment_uplift']:.0%} abandonment "
        f"({params['n_patients_affected']} patients flipped to abandoned)."
    )


# ---------------------------------------------------------------------------
# E5: vendor methodology restatement
# ---------------------------------------------------------------------------


def _sample_e5(rng: np.random.Generator, world: dict) -> dict:
    return {
        "restatement_month": _random_month_start(rng, cfg.SIM_START, cfg.SIM_END),
        "shift_pct": round(float(rng.uniform(0.05, 0.15)), 4),
        "direction": int(rng.choice([-1, 1])),
    }


def _apply_e5(rng: np.random.Generator, world: dict, params: dict) -> None:
    # Rx audit projection doesn't exist yet as a true-world quantity (it's
    # derived per-source from claims/fills). This is ground truth for that
    # future module to apply as an artificial shift on top of its own
    # otherwise-correct projection for the named month.
    world["vendor_restatement"] = pd.DataFrame(
        [
            {
                "restatement_month": params["restatement_month"],
                "shift_pct": params["shift_pct"],
                "direction": params["direction"],
            }
        ]
    )


def _describe_e5(params: dict) -> str:
    sign = "+" if params["direction"] > 0 else "-"
    return (
        f"Rx audit vendor restatement in {_fmt(params['restatement_month'])}: "
        f"{sign}{params['shift_pct']:.0%} artificial shift."
    )


# ---------------------------------------------------------------------------
# E6: source-of-business skew
# ---------------------------------------------------------------------------


def _sample_e6(rng: np.random.Generator, world: dict) -> dict:
    return {"target_share": round(float(rng.uniform(0.40, 0.70)), 4)}


def _apply_e6(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    n = len(patients)
    is_switch = np.zeros(n, dtype=bool)
    prior_product = np.full(n, "", dtype=object)

    veltrana_post = np.where(
        (
            (patients["index_product"] == "VELTRANA")
            & (patients["index_start_date"] >= np.datetime64(cfg.LAUNCH_DATE))
        ).values
    )[0]
    # Baseline: about half of Veltrana starts are switches from an existing
    # therapy, half are treatment-naive. Only switches have a source product.
    switch_flags = rng.random(len(veltrana_post)) < 0.5
    switch_idx = veltrana_post[switch_flags]
    is_switch[switch_idx] = True

    other_products = [p for p in NON_VELTRANA_PRODUCTS if p != "DERMAVEX"]
    other_probs = np.array([cfg.BASELINE_SOURCE_SHARE[p] for p in other_products])
    other_probs = other_probs / other_probs.sum()

    from_dermavex = rng.random(len(switch_idx)) < params["target_share"]
    prior_product[switch_idx[from_dermavex]] = "DERMAVEX"
    remaining = switch_idx[~from_dermavex]
    if len(remaining):
        prior_product[remaining] = rng.choice(other_products, size=len(remaining), p=other_probs)

    patients["is_switch"] = is_switch
    patients["prior_product"] = prior_product
    params["n_switch_patients"] = int(len(switch_idx))
    params["n_from_dermavex"] = int(from_dermavex.sum())


def _describe_e6(params: dict) -> str:
    return (
        f"Source-of-business skew: {params['target_share']:.0%} of Veltrana switches "
        f"({params['n_from_dermavex']} of {params['n_switch_patients']}) sourced from Dermavex."
    )


# ---------------------------------------------------------------------------
# E7: competitor momentum shift
# ---------------------------------------------------------------------------


def _sample_e7(rng: np.random.Generator, world: dict) -> dict:
    start = _random_month_start(rng, _add_months(cfg.LAUNCH_DATE, 1), _add_months(cfg.SIM_END, -2))
    return {
        "start_date": start,
        "magnitude": round(float(rng.uniform(0.10, 0.25)), 4),
    }


def _apply_e7(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    if "is_switch" in patients.columns:
        naive = ~patients["is_switch"].values
    else:
        naive = np.ones(len(patients), dtype=bool)

    mask = (
        naive
        & (patients["index_start_date"] >= params["start_date"]).values
        & (~patients["index_product"].isin(["VELTRANA", "ORELTA"])).values
    )
    idx = patients.index[mask].to_numpy()
    n_flip = int(round(len(idx) * params["magnitude"]))
    if n_flip:
        flip_idx = rng.choice(idx, size=n_flip, replace=False)
        patients.loc[flip_idx, "index_product"] = "ORELTA"
    params["n_patients_affected"] = n_flip


def _describe_e7(params: dict) -> str:
    return (
        f"Orelta (Comp D) momentum shift among naive starts from {_fmt(params['start_date'])}: "
        f"+{params['magnitude']:.0%} share ({params['n_patients_affected']} patients flipped)."
    )


# ---------------------------------------------------------------------------
# E8: speaker program halo
# ---------------------------------------------------------------------------


def _sample_e8(rng: np.random.Generator, world: dict) -> dict:
    region = str(rng.choice(world["territories"]["region_id"].unique()))
    start = _random_month_start(rng, _add_months(cfg.LAUNCH_DATE, 1), _add_months(cfg.SIM_END, -2))
    return {
        "region_id": region,
        "start_date": start,
        "adoption_lift": round(float(rng.uniform(0.05, 0.20)), 4),
        "attendee_fraction": round(float(rng.uniform(0.05, 0.15)), 4),
    }


def _apply_e8(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    hcps = world["hcps"]

    region_hcps = hcps[hcps["region_id"] == params["region_id"]]
    n_attendees = max(1, int(round(len(region_hcps) * params["attendee_fraction"])))
    attendee_ids = rng.choice(region_hcps["hcp_id"].values, size=n_attendees, replace=False)

    attendee_hcos = hcps.loc[hcps["hcp_id"].isin(attendee_ids), "hco_id"].unique()
    peer_hcps = hcps.loc[
        hcps["hco_id"].isin(attendee_hcos) & ~hcps["hcp_id"].isin(attendee_ids), "hcp_id"
    ].values

    mask = (
        patients["prescriber_hcp_id"].isin(peer_hcps)
        & (patients["index_start_date"] >= params["start_date"])
        & (patients["index_product"] != "VELTRANA")
    )
    idx = patients.index[mask].to_numpy()
    n_flip = int(round(len(idx) * params["adoption_lift"]))
    if n_flip:
        flip_idx = rng.choice(idx, size=n_flip, replace=False)
        patients.loc[flip_idx, "index_product"] = "VELTRANA"

    world["speaker_program_attendees"] = pd.DataFrame({"hcp_id": attendee_ids})
    params["n_attendees"] = n_attendees
    params["n_patients_affected"] = n_flip


def _describe_e8(params: dict) -> str:
    return (
        f"Speaker program halo in {params['region_id']} from {_fmt(params['start_date'])} "
        f"({params['n_attendees']} attendees): +{params['adoption_lift']:.0%} adoption among "
        f"peer-HCP patients ({params['n_patients_affected']} flipped to Veltrana)."
    )


# ---------------------------------------------------------------------------
# E9: SP inventory build
# ---------------------------------------------------------------------------


def _sample_e9(rng: np.random.Generator, world: dict) -> dict:
    return {
        "quarter": _random_quarter_start(rng, cfg.LAUNCH_DATE, _add_months(cfg.SIM_END, -1)),
        "excess_weeks": int(rng.integers(1, 4)),
    }


def _apply_e9(rng: np.random.Generator, world: dict, params: dict) -> None:
    # Sell-in (SP x NDC x day) doesn't exist yet as a true-world table - this
    # is ground truth for the future sell-in source module to build the
    # sell-in/sell-out divergence from.
    world["sp_inventory_build"] = pd.DataFrame(
        [{"quarter": params["quarter"], "excess_weeks": params["excess_weeks"]}]
    )


def _describe_e9(params: dict) -> str:
    return f"SP inventory build in {_fmt(params['quarter'])}: {params['excess_weeks']} weeks excess supply."


# ---------------------------------------------------------------------------
# E10: SP-level persistence gap
# ---------------------------------------------------------------------------


def _sample_e10(rng: np.random.Generator, world: dict) -> dict:
    return {
        "sp": str(rng.choice(cfg.SPECIALTY_PHARMACIES)),
        "persistence_penalty": round(float(rng.uniform(0.10, 0.25)), 4),
    }


def _apply_e10(rng: np.random.Generator, world: dict, params: dict) -> None:
    patients = world["patients"]
    n = len(patients)

    fillers = np.where(
        ((patients["index_product"] == "VELTRANA") & patients["reached_first_fill"]).values
    )[0]
    dispensing_sp = np.full(n, "", dtype=object)
    sp_names = list(cfg.SP_SHARE.keys())
    sp_probs = np.array(list(cfg.SP_SHARE.values()))
    dispensing_sp[fillers] = rng.choice(sp_names, size=len(fillers), p=sp_probs)
    patients["dispensing_sp"] = dispensing_sp

    target_idx = fillers[dispensing_sp[fillers] == params["sp"]]
    if len(target_idx):
        current = patients.loc[target_idx, "persistence_months"].values.astype(float)
        reduced = np.clip(np.round(current * (1 - params["persistence_penalty"])), 1, None)
        patients.loc[target_idx, "persistence_months"] = reduced.astype(int)
    params["n_patients_affected"] = int(len(target_idx))


def _describe_e10(params: dict) -> str:
    return (
        f"Persistence gap at {params['sp']}: -{params['persistence_penalty']:.0%} relative "
        f"persistence ({params['n_patients_affected']} patients shortened)."
    )


# ---------------------------------------------------------------------------
# Catalog and orchestration
# ---------------------------------------------------------------------------

CATALOG = [
    {"id": "E1", "name": "Payer formulary downgrade", "sample": _sample_e1, "apply": _apply_e1, "describe": _describe_e1},
    {"id": "E2", "name": "Rep vacancy", "sample": _sample_e2, "apply": _apply_e2, "describe": _describe_e2},
    {"id": "E3", "name": "Call saturation", "sample": _sample_e3, "apply": _apply_e3, "describe": _describe_e3},
    {"id": "E4", "name": "Copay-driven abandonment", "sample": _sample_e4, "apply": _apply_e4, "describe": _describe_e4},
    {"id": "E5", "name": "Vendor methodology restatement", "sample": _sample_e5, "apply": _apply_e5, "describe": _describe_e5},
    {"id": "E6", "name": "Source-of-business skew", "sample": _sample_e6, "apply": _apply_e6, "describe": _describe_e6},
    {"id": "E7", "name": "Competitor momentum shift", "sample": _sample_e7, "apply": _apply_e7, "describe": _describe_e7},
    {"id": "E8", "name": "Speaker program halo", "sample": _sample_e8, "apply": _apply_e8, "describe": _describe_e8},
    {"id": "E9", "name": "SP inventory build", "sample": _sample_e9, "apply": _apply_e9, "describe": _describe_e9},
    {"id": "E10", "name": "SP-level persistence gap", "sample": _sample_e10, "apply": _apply_e10, "describe": _describe_e10},
]


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def inject_effects(world: dict, rng: np.random.Generator) -> list[dict]:
    """
    Samples 5-7 candidates without replacement, randomizes their params,
    and applies each to `world` in place. Returns the activated-effect
    records (id, name, params, description) that get sealed into the
    answer key - this is the only place that list is assembled.
    """
    n_effects = int(rng.integers(N_EFFECTS_MIN, N_EFFECTS_MAX + 1))
    chosen_ids = set(rng.choice([e["id"] for e in CATALOG], size=n_effects, replace=False).tolist())
    chosen = [e for e in CATALOG if e["id"] in chosen_ids]

    activated = []
    for effect in chosen:
        params = effect["sample"](rng, world)
        effect["apply"](rng, world, params)
        activated.append(
            {
                "id": effect["id"],
                "name": effect["name"],
                "params": _json_safe(params),
                "description": effect["describe"](params),
            }
        )
    return activated


def build_and_seal(seed: int) -> dict:
    """
    Runs the full Phase 1 build-order steps 1-2: builds the true world,
    samples and applies effects, and writes the sealed answer key. Returns
    the (now effect-perturbed) world dict for per-source derivation to
    consume in step 3.
    """
    world = build_true_world(seed)
    # A generator derived from, but decoupled from, the world-building rng
    # so effect sampling doesn't share a draw sequence with world.py.
    seed_rng = np.random.default_rng(seed)
    effect_rng = np.random.default_rng(int(seed_rng.integers(0, 2**31 - 1)))

    activated = inject_effects(world, effect_rng)
    activated.sort(key=lambda e: int(e["id"][1:]))

    answer_key = {
        "seed": seed,
        "n_effects_activated": len(activated),
        "activated_effects": activated,
    }
    ANSWER_KEY_PATH.write_text(json.dumps(answer_key, indent=2))
    return world


if __name__ == "__main__":
    world = build_and_seal(seed=42)
    key = json.loads(ANSWER_KEY_PATH.read_text())
    print(f"Wrote {ANSWER_KEY_PATH}")
    print(f"Activated {key['n_effects_activated']} effects:")
    for effect in key["activated_effects"]:
        print(f"  {effect['id']} ({effect['name']}): {effect['description']}")
