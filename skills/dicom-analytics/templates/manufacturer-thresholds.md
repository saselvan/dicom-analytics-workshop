# Template 3: Manufacturer-specific thresholds

Load when the user's question requires different thresholds per manufacturer
(common in vendor-aware quality compliance, e.g., Philips CT requires different
slice thickness limits than GE/Siemens for thin-slice protocols).

## Use case

Different vendors have different parameter ranges that constitute "qualifying"
versus "not qualifying" for a given clinical or research protocol. Apply
per-manufacturer thresholds in a single CASE.

## Pattern

```sql
SELECT
  <study_uid_column>,
  <series_uid_column>,
  <manufacturer_column>,
  <numeric_tag_column>,
  CASE
    WHEN UPPER(<manufacturer_column>) LIKE '%PHILIPS%' AND <numeric_tag_column> {op_a} {threshold_philips} THEN 'qualifying'
    WHEN UPPER(<manufacturer_column>) NOT LIKE '%PHILIPS%' AND <numeric_tag_column> {op_a} {threshold_other} THEN 'qualifying'
    ELSE 'not qualifying'
  END AS qualification_status
FROM <curated_surface>
WHERE <modality_column> = '{modality}'
  AND NOT array_contains(<image_type_column>, 'LOCALIZER')
  AND NOT array_contains(<image_type_column>, 'SCOUT')
```

## Worked example

```sql
-- Q: Find CT studies meeting manufacturer-specific slice_thickness thresholds:
--    Philips ≤ 0.80 mm, others ≤ 0.425 mm
SELECT
  study_instance_uid, series_instance_uid, manufacturer, slice_thickness,
  CASE
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' AND slice_thickness <= 0.80 THEN 'qualifying'
    WHEN UPPER(manufacturer) NOT LIKE '%PHILIPS%' AND slice_thickness <= 0.425 THEN 'qualifying'
    ELSE 'not qualifying'
  END AS qualification_status
FROM silver.dicom_series
WHERE modality = 'CT'
  AND NOT array_contains(image_type, 'LOCALIZER')
  AND NOT array_contains(image_type, 'SCOUT')
```

## Three-way or N-way thresholds

For more than two threshold groups, expand the CASE:

```sql
CASE
  WHEN UPPER(manufacturer) LIKE '%GE%' AND slice_thickness <= 0.625 THEN 'qualifying'
  WHEN UPPER(manufacturer) LIKE '%SIEMENS%' AND slice_thickness <= 0.50 THEN 'qualifying'
  WHEN UPPER(manufacturer) LIKE '%PHILIPS%' AND slice_thickness <= 0.80 THEN 'qualifying'
  WHEN UPPER(manufacturer) LIKE '%CANON%' AND slice_thickness <= 0.50 THEN 'qualifying'
  ELSE 'not qualifying'
END AS qualification_status
```

## Aggregate version (counts per manufacturer)

To summarize qualification rates rather than list individual studies:

```sql
WITH qualified AS (
  SELECT
    <study_uid_column>,
    <series_uid_column>,
    <manufacturer_column>,
    <numeric_tag_column>,
    CASE
      WHEN UPPER(<manufacturer_column>) LIKE '%PHILIPS%' AND <numeric_tag_column> {op_a} {threshold_philips} THEN 'qualifying'
      WHEN UPPER(<manufacturer_column>) NOT LIKE '%PHILIPS%' AND <numeric_tag_column> {op_a} {threshold_other} THEN 'qualifying'
      ELSE 'not qualifying'
    END AS qualification_status
  FROM <curated_surface>
  WHERE <modality_column> = '{modality}'
    AND NOT array_contains(<image_type_column>, 'LOCALIZER')
    AND NOT array_contains(<image_type_column>, 'SCOUT')
)
SELECT
  CASE
    WHEN UPPER(manufacturer) LIKE '%GE%' THEN 'GE'
    WHEN UPPER(manufacturer) LIKE '%SIEMENS%' THEN 'SIEMENS'
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' THEN 'PHILIPS'
    ELSE manufacturer
  END AS manufacturer_normalized,
  COUNT(*) AS total,
  SUM(CASE WHEN qualification_status = 'qualifying' THEN 1 ELSE 0 END) AS qualifying,
  ROUND(100.0 * SUM(CASE WHEN qualification_status = 'qualifying' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_qualifying
FROM qualified
GROUP BY 1
```

## Domain rules to apply

- `domain-rules/exclusions.md` — LOCALIZER / SCOUT exclusion
- `domain-rules/normalization.md` — manufacturer matching uses LIKE patterns (avoid equality on raw column)
- `domain-rules/phi.md` — Case 2 applies if individual UIDs in output
