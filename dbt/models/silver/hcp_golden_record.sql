-- The golden record: one row per real HCP, after (1) collapsing
-- bronze.hcp_master's 14 quarterly snapshots to each identity's latest
-- known state (int_hcp_master_latest) and (2) fuzzy-merging the ~320
-- duplicate identities that didn't share a usable npi back onto their
-- real counterpart (int_hcp_fuzzy_candidates / int_hcp_golden_assignment).
--
-- Attributes come from the canonical side of each golden group - the
-- record with a real, usable npi when there is one. n_source_records
-- says how many raw hcp_master identities fed into this golden record
-- (1 for an HCP with no duplicate, 2 for one that had exactly one); see
-- hcp_golden_record_xref for exactly which raw records and why they
-- matched.
with golden_ids as (
    select * from {{ ref('int_hcp_golden_ids') }}
),

latest as (
    select * from {{ ref('int_hcp_master_latest') }}
),

source_counts as (
    select canonical_key, count(*) as n_source_records
    from {{ ref('int_hcp_golden_assignment') }}
    group by canonical_key
)

select
    g.golden_hcp_id,
    l.npi,
    l.first_name,
    l.last_name,
    l.specialty,
    l.hco_id,
    l.territory_id,
    l.region_id,
    l.address,
    l.city,
    l.state,
    l.zip,
    l.latest_quarter,
    sc.n_source_records
from golden_ids g
inner join latest l on l.collapse_key = g.canonical_key
inner join source_counts sc on sc.canonical_key = g.canonical_key
order by g.golden_hcp_id
