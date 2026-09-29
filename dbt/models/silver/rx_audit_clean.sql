-- bronze.rx_audit with hcp_id replaced by golden_hcp_id. Every other
-- value is passed through exactly as observed - no smoothing, no
-- imputing, no resolving the projection noise or the restatement
-- quirk. That's Bronze's honest signal; cleaning it is Gold's job, not
-- Silver's.
--
-- left join (not inner) on purpose: if some hcp_id in bronze.rx_audit
-- ever failed to resolve to a golden record, an inner join would drop
-- that row silently. This lets it through with a null golden_hcp_id
-- instead, and the not_null test on golden_hcp_id in
-- _silver__models.yml turns that into a loud build failure.
select
    x.golden_hcp_id,
    r.product,
    r.payer_channel,
    r.week_of,
    r.report_date,
    r.projected_units
from {{ source('bronze', 'rx_audit') }} r
left join {{ ref('hcp_golden_record_xref') }} x on x.raw_hcp_id = r.hcp_id
