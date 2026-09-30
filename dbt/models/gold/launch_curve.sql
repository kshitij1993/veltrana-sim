-- Veltrana's cumulative NBRx by month since launch, next to Clarivo
-- over the same calendar months, as the analog.
--
-- Clarivo, not a data-mined pick: it's the only other IL-23 inhibitor
-- in the competitive set (README's competitive-landscape table), so
-- it's the natural mechanism-of-action analog a real brand team would
-- benchmark against. None of the 4 competitors actually launch inside
-- this simulation's window - they're all already on the market at
-- SIM_START - so there's no "months since ITS OWN launch" curve to
-- align to; this instead lines Clarivo's volume up against Veltrana's
-- launch-month calendar, answering "how does our ramp compare to what
-- an established comparable adds over an equivalent stretch."
--
-- launch_month is hardcoded to 2025-03-01, matching
-- generator/config.py's LAUNCH_DATE - keep these in sync if that ever
-- changes. It has to be the real calendar launch date, not "the first
-- month with observed Veltrana volume": the ramp formula in world.py
-- (veltrana_share = 0.12 * months_since_launch/9) is exactly 0 in the
-- launch month itself, so month 0 is a true, meaningful zero - an
-- earlier version of this model anchored on first-observed-volume
-- instead and silently dropped that month.
with bounds as (
    select
        date '2025-03-01' as launch_month,
        max(date_trunc('month', week_of))::date as max_month
    from {{ ref('rx_audit_clean') }}
),

months as (
    select generate_series(launch_month, max_month, interval '1 month')::date as month
    from bounds
),

monthly as (
    select
        product,
        date_trunc('month', week_of)::date as month,
        sum(projected_nrx) as nrx
    from {{ ref('rx_audit_clean') }}
    where product in ('VELTRANA', 'CLARIVO')
    group by product, date_trunc('month', week_of)
),

pivoted as (
    select
        m.month,
        (
            extract(year from age(m.month, b.launch_month)) * 12
            + extract(month from age(m.month, b.launch_month))
        )::int as months_since_launch,
        coalesce(sum(case when mo.product = 'VELTRANA' then mo.nrx end), 0) as veltrana_nrx,
        coalesce(sum(case when mo.product = 'CLARIVO' then mo.nrx end), 0) as clarivo_nrx
    from months m
    cross join bounds b
    left join monthly mo on mo.month = m.month
    group by m.month, b.launch_month
)

select
    months_since_launch,
    month,
    veltrana_nrx,
    clarivo_nrx,
    sum(veltrana_nrx) over (order by months_since_launch) as veltrana_cumulative_nrx,
    sum(clarivo_nrx) over (order by months_since_launch) as clarivo_cumulative_nrx
from pivoted
order by months_since_launch
