-- Fuzzy-matches the ~4,320 collapse_key identities from
-- int_hcp_master_latest against each other to catch same-person
-- duplicates that didn't share a usable npi in the collapse step.
--
-- Blocked on (territory_id, specialty): a duplicate MDM record still
-- carries the real person's actual territory and, usually, their actual
-- specialty - only the ~2% specialty-mislabel quirk can knock a true
-- pair out of this block, which is a real, acknowledged miss, not a bug.
-- Candidate pairs are trigram-similarity-scored on normalized last name,
-- first name, and address (pg_trgm), and only *mutual* best matches
-- above the threshold survive - each identity ends up paired with at
-- most one other. That's sufficient here because this dataset never
-- plants more than one duplicate per real HCP, so a match graph is only
-- ever isolated pairs, never longer chains needing full transitive
-- closure.
{% set threshold = 0.55 %}

with base as (
    select * from {{ ref('int_hcp_master_latest') }}
),

candidates as (
    select
        a.collapse_key as collapse_key_a,
        b.collapse_key as collapse_key_b,
        similarity(a.last_name_norm, b.last_name_norm) as last_name_sim,
        similarity(a.first_name_norm, b.first_name_norm) as first_name_sim,
        similarity(a.address_norm, b.address_norm) as address_sim,
        (
            0.5 * similarity(a.last_name_norm, b.last_name_norm)
            + 0.2 * similarity(a.first_name_norm, b.first_name_norm)
            + 0.3 * similarity(a.address_norm, b.address_norm)
        ) as match_score
    from base a
    join base b
        on a.collapse_key < b.collapse_key
        and a.territory_id = b.territory_id
        and a.specialty = b.specialty
),

scored as (
    select *
    from candidates
    where match_score >= {{ threshold }}
),

best_per_a as (
    select *, row_number() over (partition by collapse_key_a order by match_score desc) as rn_a
    from scored
),

best_per_b as (
    select *, row_number() over (partition by collapse_key_b order by match_score desc) as rn_b
    from scored
)

select
    a.collapse_key_a,
    a.collapse_key_b,
    a.last_name_sim,
    a.first_name_sim,
    a.address_sim,
    a.match_score
from best_per_a a
join best_per_b b
    on a.collapse_key_a = b.collapse_key_a
    and a.collapse_key_b = b.collapse_key_b
where a.rn_a = 1 and b.rn_b = 1
