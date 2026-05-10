# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Create Views
# MAGIC
# MAGIC Creates two views over Lima's bronze table:
# MAGIC
# MAGIC - **`bronze.dicom_tags_long`** — EAV exploration view. One row per
# MAGIC   `(study_uid, series_uid, sop_uid, tag_id, tag_keyword, value)`. Used by the
# MAGIC   `dicom-analytics` skill for "what tags exist," value distribution, coverage
# MAGIC   discovery, and cross-modality comparisons. Aggregated to series grain to
# MAGIC   keep cardinality manageable.
# MAGIC
# MAGIC The curated table `silver.dicom_series` is created by the SDP pipeline in
# MAGIC `pipelines/dicom_silver.py`, not in this notebook.
# MAGIC
# MAGIC ## Inputs
# MAGIC - `<catalog>.<bronze_schema>.<bronze_table>` (Lima's existing bronze, parameterized)
# MAGIC - `reference/ps36_attributes.json` (PS3.6 keyword lookup)
# MAGIC
# MAGIC ## Outputs
# MAGIC - `<catalog>.bronze.dicom_tags_long` (view)
# MAGIC
# MAGIC ## Run
# MAGIC Re-run any time you want to refresh the keyword lookup table from a newer
# MAGIC PS3.6 snapshot. The view itself is logical — no materialization, picks up
# MAGIC bronze updates automatically.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

import yaml
from pathlib import Path

# Load workshop config (3 values: catalog, schema, bronze_table)
config_path = Path("../config/workshop.yml")
with open(config_path) as f:
    config = yaml.safe_load(f)

CATALOG = config["catalog"]
BRONZE_SCHEMA = config.get("bronze_schema", "bronze")
SILVER_SCHEMA = config.get("silver_schema", "silver")
BRONZE_TABLE = config["bronze_table"]
PAYLOAD_COLUMN = config.get("payload_column", "dicom_payload")

print(f"Catalog: {CATALOG}")
print(f"Bronze:  {CATALOG}.{BRONZE_SCHEMA}.{BRONZE_TABLE}")
print(f"Payload: {PAYLOAD_COLUMN}")

# Detect payload column type (VARIANT vs STRING) — mirrors dicom_silver.py logic.
# STRING payloads use get_json_object / from_json; VARIANT payloads need to_json()
# wrapper or colon-path syntax. Fail fast if the column doesn't exist.
_bronze_schema = spark.table(f"{CATALOG}.{BRONZE_SCHEMA}.{BRONZE_TABLE}").schema
_payload_field = next((f for f in _bronze_schema if f.name == PAYLOAD_COLUMN), None)
if _payload_field is None:
    raise ValueError(
        f"Payload column '{PAYLOAD_COLUMN}' not found in {CATALOG}.{BRONZE_SCHEMA}.{BRONZE_TABLE}. "
        f"Available columns: {[f.name for f in _bronze_schema]}. "
        f"Set 'payload_column' in config/workshop.yml to the correct column."
    )
PAYLOAD_IS_VARIANT = _payload_field.dataType.typeName().lower() == "variant"
print(f"Payload type: {'VARIANT' if PAYLOAD_IS_VARIANT else 'STRING'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load PS3.6 keyword lookup
# MAGIC
# MAGIC The PS3.6 dictionary maps DICOM hex tag IDs (e.g. `(0008,0060)`) to keywords
# MAGIC (`Modality`) and VR codes. Used by the EAV explorer view to give users readable
# MAGIC tag names instead of hex strings.

# COMMAND ----------

import json

ps36_path = Path("../reference/ps36_attributes.json")
with open(ps36_path) as f:
    ps36_attrs = json.load(f)

# innolitics format: list of dicts with 'tag', 'name', 'keyword', 'valueRepresentation'
# Tag format like '(0008,0060)' -> normalize to '00080060' (8-char uppercase hex)
def normalize_tag_id(tag_str: str) -> str:
    return tag_str.replace("(", "").replace(")", "").replace(",", "").upper()

lookup_rows = [
    {
        "tag_id": normalize_tag_id(a["tag"]),
        "tag_keyword": a["keyword"],
        "tag_name": a["name"],
        "vr": a["valueRepresentation"],
    }
    for a in ps36_attrs
    if a.get("keyword") and a.get("tag")
]

lookup_df = spark.createDataFrame(lookup_rows)
lookup_df.createOrReplaceTempView("_ps36_lookup")
print(f"Loaded {lookup_df.count()} PS3.6 attributes for keyword lookup")

# Persist to a small reference table so the view definition can JOIN cleanly without
# depending on this notebook re-running every session
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.reference")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reference.ps36_keyword_lookup")
(
    lookup_df.write
    .mode("overwrite")
    .saveAsTable(f"{CATALOG}.reference.ps36_keyword_lookup")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the EAV exploration view
# MAGIC
# MAGIC Pattern: explode the JSON payload's top-level keys (DICOM hex tag IDs), then
# MAGIC for each, extract `Value[0]` as a STRING. JOIN to the keyword lookup so users
# MAGIC can query by readable tag name (`SliceThickness`) rather than hex (`00180050`).
# MAGIC
# MAGIC We aggregate to series grain by taking the first non-null value per
# MAGIC `(study_uid, series_uid, tag_id)`. This matches silver's series-level grain
# MAGIC and keeps the view's row count manageable (vs ~700 × instance_count rows).
# MAGIC
# MAGIC ### Notes
# MAGIC - This view is logical — picks up bronze changes automatically.
# MAGIC - Sequence (VR=SQ) tag values are returned as nested JSON strings; users typically
# MAGIC   query bronze directly for sequence sub-fields, not via this view.
# MAGIC - Private/vendor tags (odd group IDs) appear here too — they don't have keywords
# MAGIC   in PS3.6, so `tag_keyword` will be NULL and `tag_name` will fall back to the
# MAGIC   hex ID. Useful for surfacing "what private tags do we have."

# COMMAND ----------

# Build type-adaptive SQL expressions based on payload column type.
# VARIANT columns need colon-path syntax for identifiers and to_json() wrapper
# for from_json(); STRING columns use get_json_object() and direct from_json().
if PAYLOAD_IS_VARIANT:
    _id_study  = f"{PAYLOAD_COLUMN}:`0020000D`.Value[0]::string"
    _id_series = f"{PAYLOAD_COLUMN}:`0020000E`.Value[0]::string"
    _id_sop    = f"{PAYLOAD_COLUMN}:`00080018`.Value[0]::string"
    _from_json_expr = f"from_json(to_json({PAYLOAD_COLUMN}), 'map<string, struct<vr: string, Value: array<string>>>')"
else:
    _id_study  = f"get_json_object({PAYLOAD_COLUMN}, '$.0020000D.Value[0]')"
    _id_series = f"get_json_object({PAYLOAD_COLUMN}, '$.0020000E.Value[0]')"
    _id_sop    = f"get_json_object({PAYLOAD_COLUMN}, '$.00080018.Value[0]')"
    _from_json_expr = f"from_json({PAYLOAD_COLUMN}, 'map<string, struct<vr: string, Value: array<string>>>')"

view_ddl = f"""
CREATE OR REPLACE VIEW {CATALOG}.{BRONZE_SCHEMA}.dicom_tags_long AS
WITH parsed AS (
  SELECT
    -- Extracted identifiers (type-adaptive: VARIANT uses colon-path, STRING uses get_json_object)
    {_id_study} AS study_uid,
    {_id_series} AS series_uid,
    {_id_sop} AS sop_uid,

    -- Explode top-level keys of the payload (each is a DICOM hex tag ID)
    explode(
      {_from_json_expr}
    ) AS (tag_id, tag_struct)
  FROM {CATALOG}.{BRONZE_SCHEMA}.{BRONZE_TABLE}
),
per_instance AS (
  SELECT
    study_uid, series_uid, sop_uid,
    upper(tag_id) AS tag_id,
    tag_struct.vr AS vr,
    -- For multi-value tags, take first; users can query bronze for full multi-value access
    element_at(tag_struct.Value, 1) AS value
  FROM parsed
  WHERE tag_struct.Value IS NOT NULL
    AND size(tag_struct.Value) > 0
),
per_series AS (
  -- Aggregate to series grain to keep cardinality reasonable for exploration
  SELECT
    study_uid, series_uid,
    tag_id,
    any_value(vr) AS vr,
    -- First non-null value across the series's instances
    first(value, ignorenulls => true) AS value
  FROM per_instance
  WHERE value IS NOT NULL
  GROUP BY study_uid, series_uid, tag_id
)
SELECT
  s.study_uid,
  s.series_uid,
  s.tag_id,
  COALESCE(k.tag_keyword, s.tag_id) AS tag_keyword,
  COALESCE(k.tag_name, '(unknown — possibly private/vendor tag)') AS tag_name,
  s.vr,
  s.value
FROM per_series s
LEFT JOIN {CATALOG}.reference.ps36_keyword_lookup k
  ON s.tag_id = k.tag_id
"""

spark.sql(view_ddl)
print(f"Created view: {CATALOG}.{BRONZE_SCHEMA}.dicom_tags_long")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Smoke test
# MAGIC
# MAGIC Verify the EAV view returns sensible data. Three checks:

# COMMAND ----------

print("Check 1: total rows in EAV view (should be roughly tag_count × series_count)")
n = spark.table(f"{CATALOG}.{BRONZE_SCHEMA}.dicom_tags_long").count()
print(f"  EAV rows: {n:,}")

# COMMAND ----------

print("Check 2: top tags by coverage")
display(
    spark.sql(f"""
        SELECT
          tag_keyword,
          tag_id,
          COUNT(DISTINCT (study_uid, series_uid)) AS series_with_value
        FROM {CATALOG}.{BRONZE_SCHEMA}.dicom_tags_long
        GROUP BY 1, 2
        ORDER BY series_with_value DESC
        LIMIT 20
    """)
)

# COMMAND ----------

print("Check 3: SliceThickness value distribution (sanity check on extraction)")
display(
    spark.sql(f"""
        SELECT
          value AS slice_thickness_raw,
          COUNT(*) AS n_series
        FROM {CATALOG}.{BRONZE_SCHEMA}.dicom_tags_long
        WHERE tag_keyword = 'SliceThickness'
        GROUP BY 1
        ORDER BY n_series DESC
        LIMIT 20
    """)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Done
# MAGIC
# MAGIC The EAV explorer view is ready. The `dicom-analytics` skill knows to route
# MAGIC exploration questions ("what tags exist," value distribution, coverage) to this
# MAGIC view automatically.
# MAGIC
# MAGIC Next step: run the silver pipeline (`pipelines/dicom_silver.py`) via
# MAGIC `notebooks/20_run_silver_pipeline.py`, which materializes the curated columnar
# MAGIC `silver.dicom_series` table.
