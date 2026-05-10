# Bronze patterns — long-tail tags, sequences, private vendor

Load when query needs to access tags that aren't in the curated surface:
- Long-tail tags not curated to silver
- Sequence (VR=SQ) tags (kept as JSON, never flattened inline)
- Private vendor tags (odd-numbered group IDs)
- Bulk-data references

Composes with `sql-patterns/variant.md` or `sql-patterns/string.md` depending on
discovered payload type.

## Long-tail tag query

For a tag not in the curated surface (e.g., `ContrastBolusAgent` if not curated):

```sql
-- VARIANT
SELECT
  COUNT(DISTINCT (<study_uid_column>, <series_uid_column>)) AS series_with_contrast
FROM <bronze_table>
WHERE payload:`00180010`.Value[0]::string IS NOT NULL

-- STRING
SELECT
  COUNT(DISTINCT (<study_uid_column>, <series_uid_column>)) AS series_with_contrast
FROM <bronze_table>
WHERE get_json_object(payload, '$.00180010.Value[0]') IS NOT NULL
```

## Sequence tag access (VR=SQ)

Sequence tags are nested JSON arrays of objects. Each item is a fully-qualified
sub-tag dictionary. Don't flatten inline — use nested access:

```sql
-- VARIANT — ReferencedStudySequence (00081110), pull referenced SOP Class UID
-- and SOP Instance UID from the first item
SELECT
  <study_uid_column>, <series_uid_column>,
  payload:`00081110`.Value[0]:`00081150`.Value[0]::string AS referenced_sop_class_uid,
  payload:`00081110`.Value[0]:`00081155`.Value[0]::string AS referenced_sop_instance_uid
FROM <bronze_table>
WHERE payload:`00081110` IS NOT NULL

-- STRING
SELECT
  <study_uid_column>, <series_uid_column>,
  get_json_object(payload, '$.00081110.Value[0].00081150.Value[0]') AS referenced_sop_class_uid,
  get_json_object(payload, '$.00081110.Value[0].00081155.Value[0]') AS referenced_sop_instance_uid
FROM <bronze_table>
WHERE get_json_object(payload, '$.00081110') IS NOT NULL
```

Common sequence tags worth knowing:
- `(0008,1110)` ReferencedStudySequence
- `(0008,1140)` ReferencedImageSequence
- `(0008,2218)` AnatomicRegionSequence
- `(0018,9304)` CTAcquisitionTypeSequence
- `(0018,9314)` CTReconstructionAlgorithmSequence
- `(0040,0275)` RequestAttributesSequence (RIS / scheduling integration)
- `(0040,0260)` PerformedProtocolCodeSequence

## Multi-frame Enhanced DICOM

### When this applies

Enhanced (multi-frame) DICOM is a different IOD family where one SOP instance
contains many frames, and acquisition parameters live inside functional group
sequences rather than at the top of the dataset. Top-level tag queries return
NULL on Enhanced data because the tags aren't there.

Detect via SOP Class UID:

| SOP Class | UID |
|---|---|
| Enhanced CT | `1.2.840.10008.5.1.4.1.1.2.1` |
| Enhanced MR | `1.2.840.10008.5.1.4.1.1.4.1` |
| Enhanced PET | `1.2.840.10008.5.1.4.1.1.128.1` |
| Enhanced US Volume | `1.2.840.10008.5.1.4.1.1.6.2` |
| Legacy Converted Enhanced CT | `1.2.840.10008.5.1.4.1.1.2.2` |
| Legacy Converted Enhanced MR | `1.2.840.10008.5.1.4.1.1.4.4` |

Common deployments: modern Siemens / GE / Philips CT scanners (post-2018), most
new MR scanners (especially Philips), newer PET. Older scanners and many U.S.
deployments still emit classic single-frame instances. Both can coexist in the
same fleet.

### Detection query

```sql
-- VARIANT
SELECT
  <study_uid_column>,
  <series_uid_column>,
  payload:`00080016`.Value[0]::string AS sop_class_uid,
  CASE
    WHEN payload:`00080016`.Value[0]::string IN (
      '1.2.840.10008.5.1.4.1.1.2.1',     -- Enhanced CT
      '1.2.840.10008.5.1.4.1.1.4.1',     -- Enhanced MR
      '1.2.840.10008.5.1.4.1.1.128.1',   -- Enhanced PET
      '1.2.840.10008.5.1.4.1.1.2.2',     -- Legacy Converted Enhanced CT
      '1.2.840.10008.5.1.4.1.1.4.4'      -- Legacy Converted Enhanced MR
    ) THEN 'enhanced'
    ELSE 'classic'
  END AS iod_family
FROM <bronze_table>
```

If a customer's curated `slice_thickness` column shows large NULL counts on CT
or MR series, run this detection — Enhanced IOD content is the most common
cause.

### Shared functional group access

Tags constant across all frames in the instance live in
`SharedFunctionalGroupsSequence (5200,9229)`. The shared group is an array of
exactly one item containing nested macros. The macros that hold the tags
customers usually want:

| Macro | Tag | Holds |
|---|---|---|
| PixelMeasuresSequence | (0028,9110) | SliceThickness, PixelSpacing, SpacingBetweenSlices |
| PlanePositionSequence | (0020,9113) | ImagePositionPatient |
| PlaneOrientationSequence | (0020,9116) | ImageOrientationPatient |
| MRTimingAndRelatedParametersSequence | (0018,9112) | RepetitionTime, FlipAngle |
| MREchoSequence | (0018,9114) | EffectiveEchoTime |
| MRImageFrameTypeSequence | (0018,9226) | FrameType (MR) |
| CTAcquisitionDetailsSequence | (0018,9304) | CT acquisition params |
| CTExposureSequence | (0018,9321) | KVP, CTDIvol, exposure |
| CTReconstructionSequence | (0018,9314) | ReconstructionAlgorithm |
| ContrastBolusUsageSequence | (0018,9341) | Contrast presence and timing |

Pattern for shared SliceThickness on Enhanced CT:

```sql
-- VARIANT
SELECT
  <study_uid_column>,
  <series_uid_column>,
  payload:`52009229`.Value[0]:`00289110`.Value[0]:`00180050`.Value[0]::double
    AS slice_thickness_shared
FROM <bronze_table>
WHERE payload:`00080016`.Value[0]::string = '1.2.840.10008.5.1.4.1.1.2.1'

-- STRING
SELECT
  <study_uid_column>,
  <series_uid_column>,
  try_cast(get_json_object(payload,
    '$.52009229.Value[0].00289110.Value[0].00180050.Value[0]') AS DOUBLE)
    AS slice_thickness_shared
FROM <bronze_table>
WHERE get_json_object(payload, '$.00080016.Value[0]')
      = '1.2.840.10008.5.1.4.1.1.2.1'
```

For shared CTDIvol on Enhanced CT:

```sql
-- VARIANT
SELECT
  payload:`52009229`.Value[0]:`00189321`.Value[0]:`00189345`.Value[0]::double
    AS ctdi_vol_shared
FROM <bronze_table>
WHERE payload:`00080016`.Value[0]::string = '1.2.840.10008.5.1.4.1.1.2.1'
```

For shared MR EffectiveEchoTime:

```sql
-- VARIANT
SELECT
  payload:`52009229`.Value[0]:`00189114`.Value[0]:`00189082`.Value[0]::double
    AS effective_echo_time
FROM <bronze_table>
WHERE payload:`00080016`.Value[0]::string = '1.2.840.10008.5.1.4.1.1.4.1'
```

### Per-frame access

`PerFrameFunctionalGroupsSequence (5200,9230)` is an array with one item per
frame. Each item contains the same macros as the shared group. Per-frame
queries require exploding the array.

```sql
-- VARIANT — per-frame slice thickness for Enhanced CT
WITH per_frame AS (
  SELECT
    <study_uid_column>,
    <series_uid_column>,
    posexplode(
      from_variant(payload:`52009230`.Value, 'array<variant>')
    ) AS (frame_idx, frame_group)
  FROM <bronze_table>
  WHERE payload:`00080016`.Value[0]::string = '1.2.840.10008.5.1.4.1.1.2.1'
)
SELECT
  <study_uid_column>,
  <series_uid_column>,
  frame_idx,
  frame_group:`00289110`.Value[0]:`00180050`.Value[0]::double AS slice_thickness
FROM per_frame
```

### Practical guidance

For routine fleet characterization (P50/P90 by manufacturer or body region),
prefer the **shared functional group** — most acquisition parameters are
constant across frames within an instance, and the shared path is one query
against one sequence position.

Reserve **per-frame** queries for cases where frame-level variation is the
analytic target (mA modulation profiles, MR timing variation across a series,
multi-phase contrast studies).

### Caveats

1. **Some tags can appear in both shared and per-frame groups.** When both are
   populated, the per-frame value wins for that frame. For aggregate
   analytics, the shared value is usually sufficient.
2. **Legacy Converted instances are technically multi-frame** but were
   originally classic single-frame. They look multi-frame in structure but
   typically have a single per-frame entry. The same patterns work.
3. **Curated silver pipelines often only handle classic IOD.** A customer
   asking "why is my slice_thickness NULL" on modern CT data is the canonical
   symptom — the silver pipeline needs to extract from the functional group,
   or the analytics need to route through bronze with these patterns.

## Dose Structured Reports (RDSR)

### Scope distinction

`templates/dose-compliance.md` queries image-header `CTDIvol (0018,9345)` from
the curated silver. That's correct for **fleet characterization** — average
dose by body region, outlier identification, vendor comparison. It is **not**
the source for regulatory submissions (ACR Dose Index Registry, state dose
registries) or per-irradiation-event analyses. Those use X-Ray Radiation Dose
Structured Reports (RDSR), which are separate DICOM SOP instances containing
the full per-event dose record.

Every CT study with dose recording produces both image instances (with
image-header CTDIvol per series) and a separate RDSR instance (with per-event
detail).

### Detection

| SR class | SOP Class UID |
|---|---|
| X-Ray Radiation Dose SR | `1.2.840.10008.5.1.4.1.1.88.67` |
| Radiopharmaceutical Radiation Dose SR | `1.2.840.10008.5.1.4.1.1.88.68` |
| Comprehensive SR | `1.2.840.10008.5.1.4.1.1.88.33` |
| Enhanced SR | `1.2.840.10008.5.1.4.1.1.88.22` |

The X-Ray RDSR (`88.67`) is the format for CT, projection X-ray, and
fluoroscopy dose.

```sql
-- VARIANT — identify RDSR instances
SELECT
  <study_uid_column>,
  <series_uid_column>,
  payload:`00080018`.Value[0]::string AS sop_instance_uid
FROM <bronze_table>
WHERE payload:`00080060`.Value[0]::string = 'SR'
  AND payload:`00080016`.Value[0]::string = '1.2.840.10008.5.1.4.1.1.88.67'

-- STRING
SELECT
  <study_uid_column>,
  <series_uid_column>,
  get_json_object(payload, '$.00080018.Value[0]') AS sop_instance_uid
FROM <bronze_table>
WHERE get_json_object(payload, '$.00080060.Value[0]') = 'SR'
  AND get_json_object(payload, '$.00080016.Value[0]')
      = '1.2.840.10008.5.1.4.1.1.88.67'
```

### Why content extraction isn't a SQL job

RDSR content lives in `ContentSequence (0040,A730)` — a recursive nested SR
template (TID 10011 root → TID 10013 acquisition events → TID 10014 CT
acquisition parameters). Each content item has:

- `ConceptNameCodeSequence (0040,A043)` — what this item *is* (concept code
  identifying the value)
- `MeasuredValueSequence (0040,A300)` containing `NumericValue (0040,A30A)` —
  the value, for numeric items
- `ContentSequence (0040,A730)` — child items, recursive

Per-event values are at varying depths because the template is hierarchical
and branch-dependent. Recursive nested-sequence traversal in pure SQL is
tractable for one or two known levels, but full TID 10011 walks rapidly become
unmaintainable.

The pragmatic options:

1. **PyDicom in a Databricks notebook.** Load the RDSR instance, walk
   `ds.ContentSequence` recursively, emit a normalized table
   `(study_uid, event_idx, ctdi_vol, dlp, phantom_type, kvp, ...)`. Standard
   approach in dose monitoring tools; ~50 lines of Python.
2. **A dedicated dose pipeline.** For ongoing dose registry submissions, build
   a silver-tier `dicom_dose_events` table populated from RDSR via a UDF or
   notebook. Skill queries then go against that flat table, not against bronze
   RDSR content.
3. **For one-off questions, image-header CTDIvol is usually sufficient.**
   Routine fleet characterization, vendor outlier identification, and
   protocol calibration all work fine off `templates/dose-compliance.md`.

### Concept codes (informational)

The DCM coding scheme codes for the per-event values customers most often want:

| Concept | Code | Meaning |
|---|---|---|
| 113830 | CTDI<sub>vol</sub> | Per-event volumetric CTDI |
| 113838 | DLP | Per-event dose-length product |
| 113819 | CT Phantom Type | head / body |
| 113820 | CT Acquisition | Marker for an acquisition event in the tree |

These codes appear inside `ConceptNameCodeSequence` items as `CodeValue
(0008,0100)` with `CodingSchemeDesignator (0008,0102)` of `'DCM'`. Even with
the codes in hand, the recursive walk to find them remains a Python job.

### When to use which source

| Use case | Source |
|---|---|
| Fleet dose characterization (P50/P90 by body region) | Image-header CTDIvol (silver) |
| Vendor / station outlier identification | Image-header CTDIvol (silver) |
| Per-irradiation-event analysis | RDSR (Python) |
| ACR Dose Index Registry submission | RDSR (Python or vendor tool) |
| State-mandated dose reporting | RDSR (typically vendor tool) |
| Patient cumulative dose tracking | RDSR (Python — image header undercounts) |

## Private / vendor tag access

Tags with odd-numbered group IDs (0009, 0019, 0029, 7053, etc.) are
vendor-specific. Always filter by manufacturer first (see
`domain-rules/normalization.md`).

### The private creator block convention

Private tags don't live at fixed element IDs. The DICOM standard requires
private creators to *reserve* an element block before using it:

- Within an odd group `gggg`, elements `(gggg,0010)` through `(gggg,00FF)` are
  *private creator reservations* — each holds a creator string identifying the
  owner.
- A creator string at `(gggg,00xx)` reserves elements `(gggg,xx00)` through
  `(gggg,xxFF)` for that owner.
- The same private tag from the same vendor can land at different element IDs
  on different scanners and software versions, depending on which slot the
  creator landed in.

If GE's `GEMS_ACQU_01` creator is at `(0019,0010)`, the GE-specific field `0A`
lives at `(0019,100A)`. If on another scanner the creator landed at
`(0019,0011)`, the same logical field is at `(0019,110A)`. Querying
`(0019,100A)` directly returns NULL on the second scanner.

### Defensive query pattern

For known private tags, check the most common slot positions and verify the
creator string. Slots `10`, `11`, `12` cover the bulk of real-world deployments:

```sql
-- VARIANT — GE-specific element 0A from the GEMS_ACQU_01 creator block
SELECT
  <study_uid_column>,
  <series_uid_column>,
  COALESCE(
    CASE WHEN payload:`00190010`.Value[0]::string = 'GEMS_ACQU_01'
         THEN payload:`0019100A`.Value[0]::string END,
    CASE WHEN payload:`00190011`.Value[0]::string = 'GEMS_ACQU_01'
         THEN payload:`0019110A`.Value[0]::string END,
    CASE WHEN payload:`00190012`.Value[0]::string = 'GEMS_ACQU_01'
         THEN payload:`0019120A`.Value[0]::string END
  ) AS ge_acqu_field_0a
FROM <bronze_table>
WHERE UPPER(payload:`00080070`.Value[0]::string) LIKE '%GE%'
```

```sql
-- STRING bronze equivalent
SELECT
  <study_uid_column>,
  <series_uid_column>,
  COALESCE(
    CASE WHEN get_json_object(payload, '$.00190010.Value[0]') = 'GEMS_ACQU_01'
         THEN get_json_object(payload, '$.0019100A.Value[0]') END,
    CASE WHEN get_json_object(payload, '$.00190011.Value[0]') = 'GEMS_ACQU_01'
         THEN get_json_object(payload, '$.0019110A.Value[0]') END,
    CASE WHEN get_json_object(payload, '$.00190012.Value[0]') = 'GEMS_ACQU_01'
         THEN get_json_object(payload, '$.0019120A.Value[0]') END
  ) AS ge_acqu_field_0a
FROM <bronze_table>
WHERE UPPER(get_json_object(payload, '$.00080070.Value[0]')) LIKE '%GE%'
```

### When the slot list isn't enough

The hardcoded slot pattern works for slots 10–12, which covers ~95% of real
deployments. For serious private-tag analytics — many tags, many slots, many
vendors — the pattern stops scaling. Two alternatives:

1. **One-time normalization to silver.** The ingest pipeline reads private
   creators per row, computes the actual element IDs, and writes normalized
   columns to silver (`ge_recon_kernel`, `siemens_csa_protocol`, etc.). Bronze
   keeps the raw payload; silver gets vendor-specific named columns. This is
   the right answer for ongoing vendor-specific analytics.
2. **PyDicom or Python UDF.** Iterating creator slots and computing real
   element IDs is straightforward in Python. Use this for one-off deep dives.

Don't try to do recursive creator-slot resolution in pure SQL beyond the small
hardcoded slot list above.

### Common private creator strings

These vary by vendor and software version — always verify against the actual
creator string in your data, not the table below:

| Vendor / context | Common creator strings |
|---|---|
| GE CT/MR | `GEMS_ACQU_01`, `GEMS_PARM_01`, `GEMS_IDEN_01`, `GEMS_PETD_01` |
| Siemens CT | `SIEMENS CT VA0  COAD`, `SIEMENS MED MARS`, `SIEMENS MEDCOM HEADER` |
| Siemens MR | `SIEMENS MR HEADER`, `SIEMENS CSA HEADER`, `SIEMENS CSA NON-IMAGE` |
| Philips CT/MR | `Philips Imaging DD 001`, `Philips MR Imaging DD 001` |
| Canon (Toshiba) | `TOSHIBA_MEC_CT3`, `TOSHIBA_MEC_MR3` |

## Bulk data references

Some DICOM tags carry image pixel data or large binary content. In DICOMweb
JSON, these appear with `BulkDataURI` instead of `Value`:

```json
"7FE00010": {"vr": "OW", "BulkDataURI": "https://..."}
```

For metadata analytics, you typically don't fetch bulk data; you just need to
know whether it's referenced. Check for the BulkDataURI field's existence:

```sql
-- VARIANT
SELECT COUNT(*) FROM <bronze_table>
WHERE payload:`7FE00010`.BulkDataURI::string IS NOT NULL
```

## When to route to bronze vs silver

Use this decision when the working dictionary doesn't have the tag the user
asked about:

1. **Tag is in PS3.6** (lookup via embedded fallback or PS3.6 keyword lookup)
   AND the tag would be a sensible silver column type (DS, IS, US, FD, CS, LO,
   SH, UI):
   → Generate the bronze query AND mention to the user that this tag could be
     curated to silver if it's a recurring need.

2. **Tag is a sequence (VR=SQ)** or has variable structure:
   → Always bronze. Sequences shouldn't be flattened to columnar form.

3. **Tag is private / vendor-specific:**
   → Always bronze. Apply the manufacturer filter pattern.

4. **Tag isn't in PS3.6 and isn't private:**
   → Either user error (typo) or non-standard extension. Probe a sample row to
     confirm the tag exists; if not, surface the absence.

## Domain rules to apply

- `domain-rules/normalization.md` — manufacturer filter for private tags
- `domain-rules/phi.md` — typical PHI rules apply
- `sql-patterns/<variant|string>.md` — type-adaptive access pattern
- `sql-patterns/direct-columns.md` — if the bronze table has top-level identifier columns (e.g., `study_instance_uid`), use them directly instead of extracting from the payload
