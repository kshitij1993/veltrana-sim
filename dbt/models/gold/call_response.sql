-- Calls per HCP per quarter, bucketed, against Veltrana TRx that same
-- quarter, with potential_decile carried alongside rather than
-- collapsed into one aggregate correlation - bucketing by raw call
-- count without the decile would make "more calls -> more Rx" look like
-- a promotional effect, when a good share of it is really just "reps
-- already call high-potential HCPs more" (crm_calls' own targeting
-- bias) showing up twice.
--
-- Scoped to quarters from Veltrana's launch quarter onward (2025-01-01,
-- the calendar quarter containing the March 2025 launch) - pre-launch
-- quarters have zero Veltrana TRx for everyone by definition and would
-- only dilute the output with uninformative rows.
with calls_quarterly as (
    select
        golden_hcp_id,
        date_trunc('quarter', call_date)::date as quarter,
        count(*) as n_calls
    from {{ ref('crm_calls') }}
    where call_date >= date '2025-01-01'
    group by golden_hcp_id, date_trunc('quarter', call_date)
),

rx_quarterly as (
    select
        golden_hcp_id,
        date_trunc('quarter', week_of)::date as quarter,
        sum(projected_trx) as veltrana_trx
    from {{ ref('rx_audit_clean') }}
    where product = 'VELTRANA' and week_of >= date '2025-01-01'
    group by golden_hcp_id, date_trunc('quarter', week_of)
),

combined as (
    select
        coalesce(c.golden_hcp_id, r.golden_hcp_id) as golden_hcp_id,
        coalesce(c.quarter, r.quarter) as quarter,
        coalesce(c.n_calls, 0) as n_calls,
        coalesce(r.veltrana_trx, 0) as veltrana_trx
    from calls_quarterly c
    full outer join rx_quarterly r
        on r.golden_hcp_id = c.golden_hcp_id and r.quarter = c.quarter
)

select
    c.golden_hcp_id,
    c.quarter,
    c.n_calls,
    case
        when c.n_calls = 0 then '0'
        when c.n_calls between 1 and 3 then '1-3'
        when c.n_calls between 4 and 6 then '4-6'
        else '7+'
    end as call_bucket,
    round(c.veltrana_trx::numeric, 1) as veltrana_trx,
    s.potential_decile
from combined c
left join {{ ref('hcp_segments') }} s on s.golden_hcp_id = c.golden_hcp_id
order by c.golden_hcp_id, c.quarter
