"""
Central constants for the Veltrana simulation, sourced from the Phase 0
design document. Nothing in world.py, effects.py, or sources/ should
hardcode a number that belongs here.
"""

from datetime import date

# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

SIM_START = date(2023, 3, 1)          # 24 months pre-launch
LAUNCH_DATE = date(2025, 3, 1)
SIM_END = date(2026, 8, 31)           # 18 months post-launch

# ---------------------------------------------------------------------------
# Population scale (1:3 of the ~450K US advanced-therapy population)
# ---------------------------------------------------------------------------

N_PATIENTS = 150_000
N_HCPS = 4_000

HCP_SPECIALTY_MIX = {
    "dermatologist": 0.70,
    "np_pa_derm": 0.20,
    "rheumatologist_other": 0.10,
}

N_REGIONS = 6
TERRITORIES_PER_REGION = 5
N_TERRITORIES = N_REGIONS * TERRITORIES_PER_REGION  # 30
HCPS_PER_TERRITORY = N_HCPS // N_TERRITORIES         # ~133

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

PRODUCTS = {
    "VELTRANA": {
        "archetype": "IL-23 inhibitor",
        "dosing": "SC, wk0/wk4, then q12w",
        "wac_per_dose": 20_500,
        "gtn_discount": 0.525,  # midpoint of 50-55%
        "is_brand": True,
    },
    "DERMAVEX": {"archetype": "IL-17A inhibitor", "dosing": "SC monthly", "is_brand": False},
    "CLARIVO": {"archetype": "IL-23 inhibitor", "dosing": "SC q8w", "is_brand": False},
    "ADALIMUMAB_BIOSIM": {"archetype": "TNF inhibitor", "dosing": "SC q2w", "is_brand": False},
    "ORELTA": {"archetype": "Oral TYK2 inhibitor", "dosing": "Oral daily", "is_brand": False},
}

# Pre-launch (no Veltrana) market share among biologic starts, by product.
# Used as the baseline the effect catalog perturbs.
BASELINE_SOURCE_SHARE = {
    "DERMAVEX": 0.38,
    "CLARIVO": 0.24,
    "ADALIMUMAB_BIOSIM": 0.28,
    "ORELTA": 0.10,
}

# ---------------------------------------------------------------------------
# Payer landscape
# ---------------------------------------------------------------------------

CHANNEL_MIX = {
    "commercial": 0.60,
    "medicare_partd": 0.25,
    "medicaid": 0.12,
    "cash_other": 0.03,
}

NATIONAL_PBM_SHARE_OF_COMMERCIAL = 0.75
N_NATIONAL_PBMS = 3
N_REGIONAL_PLANS = 12

FORMULARY_STATES = ["preferred", "non_preferred", "pa_biosim_step", "not_covered"]

# Months post-launch for Veltrana to reach steady-state formulary access.
ACCESS_RAMP_MONTHS = 9

# ---------------------------------------------------------------------------
# Patient journey baseline rates (pre-effect)
# ---------------------------------------------------------------------------

BASELINE_RATES = {
    "hub_referral_to_bv_complete": 0.95,
    "pa_required_commercial": 0.85,
    "pa_approved_first_submission": 0.65,
    "denial_appeal_overturn_rate": 0.50,
    "median_days_referral_to_fill": 18,
    "sp_abandonment_rate": 0.12,
    "persistence_12mo": 0.70,
}

# ---------------------------------------------------------------------------
# Specialty pharmacy network
# ---------------------------------------------------------------------------

SPECIALTY_PHARMACIES = ["SP_ALPHA", "SP_BRAVO", "SP_CHARLIE"]
SP_SHARE = {"SP_ALPHA": 0.45, "SP_BRAVO": 0.35, "SP_CHARLIE": 0.20}

# Each SP has its own status-code vocabulary (a built-in data quirk).
SP_STATUS_CODE_MAPS = {
    "SP_ALPHA": {
        "referral_received": "RX_RCVD",
        "benefit_verification": "BV_DONE",
        "pa_pending": "PA_PEND",
        "pa_approved": "PA_APPR",
        "pa_denied": "PA_DENY",
        "first_fill": "FILL_1",
        "refill": "FILL_RPT",
        "abandoned": "ABD",
    },
    "SP_BRAVO": {
        "referral_received": "NEW_REFERRAL",
        "benefit_verification": "BENEFITS_VERIFIED",
        "pa_pending": "PRIOR_AUTH_SUBMITTED",
        "pa_approved": "PRIOR_AUTH_APPROVED",
        "pa_denied": "PRIOR_AUTH_DENIED",
        "first_fill": "DISPENSED_INITIAL",
        "refill": "DISPENSED_REFILL",
        "abandoned": "PATIENT_WITHDREW",
    },
    "SP_CHARLIE": {
        "referral_received": "01_INTAKE",
        "benefit_verification": "02_BV",
        "pa_pending": "03_PA_SUBMITTED",
        "pa_approved": "04_PA_APPROVED",
        "pa_denied": "04_PA_REJECTED",
        "first_fill": "05_FIRST_DISP",
        "refill": "06_REFILL_DISP",
        "abandoned": "99_LOST",
    },
}

# ---------------------------------------------------------------------------
# Data source coverage / lag characteristics
# ---------------------------------------------------------------------------

CLAIMS_PATIENT_COVERAGE = 0.65
CLAIMS_MEDICAID_UNDERCAPTURE = 0.35  # additional coverage penalty for Medicaid patients
CLAIMS_LAG_WEEKS = (4, 6)

RX_AUDIT_LAG_WEEKS = 2
RX_AUDIT_PROJECTION_NOISE_SD = 0.03  # as a fraction of true weekly volume

# ---------------------------------------------------------------------------
# Random seed
# ---------------------------------------------------------------------------
# Set privately per run. Kept out of version control alongside answer_key.json
# if you want the blind test to hold across sessions.

DEFAULT_SEED = None  # override at runtime, e.g. via generate.py --seed
