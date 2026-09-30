-- Potential vs. actual for every golden HCP. No ground-truth "potential"
-- exists anywhere in Bronze/Silver, on purpose - a real HCP's true
-- prescribing potential is never directly observed, only estimated, and
-- this mart is that estimate: potential_decile ranks each HCP's total
-- across-all-products TRx (their whole psoriasis-biologic practice size,
-- not just Veltrana - that's the addressable pool) against their own
-- specialty + territory peers, per the task's "estimated from
-- specialty/territory peers." veltrana_trx is what they actually wrote
-- for the brand. call_decile ranks total calls received, population-
-- wide (reps allocate calls across a whole territory, not within a
-- narrow peer group, so this one isn't partitioned).
--
-- The two flags are this mart's actual point: whitespace HCPs
-- (high potential, under-called) and over-served HCPs (low potential,
-- over-called) - the two segments a targeting review needs to see
-- named, not buried in a correlation.
with rx_by_hcp as (
    select
        golden_hcp_id,
        sum(case when product = 'VELTRANA' then projected_trx else 0 end) as veltrana_trx,
        sum(projected_trx) as total_market_trx
    from {{ ref('rx_audit_clean') }}
    group by golden_hcp_id
),

calls_by_hcp as (
    select golden_hcp_id, count(*) as total_calls
    from {{ ref('crm_calls') }}
    group by golden_hcp_id
),

base as (
    select
        h.golden_hcp_id,
        h.specialty,
        h.territory_id,
        h.region_id,
        coalesce(r.veltrana_trx, 0) as veltrana_trx,
        coalesce(r.total_market_trx, 0) as total_market_trx,
        coalesce(c.total_calls, 0) as total_calls
    from {{ ref('hcp_golden_record') }} h
    left join rx_by_hcp r on r.golden_hcp_id = h.golden_hcp_id
    left join calls_by_hcp c on c.golden_hcp_id = h.golden_hcp_id
),

scored as (
    select
        *,
        ntile(10) over (partition by specialty, territory_id order by total_market_trx) as potential_decile,
        ntile(10) over (order by total_calls) as call_decile
    from base
)

select
    golden_hcp_id,
    specialty,
    territory_id,
    region_id,
    round(total_market_trx::numeric, 1) as total_market_trx,
    round(veltrana_trx::numeric, 1) as veltrana_trx,
    total_calls,
    potential_decile,
    call_decile,
    (potential_decile >= 8 and call_decile <= 3) as flag_high_potential_low_calls,
    (potential_decile <= 3 and call_decile >= 8) as flag_low_potential_high_calls
from scored
order by golden_hcp_id
