# Template 7: Scanner utilization metrics

Load when the user's question maps to "Operational / scanner utilization" class.

## Use case

Operational analytics — study duration, interpatient time, scanner throughput.
Standard for capacity planning, scheduling optimization, fleet operational
review.

## Critical caveat

**DICOM-derived utilization is an estimate.** Definitive operational analytics
need RIS appointment data joined in. State this caveat once when generating
utilization queries:

> "Note: scanner utilization computed from DICOM acquisition timestamps is an
> estimate. Definitive operational metrics need RIS appointment data joined in
> (no-shows, cancellations, time spent on patient prep aren't captured here)."

## Pattern — study duration distribution by station

Requires `study_time` / `series_time` / `acquisition_time` in the curated surface
(curated as STRING in DICOMweb format `HHMMSS.FFFFFF`; cast to TIMESTAMP for
arithmetic). See `domain-rules/parsing.md` for time parsing details.

```sql
WITH study_bounds AS (
  SELECT
    <study_uid_column>,
    <station_name_column>,
    MIN(to_timestamp(concat(<study_date_column>, ' ',
        regexp_replace(<acquisition_time_column>, '[:.\\s]', '')), 'yyyy-MM-dd HHmmss')) AS first_acq,
    MAX(to_timestamp(concat(<study_date_column>, ' ',
        regexp_replace(<acquisition_time_column>, '[:.\\s]', '')), 'yyyy-MM-dd HHmmss')) AS last_acq
  FROM <curated_surface>
  WHERE <modality_column> = '{modality}'
    AND <study_date_column> >= current_date() - INTERVAL '{time_window}'
    AND <acquisition_time_column> IS NOT NULL
  GROUP BY 1, 2
)
SELECT
  <station_name_column>,
  COUNT(*) AS studies,
  PERCENTILE_CONT(0.5) WITHIN GROUP (
    ORDER BY (unix_timestamp(last_acq) - unix_timestamp(first_acq)) / 60.0
  ) AS median_duration_min,
  PERCENTILE_CONT(0.9) WITHIN GROUP (
    ORDER BY (unix_timestamp(last_acq) - unix_timestamp(first_acq)) / 60.0
  ) AS p90_duration_min
FROM study_bounds
GROUP BY 1
ORDER BY studies DESC
```

## Pattern — interpatient time (gap between consecutive studies on same scanner)

```sql
WITH study_starts AS (
  SELECT
    <station_name_column>,
    <study_uid_column>,
    MIN(to_timestamp(concat(<study_date_column>, ' ',
        regexp_replace(<acquisition_time_column>, '[:.\\s]', '')), 'yyyy-MM-dd HHmmss')) AS study_start,
    MAX(to_timestamp(concat(<study_date_column>, ' ',
        regexp_replace(<acquisition_time_column>, '[:.\\s]', '')), 'yyyy-MM-dd HHmmss')) AS study_end
  FROM <curated_surface>
  WHERE <modality_column> = '{modality}'
    AND <acquisition_time_column> IS NOT NULL
  GROUP BY 1, 2
),
gaps AS (
  SELECT
    <station_name_column>,
    study_start,
    study_end,
    LAG(study_end) OVER (PARTITION BY <station_name_column> ORDER BY study_start) AS prev_end
  FROM study_starts
)
SELECT
  <station_name_column>,
  PERCENTILE_CONT(0.5) WITHIN GROUP (
    ORDER BY (unix_timestamp(study_start) - unix_timestamp(prev_end)) / 60.0
  ) AS median_interpatient_min
FROM gaps
WHERE prev_end IS NOT NULL
  AND DATE(study_start) = DATE(prev_end)  -- same-day pairs only
GROUP BY 1
```

The `DATE(study_start) = DATE(prev_end)` filter excludes overnight gaps. Adjust
or remove if the user's facility runs overnight scanning and that's part of the
scope.

## Caveats specific to DICOM-derived utilization

1. **Series-level vs study-level granularity.** A study may contain multiple
   series; "study duration" here is the time span across all instances. For a
   strict definition, use first-instance to last-instance of the lowest-numbered
   series.
2. **NULL acquisition_time.** Derived series, secondary capture, and reformatted
   reconstructions often have NULL `acquisition_time`. The pattern filters these
   out via `IS NOT NULL` — but the filter affects which series contribute to the
   timestamp range. Surface this if the user asks about specific protocols.
3. **Same-day filter.** The interpatient pattern uses same-day filtering. If
   facilities run 24-hour or overnight scanning, this is wrong. Surface the
   choice if scanner ID suggests an emergency or 24-hour facility.
4. **Timezone assumption.** The timestamps constructed by these patterns are
   timezone-naive — `to_timestamp` produces values in the session's local
   timezone. This is correct when all stations are in one timezone. Two failure
   modes when they're not:

   **Cross-timezone stations:** if `station_name` values include scanners in
   different timezones, duration comparisons across stations are off by the
   timezone delta. The patterns partition by `station_name`, so within-station
   arithmetic is safe — but any cross-station aggregation (e.g., fleet-wide
   P50 duration) is wrong.

   **DST transitions:** within a single station, a study spanning a DST
   boundary (e.g., 01:30 → 03:30 spring-forward) produces a duration inflated
   or deflated by one hour. This is rare (most studies are short) but real for
   long MR or interventional studies.

   **Detection (generation-time):** before emitting utilization SQL, probe for
   multi-timezone risk:

   ```sql
   SELECT DISTINCT <station_name_column>,
     COALESCE(<institution_name_column>, 'unknown') AS institution
   FROM <curated_surface>
   WHERE <modality_column> = '{modality}'
   ```

   If distinct institutions or station-name prefixes suggest multiple
   geographic sites, surface:

   > "Station names suggest scanners in multiple sites. Utilization timestamps
   > are timezone-naive — within-station duration is correct, but cross-station
   > comparisons may be off. Filter to a single site, or confirm all sites are
   > in the same timezone."

   If the curated surface has a `timezone` or `utc_offset` column, use it to
   normalize. Otherwise, accept the limitation and document it inline.

## Domain rules to apply

- `domain-rules/parsing.md` — time format and TIMESTAMP construction
- `domain-rules/phi.md` — Case 1 applies (no patient identifiers in output, full precision OK)
- `domain-rules/exclusions.md` — exclusion does NOT apply (utilization is a volume/timing question, not parameter analytics)
