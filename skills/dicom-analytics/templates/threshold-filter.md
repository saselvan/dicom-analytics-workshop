# Template 1: Threshold filter on a curated tag

Load when the user's question maps to "Threshold filter / qualification" class
(see Question Class Catalog in core SKILL.md).

## Use case

Find studies where a numeric DICOM tag meets a threshold. Common in research
cohort identification and quality compliance work.

## Pattern

```sql
SELECT
  <study_uid_column>,
  <series_uid_column>,
  <modality_column>,
  <manufacturer_column>,
  <numeric_tag_column>
FROM <curated_surface>
WHERE <modality_column> = '{modality}'
  AND <numeric_tag_column> {op} {threshold}
  AND NOT array_contains(<image_type_column>, 'LOCALIZER')
  AND NOT array_contains(<image_type_column>, 'SCOUT')
```

Constraints:
- `{modality}`: one of CT, MR, US, XA, ES, PT, DX, CR, MG, RF, NM
- `{numeric_tag_column}`: any numeric column from the working dictionary (DOUBLE, INT)
- `{op}`: `<`, `<=`, `>`, `>=`, `=`, `!=`, `BETWEEN`

## Worked examples

```sql
-- Q: Find CT studies with slice_thickness < 0.75 mm
SELECT study_instance_uid, series_instance_uid, modality, manufacturer, slice_thickness
FROM silver.dicom_series
WHERE modality = 'CT' AND slice_thickness < 0.75
  AND NOT array_contains(image_type, 'LOCALIZER')
  AND NOT array_contains(image_type, 'SCOUT')
```

```sql
-- Q: Find MR studies with repetition_time > 4000 ms
SELECT study_instance_uid, series_instance_uid, modality, manufacturer, repetition_time
FROM silver.dicom_series
WHERE modality = 'MR' AND repetition_time > 4000
```

```sql
-- Q: Find DX studies with kvp BETWEEN 80 AND 120
SELECT study_instance_uid, series_instance_uid, modality, manufacturer, kvp
FROM silver.dicom_series
WHERE modality = 'DX' AND kvp BETWEEN 80 AND 120
```

## Bronze fallback

If `<numeric_tag_column>` isn't in the working dictionary, route to bronze and
use the type-adaptive access pattern from `sql-patterns/<variant|string>.md`.
See `templates/bronze-patterns.md`.

## Domain rules to apply

- `domain-rules/exclusions.md` — LOCALIZER / SCOUT exclusion (non-optional for slice/position/acquisition queries)
- `domain-rules/normalization.md` — if filtering or grouping by manufacturer/body part
- `domain-rules/phi.md` — Case 2 applies (UIDs in output, no patient_age — default month-grain dates)
