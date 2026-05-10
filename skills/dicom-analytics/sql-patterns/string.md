# SQL access patterns — STRING bronze (containing JSON)

Load when Discovery Step 1 determines the bronze payload column is type `STRING`
with stringified JSON content.

## Single-value extraction

Use `get_json_object` with `$.` JSONPath. Hex keys work cleanly without quoting:

```sql
SELECT get_json_object(payload, '$.00080060.Value[0]') AS modality
FROM <bronze_table>
```

`get_json_object` always returns STRING. Cast to other types with `try_cast`
(returns NULL on cast failure rather than throwing).

## Multi-value array indexing

Index by position in the JSONPath:

```sql
SELECT
  try_cast(get_json_object(payload, '$.00280030.Value[0]') AS DOUBLE) AS pixel_spacing_row,
  try_cast(get_json_object(payload, '$.00280030.Value[1]') AS DOUBLE) AS pixel_spacing_col
FROM <bronze_table>
```

ImagePositionPatient (3-component):

```sql
SELECT
  try_cast(get_json_object(payload, '$.00200032.Value[0]') AS DOUBLE) AS image_position_x,
  try_cast(get_json_object(payload, '$.00200032.Value[1]') AS DOUBLE) AS image_position_y,
  try_cast(get_json_object(payload, '$.00200032.Value[2]') AS DOUBLE) AS image_position_z
FROM <bronze_table>
```

## Nested sequence access (VR=SQ tags)

Dot-chain through nested objects in the JSONPath:

```sql
SELECT
  get_json_object(payload, '$.00120064.Value[0].00080100.Value[0]') AS first_seq_value
FROM <bronze_table>
```

ReferencedStudySequence pattern:

```sql
SELECT
  get_json_object(payload, '$.00081110.Value[0].00081150.Value[0]') AS referenced_sop_class_uid,
  get_json_object(payload, '$.00081110.Value[0].00081155.Value[0]') AS referenced_sop_instance_uid
FROM <bronze_table>
WHERE get_json_object(payload, '$.00081110') IS NOT NULL
```

## Multi-value CS arrays (e.g., ImageType)

`get_json_object` returns the whole array as a JSON string; parse with `from_json`:

```sql
SELECT
  from_json(get_json_object(payload, '$.00080008.Value'), 'array<string>') AS image_type
FROM <bronze_table>
WHERE array_contains(
  from_json(get_json_object(payload, '$.00080008.Value'), 'array<string>'),
  'LOCALIZER'
)
```

## Type casting after extraction

`get_json_object` returns STRING. Always cast with `try_cast` for numeric types:

| Source type | Cast target | Pattern |
|-------------|-------------|---------|
| DS (decimal string) | DOUBLE | `try_cast(get_json_object(...) AS DOUBLE)` |
| IS (integer string) | INT | `try_cast(get_json_object(...) AS INT)` |
| US (unsigned short) | INT | `try_cast(get_json_object(...) AS INT)` |
| FD (floating double) | DOUBLE | `try_cast(get_json_object(...) AS DOUBLE)` |
| DA (date) | DATE | `to_date(get_json_object(...), 'yyyyMMdd')` |
| TM (time) | STRING | leave as STRING; cast to TIMESTAMP at query time per Template 7 |
| CS / LO / SH / UI / AE | STRING | use directly |

## PN (Person Name) — structured object access

```sql
SELECT
  get_json_object(payload, '$.00100010.Value[0].Alphabetic') AS patient_name_alphabetic
FROM <bronze_table>
```

Patient names are PHI. Do not extract into result sets except for narrow,
documented technical uses. See `domain-rules/phi.md`.

## Performance considerations

`get_json_object` parses JSON at query time, per row. For frequent analytics on
the same bronze, consider materialization to VARIANT — pre-parsed binary format
with columnar sub-field pruning, materially faster for repeated analytical
queries.

Non-blocking caveat: queries work correctly against STRING bronze. The
performance note is informational.
