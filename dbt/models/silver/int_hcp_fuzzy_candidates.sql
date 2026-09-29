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
--
-- address_sim >= 0.5 is a hard requirement, not just part of the
-- weighted score. It was added after an audit of a run's fuzzy matches
-- turned up 5 false positives out of 325 (two different real HCPs who
-- happened to share last name + territory + specialty, e.g. two
-- different "Tammy Williams", both dermatologists in T0401) - every one
-- of them scored above the old 0.55 match_score threshold on last-name +
-- first-name similarity alone, with a real address_sim under 0.3. Every
-- *genuine* duplicate in that same audit had
-- address_sim >= 0.667 (nearly all exactly 1.0) - a real duplicate
-- record is a re-entry of the same provider's same known address, so a
-- clean gap between "same address, near-certainly the same person" and
-- "same surname at a different address, near-certainly two different
-- people" is the reliable signal here, more reliable than the blended
-- score (true-match/false-positive match_scores came within 0.02 of
-- each other: 0.725 vs 0.707). Same-name-different-address pairs like
-- that no longer match at all now; a true duplicate never loses because
-- of it.
{% set threshold = 0.6 %}
{% set address_sim_floor = 0.5 %}

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
      and address_sim >= {{ address_sim_floor }}
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
