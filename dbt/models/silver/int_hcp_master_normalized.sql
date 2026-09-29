{{
    config(materialized='view')
}}

-- One row per bronze.hcp_master row (all 14 quarterly snapshots), with
-- the fields the rest of the golden-record chain matches on normalized:
--   - collapse_key: npi when it's usable, else the row's own hcp_id.
--     An empty-string npi (about half of the injected duplicates) must
--     NOT be used as a grouping key - every blank-npi row would collapse
--     into one giant false group otherwise. Falling back to hcp_id keeps
--     each duplicate's own 14 quarters together without merging it into
--     anyone else's.
--   - last_name_norm / first_name_norm / address_norm: uppercased, with
--     name suffixes (JR/SR/II/III/MD) and address suffix words
--     abbreviated to a canonical short form, so a same-person record
--     entered two different ways still compares as near-identical text
--     for the fuzzy match in int_hcp_fuzzy_candidates.
select
    hcp_id,
    npi,
    nullif(npi, '') as npi_clean,
    coalesce(nullif(npi, ''), hcp_id) as collapse_key,
    first_name,
    last_name,
    specialty,
    hco_id,
    territory_id,
    region_id,
    address,
    city,
    state,
    zip,
    quarter,

    upper(first_name) as first_name_norm,
    upper(regexp_replace(last_name, '\s+(JR|SR|II|III|MD)$', '', 'gi')) as last_name_norm,
    upper(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(
        regexp_replace(address, '\mStreet\M', 'St', 'gi'),
        '\mAvenue\M', 'Ave', 'gi'),
        '\mSuite\M', 'Ste', 'gi'),
        '\mRoad\M', 'Rd', 'gi'),
        '\mDrive\M', 'Dr', 'gi'),
        '\mBoulevard\M', 'Blvd', 'gi')
    ) as address_norm
from {{ source('bronze', 'hcp_master') }}
