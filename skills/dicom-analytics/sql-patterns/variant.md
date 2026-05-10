# SQL access patterns — VARIANT bronze

Load when Discovery Step 1 determines the bronze payload column is type `VARIANT`.

## Single-value extraction

Use backtick colon syntax for hex tag keys (numeric identifiers must be quoted):

```sql
SELECT payload:`00080060`.Value[0]::string AS modality
FROM <bronze_table>
```

## Multi-value array indexing

For multi-value DS tags (e.g., PixelSpacing — 2-component array):

```sql
SELECT
  payload:`00280030`.Value[0]::double AS pixel_spacing_row,
  payload:`00280030`.Value[1]::double AS pixel_spacing_col
FROM <bronze_table>
```

ImagePositionPatient (3-component DS array):

```sql
SELECT
  payload:`00200032`.Value[0]::double AS image_position_x,
  payload:`00200032`.Value[1]::double AS image_position_y,
  payload:`00200032`.Value[2]::double AS image_position_z
FROM <bronze_table>
```

## Nested sequence access (VR=SQ tags)

Only hex segments need backticks; `Value` is a regular identifier:

```sql
SELECT
  payload:`00120064`.Value[0]:`00080100`.Value[0]::string AS first_seq_value
FROM <bronze_table>
```

ReferencedStudySequence pattern:

```sql
SELECT
  payload:`00081110`.Value[0]:`00081150`.Value[0]::string AS referenced_sop_class_uid,
  payload:`00081110`.Value[0]:`00081155`.Value[0]::string AS referenced_sop_instance_uid
FROM <bronze_table>
WHERE payload:`00081110` IS NOT NULL
```

## Multi-value CS arrays (e.g., ImageType)

```sql
SELECT
  try_variant_get(payload, '$.00080008.Value', 'array<string>') AS image_type
FROM <bronze_table>
WHERE array_contains(
  try_variant_get(payload, '$.00080008.Value', 'array<string>'),
  'LOCALIZER'
)
```

## Function-based access (programmatic / parameterized)

For programmatic path construction (parameterized tag IDs, defensive type
handling), use `try_variant_get` instead of colon syntax — it returns NULL on
type mismatch:

```sql
SELECT try_variant_get(payload, '$.00080060.Value[0]', 'string') AS modality
FROM <bronze_table>
```

`try_variant_get` is preferable when:
- The tag ID is a runtime parameter
- The data has heterogeneous VRs and you need NULL-safe failure
- Generating SQL programmatically (skill code, not manual queries)

`variant_get` (without `try_`) throws on type mismatch — useful for fail-fast
validation but rarely the right default for analytics.

## PN (Person Name) — structured object access

PN values are nested objects, not flat strings:

```json
"00100010": {"vr": "PN", "Value": [{"Alphabetic": "Doe^John", ...}]}
```

```sql
SELECT
  payload:`00100010`.Value[0]:Alphabetic::string AS patient_name_alphabetic
FROM <bronze_table>
```

Patient names are PHI. Do not extract into result sets except for narrow,
documented technical uses. See `domain-rules/phi.md`.

## Performance characteristics

Persisted Delta with VARIANT type:
- Pre-parsed binary representation
- Columnar sub-field pruning (only accessed paths are read)
- Materially faster than STRING + `get_json_object` for repeated analytical queries

This is the recommended bronze format for ongoing analytics workloads.
