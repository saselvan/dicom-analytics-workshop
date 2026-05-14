"""
DICOM Silver Pipeline — series-level curated table from instance-level bronze.

Sources: bronze.dicom_raw (DICOMweb JSON payload, instance-level)
Target:  dicom_series (~30 named columns, series-level)

Uses the modern Spark Declarative Pipelines (SDP) Python API. All transformation
logic is expressed as SQL — Python is used only for configuration and type detection.
The pipeline is fully declarative: each decorated function returns a single SQL
expression defining WHAT the table contains, not HOW to compute it.

Bronze payload format (DICOMweb / QIDO-RS / WADO-RS, per DICOM PS3.18):
  { "00080060": {"vr": "CS", "Value": ["CT"]}, ... }

Configuration parameters (set in databricks.yml or pipeline UI):
- dicom.payload_column           (default: "dicom_payload")
- dicom.bronze_table             (default: "bronze.dicom_raw")
- dicom.series_type_rules_table  (default: "samuels_fevm_catalog.dicom_silver.series_type_rules")

To add a tag to silver:
- Open this file in the Lakeflow Pipelines Editor.
- Prompt Genie Code Agent mode: "add <tag_name> to the silver pipeline as <type>".
- Genie reads dicom-analytics + databricks-spark-declarative-pipelines skills;
  emits the SQL edits. Review the diff, approve, run a full refresh.

Author: Samuel Selvan
Account: NWM
"""

from pyspark import pipelines as dp


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAYLOAD_COL   = spark.conf.get("dicom.payload_column", "dicom_payload")
BRONZE_TABLE  = spark.conf.get("dicom.bronze_table", "bronze.dicom_raw")
RULES_TABLE   = spark.conf.get("dicom.series_type_rules_table",
                               "samuels_fevm_catalog.dicom_silver.series_type_rules")

# Detect payload column type — determines SQL extraction syntax.
_payload_type = next(
    (f.dataType.typeName() for f in spark.table(BRONZE_TABLE).schema
     if f.name == PAYLOAD_COL), None
)
if _payload_type is None:
    raise ValueError(f"Column '{PAYLOAD_COL}' not found in {BRONZE_TABLE}")

IS_VARIANT = _payload_type.lower() == "variant"

# Build extraction expressions based on payload type.
# VARIANT: try_variant_get(col, '$.TAG.Value[N]', 'type')
# STRING:  try_cast(get_json_object(col, '$.TAG.Value[N]'), type)
def _v(tag, idx=0, typ="string"):
    """Generate a type-adaptive extraction expression for a single tag value."""
    if IS_VARIANT:
        return f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag}.Value[{idx}]', '{typ}')"
    if typ == "string":
        return f"get_json_object({PAYLOAD_COL}, '$.{tag}.Value[{idx}]')"
    return f"try_cast(get_json_object({PAYLOAD_COL}, '$.{tag}.Value[{idx}]'), {typ})"

def _arr(tag):
    """Generate a type-adaptive extraction for an array-typed tag."""
    if IS_VARIANT:
        return f"try_variant_get(`{PAYLOAD_COL}`, '$.{tag}.Value', 'array<string>')"
    return f"from_json(get_json_object({PAYLOAD_COL}, '$.{tag}.Value'), 'array<string>')"

def _date(tag):
    """Generate date extraction with format normalization."""
    raw = _v(tag, 0, "string")
    return f"to_date(regexp_replace(trim({raw}), '[.\\\\-/]', ''), 'yyyyMMdd')"


# ---------------------------------------------------------------------------
# Bronze → instance-level extracted projection
# ---------------------------------------------------------------------------

@dp.temporary_view(
    name="bronze_dicom_extracted",
    comment="DICOMweb JSON projected to named columns. Type-adaptive to VARIANT or STRING."
)
def bronze_dicom_extracted():
    return spark.sql(f"""
    SELECT
        -- Identifiers
        TRIM({_v('0020000D')})  AS study_instance_uid,
        TRIM({_v('0020000E')})  AS series_instance_uid,
        TRIM({_v('00080018')})  AS sop_instance_uid,

        -- Modality / device
        TRIM({_v('00080060')})  AS modality,
        TRIM({_v('00080070')})  AS manufacturer,
        TRIM({_v('00081090')})  AS manufacturer_model_name,
        TRIM({_v('00081010')})  AS station_name,

        -- Anatomy / context
        TRIM({_v('00180015')})  AS body_part_examined,
        TRIM({_v('00181030')})  AS protocol_name,

        -- Dates
        {_date('00080020')}     AS study_date,
        {_date('00080021')}     AS series_date,
        {_date('00080022')}     AS acquisition_date,

        -- Patient demographics (non-PHI)
        TRIM({_v('00101010')})  AS patient_age,
        TRIM({_v('00100040')})  AS patient_sex,

        -- Acquisition parameters
        {_v('00180050', 0, 'double')}  AS slice_thickness,
        {_v('00180088', 0, 'double')}  AS spacing_between_slices,
        {_v('00180060', 0, 'double')}  AS kvp,
        {_v('00180080', 0, 'double')}  AS repetition_time,
        {_v('00180081', 0, 'double')}  AS echo_time,
        {_v('00181314', 0, 'double')}  AS flip_angle,
        {_v('00180087', 0, 'double')}  AS magnetic_field_strength,

        -- Multi-value: named components
        {_v('00280030', 0, 'double')}  AS pixel_spacing_row,
        {_v('00280030', 1, 'double')}  AS pixel_spacing_col,
        {_v('00200032', 0, 'double')}  AS image_position_x,
        {_v('00200032', 1, 'double')}  AS image_position_y,
        {_v('00200032', 2, 'double')}  AS image_position_z,

        -- Image
        {_arr('00080008')}             AS image_type,
        TRIM({_v('00280004')})         AS photometric_interpretation,
        {_v('00280010', 0, 'int')}     AS rows_px,
        {_v('00280011', 0, 'int')}     AS columns_px,

        _ingestion_timestamp
    FROM {BRONZE_TABLE}
    """)


# ---------------------------------------------------------------------------
# Series-level silver with config-driven series_type classification
# ---------------------------------------------------------------------------

@dp.table(
    name="dicom_series",
    comment="Curated series-level DICOM metadata with config-driven series_type "
            "classification. Aggregated from instance-level bronze.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
    cluster_by=["modality", "study_instance_uid"],
)
def dicom_series():
    return spark.sql(f"""
    WITH series_agg AS (
        SELECT
            study_instance_uid,
            series_instance_uid,
            first_value(modality, true)                   AS modality,
            first_value(manufacturer, true)               AS manufacturer,
            first_value(manufacturer_model_name, true)    AS manufacturer_model_name,
            first_value(station_name, true)               AS station_name,
            first_value(body_part_examined, true)          AS body_part_examined,
            first_value(protocol_name, true)              AS protocol_name,
            first_value(study_date, true)                 AS study_date,
            first_value(series_date, true)                AS series_date,
            first_value(acquisition_date, true)           AS acquisition_date,
            first_value(patient_age, true)                AS patient_age,
            first_value(patient_sex, true)                AS patient_sex,
            first_value(slice_thickness, true)            AS slice_thickness,
            first_value(spacing_between_slices, true)     AS spacing_between_slices,
            first_value(kvp, true)                        AS kvp,
            first_value(repetition_time, true)            AS repetition_time,
            first_value(echo_time, true)                  AS echo_time,
            first_value(flip_angle, true)                 AS flip_angle,
            first_value(magnetic_field_strength, true)    AS magnetic_field_strength,
            first_value(pixel_spacing_row, true)          AS pixel_spacing_row,
            first_value(pixel_spacing_col, true)          AS pixel_spacing_col,
            first_value(image_position_x, true)           AS image_position_x,
            first_value(image_position_y, true)           AS image_position_y,
            first_value(image_position_z, true)           AS image_position_z,
            first_value(image_type, true)                 AS image_type,
            first_value(photometric_interpretation, true) AS photometric_interpretation,
            first_value(rows_px, true)                    AS rows_px,
            first_value(columns_px, true)                 AS columns_px,
            COUNT(*)                                      AS instance_count,
            MAX(_ingestion_timestamp)                     AS _last_ingestion_timestamp
        FROM bronze_dicom_extracted
        GROUP BY study_instance_uid, series_instance_uid
    ),

    with_signals AS (
        SELECT *,
            CASE WHEN size(image_type) >= 3 THEN UPPER(image_type[2]) END
                AS image_type_class
        FROM series_agg
    ),

    classified AS (
        SELECT
            s.series_instance_uid,
            MIN_BY(r.series_type, r.priority) AS series_type
        FROM with_signals s
        JOIN {RULES_TABLE} r
          ON (r.signal_source = 'image_type_class' AND r.match_operator = 'equals'
              AND s.image_type_class = r.match_value)
          OR (r.signal_source = 'image_type_class' AND r.match_operator = 'in'
              AND array_contains(split(r.match_value, ','), s.image_type_class))
          OR (r.signal_source = 'series_description' AND r.match_operator = 'like'
              AND UPPER(s.protocol_name) LIKE r.match_value)
          OR (r.signal_source = 'modality' AND r.match_operator = 'in'
              AND array_contains(split(r.match_value, ','), s.modality))
          OR (r.signal_source = 'modality' AND r.match_operator = 'not_in'
              AND NOT array_contains(split(r.match_value, ','), s.modality))
          OR (r.signal_source = 'image_count_thickness' AND r.match_operator = 'lt_and'
              AND s.instance_count <= CAST(split(r.match_value, '[|]')[0] AS INT)
              AND s.slice_thickness > CAST(split(r.match_value, '[|]')[1] AS DOUBLE))
        GROUP BY s.series_instance_uid
    )

    SELECT
        s.study_instance_uid,
        s.series_instance_uid,
        s.modality,
        s.manufacturer,
        s.manufacturer_model_name,
        s.station_name,
        s.body_part_examined,
        s.protocol_name,
        s.study_date,
        s.series_date,
        s.acquisition_date,
        s.patient_age,
        s.patient_sex,
        s.slice_thickness,
        s.spacing_between_slices,
        s.kvp,
        s.repetition_time,
        s.echo_time,
        s.flip_angle,
        s.magnetic_field_strength,
        s.pixel_spacing_row,
        s.pixel_spacing_col,
        s.image_position_x,
        s.image_position_y,
        s.image_position_z,
        s.image_type,
        s.photometric_interpretation,
        s.rows_px,
        s.columns_px,
        s.instance_count,
        s._last_ingestion_timestamp,
        COALESCE(c.series_type, 'other') AS series_type
    FROM with_signals s
    LEFT JOIN classified c ON s.series_instance_uid = c.series_instance_uid
    """)


# ---------------------------------------------------------------------------
# Data quality expectations
# ---------------------------------------------------------------------------

@dp.expect("modality_is_series_constant",
            "modality_distinct_count <= 1")
@dp.expect("manufacturer_is_series_constant",
            "manufacturer_distinct_count <= 1")
@dp.expect("slice_thickness_is_series_constant_or_null",
            "slice_thickness_distinct_count <= 1")
@dp.temporary_view(
    name="series_constant_violations",
    comment="Surfaces series where supposedly-constant fields have multiple "
            "distinct values. Warn-only; pipeline does not fail."
)
def series_constant_violations():
    return spark.sql("""
    SELECT study_instance_uid, series_instance_uid,
           COUNT(DISTINCT modality)        AS modality_distinct_count,
           COUNT(DISTINCT manufacturer)    AS manufacturer_distinct_count,
           COUNT(DISTINCT slice_thickness) AS slice_thickness_distinct_count
    FROM bronze_dicom_extracted
    GROUP BY study_instance_uid, series_instance_uid
    HAVING COUNT(DISTINCT modality) > 1
        OR COUNT(DISTINCT manufacturer) > 1
        OR COUNT(DISTINCT slice_thickness) > 1
    """)
