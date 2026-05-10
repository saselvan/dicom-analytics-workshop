# Domain rules — PHI handling

Load when output includes patient identifiers, when query touches PHI fields, or
when generating cohort queries.

## What's PHI in DICOM

Direct identifiers — never extract or surface in result sets:
- Patient name (PN, tag 0010,0010)
- Referring physician name (PN, tag 0008,0090)
- Operator name (PN, tag 0008,1070)
- Accession number (SH, tag 0008,0050)
- Medical record number (variable; institutional, often in 0010,0020 PatientID)
- Other direct identifiers per HIPAA Safe Harbor (45 CFR 164.514)

These tags exist in bronze. Do not extract them into output. Skill access patterns
for PN are documented in `sql-patterns/variant.md` and `string.md` — they exist
for narrow technical uses (e.g., debugging an extraction bug), not for analytics.

## Quasi-identifiers and k-anonymity

HIPAA Safe Harbor (45 CFR 164.514) names 18 direct identifiers. Removing those
is necessary but not sufficient. *Combinations* of quasi-identifying fields can
re-identify a patient even when each field alone is non-identifying. The
relevant standard is k-anonymity: every combination of quasi-identifiers in
the result should appear in at least k records.

Common DICOM quasi-identifiers:

| Field | Risk |
|---|---|
| `study_date` (full precision) | Elevated in low-volume settings |
| `station_name` + `study_date` | High at single-station sites |
| `station_name` + `body_part_examined` + day | Low-volume body part at low-volume station |
| `patient_age` (year) + `patient_sex` + `study_date` + `body_part_examined` | High for unusual age + procedure combinations |
| `protocol_name`, `study_description` (free text) | Often contain identifying info directly |
| `institution_name` + small geographic area | Direct geographic identifier |

For multi-station urban hospitals with high daily volume, quasi-id risk on
`station_name × date × body_part` is low. For single-station rural sites,
specialty centers, and pediatric subgroups, the risk is meaningful.

### Detection

For result sets that include any combination of quasi-identifiers, probe for
small-cell counts before releasing:

```sql
-- Probe for k-anonymity violations on (station, date, body_part)
SELECT
  station_name,
  study_date,
  body_part_examined,
  COUNT(*) AS cell_size
FROM <result_set>
GROUP BY 1, 2, 3
HAVING COUNT(*) < 5  -- threshold; common values are k=5 or k=11
```

If any cells fall below `k`, the result set is at risk. Mitigations:

1. **Coarsen the date.** Day → week, week → month, month → quarter. Each
   coarsening typically increases cell counts substantially.
2. **Aggregate the station.** Group by site or region instead of station;
   suppress single-station rows.
3. **Suppress small cells.** Replace counts in cells below `k` with `<k` or
   NULL. Note the suppression in the result.
4. **Drop the offending field.** If `body_part_examined` is causing small
   cells and isn't load-bearing for the question, drop it.

### When this applies

Run the k-anonymity probe before releasing result sets that:

- Group by `station_name` or `institution_name` AND any temporal field
- Include `patient_age` at year precision, especially with `patient_sex` and
  any procedure or anatomy field
- Surface `protocol_name` or `study_description` in the output

For pure aggregate counts at high cardinality (modality × manufacturer with
fleet-scale denominators), k-anonymity risk is typically negligible — the
probe is for cohort-style outputs and operational reports that segment finely.

### Threshold guidance

`k` thresholds vary by jurisdiction and use case:

| Context | Common `k` threshold |
|---|---|
| Internal research / IRB-supervised | k ≥ 5 |
| HHS de-identification expert determination (Statistical Standard) | k ≥ 5 |
| External release / public data | k ≥ 11 |
| Data sharing agreements | per the agreement; sometimes k ≥ 20 |

The compliance officer at each customer site should set the threshold for
their actual scope. The skill applies whatever value the user (or their
documented preference) provides.

## Pseudonymous identifiers

`study_instance_uid`, `series_instance_uid`, `sop_instance_uid` are pseudonymous —
usable for joins, cohort assembly, and handoff to research workflows. Not typically
surfaced as final results in operational reporting, but appropriate as outputs of
cohort identification queries.

## Free-text fields

`protocol_name`, `study_description`, `series_description` are free text and
frequently contain PHI in practice (technologist notes, patient names, etc.).
Treat with care:
- Do NOT include in broad `SELECT *`
- Surface only when the user's query specifically requires them
- Filter with `LIKE` patterns rather than equality where possible

## Date precision

DICOMweb dates come as `YYYYMMDD` strings. Date precision in output is governed
by what else is in the output, not by a blanket rule. Apply this precedence,
in order:

### Case 1 — Operational / aggregate queries with no patient-level identifiers

Scanner counts, station throughput, fleet-level distributions, utilization
metrics. Full date precision OK. Time precision OK if needed for arithmetic.
HIPAA Safe Harbor doesn't apply because no patient identifiers are in the result.

Examples: scanner utilization (Template 7), aggregate counts grouped by
station/manufacturer/body region with no UIDs in the result.

### Case 2 — Patient-cohort queries

Output includes `study_instance_uid`, `series_instance_uid`, `sop_instance_uid`,
or `patient_age`:

- **If `patient_age` is in output AND any age value ≥ 89:** year-truncate all
  dates in the result. This is the HIPAA Safe Harbor 90+ rule (45 CFR 164.514).

  **Detection (generation-time):** `patient_age` is a STRING in `nnnY` format.
  Lexicographic comparison does NOT work reliably (e.g., `"9Y"` > `"45Y"` is
  true lexicographically but wrong numerically). Always integer-cast before
  checking:
  ```sql
  -- Run at generation time to determine date truncation grain
  SELECT MAX(CAST(REGEXP_EXTRACT(<patient_age_column>, '^\\s*(\\d+)\\s*[YMWD]?\\s*$', 1) AS INT)) AS max_age
  FROM <data_source>
  WHERE <same_filters_as_cohort>
  ```
  If `max_age >= 89` → use `DATE_TRUNC('year', ...)` on all dates in the output.

  **Application:**
  ```sql
  SELECT DATE_TRUNC('year', study_date) AS study_year, ...
  ```

- **Otherwise** (patient identifiers but no 90+ ages): default to month-grain
  for analytics (`DATE_TRUNC('month', ...)`). Ask the user if year-grain is
  required by their IRB or compliance scope before going finer than month.
- **For ambiguous patient-cohort queries:** ask before applying full precision.

### Case 3 — Time-series and trend queries (Template 4 pattern)

The user-supplied `{grain}` placeholder controls precision. If `{grain}` is
`day` or `week` AND output includes patient identifiers, surface the precision
question to the user rather than silently produce finer-than-month patient-level
dates:

> "You requested daily granularity for a query that includes patient study UIDs.
> That output exposes per-patient dates at day precision. Confirm: proceed with
> day-grain (acceptable for your compliance scope), or coarsen to month-grain?"

### Case 4 — Internal filters, joins, and intermediate CTEs

Full precision is always OK in computation. Date precision rules apply only to
fields surfaced in the final result set, not to intermediate columns or filter
predicates.

```sql
-- OK: full-precision date in WHERE clause, year-truncated in output
SELECT DATE_TRUNC('year', study_date) AS study_year, COUNT(*) AS series_count
FROM <curated_surface>
WHERE study_date >= DATE '2018-01-01' AND study_date < DATE '2024-01-01'
GROUP BY 1
```

### Quick reference

| Query shape | Date precision in output |
|------------|--------------------------|
| Aggregate counts/distributions, no UIDs | Full precision OK |
| Operational/utilization, no patient identifiers | Full precision OK (date+time) |
| Patient cohort, no patient_age 90+ | Default month; ask if finer |
| Patient cohort, patient_age 90+ in result | Year (Safe Harbor) |
| Time-series with `{grain}` placeholder, no UIDs | Use `{grain}` as given |
| Time-series with `{grain}` placeholder, UIDs in result | Confirm grain ≥ month with user |
| Internal joins / filters / WHERE clauses | Full precision always |

## UC permissions are the boundary

Bronze is identified data, gated by Unity Catalog permissions. Queries inherit
the user's UC access — never bypass. If a user's query would expose data they
don't have UC access to, the query fails at the UC layer, not at the skill
layer. Don't try to enforce access rules in SQL.

## Workspace-level note

Healthcare customers typically have UC permissions configured such that:
- Bronze tables are restricted to a small set of data engineers
- Silver tables are open to a broader analytics audience (UIDs but not direct
  identifiers)
- Reference tables (PS3.6 lookup, etc.) are open to all

This is the deployment-time policy, not a skill-time concern. Skill behavior is
identical regardless of permission scope.
