# Template 5: Coverage / NULL audit

Load when the user's question maps to "Coverage / data quality" class.

## Use case

Measure what fraction of series have a given tag populated. Used for pipeline
health checks, schema completeness verification, governance reporting.

## Pattern

```sql
SELECT
  <modality_column>,
  COUNT(*) AS total_series,
  COUNT(<tag_column>) AS with_value,
  COUNT(*) - COUNT(<tag_column>) AS null_count,
  ROUND(100.0 * (COUNT(*) - COUNT(<tag_column>)) / COUNT(*), 2) AS null_pct
FROM <curated_surface>
WHERE <modality_column> = '{modality}'
GROUP BY 1
```

`COUNT(<column>)` counts non-NULL values. The arithmetic produces both the raw
count and the percentage.

## Worked examples

```sql
-- Q: What's the slice_thickness coverage rate for CT series?
SELECT
  modality,
  COUNT(*) AS total_series,
  COUNT(slice_thickness) AS with_value,
  COUNT(*) - COUNT(slice_thickness) AS null_count,
  ROUND(100.0 * (COUNT(*) - COUNT(slice_thickness)) / COUNT(*), 2) AS null_pct
FROM silver.dicom_series
WHERE modality = 'CT'
GROUP BY modality
```

```sql
-- Q: ctdi_vol coverage by manufacturer for CT
SELECT
  CASE
    WHEN UPPER(manufacturer) LIKE '%GE%' THEN 'GE'
    WHEN UPPER(manufacturer) LIKE '%SIEMENS%' THEN 'SIEMENS'
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' THEN 'PHILIPS'
    ELSE manufacturer
  END AS manufacturer_normalized,
  COUNT(*) AS total_series,
  COUNT(ctdi_vol) AS with_value,
  ROUND(100.0 * COUNT(ctdi_vol) / COUNT(*), 2) AS pct_populated
FROM silver.dicom_series
WHERE modality = 'CT'
GROUP BY 1
ORDER BY pct_populated DESC
```

## Coverage with exclusions

Coverage is a **volume question** — the LOCALIZER/SCOUT exclusion from
`domain-rules/exclusions.md` does NOT apply by default. All series belong in
the denominator because the question is "what fraction of series have this tag
populated."

When the user asks about **parameter coverage** specifically (e.g., "what % of
CT series have a meaningful slice_thickness value"), apply the exclusion —
localizer slice_thickness values are misleading, and including them inflates
coverage without adding meaningful data.

Surface the choice when ambiguous:

> "Coverage interpretation:
> - **Pipeline health** (include all series — default): does the extraction work for the bronze rows that have this field?
> - **Parameter coverage** (exclude LOCALIZER/SCOUT per `exclusions.md`): of the series where this field is clinically meaningful, what fraction have it?"

## Coverage across multiple tags

```sql
SELECT
  modality,
  COUNT(*) AS total_series,
  ROUND(100.0 * COUNT(slice_thickness) / COUNT(*), 2) AS slice_thickness_pct,
  ROUND(100.0 * COUNT(kvp) / COUNT(*), 2) AS kvp_pct,
  ROUND(100.0 * COUNT(ctdi_vol) / COUNT(*), 2) AS ctdi_vol_pct,
  ROUND(100.0 * COUNT(repetition_time) / COUNT(*), 2) AS repetition_time_pct
FROM silver.dicom_series
GROUP BY modality
```

This is useful for snapshotting overall pipeline health across a tag set. The
zeros for non-applicable fields (e.g., MR fields on CT rows) are expected.

## Domain rules to apply

- `domain-rules/normalization.md` — if grouping by manufacturer/body part
- `domain-rules/phi.md` — Case 1 (no patient identifiers in output, full precision OK)
- `domain-rules/exclusions.md` — exclusion does NOT apply by default (volume question); apply only for parameter coverage queries
