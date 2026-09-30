-- For each detected Veltrana formulary_state change (plan x quarter),
-- claims-derived NBRx before/after on that plan vs. a diff-in-diff
-- control: the same before/after comparison averaged across every
-- OTHER plan that had no formulary_state change that same quarter.
--
-- Built at plan grain, not region: plan_id and region_id are assigned
-- independently of each other in this simulation (a patient's plan and
-- their prescriber's region are two separate random draws in world.py),
-- so a plan-level formulary change has no single "affected region" -
-- its enrollees are spread across all regions. Plan is the grain this
-- comparison is actually coherent at.
--
-- Uses claims_clean, not rx_audit_clean: rx_audit only carries
-- payer_channel (commercial/medicare_partd/...), not individual
-- plan_id, so it can't resolve to a specific plan at all. NBRx here is
-- claims' fill_number = 1, subject to claims' own ~65% coverage
-- sampling - a noisier signal than rx_audit's near-total panel, but the
-- only one with the right grain.
with formulary_changes as (
    select
        plan_id,
        product,
        quarter,
        formulary_state,
        lag(formulary_state) over (partition by plan_id, product order by quarter) as prev_state,
        lag(quarter) over (partition by plan_id, product order by quarter) as prev_quarter
    from {{ ref('formulary') }}
    where product = 'VELTRANA'
),

detected_changes as (
    select
        plan_id,
        quarter as change_quarter,
        prev_quarter,
        prev_state,
        formulary_state as new_state
    from formulary_changes
    where prev_state is not null and prev_state != formulary_state
),

nbrx_by_plan_quarter as (
    select
        plan_id,
        date_trunc('quarter', service_date)::date as quarter,
        count(*) filter (where fill_number = 1) as nbrx
    from {{ ref('claims_clean') }}
    where product = 'VELTRANA'
    group by plan_id, date_trunc('quarter', service_date)
),

all_plans as (
    select distinct plan_id from {{ ref('formulary') }}
),

control_avg as (
    select
        dc.change_quarter,
        dc.prev_quarter,
        avg(coalesce(b.nbrx, 0)) as control_nbrx_before,
        avg(coalesce(a.nbrx, 0)) as control_nbrx_after
    from (select distinct change_quarter, prev_quarter from detected_changes) dc
    cross join all_plans p
    left join nbrx_by_plan_quarter b on b.plan_id = p.plan_id and b.quarter = dc.prev_quarter
    left join nbrx_by_plan_quarter a on a.plan_id = p.plan_id and a.quarter = dc.change_quarter
    where p.plan_id not in (
        select plan_id from detected_changes dc2 where dc2.change_quarter = dc.change_quarter
    )
    group by dc.change_quarter, dc.prev_quarter
)

select
    dc.plan_id,
    dc.change_quarter,
    dc.prev_state,
    dc.new_state,
    coalesce(bef.nbrx, 0) as nbrx_before,
    coalesce(aft.nbrx, 0) as nbrx_after,
    coalesce(aft.nbrx, 0) - coalesce(bef.nbrx, 0) as affected_delta,
    round(ca.control_nbrx_before::numeric, 2) as control_nbrx_before,
    round(ca.control_nbrx_after::numeric, 2) as control_nbrx_after,
    round((ca.control_nbrx_after - ca.control_nbrx_before)::numeric, 2) as control_delta,
    round(
        (coalesce(aft.nbrx, 0) - coalesce(bef.nbrx, 0))
        - (ca.control_nbrx_after - ca.control_nbrx_before)
    ::numeric, 2) as diff_in_diff
from detected_changes dc
left join nbrx_by_plan_quarter bef on bef.plan_id = dc.plan_id and bef.quarter = dc.prev_quarter
left join nbrx_by_plan_quarter aft on aft.plan_id = dc.plan_id and aft.quarter = dc.change_quarter
left join control_avg ca on ca.change_quarter = dc.change_quarter
order by dc.change_quarter, dc.plan_id
