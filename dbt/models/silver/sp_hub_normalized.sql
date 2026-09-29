-- bronze.sp_hub's three per-SP status_code vocabularies
-- (config.SP_STATUS_CODE_MAPS), collapsed to one canonical journey_stage
-- (referral_received, benefit_verification, pa_pending, pa_approved,
-- pa_denied, first_fill, refill, abandoned) via the sp_status_code_map
-- seed - generated straight from that same config dict, so the mapping
-- can't drift out of sync with the generator by hand-typo.
--
-- sp and status_code are kept alongside journey_stage rather than
-- dropped: a funnel built on journey_stage doesn't need to know which
-- SP a row came from, but being able to trace a stage back to its raw
-- per-SP code is still worth keeping for audit.
--
-- left join: an unmapped (sp, status_code) pair - a code the seed
-- doesn't know about - surfaces as a null journey_stage instead of a
-- row that silently vanishes; the not_null test on journey_stage in
-- _silver__models.yml catches it.
select
    e.event_id,
    e.patient_id,
    e.sp,
    e.status_code,
    m.journey_stage,
    e.event_date,
    e.report_date
from {{ source('bronze', 'sp_hub') }} e
left join {{ ref('sp_status_code_map') }} m
    on m.sp = e.sp and m.status_code = e.status_code
