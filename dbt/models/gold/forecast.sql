-- 4-quarter active-patient projection: observed monthly start rate
-- (trailing 3 months, held flat) projected forward, with each cohort's
-- projected size discounted by int_persistence_km's actual survival
-- curve at however many months will have elapsed by each forecast
-- quarter-end - not a trend line fit through historical patient counts,
-- which would extrapolate momentum without ever accounting for
-- attrition.
with sim_end as (
    select max(event_date) as sim_end_date
    from {{ ref('sp_hub_normalized') }}
    where journey_stage in ('first_fill', 'refill')
),

monthly_starts as (
    select
        date_trunc('month', event_date)::date as start_month,
        count(distinct patient_id) as n_starts
    from {{ ref('sp_hub_normalized') }}
    where journey_stage = 'first_fill'
    group by date_trunc('month', event_date)
),

recent_rate as (
    select avg(n_starts) as avg_monthly_starts
    from monthly_starts
    where start_month >= (select max(start_month) from monthly_starts) - interval '2 months'
),

forecast_quarters as (
    select quarters_ahead from generate_series(1, 4) as quarters_ahead
),

quarter_ends as (
    select
        fq.quarters_ahead,
        (
            date_trunc('quarter', s.sim_end_date)
            + (fq.quarters_ahead * interval '3 months')
            + interval '3 months' - interval '1 day'
        )::date as quarter_end
    from forecast_quarters fq
    cross join sim_end s
),

-- historical cohorts (actual starts) plus projected future cohorts
-- (flat at the trailing rate) out to the last forecast quarter-end
cohort_months as (
    select start_month, n_starts, false as is_projected
    from monthly_starts

    union all

    select
        gs::date as start_month,
        r.avg_monthly_starts as n_starts,
        true as is_projected
    from generate_series(
        (select max(start_month) + interval '1 month' from monthly_starts),
        (select max(quarter_end) from quarter_ends),
        interval '1 month'
    ) as gs
    cross join recent_rate r
),

cohort_x_quarter as (
    select
        q.quarters_ahead,
        q.quarter_end,
        c.n_starts,
        c.is_projected,
        (q.quarter_end - c.start_month) as days_elapsed
    from quarter_ends q
    cross join cohort_months c
    where c.start_month <= q.quarter_end
)

select
    cq.quarters_ahead,
    cq.quarter_end,
    round(sum(cq.n_starts * coalesce(km.km_survival, 1.0))::numeric, 0) as projected_active_patients,
    bool_or(cq.is_projected) as includes_projected_cohorts,
    round((select avg_monthly_starts from recent_rate)::numeric, 1) as assumed_monthly_start_rate
from cohort_x_quarter cq
left join lateral (
    select km_survival
    from {{ ref('int_persistence_km') }} km2
    where km2.days_since_first_fill <= cq.days_elapsed
    order by km2.days_since_first_fill desc
    limit 1
) km on true
group by cq.quarters_ahead, cq.quarter_end
order by cq.quarters_ahead
