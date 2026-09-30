-- Region R06, Q1 2026 -> Q2 2026: decomposes the change in Veltrana TRx
-- into market (category grew/shrank), share (Veltrana's share of that
-- category moved), and share's own two named sub-drivers - access and
-- field - with whatever's left as residual_share_effect.
--
-- market_effect and share_effect_total are exact: standard two-term
-- volume-bridge algebra (market_effect at baseline share, share_effect
-- at ending market size), and they sum to total_change exactly by
-- construction. access_effect and field_effect are NOT exact - they're
-- transparent, best-effort estimates of what drove the share move, and
-- residual_share_effect is a plug so all four pieces still add up to
-- the real total_change: market_effect + access_effect + field_effect +
-- residual_share_effect = total_change.
--
-- R06, not a data-mined "worst region": it's the one region with a
-- planted effect this run (a speaker-program halo, E8 - see
-- hcp_golden_record_xref-adjacent effects work earlier this
-- conversation). That effect has no clean proxy in either access or
-- field as built here (it's a peer-adoption mechanism, not a formulary
-- change or a call), so expect it to show up as unexplained residual,
-- not as access or field - which is the honest, correct outcome for a
-- blind analysis, not a modeling gap.
--
-- access_effect sums formulary_impact's diff_in_diff for any change in
-- this window - it can only ever be a rough regional proxy since plan
-- and region are independently assigned (see formulary_impact's own
-- notes), and it's genuinely 0 this window: no formulary change fell
-- between these two quarters this run.
--
-- field_effect multiplies the quarter's call-volume change in this
-- region by a per-call value estimated from gold.call_response,
-- restricted to middle-potential (decile 4-6) HCPs to dampen the
-- targeting-bias confound task 5 surfaced. It is a proxy, not a causal
-- estimate - call_response's own notes found call buckets don't move
-- monotonically with Rx even within a potential band, likely because
-- same-quarter call count is confounded with existing patients' refill
-- carryover.
with region as (select 'R06'::text as region_id),
before_q as (select date '2026-01-01' as q),
after_q as (select date '2026-04-01' as q),

rx_before as (
    select
        sum(r.projected_trx) filter (where r.product = 'VELTRANA') as veltrana_trx,
        sum(r.projected_trx) as market_trx
    from {{ ref('rx_audit_clean') }} r
    join {{ ref('hcp_golden_record') }} h on h.golden_hcp_id = r.golden_hcp_id
    where h.region_id = (select region_id from region)
      and date_trunc('quarter', r.week_of)::date = (select q from before_q)
),

rx_after as (
    select
        sum(r.projected_trx) filter (where r.product = 'VELTRANA') as veltrana_trx,
        sum(r.projected_trx) as market_trx
    from {{ ref('rx_audit_clean') }} r
    join {{ ref('hcp_golden_record') }} h on h.golden_hcp_id = r.golden_hcp_id
    where h.region_id = (select region_id from region)
      and date_trunc('quarter', r.week_of)::date = (select q from after_q)
),

calls_before as (
    select count(*) as n_calls
    from {{ ref('crm_calls') }} c
    join {{ ref('hcp_golden_record') }} h on h.golden_hcp_id = c.golden_hcp_id
    where h.region_id = (select region_id from region)
      and date_trunc('quarter', c.call_date)::date = (select q from before_q)
),

calls_after as (
    select count(*) as n_calls
    from {{ ref('crm_calls') }} c
    join {{ ref('hcp_golden_record') }} h on h.golden_hcp_id = c.golden_hcp_id
    where h.region_id = (select region_id from region)
      and date_trunc('quarter', c.call_date)::date = (select q from after_q)
),

access as (
    -- strictly after before_q: a change_quarter equal to before_q
    -- already happened before this window opened (it's baked into the
    -- before-quarter baseline itself, not something that changed
    -- during before->after)
    select coalesce(sum(diff_in_diff), 0) as access_effect
    from {{ ref('formulary_impact') }}
    where change_quarter > (select q from before_q) and change_quarter <= (select q from after_q)
),

per_call_value as (
    select
        coalesce(
            avg(veltrana_trx) filter (where call_bucket = '1-3')
            - avg(veltrana_trx) filter (where call_bucket = '0'),
            0
        ) as v
    from {{ ref('call_response') }}
    where potential_decile between 4 and 6
)

select
    (select region_id from region) as region_id,
    (select q from before_q) as before_quarter,
    (select q from after_q) as after_quarter,
    round(b.market_trx::numeric, 1) as market_before,
    round(a.market_trx::numeric, 1) as market_after,
    round(b.veltrana_trx::numeric, 1) as veltrana_before,
    round(a.veltrana_trx::numeric, 1) as veltrana_after,
    round((a.veltrana_trx - b.veltrana_trx)::numeric, 1) as total_change,
    round(
        ((a.market_trx - b.market_trx) * (b.veltrana_trx / nullif(b.market_trx, 0)))
    ::numeric, 1) as market_effect,
    round(
        ((a.veltrana_trx / nullif(a.market_trx, 0) - b.veltrana_trx / nullif(b.market_trx, 0)) * a.market_trx)
    ::numeric, 1) as share_effect_total,
    round(ac.access_effect::numeric, 1) as access_effect,
    round(((ca.n_calls - cb.n_calls) * pcv.v)::numeric, 1) as field_effect,
    round((
        (a.veltrana_trx - b.veltrana_trx)
        - ((a.market_trx - b.market_trx) * (b.veltrana_trx / nullif(b.market_trx, 0)))
        - ac.access_effect
        - ((ca.n_calls - cb.n_calls) * pcv.v)
    )::numeric, 1) as residual_share_effect
from rx_before b, rx_after a, calls_before cb, calls_after ca, access ac, per_call_value pcv
