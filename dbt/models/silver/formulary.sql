-- bronze.formulary passed through as-is - plan x product x quarter
-- formulary state, already at the grain and cleanliness Gold needs.
select
    plan_id,
    product,
    quarter,
    formulary_state,
    effective_date
from {{ source('bronze', 'formulary') }}
