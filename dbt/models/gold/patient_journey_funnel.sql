-- One row per Veltrana patient: the referral -> BV -> PA -> first-fill
-- funnel from silver.sp_hub_normalized, plus an observed persistence
-- proxy from silver.claims_clean.
--
-- Every patient in sp_hub_normalized was referred (that's the first
-- event any of them ever gets), so that table's distinct patient_id set
-- *is* the funnel's population - no separate "who's in scope" filter
-- needed.
--
-- claims_clean carries a tokenized patient_token, not patient_id, so it
-- can't be joined directly. The token is a deterministic hash
-- (patient_token = sha1('laad:' || patient_id)[:16], see
-- generator/sources/common.tokenize_id) - recomputing it here with
-- pgcrypto's digest() is not a shortcut around the tokenization, it's
-- exactly the mechanism real claims/hub token-matching services use: a
-- brand's hub program and a claims vendor apply the same deterministic
-- hash to the same patient identifier so the two sides' data can be
-- linked without either one ever handing over raw PII. Only sp_hub's own
-- enrolled (Veltrana, hub-tracked) patients get de-tokenized this way -
-- competitor claims stay tokenized and unlinkable, same as in reality.
--
-- persistence_months here is an *observed*, claims-derived figure - the
-- span between a patient's first and last Veltrana claim in the ~65%-
-- covered (further gap-reduced) claims sample - not the true world's
-- ground-truth persistence_months. It will read low for a lot of
-- patients for reasons that have nothing to do with true persistence:
-- claims coverage gaps, and - more importantly - right-censoring, since
-- Veltrana only launched 18 months before the data window ends, so a
-- patient who started 3 months ago cannot show 12 months of persistence
-- yet no matter how persistent they truly are. Treat this column as a
-- rough, censoring-biased proxy; a real Kaplan-Meier estimate (Phase 3)
-- has to account for who's even had the chance to reach each duration.
with events as (
    select
        patient_id,
        journey_stage,
        min(event_date) as first_event_date
    from {{ ref('sp_hub_normalized') }}
    group by patient_id, journey_stage
),

pivoted as (
    select
        patient_id,
        max(case when journey_stage = 'referral_received' then first_event_date end) as referral_date,
        max(case when journey_stage = 'benefit_verification' then first_event_date end) as bv_date,
        max(case when journey_stage = 'pa_approved' then first_event_date end) as pa_approved_date,
        max(case when journey_stage = 'first_fill' then first_event_date end) as first_fill_date,
        max(case when journey_stage = 'abandoned' then first_event_date end) as abandoned_date
    from events
    group by patient_id
),

patient_crosswalk as (
    select
        patient_id,
        left(encode(digest('laad:' || patient_id, 'sha1'), 'hex'), 16) as patient_token
    from pivoted
),

claims_summary as (
    select
        pc.patient_id,
        min(c.service_date) as first_claim_date,
        max(c.service_date) as last_claim_date
    from patient_crosswalk pc
    inner join {{ ref('claims_clean') }} c
        on c.patient_token = pc.patient_token
        and c.product = 'VELTRANA'
    group by pc.patient_id
)

select
    p.patient_id,
    (p.bv_date is not null) as reached_bv,
    (p.pa_approved_date is not null) as reached_pa_approval,
    (p.first_fill_date is not null) as reached_first_fill,
    (p.abandoned_date is not null) as abandoned,
    case
        when p.referral_date is not null and p.first_fill_date is not null
        then round(extract(epoch from (p.first_fill_date - p.referral_date)) / 86400.0)::int
    end as days_referral_to_fill,
    case
        when cs.first_claim_date is not null
        then round((extract(epoch from (cs.last_claim_date - cs.first_claim_date)) / 86400.0 / 30)::numeric, 1)
    end as persistence_months
from pivoted p
left join claims_summary cs on cs.patient_id = p.patient_id
