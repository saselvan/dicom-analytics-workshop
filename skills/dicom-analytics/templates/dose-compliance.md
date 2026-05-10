# Template 6: Dose compliance vs Diagnostic Reference Levels (CT)

Load when the user's question maps to "Dose compliance" class.

## Use case

CT dose monitoring against institutional or national DRLs (ACR Dose Index
Registry, European DRLs, etc.). Identify outliers, characterize fleet dose
distribution by body region, support regulatory reporting.

## Scope: image-header dose, not RDSR

This template queries image-header `CTDIvol (0018,9345)` from the curated
silver. That's correct for fleet characterization, vendor comparison, and
outlier identification. It is **not** the source for regulatory submission.

ACR Dose Index Registry, state dose registries, per-irradiation-event analyses,
and patient cumulative-dose tracking require X-Ray Radiation Dose Structured
Reports (RDSR), which sit in bronze as separate SOP instances. See
`templates/bronze-patterns.md` "Dose Structured Reports" for detection and the
recommended Python escalation path.

## Pattern — outliers exceeding threshold

Requires `ctdi_vol` and `body_part_examined` in the curated surface. Apply body
part normalization (see `domain-rules/normalization.md`) because raw
`body_part_examined` is technologist-entered free text.

```sql
WITH normalized AS (
  SELECT *,
    CASE
      WHEN (UPPER(<body_part_column>) LIKE '%CHEST%' AND UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%')
        OR UPPER(<body_part_column>) LIKE '%CAP%' THEN 'CHEST_ABDOMEN_PELVIS'
      WHEN (UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%')
        OR UPPER(<body_part_column>) LIKE 'ABD%PEL%' THEN 'ABDOMEN_PELVIS'
      WHEN UPPER(<body_part_column>) LIKE '%CHEST%' OR UPPER(<body_part_column>) LIKE '%THORAX%' THEN 'CHEST'
      WHEN UPPER(<body_part_column>) LIKE '%ABDOMEN%' THEN 'ABDOMEN'
      WHEN UPPER(<body_part_column>) LIKE '%HEAD%' OR UPPER(<body_part_column>) LIKE '%BRAIN%' THEN 'HEAD'
      ELSE UPPER(<body_part_column>)
    END AS body_part_normalized
  FROM <curated_surface>
)
SELECT
  <study_uid_column>,
  <series_uid_column>,
  body_part_normalized,
  <body_part_column> AS body_part_raw,
  <ctdi_vol_column>,
  <manufacturer_column>,
  <station_name_column>
FROM normalized
WHERE <modality_column> = 'CT'
  AND body_part_normalized = '{body_part}'
  AND <ctdi_vol_column> > {drl_threshold}
  AND NOT array_contains(<image_type_column>, 'LOCALIZER')
  AND NOT array_contains(<image_type_column>, 'SCOUT')
ORDER BY <ctdi_vol_column> DESC
```

## Worked example

```sql
-- Q: chest CT exceeding institutional DRL of 14 mGy
WITH normalized AS (
  SELECT *,
    CASE
      WHEN (UPPER(body_part_examined) LIKE '%CHEST%' AND UPPER(body_part_examined) LIKE '%ABDOMEN%' AND UPPER(body_part_examined) LIKE '%PELVIS%')
        OR UPPER(body_part_examined) LIKE '%CAP%' THEN 'CHEST_ABDOMEN_PELVIS'
      WHEN UPPER(body_part_examined) LIKE '%CHEST%' OR UPPER(body_part_examined) LIKE '%THORAX%' THEN 'CHEST'
      ELSE UPPER(body_part_examined)
    END AS body_part_normalized
  FROM silver.dicom_series
)
SELECT study_instance_uid, series_instance_uid, body_part_normalized,
       body_part_examined AS body_part_raw, ctdi_vol, manufacturer, station_name
FROM normalized
WHERE modality = 'CT' AND body_part_normalized = 'CHEST'
  AND ctdi_vol > 14.0
  AND NOT array_contains(image_type, 'LOCALIZER')
  AND NOT array_contains(image_type, 'SCOUT')
ORDER BY ctdi_vol DESC
```

## Pattern — distribution by body region (ACR DIR-style)

```sql
WITH normalized AS (
  SELECT *,
    CASE
      WHEN (UPPER(<body_part_column>) LIKE '%CHEST%' AND UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%')
        OR UPPER(<body_part_column>) LIKE '%CAP%' THEN 'CHEST_ABDOMEN_PELVIS'
      WHEN (UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%') THEN 'ABDOMEN_PELVIS'
      WHEN UPPER(<body_part_column>) LIKE '%CHEST%' OR UPPER(<body_part_column>) LIKE '%THORAX%' THEN 'CHEST'
      WHEN UPPER(<body_part_column>) LIKE '%ABDOMEN%' THEN 'ABDOMEN'
      WHEN UPPER(<body_part_column>) LIKE '%HEAD%' OR UPPER(<body_part_column>) LIKE '%BRAIN%' THEN 'HEAD'
      ELSE UPPER(<body_part_column>)
    END AS body_part_normalized
  FROM <curated_surface>
  WHERE <modality_column> = 'CT'
    AND <ctdi_vol_column> IS NOT NULL
    AND NOT array_contains(<image_type_column>, 'LOCALIZER')
    AND NOT array_contains(<image_type_column>, 'SCOUT')
)
SELECT
  body_part_normalized,
  COUNT(*) AS series_count,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY <ctdi_vol_column>) AS p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY <ctdi_vol_column>) AS p75,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY <ctdi_vol_column>) AS p95
FROM normalized
GROUP BY 1
ORDER BY p50 DESC
```

## Common DRL values (informational, US institutional examples)

| Body region | CTDIvol DRL (mGy) | Notes |
|-------------|-------------------|-------|
| Head (adult) | 60 | Routine head |
| Head (pediatric) | 30–40 | Age-stratified in practice |
| Chest (adult) | 14 | Routine chest |
| Abdomen (adult) | 25 | Routine abdomen |
| Abdomen-pelvis (adult) | 25 | Combined exam |

These are illustrative values; institutional DRLs vary. Each site should set
their actual DRLs based on their compliance scope (ACR DIR participation, state
regulations, etc.).

## Modalities other than CT

CTDIvol is CT-specific. For other modalities:
- **Mammography:** Mean Glandular Dose (MGD) — see DICOM (0040,0316)
- **Fluoroscopy / X-ray:** Dose Area Product (DAP) — see DICOM (0018,115E)
- **PET / nuclear medicine:** Radiopharmaceutical activity — DICOM (0018,1074)

These tags may not be in the typical curated silver shape; check the working
dictionary or fall back to bronze.

## Domain rules to apply

- `domain-rules/exclusions.md` — LOCALIZER and SCOUT exclusion (parameter analytics — non-optional)
- `domain-rules/normalization.md` — body part CASE pattern (above)
- `domain-rules/phi.md` — Case 2 if individual UIDs in output
