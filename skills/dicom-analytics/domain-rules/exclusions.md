# Domain rules — exclusions

Load when generating queries that touch acquisition parameters, dose metrics,
or cohort identification criteria.

## Scope: parameter analytics vs volume queries

This exclusion applies to **parameter analytics** — queries on slice thickness,
image position, pixel spacing, acquisition parameters, dose metrics (CTDIvol,
DLP), and technical-parameter cohort criteria. In these contexts, LOCALIZER and
SCOUT series carry misleading values (e.g., `slice_thickness` encodes scan
range, not slice interval; `ImagePositionPatient` indicates scout positioning,
not patient anatomy alignment).

This exclusion does **NOT** apply to **volume queries** — series counts, study
counts, coverage audits, tag-discovery questions, or utilization timing. In
those contexts, all series including localizers contribute to the correct
answer.

| Query type | Exclusion applies? | Reason |
|---|---|---|
| Slice/position/acquisition parameter analytics | **Yes** — non-optional | Parameter values are misleading on localizers |
| Dose compliance (CTDIvol, DLP) | **Yes** — non-optional | Dose values on scouts are scan-range artifacts |
| Cohort identification with technical criteria | **Yes** — non-optional | Technical criteria use parameter values |
| Volume / count queries | **No** | All series are part of the count |
| Coverage / data quality queries | **No** | All series belong in the denominator |
| Tag-discovery / EAV exploration | **No** | Localizer tags are valid data |
| Scanner utilization (timing) | **No** | Localizer scans contribute to utilization |
| Time-series of volume | **No** | Volume question |
| Time-series of a parameter (e.g., P90 slice_thickness over time) | **Yes** | Parameter analytics rule applies |

## The exclusion

```sql
WHERE NOT array_contains(image_type, 'LOCALIZER')
  AND NOT array_contains(image_type, 'SCOUT')
```

When this rule applies, it is **non-optional**. Apply silently in generated
queries; mention inline once when applying ("Excluding LOCALIZER and SCOUT
series — standard for parameter analytics").

## Bronze fallback for image_type

If `image_type` is not in the working dictionary (Discovery Step 5 didn't find it),
fall back to bronze extraction:

```sql
-- VARIANT
NOT array_contains(
  try_variant_get(payload, '$.00080008.Value', 'array<string>'),
  'LOCALIZER'
)
AND NOT array_contains(
  try_variant_get(payload, '$.00080008.Value', 'array<string>'),
  'SCOUT'
)

-- STRING
NOT array_contains(
  from_json(get_json_object(payload, '$.00080008.Value'), 'array<string>'),
  'LOCALIZER'
)
AND NOT array_contains(
  from_json(get_json_object(payload, '$.00080008.Value'), 'array<string>'),
  'SCOUT'
)
```

## Other exclusion considerations

These are NOT non-optional but worth surfacing for technical-parameter analytics:

- **Derived series.** ImageType containing `DERIVED` or `SECONDARY` typically means
  reformatted, post-processed, or computed series — not the original acquisition.
  For protocol calibration analytics, exclude. For coverage / volume, include.
- **Calibration / phantom series.** Some protocols include phantom imaging in
  routine workflows. ImageType may contain `PHANTOM`. Exclude from clinical
  analytics.

These are user-confirmable defaults. Surface in the question refinement when
ambiguous: "Default exclusions: LOCALIZER, SCOUT, DERIVED. Apply, or include all?"
