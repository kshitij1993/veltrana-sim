-- Patient-level duration + event indicator, then a proper Kaplan-Meier
-- life table over it. Not the same thing as patient_journey_funnel's
-- persistence_months, which is just (last claim - first claim) and
-- can't tell "discontinued" from "censored, still active, we just
-- haven't observed their next refill yet." Built from
-- sp_hub_normalized (100% Veltrana coverage) rather than claims
-- (~65% sampled) because a survival estimate needs a clean
-- discontinuation signal, not claims' sampling-driven gaps.
--
-- event_observed = 1 (discontinuation) when the gap between a patient's
-- last observed fill/refill and the end of the data window exceeds 168
-- days - 2x Veltrana's 84-day maintenance interval, room for one missed
-- cycle before calling it a discontinuation rather than "hasn't had
-- their next scheduled refill yet." Otherwise the patient is
-- right-censored: still possibly active, observation just stopped at
-- SIM_END. n_at_risk(t) counts everyone followed at least t months;
-- km_survival is the standard cumulative product of (1 - events/at_risk)
-- across every duration up to and including t.
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
        floor(extract(epoch from (p.last_event_date - p.first_fill_date)) / 86400.0 / 30)::int as duration_months,
        case when (s.sim_end_date - p.last_event_date) > interval '168 days' then 1 else 0 end as event_observed
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
