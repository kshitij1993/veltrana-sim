-- bronze.rep_roster passed through, plus n_zips: how many zips
-- silver.alignment assigns to this territory as of this row's month
-- (the most recent annual alignment snapshot on or before that month).
-- alignment.py plants exactly one mid-period realignment - this join is
-- what surfaces it on the roster: n_zips shifts for whichever
-- territories gained or lost zips at that date, and nowhere else does
-- this model invent new business logic beyond that lookup.
with zip_counts as (
    select territory_id, effective_date, count(*) as n_zips
    from {{ ref('alignment') }}
    group by territory_id, effective_date
)

select
    r.territory_id,
    r.region_id,
    r.month,
    r.rep_id,
    r.status,
    z.n_zips
from {{ source('bronze', 'rep_roster') }} r
left join zip_counts z
    on z.territory_id = r.territory_id
    and z.effective_date = (
        select max(z2.effective_date)
        from zip_counts z2
        where z2.territory_id = r.territory_id
          and z2.effective_date <= r.month
    )
