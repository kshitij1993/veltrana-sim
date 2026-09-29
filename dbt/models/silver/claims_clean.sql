-- bronze.claims with hcp_id replaced by golden_hcp_id. Every other
-- value - patient_token, dates, is_late_adjudication, the lot - is
-- passed through exactly as observed. patient_token is already
-- tokenized upstream and isn't touched here; there's no HCP-style
-- duplicate problem on the patient side to resolve.
--
-- left join (not inner), same reasoning as rx_audit_clean: a failed
-- match surfaces as a null golden_hcp_id rather than a row that just
-- silently isn't there, and the not_null test catches it.
select
    c.claim_id,
    c.patient_token,
    c.product,
    x.golden_hcp_id,
    c.payer_channel,
    c.plan_id,
    c.region_id,
    c.territory_id,
    c.service_date,
    c.adjudication_date,
    c.is_late_adjudication,
    c.fill_number
from {{ source('bronze', 'claims') }} c
left join {{ ref('hcp_golden_record_xref') }} x on x.raw_hcp_id = c.hcp_id
