# Domain rules — parsing

Load when generating queries that parse `patient_age`, time fields, multi-value
DS values, or DICOMweb-format JSON structures.

## Patient age

Format: `nnnY` (years) in 99% of cases. Variants: `nnnM` (months), `nnnW` (weeks),
`nnnD` (days). Convert to integer years for analytics:

```sql
CAST(REGEXP_EXTRACT(<age_column>, '^\\s*(\\d+)\\s*Y?\\s*$', 1) AS INT) AS age_years
```

The `Y?` makes the unit suffix optional (covers exporters that strip it).
`\\s*` handles leading/trailing whitespace. Leading zeros are handled by CAST:
`045Y` → `045` → CAST to INT → `45`. Works on `'45Y'`, `'045'`, `'045Y '`.

Reject non-Y units in analytics queries unless the user explicitly asks for
pediatric (months/days) data. If the query needs pediatric ages:

```sql
CASE
  WHEN <age_column> LIKE '%Y%' THEN CAST(REGEXP_EXTRACT(<age_column>, '^\\s*(\\d+)\\s*Y?\\s*$', 1) AS INT) * 365
  WHEN <age_column> LIKE '%M%' THEN CAST(REGEXP_EXTRACT(<age_column>, '^\\s*(\\d+)\\s*M?\\s*$', 1) AS INT) * 30
  WHEN <age_column> LIKE '%W%' THEN CAST(REGEXP_EXTRACT(<age_column>, '^\\s*(\\d+)\\s*W?\\s*$', 1) AS INT) * 7
  WHEN <age_column> LIKE '%D%' THEN CAST(REGEXP_EXTRACT(<age_column>, '^\\s*(\\d+)\\s*D?\\s*$', 1) AS INT)
  ELSE NULL
END AS age_days
```

## DICOMweb multi-value conventions

DICOMweb encodes multi-value tags as JSON arrays in the `Value` field — NOT as
backslash-separated strings (which is the traditional DICOM binary encoding).
Index by position:

For curated columns (component splits already in silver):
- `pixel_spacing_row` (Value[0]), `pixel_spacing_col` (Value[1])
- `image_position_x` (Value[0]), `image_position_y` (Value[1]), `image_position_z` (Value[2])

For raw bronze access — see `sql-patterns/variant.md` and `string.md` for the
syntax. Multi-value pattern in both:

| Multiplicity | What's in Value | Access |
|--------------|-----------------|--------|
| Single value (VM=1) | `Value: ["x"]` | Index `[0]` always |
| Fixed multi-value (VM=2, VM=3) | `Value: ["x", "y"]` or `["x", "y", "z"]` | Index by position |
| Variable multi-value (VM=1-n) | `Value: [...]` (length varies) | Use `from_json(...,'array<string>')` for ARRAY semantics |
| No value (empty tag) | Tag may have only `vr`, no `Value` field | Returns NULL — handle with COALESCE or filter |

## Time format (TM)

Format: `HHMMSS.FFFFFF` (with optional fractional seconds) or `HHMMSS` (without).
Stored as STRING in silver — cast to TIMESTAMP at query time when needed for
arithmetic.

To normalize time to `HHMMSS` (strips colons, dots, fractional seconds, and
whitespace — real-world DICOM exports sometimes include colons like `14:30:00`):

```sql
regexp_replace(<time_column>, '[:.\\s]', '')  -- normalizes to HHMMSS
```

To construct a TIMESTAMP from date + time columns:

```sql
to_timestamp(
  concat(<date_column>, ' ', regexp_replace(<time_column>, '[:.\\s]', '')),
  'yyyy-MM-dd HHmmss'
)
```

To preserve fractional seconds (rarely needed, but possible):

```sql
to_timestamp(
  concat(CAST(<date_column> AS STRING), ' ', <time_column>),
  'yyyy-MM-dd HHmmss.SSSSSS'
)
```

If the time column may be NULL (some series don't have AcquisitionTime
populated, especially derived series), wrap with COALESCE or filter
`WHERE <time_column> IS NOT NULL` before the timestamp construction.

## Date format (DA)

Format: `YYYYMMDD` (no separators) in DICOMweb. Already parsed to DATE in silver
(see pipeline `da_first` sanitizer). For raw bronze access:

```sql
to_date(<extracted_date_string>, 'yyyyMMdd')
```

Tolerate legacy format variants (with separators) by stripping non-digits first:

```sql
to_date(regexp_replace(<extracted_date_string>, '[\\.\\-/]', ''), 'yyyyMMdd')
```

## VR-specific cast targets

| VR | Type semantics | Cast target | Notes |
|----|---------------|-------------|-------|
| CS | Code String (controlled) | STRING | Trim whitespace |
| LO | Long String (free text up to 64 chars) | STRING | Trim whitespace |
| SH | Short String | STRING | Trim |
| UI | Unique Identifier (dot-delimited OID) | STRING | Always STRING |
| AE | Application Entity | STRING | Trim |
| AS | Age String | STRING | Format `nnnY` |
| DS | Decimal String | DOUBLE | `try_cast` for safety |
| IS | Integer String | INT | `try_cast` for safety |
| US | Unsigned Short | INT | JSON number; `try_cast` to INT |
| FD | Floating Double | DOUBLE | JSON number; `try_cast` to DOUBLE |
| FL | Floating Single | DOUBLE | JSON number; cast to DOUBLE for SQL convenience |
| DA | Date | DATE | `to_date(..., 'yyyyMMdd')` |
| TM | Time | STRING | Cast to TIMESTAMP at query time |
| DT | DateTime | TIMESTAMP | Format: `YYYYMMDDHHMMSS.FFFFFF` |
| PN | Person Name | nested object | Access `.Alphabetic` sub-field; PHI |
| SQ | Sequence | nested array of objects | Don't flatten; nested access |
