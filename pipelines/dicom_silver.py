"""
DICOM Silver Pipeline — series-level curated table from instance-level bronze.

Sources: bronze.dicom_raw (DICOMweb JSON payload, instance-level)
Target:  silver.dicom_series (~30 named columns, series-level)

Bronze payload format (DICOMweb / QIDO-RS / WADO-RS, per DICOM PS3.18):
  {
    "00080060": {"vr": "CS", "Value": ["CT"]},                         # single-value
    "00280030": {"vr": "DS", "Value": [0.648438, 0.648438]},           # multi-value DS
    "00200032": {"vr": "DS", "Value": [-154.0, -85.0, 1585.0]},        # 3-component
    "00080008": {"vr": "CS", "Value": ["ORIGINAL","PRIMARY","AXIAL"]}, # multi-value CS
    "00100010": {"vr": "PN", "Value": [{"Alphabetic": "Doe^John"}]},   # PN structured
    "00120064": {"vr": "SQ", "Value": [{...nested tag dict...}]},      # sequence
    "00080030": {"vr": "TM"},                                          # no Value field
    "7FE00010": {"vr": "OW", "BulkDataURI": "https://..."}             # bulk data
  }

NOTE: DICOMweb JSON uses proper JSON arrays for multi-value tags. Traditional DICOM's
backslash-separated multi-value encoding does NOT apply here.

Type-adaptive access:
- If bronze payload column is VARIANT: use try_variant_get(...) for safe casting.
  Backtick colon syntax (payload:`00080060`...) also works in SQL but is awkward
  to construct programmatically; functions are cleaner here.
- If bronze payload column is STRING: use get_json_object + try_cast.

Both paths are supported; the pipeline detects payload type at module load and
selects the appropriate sanitizer family.

Pipeline context (vs ad-hoc skill):
This pipeline does NOT use runtime schema discovery. The payload column name and
bronze table are configured via SDP pipeline configuration parameters
(`dicom.payload_column`, `dicom.bronze_table`) for deterministic deployment behavior.
The dicom-analytics skill in ad-hoc mode (notebooks, SQL editor) handles unknown
schemas via its Discovery Phase; this pipeline trusts its configuration.

Configuration parameters (set in databricks.yml or pipeline UI):
- dicom.payload_column   (default: "dicom_payload")
- dicom.bronze_table     (default: "bronze.dicom_raw")

To add a tag to silver:
- Open this file in the Lakeflow Pipelines Editor.
- Prompt Genie Code Agent mode: "add <tag_name> to the silver pipeline as <type>".
- Genie reads dicom-analytics + databricks-spark-declarative-pipelines skills;
  emits the edits to this file plus an entry in skills/dicom-analytics/SKILL.md's
  curated tag dictionary.
- Review the multi-file diff, approve, run a full refresh of the pipeline.

Author: Samuel Selvan
Account: NWM
"""

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, VariantType


# ---------------------------------------------------------------------------
# Configuration — read from SDP pipeline parameters
# ---------------------------------------------------------------------------

PAYLOAD_COL = spark.conf.get("dicom.payload_column", "dicom_payload")
BRONZE_TABLE = spark.conf.get("dicom.bronze_table", "bronze.dicom_raw")

# Detect payload column type to select the appropriate sanitizer family.
# Pipelines fail fast if the bronze table or column is missing — that's a config
# error that should surface immediately, not silently produce wrong data.
_bronze_schema = spark.table(BRONZE_TABLE).schema
_payload_field = next((f for f in _bronze_schema if f.name == PAYLOAD_COL), None)
if _payload_field is None:
    raise ValueError(
        f"Configured payload column '{PAYLOAD_COL}' not found in {BRONZE_TABLE}. "
        f"Available columns: {[f.name for f in _bronze_schema]}. "
        f"Set 'dicom.payload_column' configuration parameter to the correct column."
    )

PAYLOAD_IS_VARIANT = _payload_field.dataType.typeName().lower() == "variant"
print(f"[dicom_silver] Bronze: {BRONZE_TABLE}, payload column: {PAYLOAD_COL} "
      f"(type: {'VARIANT' if PAYLOAD_IS_VARIANT else 'STRING'})")


# ---------------------------------------------------------------------------
# Sanitizers — extract and cast tag values from the DICOMweb JSON payload.
#
# All take a tag_id (8-char hex like "00080060") and construct the access
# expression internally based on the discovered payload column type.
# ---------------------------------------------------------------------------

def ds_first(tag_id: str):
    """Single-value DS (or first of multi-value), as DOUBLE.
    Used for: SliceThickness, KVP, RepetitionTime, etc."""
    if PAYLOAD_IS_VARIANT:
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0]', 'double')"
        )
    return F.try_cast(
        F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[0]"),
        DoubleType()
    )


def ds_at(tag_id: str, idx: int):
    """Multi-value DS, idx-th component, as DOUBLE.
    Used for: PixelSpacing[row=0, col=1], ImagePositionPatient[x=0, y=1, z=2],
              ImageOrientationPatient[row_x=0..z=5]."""
    if PAYLOAD_IS_VARIANT:
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[{idx}]', 'double')"
        )
    return F.try_cast(
        F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[{idx}]"),
        DoubleType()
    )


def is_first(tag_id: str):
    """Single IS (integer string), as INT. Used for: SeriesNumber, InstanceNumber."""
    if PAYLOAD_IS_VARIANT:
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0]', 'int')"
        )
    return F.try_cast(
        F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[0]"),
        IntegerType()
    )


def us_first(tag_id: str):
    """US (unsigned short) — JSON number, as INT. Used for: Rows, Columns, BitsAllocated."""
    if PAYLOAD_IS_VARIANT:
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0]', 'int')"
        )
    return F.try_cast(
        F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[0]"),
        IntegerType()
    )


def da_first(tag_id: str):
    """DA (date) — should be YYYYMMDD. Tolerates YYYY.MM.DD / YYYY-MM-DD legacy variants."""
    if PAYLOAD_IS_VARIANT:
        raw = F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0]', 'string')"
        )
    else:
        raw = F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[0]")
    cleaned = F.regexp_replace(F.trim(raw), r"[\.\-/]", "")
    return F.to_date(cleaned, "yyyyMMdd")


def cs_first(tag_id: str):
    """CS / LO / SH / UI / AE / AS / ST — single string value. Trims whitespace.
    PHI-bearing string fields (PN, free-text descriptions) are NOT extracted into silver."""
    if PAYLOAD_IS_VARIANT:
        return F.trim(F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0]', 'string')"
        ))
    return F.trim(
        F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value[0]")
    )


def cs_array(tag_id: str):
    """Multi-value CS — returns ARRAY<STRING>. Used for: ImageType, etc."""
    if PAYLOAD_IS_VARIANT:
        # try_variant_get with array<string> target type
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value', 'array<string>')"
        )
    raw = F.get_json_object(F.col(PAYLOAD_COL), f"$.{tag_id}.Value")
    return F.from_json(raw, "array<string>")


def pn_alphabetic(tag_id: str):
    """PN (person name) — Alphabetic component. PN values are objects with
    {Alphabetic, Ideographic, Phonetic}. Not used in silver (PHI), but provided for
    bronze-layer extraction patterns if ever needed for PHI workflows."""
    if PAYLOAD_IS_VARIANT:
        return F.expr(
            f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag_id}.Value[0].Alphabetic', 'string')"
        )
    return F.get_json_object(
        F.col(PAYLOAD_COL),
        f"$.{tag_id}.Value[0].Alphabetic"
    )


# ---------------------------------------------------------------------------
# Bronze -> instance-level extracted projection
# ---------------------------------------------------------------------------

@dlt.view(
    name="bronze_dicom_extracted",
    comment="Bronze DICOMweb JSON projected to instance-level rows with named columns. "
            "Source for the series-level silver aggregation. Type-adapted to the "
            "discovered bronze payload column (VARIANT or STRING)."
)
def bronze_dicom_extracted():
    return (
        spark.read.table(BRONZE_TABLE)
        .select(
            # Identifiers — note: depending on Lima's bronze, these may already exist
            # as separate columns. If so, replace these calls with direct column refs.
            cs_first("0020000D").alias("study_instance_uid"),
            cs_first("0020000E").alias("series_instance_uid"),
            cs_first("00080018").alias("sop_instance_uid"),

            # Modality / device
            cs_first("00080060").alias("modality"),
            cs_first("00080070").alias("manufacturer"),
            cs_first("00081090").alias("manufacturer_model_name"),
            cs_first("00081010").alias("station_name"),

            # Anatomy / context
            cs_first("00180015").alias("body_part_examined"),
            cs_first("00181030").alias("protocol_name"),

            # Dates
            da_first("00080020").alias("study_date"),
            da_first("00080021").alias("series_date"),
            da_first("00080022").alias("acquisition_date"),

            # Patient demographics (non-PHI: age string, sex code)
            cs_first("00101010").alias("patient_age"),
            cs_first("00100040").alias("patient_sex"),

            # Acquisition parameters
            ds_first("00180050").alias("slice_thickness"),
            ds_first("00180088").alias("spacing_between_slices"),
            ds_first("00180060").alias("kvp"),
            ds_first("00180080").alias("repetition_time"),
            ds_first("00180081").alias("echo_time"),
            ds_first("00181314").alias("flip_angle"),
            ds_first("00180087").alias("magnetic_field_strength"),
            # --- PRE-STAGED: Litmus test recovery (uncomment if Genie hangs) ---
            # ds_first("00181041").alias("contrast_bolus_volume"),

            # Multi-value DS — named component split (Value array indexing)
            ds_at("00280030", 0).alias("pixel_spacing_row"),
            ds_at("00280030", 1).alias("pixel_spacing_col"),
            ds_at("00200032", 0).alias("image_position_x"),
            ds_at("00200032", 1).alias("image_position_y"),
            ds_at("00200032", 2).alias("image_position_z"),

            # Image
            cs_array("00080008").alias("image_type"),
            cs_first("00280004").alias("photometric_interpretation"),
            us_first("00280010").alias("rows"),
            us_first("00280011").alias("columns"),

            # Audit
            F.col("_ingestion_timestamp").alias("_ingestion_timestamp"),
        )
    )


# ---------------------------------------------------------------------------
# Series-level silver
# ---------------------------------------------------------------------------

@dlt.table(
    name="dicom_series",
    comment="Curated series-level DICOM metadata. ~30 named columns from PS3.6. "
            "Aggregated from instance-level bronze via first(... ignorenulls=True) "
            "for series-constant fields. See skills/dicom-analytics/SKILL.md for the "
            "tag dictionary, routing rules, and canonical query patterns.",
    table_properties={
        "delta.enableChangeDataFeed": "false",
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
        "delta.columnMapping.mode": "name",
    },
    cluster_by=["modality", "study_instance_uid"],  # liquid clustering
)
def dicom_series():
    extracted = dlt.read("bronze_dicom_extracted")

    return (
        extracted
        .groupBy("study_instance_uid", "series_instance_uid")
        .agg(
            # Series-constant fields: first non-null value
            F.first("modality", ignorenulls=True).alias("modality"),
            F.first("manufacturer", ignorenulls=True).alias("manufacturer"),
            F.first("manufacturer_model_name", ignorenulls=True).alias("manufacturer_model_name"),
            F.first("station_name", ignorenulls=True).alias("station_name"),
            F.first("body_part_examined", ignorenulls=True).alias("body_part_examined"),
            F.first("protocol_name", ignorenulls=True).alias("protocol_name"),

            F.first("study_date", ignorenulls=True).alias("study_date"),
            F.first("series_date", ignorenulls=True).alias("series_date"),
            F.first("acquisition_date", ignorenulls=True).alias("acquisition_date"),

            F.first("patient_age", ignorenulls=True).alias("patient_age"),
            F.first("patient_sex", ignorenulls=True).alias("patient_sex"),

            F.first("slice_thickness", ignorenulls=True).alias("slice_thickness"),
            F.first("spacing_between_slices", ignorenulls=True).alias("spacing_between_slices"),
            F.first("kvp", ignorenulls=True).alias("kvp"),
            F.first("repetition_time", ignorenulls=True).alias("repetition_time"),
            F.first("echo_time", ignorenulls=True).alias("echo_time"),
            F.first("flip_angle", ignorenulls=True).alias("flip_angle"),
            F.first("magnetic_field_strength", ignorenulls=True).alias("magnetic_field_strength"),
            # --- PRE-STAGED: Litmus test recovery (uncomment if Genie hangs) ---
            # F.first("contrast_bolus_volume", ignorenulls=True).alias("contrast_bolus_volume"),

            F.first("pixel_spacing_row", ignorenulls=True).alias("pixel_spacing_row"),
            F.first("pixel_spacing_col", ignorenulls=True).alias("pixel_spacing_col"),
            F.first("image_position_x", ignorenulls=True).alias("image_position_x"),
            F.first("image_position_y", ignorenulls=True).alias("image_position_y"),
            F.first("image_position_z", ignorenulls=True).alias("image_position_z"),

            F.first("image_type", ignorenulls=True).alias("image_type"),
            F.first("photometric_interpretation", ignorenulls=True).alias("photometric_interpretation"),
            F.first("rows", ignorenulls=True).alias("rows"),
            F.first("columns", ignorenulls=True).alias("columns"),

            # Series-derived
            F.count(F.lit(1)).alias("instance_count"),
            F.max("_ingestion_timestamp").alias("_last_ingestion_timestamp"),
        )
    )


# ---------------------------------------------------------------------------
# Pipeline assertions (warn-only for v1)
#
# For fields that should be series-constant, log series where multiple distinct
# values were observed. Surfaces data heterogeneity without failing the run.
# ---------------------------------------------------------------------------

@dlt.expect("modality_is_series_constant",
            "modality_distinct_count <= 1")
@dlt.expect("manufacturer_is_series_constant",
            "manufacturer_distinct_count <= 1")
@dlt.expect("slice_thickness_is_series_constant_or_null",
            "slice_thickness_distinct_count <= 1")
@dlt.view(
    name="series_constant_violations",
    comment="Diagnostic view — surfaces series where supposedly-constant fields "
            "have multiple distinct values. WARN-only; pipeline does not fail."
)
def series_constant_violations():
    extracted = dlt.read("bronze_dicom_extracted")
    return (
        extracted
        .groupBy("study_instance_uid", "series_instance_uid")
        .agg(
            F.countDistinct("modality").alias("modality_distinct_count"),
            F.countDistinct("manufacturer").alias("manufacturer_distinct_count"),
            F.countDistinct("slice_thickness").alias("slice_thickness_distinct_count"),
        )
        .filter(
            (F.col("modality_distinct_count") > 1)
            | (F.col("manufacturer_distinct_count") > 1)
            | (F.col("slice_thickness_distinct_count") > 1)
        )
    )
