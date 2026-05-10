# SQL access patterns — top-level identifier columns

Load when Discovery Step 1 finds identifier columns at the top level of bronze
(not embedded only in the JSON payload).

## Pattern

Reference identifier columns directly. Do NOT extract from the payload when a
top-level column already exists.

```sql
SELECT
  study_instance_uid,
  series_instance_uid,
  sop_instance_uid,
  ...
FROM <bronze_table>
```

## Mixed access

If only some identifiers are at top level, mix patterns — direct reference for
those extracted, payload extraction for the rest. Example: bronze has
`study_instance_uid` and `series_instance_uid` at top level, but `sop_instance_uid`
only in the payload:

```sql
-- VARIANT bronze
SELECT
  study_instance_uid,
  series_instance_uid,
  payload:`00080018`.Value[0]::string AS sop_instance_uid
FROM <bronze_table>

-- STRING bronze
SELECT
  study_instance_uid,
  series_instance_uid,
  get_json_object(payload, '$.00080018.Value[0]') AS sop_instance_uid
FROM <bronze_table>
```

## Common identifier column variants

Discovery Step 1 may classify columns by name. Watch for these naming variants
when matching:

| Canonical | Common variants |
|-----------|-----------------|
| `study_instance_uid` | `study_uid`, `studyinstanceuid`, `studyuid`, `StudyInstanceUID` |
| `series_instance_uid` | `series_uid`, `seriesinstanceuid`, `seriesuid` |
| `sop_instance_uid` | `sop_uid`, `instance_uid`, `sopinstanceuid` |

Discovery resolves the actual column name; templates use the discovered name.

## When identifiers are NOT at top level

Discovery Step 1 reports "identifier columns: extracted from payload." In that
case, do NOT load this sub-skill — load `sql-patterns/variant.md` or `string.md`
instead, and extract identifiers from the payload using the standard patterns.

## Performance

Direct column reference is always faster than payload extraction. Prefer top-level
columns when both exist.

### Caveat: top-level vs payload UID divergence

When both top-level identifier columns AND the same identifiers in the
payload exist, they should match. They usually do, but pipeline bugs,
late-arriving updates, and dedup mismatches can cause divergence. For
data-quality work the divergence is itself the question; for routine
analytics it's a non-event. If a customer reports unexpected results,
reconcile with:

```sql
SELECT COUNT(*) AS total,
       SUM(CASE WHEN <study_uid_column> != payload:`0020000D`.Value[0]::string
                THEN 1 ELSE 0 END) AS divergent
FROM <bronze_table>
```

A non-zero `divergent` count is a flag for the data engineering team, not a
reason to switch the analytics to use the payload value.
