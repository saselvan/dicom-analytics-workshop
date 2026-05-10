# Template 8: Cohort identification

Load when the user's question maps to "Cohort / case identification" class.

## Use case

Multi-criteria cohort assembly for research enrollment, AI training data
preparation, clinical trial recruitment, or quality registry submission.
Combines demographic + technical + temporal + exclusion criteria into one query
and produces both the cohort itself (study/series UIDs) and a cohort summary.

Different from Templates 1–3 because the output is a list of UIDs for handoff,
not an aggregate.

## Pattern — cohort query

Date precision follows `domain-rules/phi.md` Case 2. The output includes UIDs
(pseudonymous identifiers), so dates must be truncated. The generation logic:

1. Build the cohort CTE with full-precision dates in WHERE (Case 4 — OK).
2. Compute `max_age_int` over the cohort.
3. If `max_age_int >= 89` → year-truncate all dates in the SELECT (Safe Harbor).
4. Otherwise → month-truncate dates in the SELECT (Case 2 default).

```sql
WITH cohort AS (
  SELECT
    <study_uid_column>,
    <series_uid_column>,
    <modality_column>,
    <manufacturer_column>,
    <body_part_column>,
    <study_date_column>,
    <patient_age_column>,
    CAST(REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*Y?\\s*$', 1) AS INT) AS age_int,
    <slice_thickness_column>,
    <contrast_bolus_agent_column>
  FROM <curated_surface>
  WHERE <modality_column> = '{modality}'
    -- Body part: apply normalization (see domain-rules/normalization.md)
    AND ({body_part_normalization_clause})
    -- Age range: parse age string to integer (see domain-rules/parsing.md)
    -- NOTE: this filter only matches Y-unit ages. For pediatric cohorts
    -- (M/W/D units), use the age_days CASE from domain-rules/parsing.md instead.
    -- See "Pediatric age warning" below.
    AND CAST(REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*Y?\\s*$', 1) AS INT)
        BETWEEN {age_min} AND {age_max}
    AND <study_date_column> BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    -- Manufacturer set: list of vendors, normalized
    AND ({manufacturer_filter_clause})
    -- Technical parameter constraint
    AND <slice_thickness_column> {slice_op} {slice_threshold}
    -- Contrast presence
    AND <contrast_bolus_agent_column> IS {contrast_filter}
    -- Standard exclusions (non-optional per domain-rules/exclusions.md)
    AND NOT array_contains(<image_type_column>, 'LOCALIZER')
    AND NOT array_contains(<image_type_column>, 'SCOUT')
    -- Protocol exclusions (per request)
    AND ({protocol_exclusion_clause})
),
age_envelope AS (
  SELECT MAX(age_int) AS max_age FROM cohort
)
-- Date truncation: Case 2 of domain-rules/phi.md
-- {date_trunc_grain} = 'year' if max_age >= 89, else 'month'
SELECT
  <study_uid_column>,
  <series_uid_column>,
  <modality_column>,
  <manufacturer_column>,
  <body_part_column>,
  DATE_TRUNC('{date_trunc_grain}', <study_date_column>) AS study_date,
  <patient_age_column>,
  <slice_thickness_column>,
  <contrast_bolus_agent_column>
FROM cohort
```

**Generation-time logic** (not in the SQL — applies when building the query):

Determine `{date_trunc_grain}` before emitting the final SELECT. Run:
```sql
SELECT MAX(CAST(REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*[YMWD]?\\s*$', 1) AS INT)) AS max_age
FROM <curated_surface>
WHERE <modality_column> = '{modality}' AND ...  -- same filters as cohort
```
If `max_age >= 89` → set `{date_trunc_grain}` = `'year'`. Otherwise → `'month'`.

## Pattern — cohort summary

Generate alongside the cohort query so the user sees the size before
downloading the full UID list. Dates are truncated to the same grain as the
cohort query:

```sql
SELECT
  COUNT(DISTINCT <study_uid_column>) AS cohort_size_studies,
  COUNT(*) AS cohort_size_series,
  COUNT(DISTINCT <manufacturer_column>) AS distinct_manufacturers,
  MIN(DATE_TRUNC('{date_trunc_grain}', <study_date_column>)) AS earliest_study,
  MAX(DATE_TRUNC('{date_trunc_grain}', <study_date_column>)) AS latest_study,
  PERCENTILE_CONT(0.5) WITHIN GROUP (
    ORDER BY CAST(REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*[YMWD]?\\s*$', 1) AS INT)
  ) AS median_age_years
FROM cohort
```

## Worked example

CT chest studies in patients 50–70 with contrast, 2022–2024, GE or Siemens only,
slice thickness ≤ 1 mm, excluding trauma protocols:

```sql
-- Age range 50-70 → max_age < 89 → month-grain dates (Case 2 default)
WITH cohort AS (
  SELECT study_instance_uid, series_instance_uid, modality, manufacturer,
         body_part_examined, study_date, patient_age, slice_thickness,
         contrast_bolus_agent
  FROM silver.dicom_series
  WHERE modality = 'CT'
    AND (UPPER(body_part_examined) LIKE '%CHEST%'
         OR UPPER(body_part_examined) LIKE '%THORAX%')
    AND CAST(REGEXP_EXTRACT(patient_age, '^\\s*(\\d+)\\s*Y?\\s*$', 1) AS INT) BETWEEN 50 AND 70
    AND study_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31'
    AND (UPPER(manufacturer) LIKE '%GE%' OR UPPER(manufacturer) LIKE '%SIEMENS%')
    AND slice_thickness <= 1.0
    AND contrast_bolus_agent IS NOT NULL
    AND NOT array_contains(image_type, 'LOCALIZER')
    AND NOT array_contains(image_type, 'SCOUT')
    AND NOT (UPPER(protocol_name) LIKE '%TRAUMA%'
             OR UPPER(protocol_name) LIKE '%EMERGEN%')
)
SELECT
  study_instance_uid, series_instance_uid, modality, manufacturer,
  body_part_examined,
  DATE_TRUNC('month', study_date) AS study_date,  -- Case 2: month-grain (age range < 89)
  patient_age, slice_thickness, contrast_bolus_agent
FROM cohort
```

## Cohort query conventions

- **Always produce both the cohort and the summary** in the same response.
  Researchers want the size visible before they commit to downloading.
- **Apply standard exclusions automatically.** LOCALIZER and SCOUT are
  non-optional. Custom exclusions (trauma, emergency, specific protocols) come
  from the user's request.
- **Output study + series UIDs both.** Some downstream workflows operate on
  studies, others on series. Provide both columns; consumer chooses.
- **Surface the cohort PHI envelope.** If the cohort summary includes
  `median_age_years` ≥ 89 OR `MAX(patient_age)` indicates 90+ ages present,
  year-truncate dates per Case 2 of the date precision rule.
- **Date precision in cohort output:** applied in the generated SQL via
  `DATE_TRUNC('{date_trunc_grain}', ...)`. The skill determines the grain at
  generation time: month-grain default, year-grain if the cohort's
  `MAX(age_int) >= 89`. This is not deferred to the user — the correct query
  is emitted directly.

## Pediatric age warning

The default age filter `REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*Y?\\s*$', 1)`
matches year-unit ages (and suffix-stripped values). Patients with `nnnM` (months), `nnnW` (weeks), or
`nnnD` (days) age values silently return NULL from the regex, NULL fails the
BETWEEN check, and the row is dropped. **No error, no warning — just zero rows
for pediatric patients.**

**Generation-time check (required when `{age_min}` < 2 OR user mentions
pediatric, neonatal, or infant):**

Before emitting the cohort SQL, probe for non-Y age units:

```sql
SELECT DISTINCT REGEXP_EXTRACT(<patient_age_column>, '[YMWD]', 0) AS unit
FROM <curated_surface>
WHERE <patient_age_column> IS NOT NULL
LIMIT 100
```

**If non-Y units exist AND `{age_min}` < 2**, surface a warning:

> "Your `patient_age` data includes non-year units (M/W/D) which the default
> age filter excludes. For a pediatric cohort, switch to the day-conversion
> pattern in `parsing.md`. To proceed with adults only, confirm."

**If non-Y units exist but `{age_min}` >= 18**, proceed with the Y-only filter
— pediatric exclusion is intended. Mention inline:

> "Note: {n} records with non-year age units (M/W/D) are excluded by the
> Y-unit age filter. This is expected for an adult cohort."

If the user confirms pediatric inclusion, replace the age filter with the
`age_days` CASE expression from `domain-rules/parsing.md` and convert
`{age_min}` / `{age_max}` to days for the BETWEEN comparison.

## Variations

**No technical filter, demographic only:**
Drop the slice_thickness clause for purely demographic cohorts.

**With contrast subgroup analysis:**
Wrap the cohort CTE with a GROUP BY on `contrast_bolus_agent IS NOT NULL` to
produce both contrast and non-contrast subgroups in one query.

**Longitudinal patient cohort:**
DICOM doesn't carry a stable cross-study patient identifier without joining to
RIS or EHR. If the user's cohort needs longitudinal tracking, surface the limit:
"DICOM alone can identify studies meeting these criteria, but longitudinal
tracking of the same patient across studies needs RIS/EHR data — without that,
each study is treated independently. Confirm scope."

## Domain rules to apply

- `domain-rules/exclusions.md` — LOCALIZER / SCOUT (always)
- `domain-rules/normalization.md` — body part and manufacturer (always)
- `domain-rules/parsing.md` — patient age regex
- `domain-rules/phi.md` — Case 2 (UIDs in output, date precision)
