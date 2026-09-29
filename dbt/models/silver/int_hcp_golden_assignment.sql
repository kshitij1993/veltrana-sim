-- Maps every collapse_key from int_hcp_master_latest to the key that
-- represents its golden group: itself if it matched no one, or a shared
-- canonical key with its fuzzy-matched partner.
--
-- The canonical side prefers whichever record has a *usable* npi
-- (npi_clean is not null) over one with a blank npi - that's an
-- unambiguous signal. It's NOT unambiguous when both sides show a
-- populated npi: a transposed-digit typo still looks like a well-formed
-- npi, and nothing in the MDM data itself says which of the two is the
-- real one - that would take an external registry lookup (e.g. NPPES),
-- which is out of scope here. For that case we fall back to hcp_id: the
-- record that was already in the roster (not one of the later, injected
-- HCPD... duplicate ids) wins, which is what a real MDM golden-record
-- process does by default absent a stronger signal - prefer the
-- longer-established record. It's a defensible default, not a claim
-- that it's always correct.
with latest as (
    select collapse_key, hcp_id, npi_clean from {{ ref('int_hcp_master_latest') }}
),

matches as (
    select * from {{ ref('int_hcp_fuzzy_candidates') }}
),

pair_canonical as (
    select
        m.collapse_key_a,
        m.collapse_key_b,
        m.match_score,
        m.last_name_sim,
        m.first_name_sim,
        m.address_sim,
        case
            when la.npi_clean is not null and lb.npi_clean is null then la.collapse_key
            when lb.npi_clean is not null and la.npi_clean is null then lb.collapse_key
            when la.hcp_id < lb.hcp_id then la.collapse_key
            else lb.collapse_key
        end as canonical_key
    from matches m
    inner join latest la on la.collapse_key = m.collapse_key_a
    inner join latest lb on lb.collapse_key = m.collapse_key_b
)

select
    l.collapse_key,
    coalesce(pc.canonical_key, l.collapse_key) as canonical_key,
    case when pc.canonical_key is not null then 'fuzzy_match' else 'no_match' end as match_method,
    pc.match_score,
    pc.last_name_sim,
    pc.first_name_sim,
    pc.address_sim
from latest l
left join pair_canonical pc
    on l.collapse_key in (pc.collapse_key_a, pc.collapse_key_b)
