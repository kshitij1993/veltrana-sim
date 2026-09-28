# Pharma commercial analytics simulation: Phase 0 design document

## Purpose

This project is a self-contained simulation of a pharma brand's commercial data
ecosystem, built to practice the full analyst workflow end to end: generate
realistic multi-source data with known effects planted inside it, build a
Bronze/Silver/Gold pipeline, run the analysis modules a brand team actually
asks for, and write the findings up the way a QBR readout would. A sealed
answer key makes it a real test of judgment rather than a confirmation
exercise.

It complements the [Pharma Analytics Field Guide](https://kshitij1993.github.io/pharma-analytics-field-guide/),
which covers vocabulary and concepts. This project is the applied layer:
taking a vague business question and producing an answer that holds up under
scrutiny.

## Repo structure

```
/design            this document, plus any supporting notes
/generator          Python data generator, per-source distortion logic
/generator/answer_key.json   sealed until Phase 5, gitignored until then
/dbt                dbt-postgres project targeting Supabase
/sql                standalone analysis SQL for the 9 modules
/notebooks          exploratory Python/pandas work for each module
/readout            Phase 4 QBR-style write-up
```

## Brand profile: Veltrana

Veltrana is a fictional IL-23 inhibitor for adults with moderate-to-severe
plaque psoriasis who are candidates for systemic therapy.

- **Dosing:** subcutaneous, at week 0 and week 4, then every 12 weeks.
- **Clinical positioning:** efficacy comparable to the class leader, with
  quarterly dosing as the main convenience differentiator.
- **Price:** WAC of about $20,500 per dose, with a gross-to-net discount of
  roughly 50 to 55%.
- **Distribution:** a limited network of three specialty pharmacies, a hub
  services program, and a commercial copay card.
- **Timing:** launched March 2025. 18 months of post-launch history through
  August 2026.
- **Strategy:** the brand team's stated positioning is "first-line biologic
  of choice." Whether the data supports that is one of the things the
  analysis is meant to test.

## Competitive landscape

| Product | Archetype | Dosing | Market role |
|---|---|---|---|
| Dermavex (Comp A) | IL-17A inhibitor | Monthly SC | NBRx leader, strongest in commercial |
| Clarivo (Comp B) | IL-23 inhibitor | Every 8 weeks SC | Persistence leader, strong Medicare access |
| Adalimumab biosimilars (Comp C) | TNF inhibitor | Every 2 weeks SC | Lowest net price, often required first via step edits |
| Orelta (Comp D) | Oral TYK2 inhibitor | Daily oral | Growing in biologic-naive patients on convenience |

All brand names are fictional. The archetypes and access dynamics reflect
the real market, including biosimilar step edits.

## Market sizing and scale

Scaled to be laptop-feasible while keeping HCP-level counts realistic. US
reference points are for calibration, not precision.

- **Advanced-therapy patients:** ~450K in the US; simulation runs at 1:3
  scale, ~150K patients.
- **HCP universe:** ~4,000 prescribers: dermatologists (~70%), NPs/PAs in
  derm practices (~20%), rheumatologists and others (~10%).
- **Field force:** 6 regions x 5 territories = 30 territories, ~130 HCPs per rep.
- **Data window:** March 2023 to August 2026 (24 months pre-launch, 18
  months post-launch).
- **Row count:** ~6M+ fill-level rows. Comfortable on Supabase's free tier
  and on an XS-equivalent compute budget.

## Payer landscape

- **Channel mix:** ~60% commercial, 25% Medicare Part D, 12% Medicaid, 3%
  cash/other.
- **Plan structure:** 3 national PBMs cover ~75% of commercial lives;
  regional plans cover the rest.
- **Formulary states:** Preferred, Non-preferred, PA with biosimilar step,
  Not covered.
- **Launch dynamics:** typical new-to-market blocks, with coverage gained
  over the first 6 to 12 months. Always-on headwind, not a planted effect.

## Patient journey baseline

Default rates before any planted effects are applied:

| Stage | Baseline |
|---|---|
| Hub referral to benefit verification | ~95% complete |
| PA required (commercial) | ~85% |
| PA approved on first submission | ~65% |
| Denials appealed and overturned | ~50% |
| Median time from referral to first fill | ~18 days |
| Abandonment at the specialty pharmacy | ~12% |
| 12-month persistence (IL-23 class) | ~70% |

## Data sources

| Dataset | Mimics | Grain | Cadence / lag | Coverage | Built-in quirks |
|---|---|---|---|---|---|
| Rx audit | IQVIA Xponent / NPA | HCP x product x payer channel x week | Weekly, 2-week lag | Projected national | Non-integer projected values, periodic restatements |
| Patient claims | LAAD / Symphony | Patient x claim | Monthly, 4-6 week lag | ~65% of patients, Medicaid undercaptured | Tokenized IDs, eligibility gaps, late adjudication |
| SP and hub status | 852/867 + hub feeds | Patient status event | Daily | ~100% Veltrana, 0% competitors | Inconsistent status codes across the 3 SPs |
| Sell-in | 867 / ex-factory | SP x NDC x day | Daily | 100% | Can diverge from dispenses |
| CRM calls | Veeva-style | Call x rep x HCP | Daily | Near complete | Duplicate logs, late entry |
| Rep roster | HR / field ops | Rep x territory x month | Monthly | 100% | Vacancies appear only here |
| HCP master | OneKey-style MDM | HCP | Quarterly | 100% | ~8% duplicates, address moves, specialty mismatches |
| Formulary | MMIT-style | Plan x product x quarter | Quarterly | Major plans | Effective-date lags |
| Alignment | Zip-to-territory | Zip | Annual | 100% | One mid-period realignment |

The SP data asymmetry is intentional: high resolution on your own brand's
patient journey, competitors visible only through claims. That mirrors what
a real brand team sees.

## Data generator design

**Core principle: one simulated world, many imperfect views.** The generator
first builds a single patient-level "true world": every patient, HCP, payer,
and clinical/access event that actually happened, with no distortion. Every
one of the 9 datasets above is then *derived* from that world by applying
the specific incompleteness, lag, and noise that its real-world counterpart
has. This is what makes source reconciliation meaningful instead of
cosmetic: the SP data doesn't just "have fewer rows," it has exactly the
coverage gap a real SP feed would have, applied to the same underlying
events that show up (differently) in claims.

**Build order:**

1. **World generation.** Simulate the patient population, HCP roster,
   territory/payer assignments, and the full clinical/access timeline for
   every patient (diagnosis, referral, PA, fill, refill, discontinuation,
   switch) against the baseline rates above. This is the ground truth and
   is never touched by any of the 9 "as-observed" generators.
2. **Effect injection.** Before deriving the observed datasets, sample 5 to
   7 candidates from the effect catalog below, randomize their location,
   timing, and magnitude, and apply them to the true world (e.g., shift a
   region's PA approval rate down starting in a given quarter). This step
   writes directly to `answer_key.json` and nothing else reads that file
   until Phase 5.
3. **Per-source derivation.** Each of the 9 datasets gets its own module
   that reads the true world and applies its specific distortion function:
   sampling for claims coverage, weekly aggregation and projection noise for
   the Rx audit, status-code remapping per SP, lag and duplication for CRM.
   These modules never see the answer key.
4. **Always-on traps.** Targeting selection bias, the January deductible
   reset, and channel-mix Simpson's paradox are applied unconditionally in
   this step, regardless of which candidate effects were sampled.
5. **Export.** Write each dataset to CSV/Parquet for loading into Supabase,
   and freeze `answer_key.json` with restricted access (kept out of the
   `dbt` and `sql` folders, gitignored, or encrypted, your call).

**Tech stack:** Python, `numpy`/`pandas` for the world simulation and
distributions, `Faker` for names and addresses on the HCP master, a fixed
`random.seed()` you set privately per run so the world is reproducible but
the effect sampling stays blind to you.

**Open question for Phase 1:** should Bronze be a straight load of these
export files (simplest, mirrors how a real vendor feed lands), or should
the generator write directly into Bronze tables via the Supabase client and
skip the file-export step? Either works; the file-export route is more
realistic to how you'd actually receive vendor data and is the current
default.

## Candidate effect catalog

The generator activates 5 to 7 of these, with randomized location, timing,
and magnitude. This list is a catalog of possibilities, not a preview of
what actually got planted in any given run.

| ID | Candidate effect | Randomized parameters |
|---|---|---|
| E1 | Payer formulary downgrade | Plan or region, quarter, NBRx impact 15-40% |
| E2 | Rep vacancy | Territory, duration 2-6 months |
| E3 | Call saturation | Threshold 4-8 calls/quarter, top deciles |
| E4 | Copay-driven abandonment | Copay threshold and abandonment uplift |
| E5 | Vendor methodology restatement | Month, artificial shift 5-15% |
| E6 | Source-of-business skew | Share of switches from Comp A, 40-70% |
| E7 | Competitor momentum shift | Comp D gains among naive patients, random start month |
| E8 | Speaker program halo | Region, adoption lift among attendee peers |
| E9 | SP inventory build | Quarter, 1-3 weeks excess supply |
| E10 | SP-level persistence gap | One SP with weaker refill performance |

**Always-on traps** (independent of which candidates are sampled):

- Targeting selection bias: reps call more on high-potential HCPs, so a
  naive analysis overstates call impact.
- January deductible reset: commercial NBRx dips every January.
- Channel-mix Simpson's paradox: aggregate trends can reverse direction
  within payer segments.

## Storage architecture: Supabase (Postgres)

Swapped from Snowflake to keep the project free of charge long-term.

- Bronze/Silver/Gold implemented as three Postgres **schemas** in one
  Supabase database, rather than three Snowflake databases.
- `dbt-postgres` targets Supabase directly; the transformation layer is
  otherwise unchanged from the original design.
- Gold is exposed as views (or materialized views where refresh cost
  matters), matching the diagram's Gold layer.
- Row-level security is not required for a single-user project, but is a
  natural fit if the Gold layer is ever exposed read-only behind the
  text-to-SQL app.
- Known constraint: the free tier pauses after a week of inactivity and
  wakes on the next request. Not a blocker, just worth knowing.

## Analytics modules

Each maps to a question a brand director or commercial analytics lead
actually asks:

1. **Launch tracking:** are we on track, vs. analog launches?
2. **Source of business:** where are new patients coming from (line of
   therapy from claims)?
3. **Patient journey and persistence:** where do we lose patients? Referral-
   to-fill funnel, Kaplan-Meier persistence, PDC.
4. **Market access impact:** what did the formulary change cost us?
   Difference-in-differences against unaffected regions, pull-through.
5. **Sales decline diagnostic:** why is a given region down X%? Decompose
   into market, share, access, and field effects.
6. **HCP segmentation and targeting:** potential vs. current value, find
   whitespace HCPs.
7. **Promotional response:** call lift with matched controls or regression,
   avoiding the "high callers write more, so calls work" trap.
8. **Data quality and reconciliation:** sell-in vs. sell-out, inventory
   build, anomaly detection (the projection restatement).
9. **Forecast:** patient-based forecast for the next four quarters.

## Delivery phases

- **Phase 0:** this document. ✅
- **Phase 1:** Python data generator, with planted effects sealed in
  `answer_key.json`.
- **Phase 2:** Supabase (Postgres) Bronze/Silver/Gold schemas, built with
  dbt, plus HCP golden record matching against Bronze.
- **Phase 3:** analysis modules in SQL and Python.
- **Phase 4:** insight readout written as a brand team QBR: headline,
  evidence, "so what," recommended action.
- **Phase 5:** grade against the answer key, document misses, publish as a
  "Case Study" mode in the field guide.

## Phase 5 grading rubric

Each activated effect scored on:

- **Detection:** found at all?
- **Attribution:** right cause named, not a confounder?
- **Sizing:** impact estimate within ±25% of true value?
- **Timing:** located within one period of when it started?

Claimed effects that weren't planted count against the score. That mirrors
the skepticism of a real QBR audience.
