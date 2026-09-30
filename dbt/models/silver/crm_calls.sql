-- bronze.crm_calls with hcp_id replaced by golden_hcp_id, same pattern
-- as rx_audit_clean/claims_clean. Left join: an unresolved hcp_id
-- surfaces as a null golden_hcp_id instead of a silently dropped row,
-- and the not_null test on golden_hcp_id turns that into a build
-- failure if it ever happens.
select
    c.call_id,
    x.golden_hcp_id,
    c.rep_id,
    c.territory_id,
    c.call_date,
    c.logged_date
from {{ source('bronze', 'crm_calls') }} c
left join {{ ref('hcp_golden_record_xref') }} x on x.raw_hcp_id = c.hcp_id
