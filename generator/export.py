"""
Phase 1 build-order steps 3 and 5: takes the effect-perturbed true world
from effects.py, runs every per-source derivation module in sources/ to
build its own imperfect view, and writes each to data/bronze/.

Always-on traps (targeting selection bias, the January deductible reset,
channel-mix Simpson's paradox) live inside the individual source modules
that they apply to (crm_calls.py, rx_audit/claims, formulary/patients),
not in a separate step here.

Nothing this script calls reads answer_key.json. Only effects.py writes
it, and only Phase 5 grading should read it.
"""

from __future__ import annotations

import argparse
import time

import config as cfg
import effects
from sources import (
    alignment,
    claims,
    common,
    crm_calls,
    formulary,
    hcp_master,
    rep_roster,
    rx_audit,
    sell_in,
    sp_hub,
)

# Modules whose grain is derived from the shared true-fills event stream.
FILLS_MODULES = {
    "rx_audit": rx_audit,
    "claims": claims,
    "sp_hub": sp_hub,
    "sell_in": sell_in,
}

# Modules that only need the world dict.
WORLD_ONLY_MODULES = {
    "crm_calls": crm_calls,
    "rep_roster": rep_roster,
    "hcp_master": hcp_master,
    "formulary": formulary,
    "alignment": alignment,
}

ALL_MODULE_NAMES = list(FILLS_MODULES) + list(WORLD_ONLY_MODULES)


def build_bronze(seed: int) -> None:
    t0 = time.time()
    world = effects.build_and_seal(seed)
    print(f"True world + effects sealed in {time.time() - t0:.1f}s -> {effects.ANSWER_KEY_PATH}")

    rngs = common.spawn_rngs(seed, "sources", ALL_MODULE_NAMES + ["dispensing_sp", "fills"])
    common.assign_dispensing_sp(world, rngs["dispensing_sp"])
    fills = common.build_true_fills(world, rngs["fills"])
    print(f"True fills: {len(fills):,} rows")

    cfg.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    for name, module in {**FILLS_MODULES, **WORLD_ONLY_MODULES}.items():
        t1 = time.time()
        if name in FILLS_MODULES:
            df = module.generate(world, rngs[name], fills)
        else:
            df = module.generate(world, rngs[name])
        path = common.write_bronze(df, name)
        print(f"  {name}: {len(df):,} rows -> {path} ({time.time() - t1:.1f}s)")

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    build_bronze(args.seed)
