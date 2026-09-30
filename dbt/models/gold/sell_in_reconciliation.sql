-- Sell-in (manufacturer's shipment ledger, silver.sell_in) vs. observed
-- dispense (silver.sp_hub_normalized's first_fill + refill events), by
-- month and by SP.
--
-- Deliberately NOT built from claims_clean: claims has no sp column at
-- all - a claims vendor never sees which specialty pharmacy dispensed
-- a fill, only the brand's own hub feed does (that's the real
-- asymmetry the README calls out). sp_hub_normalized is also just a
-- better dispense signal for this specific comparison regardless: 100%
-- Veltrana coverage, no claims lag, no eligibility-gap sampling.
--
-- variance_flag fires when the gap exceeds 25% of that month's dispense
-- volume (or 5 units, whichever is bigger, so a 1-2 unit gap in an
-- early, thin month doesn't read as a false alarm at 200%+ relative
-- variance).
with dispense_monthly as (
    select
        sp,
        date_trunc('month', event_date)::date as month,
        count(*) as dispense_units
    from {{ ref('sp_hub_normalized') }}
    where journey_stage in ('first_fill', 'refill')
    group by sp, date_trunc('month', event_date)
),

sell_in_monthly as (
    select
        sp,
        date_trunc('month', ship_date)::date as month,
        sum(units) as sell_in_units
    from {{ ref('sell_in') }}
    group by sp, date_trunc('month', ship_date)
),

combined as (
    select
        coalesce(s.sp, d.sp) as sp,
        coalesce(s.month, d.month) as month,
        coalesce(s.sell_in_units, 0) as sell_in_units,
        coalesce(d.dispense_units, 0) as dispense_units
    from sell_in_monthly s
    full outer join dispense_monthly d on d.sp = s.sp and d.month = s.month
)

select
    sp,
    month,
    sell_in_units,
    dispense_units,
    sell_in_units - dispense_units as variance_units,
    round(100.0 * (sell_in_units - dispense_units) / nullif(dispense_units, 0), 1) as variance_pct,
    abs(sell_in_units - dispense_units) > greatest(dispense_units * 0.25, 5) as variance_flag
from combined
order by sp, month
