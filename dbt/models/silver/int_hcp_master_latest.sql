-- Collapses the 14 quarterly snapshots down to one row per collapse_key
-- (real npi, or the raw hcp_id when npi isn't usable), keeping that
-- identity's most recent known state. This is the "collapse to one row
-- per NPI representing latest known state" step - it does NOT yet merge
-- the ~320 duplicate identities into their real counterpart, since by
-- construction they don't share a usable npi with it. That's
-- int_hcp_fuzzy_candidates' job.
with ranked as (
    select
        *,
        row_number() over (
            partition by collapse_key order by quarter desc, hcp_id desc
        ) as rn,
        count(*) over (partition by collapse_key) as n_snapshots
    from {{ ref('int_hcp_master_normalized') }}
)
select
    collapse_key,
    hcp_id,
    npi,
    npi_clean,
    first_name,
    last_name,
    first_name_norm,
    last_name_norm,
    specialty,
    hco_id,
    territory_id,
    region_id,
    address,
    address_norm,
    city,
    state,
    zip,
    quarter as latest_quarter,
    n_snapshots
from ranked
where rn = 1
