# Template 2: Distribution / percentiles by manufacturer

Load when the user's question maps to "Distribution / percentiles" class.

## Use case

Percentile breakdown of a numeric tag across the fleet. Standard for protocol
calibration, outlier detection, fleet characterization.

## Pattern

```sql
SELECT
  CASE
    WHEN UPPER(<manufacturer_column>) LIKE '%GE%' THEN 'GE'
    WHEN UPPER(<manufacturer_column>) LIKE '%SIEMENS%' THEN 'SIEMENS'
    WHEN UPPER(<manufacturer_column>) LIKE '%PHILIPS%' THEN 'PHILIPS'
    ELSE <manufacturer_column>
  END AS manufacturer_normalized,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY <numeric_tag_column>) AS p50,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY <numeric_tag_column>) AS p90,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY <numeric_tag_column>) AS p99,
  COUNT(*) AS series_count
FROM <curated_surface>
WHERE <modality_column> = '{modality}'
  AND <numeric_tag_column> IS NOT NULL
  AND NOT array_contains(<image_type_column>, 'LOCALIZER')
  AND NOT array_contains(<image_type_column>, 'SCOUT')
GROUP BY 1
ORDER BY series_count DESC
```

## Worked example

```sql
-- Q: slice_thickness distribution for CT, by manufacturer
SELECT
  CASE
    WHEN UPPER(manufacturer) LIKE '%GE%' THEN 'GE'
    WHEN UPPER(manufacturer) LIKE '%SIEMENS%' THEN 'SIEMENS'
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' THEN 'PHILIPS'
    ELSE manufacturer
  END AS manufacturer_normalized,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY slice_thickness) AS p50,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY slice_thickness) AS p90,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY slice_thickness) AS p99,
  COUNT(*) AS series_count
FROM silver.dicom_series
WHERE modality = 'CT'
  AND slice_thickness IS NOT NULL
  AND NOT array_contains(image_type, 'LOCALIZER')
  AND NOT array_contains(image_type, 'SCOUT')
GROUP BY 1
ORDER BY series_count DESC
```

## Variations

**Group by station instead of manufacturer:**

```sql
GROUP BY <station_name_column>  -- single-site fleet view
```

**Add body part as a second grouping dimension:**

```sql
GROUP BY 1, body_part_normalized
```

(Apply body part normalization first — see `domain-rules/normalization.md`.)

**Different percentiles:**

```sql
PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY <numeric_tag_column>) AS p25,
PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY <numeric_tag_column>) AS p75
```

## Domain rules to apply

- `domain-rules/exclusions.md` — LOCALIZER / SCOUT exclusion (non-optional)
- `domain-rules/normalization.md` — manufacturer CASE (above) and body part CASE (if grouping)
- `domain-rules/phi.md` — Case 1 applies (no patient identifiers in output, full date precision OK)
