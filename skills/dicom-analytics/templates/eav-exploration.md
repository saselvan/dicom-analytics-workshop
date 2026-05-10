# Template 9: EAV exploration — what tags exist

Load when the user's question is about tag inventory, coverage discovery, or
cross-modality tag comparison. Routes to the EAV exploration view from
Discovery Step 4.

## Use case

Tag-shape questions that don't fit columnar analytics:
- "What DICOM tags do we have data for?"
- "What's the value distribution for SliceThickness across modalities?"
- "Which tags are populated for CT but not for MR?"
- "How many distinct values does ProtocolName take?"

## Pattern — tag inventory with coverage

The denominator assumes `<curated_surface>` is **series-grain** (one row per
study × series). If the curated surface is study-grain or instance-grain,
adjust the denominator accordingly.

```sql
SELECT
  <tag_keyword_column>,
  <tag_id_column>,
  COUNT(DISTINCT (<study_uid_column>, <series_uid_column>)) AS series_with_value,
  COUNT(DISTINCT (<study_uid_column>, <series_uid_column>)) * 100.0 /
    (SELECT COUNT(*) FROM <curated_surface>) AS coverage_pct
    -- ^ denominator assumes curated_surface is series-grain
FROM <eav_view>
GROUP BY 1, 2
ORDER BY series_with_value DESC
```

## Pattern — value distribution for a specific tag across modalities

```sql
SELECT
  s.<modality_column>,
  t.<value_column> AS raw_value,
  COUNT(*) AS occurrences
FROM <eav_view> t
JOIN <curated_surface> s
  ON t.<study_uid_column> = s.<study_uid_column>
 AND t.<series_uid_column> = s.<series_uid_column>
WHERE t.<tag_keyword_column> = '{keyword}'
GROUP BY 1, 2
ORDER BY 1, occurrences DESC
```

## Pattern — tags present on one modality but not another

**Preferred: set-difference approach.** Aggregates each modality's tag set
independently, then subtracts. Avoids a correlated subquery against what can
be a billion-row EAV view:

```sql
WITH tags_a AS (
  SELECT DISTINCT t.<tag_keyword_column>
  FROM <eav_view> t
  JOIN <curated_surface> s
    ON t.<study_uid_column> = s.<study_uid_column>
   AND t.<series_uid_column> = s.<series_uid_column>
  WHERE s.<modality_column> = '{modality_a}'
),
tags_b AS (
  SELECT DISTINCT t.<tag_keyword_column>
  FROM <eav_view> t
  JOIN <curated_surface> s
    ON t.<study_uid_column> = s.<study_uid_column>
   AND t.<series_uid_column> = s.<series_uid_column>
  WHERE s.<modality_column> = '{modality_b}'
)
SELECT a.<tag_keyword_column>
FROM tags_a a
LEFT JOIN tags_b b ON a.<tag_keyword_column> = b.<tag_keyword_column>
WHERE b.<tag_keyword_column> IS NULL
```

This runs two independent scans (each filtered early on modality) and joins
the small result sets (~hundreds of distinct tag keywords). On a large EAV
view, this is orders of magnitude faster than a correlated `NOT EXISTS` that
probes the full view per outer row.

## Worked examples

```sql
-- Q: What DICOM tags do we have data for, with coverage?
SELECT
  tag_keyword,
  tag_id,
  COUNT(DISTINCT (study_uid, series_uid)) AS series_with_value,
  COUNT(DISTINCT (study_uid, series_uid)) * 100.0 /
    (SELECT COUNT(*) FROM silver.dicom_series) AS coverage_pct
FROM bronze.dicom_tags_long
GROUP BY 1, 2
ORDER BY series_with_value DESC
```

```sql
-- Q: SliceThickness distribution across modalities
SELECT
  s.modality,
  t.value AS slice_thickness_raw,
  COUNT(*) AS occurrences
FROM bronze.dicom_tags_long t
JOIN silver.dicom_series s
  ON t.study_uid = s.study_instance_uid AND t.series_uid = s.series_instance_uid
WHERE t.tag_keyword = 'SliceThickness'
GROUP BY 1, 2
ORDER BY 1, occurrences DESC
```

```sql
-- Q: Tags present on CT but not on MR
SELECT DISTINCT t1.tag_keyword
FROM bronze.dicom_tags_long t1
JOIN silver.dicom_series s1
  ON t1.study_uid = s1.study_instance_uid AND t1.series_uid = s1.series_instance_uid
WHERE s1.modality = 'CT'
  AND NOT EXISTS (
    SELECT 1 FROM bronze.dicom_tags_long t2
    JOIN silver.dicom_series s2
      ON t2.study_uid = s2.study_instance_uid AND t2.series_uid = s2.series_instance_uid
    WHERE s2.modality = 'MR'
      AND t2.tag_keyword = t1.tag_keyword
  )
```

## When EAV view doesn't exist

If Discovery Step 4 didn't find an EAV view, fall back to bronze with explicit
JSON path enumeration. This is slower and requires the user to specify which
tags to inspect:

```sql
-- VARIANT bronze
SELECT
  payload:`00080060`.Value[0]::string AS modality,
  COUNT(*) AS series_count,
  COUNT(payload:`<tag_id>`) AS series_with_tag,
  ROUND(100.0 * COUNT(payload:`<tag_id>`) / COUNT(*), 2) AS coverage_pct
FROM <bronze_table>
GROUP BY 1
```

This works for one tag at a time. For wide-coverage discovery questions, the
EAV view is materially better.

## Performance considerations

EAV views can be large (one row per study × series × tag = potentially billions
of rows for a multi-million series silver). Most operations should filter early
on tag_keyword or modality. Avoid `SELECT * FROM <eav_view>` without filters.

## Domain rules to apply

- `domain-rules/phi.md` — Case 1 if no patient identifiers; Case 2 if surfacing UIDs
- `domain-rules/exclusions.md` — exclusion does NOT apply (tag-discovery is a volume question)
