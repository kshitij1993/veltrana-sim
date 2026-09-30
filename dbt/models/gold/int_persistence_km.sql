-- Kaplan-Meier life table over Veltrana patients' fill/refill history,
-- built at the PATIENT level rather than one population-wide gap rule.
-- The earlier flat-threshold version applied the same maintenance-
-- interval-based window to every patient regardless of where they
-- actually were in their own dosing schedule. Checked directly against
-- world.py's own ground truth, that mis-timed events - over-detecting
-- in the first 3 months and under-detecting from 6 months onward - and
-- flooring continuous event times into whole-month buckets was
-- contributing to the same mismatch on top of that.
--
-- Each patient's own next-expected-fill date comes from their own last
-- observed fill and Veltrana's real dosing schedule (config.py's
-- VELTRANA_INDUCTION_INTERVAL_DAYS=28, PRODUCT_FILL_INTERVAL_DAYS["VELTRANA"]=84):
-- 28 days after the first fill (wk0->wk4 induction), 84 days after
-- every fill from then on (q12w maintenance) - never a single flat
-- interval applied regardless of phase.
--
-- Grace period: half of whichever interval currently applies - 14 days
-- in induction, 42 in maintenance. So a patient is only called
-- discontinued once they're 1.5x their own CURRENT interval past their
-- last fill with nothing next: clearly overdue, not just running a
-- little late, while short enough that a patient who drops during
-- induction isn't forced to wait out a maintenance-length window to be
-- confirmed - the specific failure mode the flat-168/126-day versions
-- had.
--
-- Event time is the exact calendar date the discontinuation first
-- becomes detectable (expected next-fill date + grace) - not the last
-- fill date, and not floored into a month bucket. Censored patients'
-- time-at-risk extends to the end of the data window (SIM_END), same
-- as the earlier fix - still needed, still correct.
with sp_events as (
    select patient_id, event_date
    from {{ ref('sp_hub_normalized') }}
    where journey_stage in ('first_fill', 'refill')
),

numbered_fills as (
    select
        patient_id,
        event_date,
        row_number() over (partition by patient_id order by event_date) as fill_number
    from sp_events
),

patient_last_fill as (
    select
        patient_id,
        min(event_date) as first_fill_date,
        max(event_date) as last_event_date,
        max(fill_number) as last_fill_number
    from numbered_fills
    group by patient_id
),

sim_end as (
    select max(event_date) as sim_end_date from sp_events
),

patient_schedule as (
    select
        p.patient_id,
        p.first_fill_date,
        p.last_event_date,
        case when p.last_fill_number = 1
            then {{ var('veltrana_induction_interval_days') }}
            else {{ var('veltrana_maintenance_interval_days') }}
        end as current_interval_days,
        s.sim_end_date
    from patient_last_fill p
    cross join sim_end s
),

events as (
    select
        patient_id,
        first_fill_date,
        sim_end_date,
        last_event_date
            + (current_interval_days * interval '1 day')
            + ((current_interval_days / 2.0) * interval '1 day') as confirm_date
    from patient_schedule
),

classified as (
    select
        patient_id,
        case when confirm_date <= sim_end_date then 1 else 0 end as event_observed,
        case
            when confirm_date <= sim_end_date
            then extract(epoch from (confirm_date - first_fill_date)) / 86400.0
            else extract(epoch from (sim_end_date - first_fill_date)) / 86400.0
        end as duration_days
    from events
),

-- Only event times need their own life-table row: survival only
-- changes at an event, so every censoring time in between would just
-- repeat the same km_survival value while inflating the row count.
distinct_times as (
    select distinct duration_days as t from classified where event_observed = 1
),

risk_and_events as (
    select
        dt.t,
        (select count(*) from classified c where c.duration_days >= dt.t) as n_at_risk,
        (select count(*) from classified c where c.duration_days = dt.t and c.event_observed = 1) as n_events
    from distinct_times dt
)

select
    t as days_since_first_fill,
    round((t / 30.0)::numeric, 2) as months_since_first_fill,
    n_at_risk,
    n_events,
    exp(sum(ln(greatest(1.0 - n_events::numeric / nullif(n_at_risk, 0), 0.0001))) over (order by t)) as km_survival
from risk_and_events
order by t
