-- bronze.alignment passed through as-is - zip x territory x
-- effective_date, already at the grain and cleanliness Gold needs. Its
-- own model mainly so silver.rep_roster can ref() it.
select
    zip,
    territory_id,
    region_id,
    effective_date
from {{ source('bronze', 'alignment') }}
