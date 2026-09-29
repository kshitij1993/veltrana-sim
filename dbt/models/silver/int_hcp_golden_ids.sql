-- One stable surrogate golden_hcp_id per distinct canonical_key. Kept as
-- its own tiny model so both hcp_golden_record and hcp_golden_record_xref
-- reference the exact same id for a given canonical_key.
select
    canonical_key,
    'HCPG' || lpad(row_number() over (order by canonical_key)::text, 6, '0') as golden_hcp_id
from (
    select distinct canonical_key
    from {{ ref('int_hcp_golden_assignment') }}
) d
