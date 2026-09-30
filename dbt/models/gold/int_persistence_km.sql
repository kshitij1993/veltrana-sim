-- Patient-level duration + event indicator, then a proper Kaplan-Meier
-- life table over it. Not the same thing as patient_journey_funnel's
-- persistence_months, which is just (last claim - first claim) and
-- can't tell "discontinued" from "censored, still active, we just
-- haven't observed their next refill yet." Built from
-- sp_hub_normalized (100% Veltrana coverage) rather than claims
-- (~65% sampled) because a survival estimate needs a clean
-- discontinuation signal, not claims' sampling-driven gaps. This table
-- only ever contains Veltrana patients - sp_hub_normalized's source
-- feed has no competitor visibility at all - so there is no
-- cross-product comparison happening here.
--
-- event_observed = 1 (discontinuation) when the gap between a patient's
-- last observed fill/refill and the end of the data window exceeds 2x
-- the product's own maintenance interval (var veltrana_maintenance_interval_days,
-- mirroring generator/config.py) - room for one missed cycle before
-- calling it a discontinuation rather than "hasn't had their next
-- scheduled refill yet." Otherwise the patient is right-censored.
--
-- duration_months is NOT simply (last_event - first_fill) for every
-- patient - that was a real bug in an earlier version of this model.
-- For a discontinued patient, last_event is a reasonable proxy for when
-- the failure happened. For a CENSORED patient, last_event is only when
-- they last happened to refill - it understates how long they were
-- actually followed, since we know they were still at risk all the way
-- to the end of the data window even without a refill event that
-- recently. Duration for censored patients has to extend to the end of
-- the window (sim_end_date), or the risk set thins out artificially at
-- longer durations and the tail of the curve is built on a
-- systematically undercounted population. n_at_risk(t) counts everyone
-- followed at least t months; km_survival is the standard cumulative
-- product of (1 - events/at_risk) across every duration up to and
-- including t.
with sp_events as (
    select patient_id, event_date
    from {{ ref('sp_hub_normalized') }}
    where journey_stage in ('first_fill', 'refill')
),

patient_span as (
    select
        patient_id,
        min(event_date) as first_fill_date,
        max(event_date) as last_event_date
    from sp_events
    group by patient_id
),

sim_end as (
    select max(event_date) as sim_end_date from sp_events
),

duration_calc as (
    select
        p.patient_id,
        case
            when (s.sim_end_date - p.last_event_date)
                 > (2 * {{ var('veltrana_maintenance_interval_days') }}) * interval '1 day'
            then 1
            else 0
        end as event_observed,
        case
            when (s.sim_end_date - p.last_event_date)
                 > (2 * {{ var('veltrana_maintenance_interval_days') }}) * interval '1 day'
            then floor(extract(epoch from (p.last_event_date - p.first_fill_date)) / 86400.0 / 30)::int
            else floor(extract(epoch from (s.sim_end_date - p.first_fill_date)) / 86400.0 / 30)::int
        end as duration_months
    from patient_span p
    cross join sim_end s
),

distinct_times as (
    select distinct duration_months as t from duration_calc
),

risk_and_events as (
    select
        dt.t,
        (select count(*) from duration_calc d where d.duration_months >= dt.t) as n_at_risk,
        (select count(*) from duration_calc d where d.duration_months = dt.t and d.event_observed = 1) as n_events
    from distinct_times dt
)

select
    t as months_since_first_fill,
    n_at_risk,
    n_events,
    exp(sum(ln(greatest(1.0 - n_events::numeric / nullif(n_at_risk, 0), 0.0001))) over (order by t)) as km_survival
from risk_and_events
order by t
