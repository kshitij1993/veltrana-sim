-- bronze.sell_in passed through as-is - SP x NDC x day shipment ledger,
-- already at the grain and cleanliness Gold needs.
select
    sell_in_id,
    ndc,
    sp,
    ship_date,
    units
from {{ source('bronze', 'sell_in') }}
