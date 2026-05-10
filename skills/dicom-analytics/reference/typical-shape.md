# Reference: typical curated silver shape

Load when the working dictionary needs reference comparison (Discovery Step 5
fallback path 2 — column lookup with no PS3.6 source available).

## Purpose

The actual columns in the user's silver come from Discovery Step 5. This file
shows what a typical curated DICOM silver might contain — a reference for
"what good looks like," not a prescription. Different hospitals curate
different subsets.

## Typical curated columns

| PS3.6 keyword | DICOM ID | Likely column name | VR | Type | Notes |
|---|---|---|---|---|---|
| StudyInstanceUID | (0020,000D) | study_instance_uid | UI | STRING | always present |
| SeriesInstanceUID | (0020,000E) | series_instance_uid | UI | STRING | always present |
| Modality | (0008,0060) | modality | CS | STRING | always present |
| Manufacturer | (0008,0070) | manufacturer | LO | STRING | usually unnormalized |
| ManufacturerModelName | (0008,1090) | manufacturer_model_name | LO | STRING |  |
| StationName | (0008,1010) | station_name | SH | STRING | LOW PHI (quasi-id) |
| StudyDate | (0008,0020) | study_date | DA | DATE | precision per Domain Rules |
| SeriesDate | (0008,0021) | series_date | DA | DATE |  |
| AcquisitionDate | (0008,0022) | acquisition_date | DA | DATE |  |
| StudyTime | (0008,0030) | study_time | TM | STRING | utilization metrics |
| SeriesTime | (0008,0031) | series_time | TM | STRING | utilization metrics |
| AcquisitionTime | (0008,0032) | acquisition_time | TM | STRING | utilization metrics |
| BodyPartExamined | (0018,0015) | body_part_examined | CS | STRING |  |
| PatientAge | (0010,1010) | patient_age | AS | STRING | format `nnnY` |
| PatientSex | (0010,0040) | patient_sex | CS | STRING | M/F/O |
| SliceThickness | (0018,0050) | slice_thickness | DS | DOUBLE | mm |
| SpacingBetweenSlices | (0018,0088) | spacing_between_slices | DS | DOUBLE | mm |
| KVP | (0018,0060) | kvp | DS | DOUBLE | CT/X-ray |
| RepetitionTime | (0018,0080) | repetition_time | DS | DOUBLE | MR TR ms |
| EchoTime | (0018,0081) | echo_time | DS | DOUBLE | MR TE ms |
| FlipAngle | (0018,1314) | flip_angle | DS | DOUBLE | MR degrees |
| MagneticFieldStrength | (0018,0087) | magnetic_field_strength | DS | DOUBLE | MR Tesla |
| CTDIvol | (0018,9345) | ctdi_vol | FD | DOUBLE | CT dose, mGy |
| ExposureTime | (0018,1150) | exposure_time | IS | INT | ms |
| XRayTubeCurrent | (0018,1151) | xray_tube_current | IS | INT | mA |
| ContrastBolusAgent | (0018,0010) | contrast_bolus_agent | LO | STRING | contrast cohort |
| ScanOptions | (0018,0022) | scan_options | CS | ARRAY<STRING> | acquisition technique |
| PixelSpacing | (0028,0030) | pixel_spacing_row, pixel_spacing_col | DS | DOUBLE | derived: component split |
| ImagePositionPatient | (0020,0032) | image_position_x, image_position_y, image_position_z | DS | DOUBLE | derived: component split |
| ImageType | (0008,0008) | image_type | CS | ARRAY<STRING> | multi-value |
| PhotometricInterpretation | (0028,0004) | photometric_interpretation | CS | STRING |  |
| Rows | (0028,0010) | rows | US | INT | image height |
| Columns | (0028,0011) | columns | US | INT | image width |
| ProtocolName | (0018,1030) | protocol_name | LO | STRING | LOW PHI (free text) |
| (computed rollup) | — | instance_count | — | INT | derived: series-level count |

## How to use this reference

When Discovery Step 5 is mapping a column to its PS3.6 origin and:
- The column comment doesn't include a hex tag ID → look up the column name here
- Match found → use the listed PS3.6 ID and keyword in the working dictionary
- No match found → fall through to PS3.6 keyword lookup table (if present in catalog) or mark `origin: "unknown"`

## What this is NOT

- **Not a prescription.** The user's silver may have fewer, more, or different columns.
- **Not exhaustive.** Many DICOM tags exist beyond this set. Bronze + EAV view handle the long tail.
- **Not fixed.** Curated tag dictionaries grow over time as analytics needs evolve. Teams typically add tags via Genie Code Agent mode as new analysis needs arise.

## Mapping fidelity

For columns NOT in this table:
- If the column has a snake_case name that converts cleanly to a known PS3.6 keyword (e.g., `aperture_shape` → `ApertureShape`), the PS3.6 keyword lookup table (Discovery Step 4) handles it.
- If the column is a derived column (component split, normalized value, computed) — the column comment should mark it with `derived:` or `computed:` prefix.
- If neither — Discovery marks `origin: "unknown"`. The column is still usable in queries; only the PS3.6 metadata is missing.
