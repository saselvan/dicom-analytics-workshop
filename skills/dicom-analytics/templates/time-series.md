# Template 4: Time series by modality

Load when the user's question maps to "Time series / trend" class.

## Use case

Volume or metric trends over time for one or more modalities. Standard for
operational monitoring, dose trending, capacity planning.

## Pattern

```sql
SELECT
  DATE_TRUNC('{grain}', <study_date_column>) AS period,
  <modality_column> AS modality,
  COUNT(DISTINCT <study_uid_column>) AS study_count,
  COUNT(*) AS series_count
FROM <curated_surface>
WHERE <study_date_column> >= DATE '{start_date}'
  AND <modality_column> = '{modality}'
GROUP BY 1, 2
ORDER BY 1
```

Constraints:
- `{grain}`: `year`, `quarter`, `month`, `week`, `day` — see Date precision rule below
- `{start_date}`: ISO date format `YYYY-MM-DD`
- `{modality}`: any modality from the canonical list in `SKILL.md` (or a list)

## Worked examples

```sql
-- Q: How many CT studies have been performed since 2018, by year?
SELECT
  DATE_TRUNC('year', study_date) AS year,
  COUNT(DISTINCT study_instance_uid) AS study_count
FROM silver.dicom_series
WHERE modality = 'CT' AND study_date >= DATE '2018-01-01'
GROUP BY 1
ORDER BY 1
```

```sql
-- Q: Monthly MR series volume for the last 24 months, by manufacturer
SELECT
  DATE_TRUNC('month', study_date) AS month,
  CASE
    WHEN UPPER(manufacturer) LIKE '%GE%' THEN 'GE'
    WHEN UPPER(manufacturer) LIKE '%SIEMENS%' THEN 'SIEMENS'
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' THEN 'PHILIPS'
    ELSE manufacturer
  END AS manufacturer_normalized,
  COUNT(*) AS series_count
FROM silver.dicom_series
WHERE modality = 'MR' AND study_date >= current_date() - INTERVAL '24 months'
GROUP BY 1, 2
ORDER BY 1, 2
```

## Date precision considerations

This template's `{grain}` placeholder controls output date precision. Apply Case 3
of the date precision rule (see `domain-rules/phi.md`):

- **No patient identifiers in output** (pure aggregate by period+modality): full
  precision OK at any grain. Use `{grain}` as given.
- **Patient identifiers in output** (e.g., adding `study_uid` for drill-down) AND
  `{grain}` is `day` or `week`: surface the precision question:

  > "You requested daily granularity for a query that includes patient study UIDs.
  > That output exposes per-patient dates at day precision. Confirm: proceed with
  > day-grain (acceptable for your compliance scope), or coarsen to month-grain?"

## Variations

**Multi-modality comparison:**

```sql
WHERE <modality_column> IN ('CT', 'MR', 'PT')
GROUP BY 1, 2  -- period, modality
```

**Year-over-year delta:**

Wrap the base query with `LAG()` for period-over-period comparison.

**Volume by station:**

```sql
GROUP BY 1, <station_name_column>
```

## Domain rules to apply

- `domain-rules/phi.md` — Case 3 (time series with grain placeholder)
- `domain-rules/normalization.md` — if grouping by manufacturer or body part
- `domain-rules/exclusions.md` — exclusion does NOT apply by default (volume time series). If the user requests time-series of a parameter (e.g., P90 slice_thickness over time), apply the parameter analytics rule from `exclusions.md`
