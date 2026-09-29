-- Audit trail: every raw hcp_master identity (one row per distinct
-- hcp_id - all of its 14 quarterly snapshots share this same mapping)
-- next to the golden_hcp_id it collapsed into. is_canonical_record marks
-- which side of a resolved pair supplied hcp_golden_record's attributes
-- (irrelevant for a singleton, where it's trivially true). match_reason
-- says whether this identity had no duplicate at all, or was one side of
-- a fuzzy-matched pair; the similarity scores let that match be
-- sanity-checked by eye instead of trusted blind.
select
    a.collapse_key as raw_identity_key,
    l.hcp_id as raw_hcp_id,
    l.npi as raw_npi,
    l.first_name as raw_first_name,
    l.last_name as raw_last_name,
    l.address as raw_address,
    g.golden_hcp_id,
    (a.collapse_key = a.canonical_key) as is_canonical_record,
    case when a.match_method = 'no_match' then 'no_duplicate_found' else 'fuzzy_match' end as match_reason,
    a.match_score,
    a.last_name_sim,
    a.first_name_sim,
    a.address_sim
from {{ ref('int_hcp_golden_assignment') }} a
inner join {{ ref('int_hcp_master_latest') }} l on l.collapse_key = a.collapse_key
inner join {{ ref('int_hcp_golden_ids') }} g on g.canonical_key = a.canonical_key
order by g.golden_hcp_id, a.collapse_key
