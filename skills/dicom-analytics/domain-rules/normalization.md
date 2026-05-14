# Domain rules — normalization

Load when generating queries that filter on `manufacturer` or `body_part_examined`,
or that group by either.

## Manufacturer normalization

Real data has variants: `'GE'`, `'GE MEDICAL SYSTEMS'`, `'GE Healthcare'`,
`'GE HEALTHCARE'` should all collapse to `'GE'`. Without normalization, equality
filters miss large fractions of relevant studies.

**Preferred (config-driven):** If `manufacturer_encoding_config` exists in the
catalog (Discovery Step 4 will find it), JOIN to it for manufacturer-aware
normalization that also carries unit conversion factors and per-manufacturer
thresholds:

```sql
-- For manufacturer grouping in analytics
WITH mfr_config AS (
  SELECT DISTINCT manufacturer_pattern,
    CASE
      WHEN manufacturer_pattern LIKE '%GE%' THEN 'GE'
      WHEN manufacturer_pattern LIKE '%SIEMENS%' THEN 'SIEMENS'
      WHEN manufacturer_pattern LIKE '%Philips%' THEN 'PHILIPS'
      WHEN manufacturer_pattern LIKE '%CANON%' OR manufacturer_pattern LIKE '%TOSHIBA%' THEN 'CANON'
      ELSE 'OTHER'
    END AS manufacturer_group
  FROM <catalog>.dicom_silver.manufacturer_encoding_config
)
SELECT s.*,
  COALESCE(mc.manufacturer_group, s.manufacturer) AS manufacturer_normalized
FROM <curated_surface> s
LEFT JOIN mfr_config mc
  ON UPPER(s.manufacturer) LIKE UPPER(mc.manufacturer_pattern)
```

For threshold queries (e.g., "thin-slice CT by manufacturer"), the config table
carries per-manufacturer thresholds (`threshold_value`) and slice category
boundaries (`slice_category_thin`, `slice_category_std`). This handles the
Philips 0.80mm vs others 0.425mm difference automatically:

```sql
SELECT s.manufacturer, ec.threshold_value,
  CASE
    WHEN s.slice_thickness <= ec.slice_category_thin THEN 'thin'
    WHEN s.slice_thickness <= ec.slice_category_std THEN 'standard'
    ELSE 'thick'
  END AS slice_category
FROM <curated_surface> s
JOIN <catalog>.dicom_silver.manufacturer_encoding_config ec
  ON UPPER(s.manufacturer) LIKE UPPER(ec.manufacturer_pattern)
  AND ec.modality = s.modality AND ec.parameter = 'slice_thickness'
WHERE s.series_type = 'volumetric'
```

**Fallback (inline CASE):** When no config table is available:

```sql
CASE
  WHEN UPPER(<manufacturer_column>) LIKE '%GE%' THEN 'GE'
  WHEN UPPER(<manufacturer_column>) LIKE '%SIEMENS%' THEN 'SIEMENS'
  WHEN UPPER(<manufacturer_column>) LIKE '%PHILIPS%' THEN 'PHILIPS'
  WHEN UPPER(<manufacturer_column>) LIKE '%CANON%' OR UPPER(<manufacturer_column>) LIKE '%TOSHIBA%' THEN 'CANON'
  WHEN UPPER(<manufacturer_column>) LIKE '%HITACHI%' THEN 'HITACHI'
  WHEN UPPER(<manufacturer_column>) LIKE '%FUJI%' THEN 'FUJIFILM'
  ELSE <manufacturer_column>
END AS manufacturer_normalized
```

If the curated surface already has a `manufacturer_normalized` column, use that
directly.

## Body part normalization

`BodyPartExamined` (0018,0015) is technologist-entered free-ish text. Real data
has inconsistent values: `CHEST`, `Chest`, `THORAX`, `"Chest w Contrast"`,
`ABDOMEN PELVIS`, `Abd/Pelvis`, `AbdPel`. Without normalization, equality filters
miss 30–50% of relevant studies in real fleets.

Apply with CASE. **Order matters** — combined-region patterns must be evaluated
before their component patterns:

```sql
CASE
  WHEN (UPPER(<body_part_column>) LIKE '%CHEST%' AND UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%')
    OR UPPER(<body_part_column>) LIKE '%CAP%' THEN 'CHEST_ABDOMEN_PELVIS'
  WHEN (UPPER(<body_part_column>) LIKE '%ABDOMEN%' AND UPPER(<body_part_column>) LIKE '%PELVIS%')
    OR UPPER(<body_part_column>) LIKE 'ABD%PEL%' THEN 'ABDOMEN_PELVIS'
  WHEN UPPER(<body_part_column>) LIKE '%CHEST%' OR UPPER(<body_part_column>) LIKE '%THORAX%' THEN 'CHEST'
  WHEN UPPER(<body_part_column>) LIKE '%ABDOMEN%' OR UPPER(<body_part_column>) LIKE 'ABD%' THEN 'ABDOMEN'
  WHEN UPPER(<body_part_column>) LIKE '%PELVIS%' THEN 'PELVIS'
  WHEN UPPER(<body_part_column>) IN ('HEAD', 'BRAIN', 'CRANIUM') OR UPPER(<body_part_column>) LIKE '%HEAD%' OR UPPER(<body_part_column>) LIKE '%BRAIN%' THEN 'HEAD'
  WHEN UPPER(<body_part_column>) LIKE '%NECK%' OR UPPER(<body_part_column>) LIKE '%CERVICAL%' THEN 'NECK'
  WHEN UPPER(<body_part_column>) LIKE '%SPINE%' OR UPPER(<body_part_column>) LIKE '%LUMBAR%' OR UPPER(<body_part_column>) LIKE '%THORACIC%' THEN 'SPINE'
  WHEN UPPER(<body_part_column>) LIKE '%KNEE%' THEN 'KNEE'
  WHEN UPPER(<body_part_column>) LIKE '%SHOULDER%' THEN 'SHOULDER'
  WHEN UPPER(<body_part_column>) LIKE '%LIVER%' THEN 'LIVER'
  WHEN UPPER(<body_part_column>) LIKE '%HEART%' OR UPPER(<body_part_column>) LIKE '%CARDIAC%' THEN 'HEART'
  ELSE UPPER(<body_part_column>)
END AS body_part_normalized
```

### Caveats — body part is NOT a clean parallel of manufacturer

1. **Spine is genuinely multi-anatomy.** Cervical, thoracic, and lumbar spine are
   clinically different. The default CASE collapses them into `SPINE`. For
   cervical-vs-lumbar comparisons, fracture cohort identification, or surgical
   planning queries, use the raw column instead, or extend the CASE to preserve
   the distinction (`CERVICAL_SPINE`, `THORACIC_SPINE`, `LUMBAR_SPINE`).

2. **Combined regions are clinically real.** `CHEST_ABDOMEN_PELVIS` (often
   abbreviated `CAP`) and `ABDOMEN_PELVIS` are common in CT trauma, oncology
   staging, and surveillance protocols. Do NOT collapse these into their
   component regions — they're separate exam types with different dose profiles
   and indications.

3. **Order matters in the CASE.** The combined-region patterns
   (CHEST_ABDOMEN_PELVIS, ABDOMEN_PELVIS) MUST be evaluated *before* their
   component patterns (CHEST, ABDOMEN, PELVIS) — otherwise a
   `CHEST_ABDOMEN_PELVIS` entry hits the `%CHEST%` pattern first and gets
   miscategorized as plain CHEST.

If the curated surface already has a `body_part_normalized` column, use that
directly.

## When the user needs raw values

For anatomic specificity beyond the normalization (e.g., "cervical spine
fractures" not "spine fractures"), use the raw `body_part_examined` column with
appropriate `LIKE` patterns. Mention this in the response so the user knows the
result reflects raw values, not the canonical normalization.

## Use in WHERE vs SELECT

**In WHERE clauses** — apply the normalization in a CTE or subquery, then filter:

```sql
WITH normalized AS (
  SELECT *,
    CASE ... END AS body_part_normalized
  FROM <curated_surface>
)
SELECT ... FROM normalized WHERE body_part_normalized = 'CHEST'
```

This is required when filtering on the normalized value. Direct application in
WHERE works but obscures the result.

**In SELECT for grouping** — apply directly:

```sql
SELECT
  CASE ... END AS body_part_normalized,
  COUNT(*)
FROM <curated_surface>
GROUP BY 1
```

## Private / vendor tag queries

Tags with odd-numbered group IDs (0009, 0019, 0029, etc.) are vendor-specific.
Always prefix queries with a manufacturer filter (using normalization where
possible). For full access patterns and vendor group conventions, see
`templates/bronze-patterns.md`.
