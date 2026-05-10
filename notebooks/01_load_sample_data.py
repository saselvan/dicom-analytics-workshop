# Databricks notebook source

# MAGIC %md
# MAGIC # 01 — Load DICOMweb Data (Bronze)
# MAGIC
# MAGIC Two loading modes — pick via the `data_source` widget:
# MAGIC
# MAGIC | Mode | Widget | Instances | Tags/instance | Use when |
# MAGIC |------|--------|-----------|---------------|----------|
# MAGIC | **A — Synthetic** | `SYNTHETIC` | ~5,800 | ~25 (clean) | Pipeline testing, no credentials needed |
# MAGIC | **B — Real IDC** | `JSONL` | ~8,700 | 87–302 (private vendor tags) | **Workshop demo**, real-world messiness |
# MAGIC
# MAGIC **Mode B** reads `.jsonl` files downloaded from the IDC Google Healthcare API (DICOMweb
# MAGIC WADO-RS). Includes private tag groups from Philips, GE, Siemens, and UCSF research.
# MAGIC Upload files to a Volume first (see Mode B cell for instructions).
# MAGIC
# MAGIC Both modes produce the same bronze table schema: `study_instance_uid`, `series_instance_uid`,
# MAGIC `sop_instance_uid`, `dicom_payload` (VARIANT or STRING), `_ingestion_timestamp`.

# COMMAND ----------

# Widget parameters
dbutils.widgets.text("catalog", "main", "Target catalog")
dbutils.widgets.text("schema", "dicom_demo", "Target schema")
dbutils.widgets.text("bronze_table_name", "dicom_raw", "Bronze table name")
dbutils.widgets.dropdown("payload_format", "VARIANT", ["VARIANT", "STRING"], "Payload column type")
dbutils.widgets.dropdown("data_source", "SYNTHETIC", ["SYNTHETIC", "JSONL"], "Data source")
dbutils.widgets.text("jsonl_volume_path", "/Volumes/main/dicom_demo/landing/dicomweb-bronze", "JSONL files path (Mode B only)")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
bronze_table_name = dbutils.widgets.get("bronze_table_name")
payload_format = dbutils.widgets.get("payload_format")
data_source = dbutils.widgets.get("data_source")
jsonl_volume_path = dbutils.widgets.get("jsonl_volume_path")

full_table_name = f"{catalog}.{schema}.{bronze_table_name}"
print(f"Target table: {full_table_name}")
print(f"Data source:  {data_source} | Payload format: {payload_format}")
if data_source == "JSONL":
    print(f"JSONL path:   {jsonl_volume_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Mode A: Generate Synthetic DICOMweb Instances
# MAGIC
# MAGIC **Skip this cell if `data_source` = JSONL.** Generates ~5,800 instances across ~60 studies
# MAGIC with realistic modality, manufacturer, and protocol distributions. All JSON payloads conform
# MAGIC to DICOMweb PS3.18 format. Includes intentional near-duplicate manufacturer names
# MAGIC (GE MEDICAL SYSTEMS vs GE Healthcare) and ~5% LOCALIZER/SCOUT series for testing.

# COMMAND ----------

import json
import random

random.seed(42)

# This cell always runs (generation is fast, pure Python, ~2 seconds).
# When data_source = JSONL, the generated data is simply ignored at load time.

# ---------------------------------------------------------------------------
# Helper: build a DICOMweb tag entry
# ---------------------------------------------------------------------------
def tag(vr, value):
    """Build a DICOMweb tag entry conforming to PS3.18 JSON model."""
    if value is None:
        return {"vr": vr}
    if not isinstance(value, list):
        value = [value]
    return {"vr": vr, "Value": value}


def generate_uid():
    """Generate a realistic DICOM UID."""
    return f"1.2.840.113619.2.55.3.{random.randint(1000000000, 9999999999)}.{random.randint(1000000000, 9999999999)}"


# ---------------------------------------------------------------------------
# Configuration tables
# ---------------------------------------------------------------------------

MANUFACTURERS = {
    "GE": ["GE MEDICAL SYSTEMS", "GE Healthcare"],
    "SIEMENS": ["SIEMENS"],
    "PHILIPS": ["PHILIPS"],
    "CANON": ["Canon Medical Systems"],
}

MODELS_BY_MANUFACTURER = {
    "GE MEDICAL SYSTEMS": ["LightSpeed VCT", "Revolution CT", "Optima CT660", "Discovery MR750", "SIGNA Pioneer", "Discovery XR656"],
    "GE Healthcare": ["LightSpeed VCT", "Revolution CT", "Optima CT660", "Discovery MR750", "SIGNA Pioneer", "Discovery XR656"],
    "SIEMENS": ["SOMATOM Force", "SOMATOM Definition AS", "Magnetom Prisma", "Magnetom Vida", "Ysio Max"],
    "PHILIPS": ["Brilliance iCT", "Ingenia", "Ingenia Elition X", "DigitalDiagnost"],
    "Canon Medical Systems": ["Aquilion ONE", "Vantage Orian", "CXDI-710C Wireless"],
}

# Filter models by modality appropriateness
CT_MODELS = {
    "GE MEDICAL SYSTEMS": ["LightSpeed VCT", "Revolution CT", "Optima CT660"],
    "GE Healthcare": ["LightSpeed VCT", "Revolution CT", "Optima CT660"],
    "SIEMENS": ["SOMATOM Force", "SOMATOM Definition AS"],
    "PHILIPS": ["Brilliance iCT"],
    "Canon Medical Systems": ["Aquilion ONE"],
}

MR_MODELS = {
    "GE MEDICAL SYSTEMS": ["Discovery MR750", "SIGNA Pioneer"],
    "GE Healthcare": ["Discovery MR750", "SIGNA Pioneer"],
    "SIEMENS": ["Magnetom Prisma", "Magnetom Vida"],
    "PHILIPS": ["Ingenia", "Ingenia Elition X"],
    "Canon Medical Systems": ["Vantage Orian"],
}

DX_MODELS = {
    "GE MEDICAL SYSTEMS": ["Discovery XR656"],
    "GE Healthcare": ["Discovery XR656"],
    "SIEMENS": ["Ysio Max"],
    "PHILIPS": ["DigitalDiagnost"],
    "Canon Medical Systems": ["CXDI-710C Wireless"],
}

US_MODELS = {
    "GE MEDICAL SYSTEMS": ["LOGIQ E10", "Voluson E10"],
    "GE Healthcare": ["LOGIQ E10", "Voluson E10"],
    "SIEMENS": ["ACUSON Sequoia", "ACUSON Juniper"],
    "PHILIPS": ["EPIQ Elite", "Affiniti 70"],
    "Canon Medical Systems": ["Aplio i800"],
}

STATION_NAMES = {
    "CT": ["CT01", "CT02", "CT03", "CT_ED", "CT_LUNG"],
    "MR": ["MR_MAIN", "MR_BREAST", "MR01", "MR02", "MR_NEURO"],
    "DX": ["DX_ER1", "DX_RAD2", "DX_ORTHO"],
    "US": ["US_MAIN", "US_OB", "US_CARDIAC", "US_ED"],
}

BODY_PARTS = ["CHEST", "ABDOMEN", "HEAD", "PELVIS", "KNEE", "SPINE", "BREAST", "SHOULDER", "HEART"]

PROTOCOLS = {
    "CT": {
        "CHEST": ["CT CHEST W CONTRAST", "CT CHEST WO CONTRAST", "CT ANGIO CHEST"],
        "ABDOMEN": ["CT ABDOMEN PELVIS WO", "CT ABDOMEN PELVIS W CONTRAST", "CT ABDOMEN W CONTRAST"],
        "HEAD": ["CT HEAD WO CONTRAST", "CT HEAD W CONTRAST", "CT HEAD W AND WO"],
        "PELVIS": ["CT ABDOMEN PELVIS WO", "CT ABDOMEN PELVIS W CONTRAST"],
        "KNEE": ["CT KNEE WO CONTRAST"],
        "SPINE": ["CT SPINE CERVICAL WO", "CT SPINE LUMBAR WO"],
        "BREAST": ["CT CHEST W CONTRAST"],
        "SHOULDER": ["CT SHOULDER WO CONTRAST"],
        "HEART": ["CT CARDIAC CTA", "CT CALCIUM SCORING"],
    },
    "MR": {
        "CHEST": ["MR CHEST W AND WO"],
        "ABDOMEN": ["MR ABDOMEN W AND WO", "MR MRCP"],
        "HEAD": ["MR BRAIN W AND WO", "MR BRAIN WO CONTRAST"],
        "PELVIS": ["MR PELVIS W AND WO"],
        "KNEE": ["MR KNEE WO CONTRAST"],
        "SPINE": ["MR SPINE CERVICAL", "MR SPINE LUMBAR", "MR SPINE THORACIC"],
        "BREAST": ["MR BREAST DYNAMIC", "MR BREAST W AND WO"],
        "SHOULDER": ["MR SHOULDER WO CONTRAST"],
        "HEART": ["MR CARDIAC FUNCTION", "MR CARDIAC STRESS"],
    },
    "DX": {
        "CHEST": ["CHEST PA AND LATERAL", "CHEST AP PORTABLE"],
        "ABDOMEN": ["ABDOMEN AP SUPINE", "ABDOMEN AP UPRIGHT"],
        "HEAD": ["SKULL 2 VIEW"],
        "PELVIS": ["PELVIS AP"],
        "KNEE": ["KNEE 3 VIEW", "KNEE 2 VIEW"],
        "SPINE": ["SPINE CERVICAL 3 VIEW", "SPINE LUMBAR 3 VIEW"],
        "BREAST": ["CHEST PA AND LATERAL"],
        "SHOULDER": ["SHOULDER 2 VIEW", "SHOULDER 3 VIEW"],
        "HEART": ["CHEST PA AND LATERAL"],
    },
    "US": {
        "CHEST": ["US CHEST"],
        "ABDOMEN": ["US ABDOMEN COMPLETE", "US ABDOMEN LIMITED", "US RUQ"],
        "HEAD": ["US CAROTID DUPLEX"],
        "PELVIS": ["US PELVIS COMPLETE", "US PELVIS TRANSVAGINAL"],
        "KNEE": ["US KNEE"],
        "SPINE": ["US SPINE"],
        "BREAST": ["US BREAST RIGHT", "US BREAST LEFT", "US BREAST BILATERAL"],
        "SHOULDER": ["US SHOULDER"],
        "HEART": ["US ECHO COMPLETE", "US ECHO LIMITED"],
    },
}

CONTRAST_AGENTS = ["Omnipaque 350", "Isovue 370", "Visipaque 320"]

# ---------------------------------------------------------------------------
# Generate study-level assignments
# ---------------------------------------------------------------------------

# Modality distribution: CT 30%, MR 30%, DX 15%, US 25%
n_studies = 60
modality_pool = ["CT"] * 18 + ["MR"] * 18 + ["DX"] * 9 + ["US"] * 15
random.shuffle(modality_pool)

studies = []
for i in range(n_studies):
    modality = modality_pool[i]

    study_uid = generate_uid()

    # Study date: 2024-01-01 to 2025-12-31 (730 days)
    day_offset = random.randint(0, 729)
    base_year = 2024
    from datetime import date, timedelta
    study_date_obj = date(base_year, 1, 1) + timedelta(days=day_offset)
    study_date = study_date_obj.strftime("%Y%m%d")

    # Study time: 06:00-22:00
    hour = random.randint(6, 21)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    study_time = f"{hour:02d}{minute:02d}{second:02d}.000000"

    patient_sex = random.choices(["M", "F", "O"], weights=[47.5, 47.5, 5.0])[0]
    patient_age = random.randint(20, 90)
    body_part = random.choice(BODY_PARTS)

    # Pick manufacturer (weighted to reflect market share)
    all_mfrs = []
    for group_names in MANUFACTURERS.values():
        all_mfrs.extend(group_names)
    # Weighted: GE variants 35%, Siemens 30%, Philips 25%, Canon 10%
    mfr_weights = [17.5, 17.5, 30.0, 25.0, 10.0]  # GE MED, GE HC, SIEMENS, PHILIPS, Canon
    manufacturer = random.choices(all_mfrs, weights=mfr_weights)[0]

    # Pick model appropriate to modality
    if modality == "CT":
        model_pool = CT_MODELS.get(manufacturer, ["Unknown"])
    elif modality == "MR":
        model_pool = MR_MODELS.get(manufacturer, ["Unknown"])
    elif modality == "US":
        model_pool = US_MODELS.get(manufacturer, ["Unknown"])
    else:
        model_pool = DX_MODELS.get(manufacturer, ["Unknown"])
    model_name = random.choice(model_pool)

    station_name = random.choice(STATION_NAMES[modality])

    # Number of series per study: 3-5
    n_series_in_study = random.randint(3, 5)

    studies.append({
        "study_uid": study_uid,
        "modality": modality,
        "study_date": study_date,
        "study_date_obj": study_date_obj,
        "study_time": study_time,
        "patient_sex": patient_sex,
        "patient_age": patient_age,
        "body_part": body_part,
        "manufacturer": manufacturer,
        "model_name": model_name,
        "station_name": station_name,
        "n_series": n_series_in_study,
    })

# ---------------------------------------------------------------------------
# Generate series and instances
# ---------------------------------------------------------------------------
instances = []
n_series_total = 0

for study in studies:
    modality = study["modality"]
    study_uid = study["study_uid"]
    body_part = study["body_part"]

    for s_idx in range(study["n_series"]):
        series_uid = generate_uid()
        n_series_total += 1

        # Series date: same as study or +0-2 days
        series_date_obj = study["study_date_obj"] + timedelta(days=random.randint(0, 2))
        series_date = series_date_obj.strftime("%Y%m%d")
        acquisition_date = series_date

        # Series/acquisition time
        h = random.randint(6, 21)
        m = random.randint(0, 59)
        s = random.randint(0, 59)
        series_time = f"{h:02d}{m:02d}{s:02d}.000000"
        acquisition_time = f"{h:02d}{m + random.randint(0, min(59 - m, 5)):02d}{random.randint(0, 59):02d}.000000"

        # Instances per series: varies by modality
        if modality == "DX":
            n_instances = random.randint(1, 4)
        elif modality == "US":
            n_instances = random.randint(5, 30)
        else:
            n_instances = random.randint(10, 50)

        # Protocol
        protocol_options = PROTOCOLS[modality].get(body_part, PROTOCOLS[modality]["CHEST"])
        protocol_name = random.choice(protocol_options)

        # ImageType: ~5% of series are LOCALIZER/SCOUT
        is_localizer = random.random() < 0.05
        if is_localizer:
            if modality == "CT":
                image_type = ["DERIVED", "SECONDARY", "LOCALIZER"]
            else:
                image_type = ["ORIGINAL", "PRIMARY", "SCOUT"]
        else:
            image_type = ["ORIGINAL", "PRIMARY", "AXIAL"]

        # Photometric interpretation
        photometric = "MONOCHROME1" if random.random() < 0.05 else "MONOCHROME2"

        # Modality-specific parameters
        slice_thickness = None
        kvp = None
        magnetic_field = None
        repetition_time = None
        echo_time = None
        ctdi_vol = None
        exposure_time = None
        tube_current = None
        contrast_agent = None
        rows = 512
        columns = 512
        pixel_spacing = [f"{random.choice([0.488, 0.500, 0.625, 0.703, 0.750]):.3f}"] * 2

        if modality == "CT":
            slice_thickness = str(round(random.choice([0.5, 0.625, 1.0, 1.25, 2.0, 2.5, 3.0, 5.0]), 3))
            kvp = str(random.choices([80, 100, 120, 140], weights=[10, 20, 60, 10])[0])
            ctdi_vol = round(random.uniform(1.0, 30.0), 2)
            exposure_time = str(random.randint(5, 2000))
            tube_current = str(random.randint(50, 800))
            # ~30% get contrast
            if random.random() < 0.30:
                contrast_agent = random.choice(CONTRAST_AGENTS)
            rows = 512
            columns = 512

        elif modality == "MR":
            slice_thickness = str(round(random.uniform(1.0, 6.0), 1))
            magnetic_field = random.choices(["1.5", "3.0"], weights=[60, 40])[0]
            repetition_time = str(round(random.uniform(5.0, 10000.0), 1))
            echo_time = str(round(random.uniform(1.0, 200.0), 1))
            rows = 512
            columns = 512
            pixel_spacing = [f"{random.choice([0.400, 0.469, 0.500, 0.625, 0.750, 1.000]):.3f}"] * 2

        elif modality == "DX":
            kvp = str(random.randint(50, 120))
            exposure_time = str(random.randint(5, 200))
            tube_current = str(random.randint(100, 800))
            rows = random.choice([2048, 3072])
            columns = random.choice([2048, 2500, 3072])
            pixel_spacing = [f"{random.choice([0.139, 0.143, 0.148, 0.175]):.3f}"] * 2

        elif modality == "US":
            # US-specific parameters
            mechanical_index = round(random.uniform(0.1, 1.9), 2)
            thermal_index = round(random.uniform(0.1, 2.5), 2)
            transducer_type = random.choice(["SECTOR", "LINEAR", "CURVED LINEAR", "PHASED"])
            transducer_freq = str(round(random.choice([2.0, 3.5, 5.0, 7.5, 10.0, 12.0, 15.0]), 1))
            rows = random.choice([480, 600, 768, 1024])
            columns = random.choice([640, 800, 1024])
            pixel_spacing = [f"{random.choice([0.200, 0.300, 0.400, 0.500]):.3f}"] * 2

        # Build the common (series-level) tags
        base_z = round(random.uniform(-200.0, 200.0), 1)

        for inst_idx in range(n_instances):
            sop_uid = generate_uid()

            # ImagePositionPatient — z increments per instance
            if slice_thickness is not None:
                z = base_z + inst_idx * float(slice_thickness)
            else:
                z = base_z + inst_idx * 1.0
            image_position = ["-125.0", "200.5", f"{z:.1f}"]

            # Build the DICOMweb JSON object
            dcm = {}
            dcm["00080018"] = tag("UI", sop_uid)
            dcm["00080020"] = tag("DA", study["study_date"])
            dcm["00080021"] = tag("DA", series_date)
            dcm["00080022"] = tag("DA", acquisition_date)
            dcm["00080030"] = tag("TM", study["study_time"])
            dcm["00080031"] = tag("TM", series_time)
            dcm["00080032"] = tag("TM", acquisition_time)
            dcm["00080060"] = tag("CS", modality)
            dcm["00080070"] = tag("LO", study["manufacturer"])
            dcm["00081090"] = tag("LO", study["model_name"])
            dcm["00081010"] = tag("SH", study["station_name"])
            dcm["00100040"] = tag("CS", study["patient_sex"])
            dcm["00101010"] = tag("AS", f"{study['patient_age']:03d}Y")
            dcm["00180015"] = tag("CS", body_part)

            # Conditional tags — only include when present
            if slice_thickness is not None:
                dcm["00180050"] = tag("DS", slice_thickness)
            if kvp is not None:
                dcm["00180060"] = tag("DS", kvp)
            if magnetic_field is not None:
                dcm["00180087"] = tag("DS", magnetic_field)
            if repetition_time is not None:
                dcm["00180080"] = tag("DS", repetition_time)
            if echo_time is not None:
                dcm["00180081"] = tag("DS", echo_time)

            dcm["00181030"] = tag("LO", protocol_name)

            if ctdi_vol is not None:
                dcm["00189345"] = tag("FD", ctdi_vol)  # FD = actual float
            if exposure_time is not None:
                dcm["00181150"] = tag("IS", exposure_time)  # IS = string integer
            if tube_current is not None:
                dcm["00181151"] = tag("IS", tube_current)
            if contrast_agent is not None:
                dcm["00180010"] = tag("LO", contrast_agent)

            # US-specific DICOM tags
            if modality == "US":
                dcm["00185022"] = tag("DS", str(mechanical_index))    # MechanicalIndex
                dcm["00185024"] = tag("DS", str(thermal_index))        # ThermalIndex
                dcm["00186031"] = tag("CS", transducer_type)           # TransducerType
                dcm["00184009"] = tag("DS", transducer_freq)           # TransducerFrequency (MHz)

            dcm["0020000D"] = tag("UI", study_uid)
            dcm["0020000E"] = tag("UI", series_uid)
            dcm["00200032"] = tag("DS", image_position)
            dcm["00280030"] = tag("DS", pixel_spacing)
            dcm["00080008"] = tag("CS", image_type)
            dcm["00280004"] = tag("CS", photometric)
            dcm["00280010"] = tag("US", rows)      # US = actual integer
            dcm["00280011"] = tag("US", columns)

            json_str = json.dumps(dcm, separators=(",", ":"))
            instances.append((study_uid, series_uid, sop_uid, json_str))

n_studies_actual = len(studies)
print(f"Generated {len(instances)} synthetic DICOMweb instances ({n_studies_actual} studies, {n_series_total} series)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Mode B: Load Real IDC DICOMweb Data from JSONL
# MAGIC
# MAGIC **Skip this cell if `data_source` = SYNTHETIC.** Reads `.jsonl` files from a Unity Catalog
# MAGIC Volume. Each line is one DICOMweb instance (raw JSON from IDC Google Healthcare API) with
# MAGIC 87–302 tags including private vendor groups (Philips, GE, Siemens, UCSF research).
# MAGIC
# MAGIC **Pre-flight:** Upload the JSONL files from `~/Downloads/dicomweb-bronze/` to the Volume:
# MAGIC ```
# MAGIC databricks fs cp -r ~/Downloads/dicomweb-bronze/ dbfs:/Volumes/main/dicom_demo/landing/dicomweb-bronze/
# MAGIC ```
# MAGIC Or use the workspace UI: Catalog → Volumes → Upload files.

# COMMAND ----------

# Load from JSONL files (real IDC data — 87-302 tags, private vendor groups)
# This cell is skipped when data_source = SYNTHETIC

if data_source == "JSONL":
    import json as _json

    # Read all .jsonl files from the Volume path
    raw_df = spark.read.text(f"{jsonl_volume_path}/*.jsonl")
    print(f"Read {raw_df.count():,} lines from {jsonl_volume_path}/*.jsonl")

    # Each line is a full DICOMweb JSON object. Extract the three UIDs for
    # convenience columns, keep the full JSON as the payload.
    from pyspark.sql import functions as F

    jsonl_df = raw_df.select(
        F.get_json_object("value", "$.0020000D.Value[0]").alias("study_instance_uid"),
        F.get_json_object("value", "$.0020000E.Value[0]").alias("series_instance_uid"),
        F.get_json_object("value", "$.00080018.Value[0]").alias("sop_instance_uid"),
        F.col("value").alias("_raw_json"),
    )

    # Drop rows where UID extraction failed (malformed lines)
    jsonl_df = jsonl_df.filter(
        F.col("study_instance_uid").isNotNull()
        & F.col("series_instance_uid").isNotNull()
        & F.col("sop_instance_uid").isNotNull()
    )

    n_dropped = raw_df.count() - jsonl_df.count()
    if n_dropped > 0:
        print(f"  Dropped {n_dropped} rows with missing UIDs")

    print(f"  Valid instances: {jsonl_df.count():,}")
else:
    print("Skipping JSONL load — data_source is SYNTHETIC")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load to Delta Bronze Table
# MAGIC
# MAGIC Creates the target catalog/schema if needed, then writes instances as a Delta table
# MAGIC with a `dicom_payload` column (VARIANT or STRING per widget selection).
# MAGIC
# MAGIC - **Mode A (SYNTHETIC):** ~5,800 instances, ~25 tags each — no credentials needed
# MAGIC - **Mode B (JSONL):** ~8,700 real IDC instances, 87–302 tags, private vendor tags included

# COMMAND ----------

from pyspark.sql import functions as F

# Ensure catalog and schema exist
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

# Pick the right source DataFrame
if data_source == "JSONL":
    source_df = jsonl_df
    print(f"Loading REAL IDC data ({source_df.count():,} instances, up to 302 tags each)...")
else:
    source_df = spark.createDataFrame(
        instances,
        ["study_instance_uid", "series_instance_uid", "sop_instance_uid", "_raw_json"],
    )
    print(f"Loading SYNTHETIC data ({source_df.count():,} instances, ~25 tags each)...")

# Add payload column based on selected format
if payload_format == "VARIANT":
    source_df = source_df.withColumn("dicom_payload", F.expr("parse_json(_raw_json)"))
else:
    source_df = source_df.withColumnRenamed("_raw_json", "dicom_payload")

# Add ingestion timestamp and drop raw JSON
source_df = source_df.withColumn("_ingestion_timestamp", F.current_timestamp())

# Select final columns in canonical order
df = source_df.select(
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
    "dicom_payload",
    "_ingestion_timestamp",
)

# Write to Delta
df.write.mode("overwrite").saveAsTable(full_table_name)

count = spark.table(full_table_name).count()
print(f"Loaded {count:,} rows to {full_table_name} (source: {data_source}, payload: {payload_format})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verification
# MAGIC
# MAGIC Quick checks to confirm the bronze table loaded correctly.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT COUNT(*) AS row_count FROM ${catalog}.${schema}.${bronze_table_name}

# COMMAND ----------

# MAGIC %sql
# MAGIC DESCRIBE TABLE EXTENDED ${catalog}.${schema}.${bronze_table_name}

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM ${catalog}.${schema}.${bronze_table_name} LIMIT 1

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT
# MAGIC   dicom_payload:00080060.Value[0]::string AS modality,
# MAGIC   COUNT(*) AS instance_count,
# MAGIC   COUNT(DISTINCT study_instance_uid) AS study_count,
# MAGIC   COUNT(DISTINCT series_instance_uid) AS series_count
# MAGIC FROM ${catalog}.${schema}.${bronze_table_name}
# MAGIC GROUP BY 1
# MAGIC ORDER BY 2 DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT COUNT(*) AS localizer_count
# MAGIC FROM ${catalog}.${schema}.${bronze_table_name}
# MAGIC WHERE array_contains(
# MAGIC   dicom_payload:00080008.Value::array<string>,
# MAGIC   'LOCALIZER'
# MAGIC ) OR array_contains(
# MAGIC   dicom_payload:00080008.Value::array<string>,
# MAGIC   'SCOUT'
# MAGIC )

# COMMAND ----------

# Summary verification
summary_df = spark.sql(f"""
    SELECT
        dicom_payload:00080060.Value[0]::string AS modality,
        COUNT(*) AS instance_count,
        COUNT(DISTINCT study_instance_uid) AS study_count,
        COUNT(DISTINCT series_instance_uid) AS series_count
    FROM {full_table_name}
    GROUP BY 1
    ORDER BY 2 DESC
""")

localizer_count = spark.sql(f"""
    SELECT COUNT(*) AS cnt
    FROM {full_table_name}
    WHERE array_contains(dicom_payload:00080008.Value::array<string>, 'LOCALIZER')
       OR array_contains(dicom_payload:00080008.Value::array<string>, 'SCOUT')
""").collect()[0]["cnt"]

# Tag richness — sample 200 rows, count top-level keys via Python
# Real IDC data: 87-302 tags. Synthetic: ~25 tags.
_sample_payloads = spark.sql(f"""
    SELECT to_json(dicom_payload) AS j FROM {full_table_name} TABLESAMPLE (200 ROWS)
""").collect()
_tag_counts = [len(json.loads(r["j"])) for r in _sample_payloads if r["j"]]
tag_stats = {
    "min_tags": min(_tag_counts) if _tag_counts else 0,
    "max_tags": max(_tag_counts) if _tag_counts else 0,
    "avg_tags": sum(_tag_counts) / len(_tag_counts) if _tag_counts else 0,
}

total_rows = spark.table(full_table_name).count()

print("=" * 60)
print(f"  Bronze Table Summary: {full_table_name}")
print(f"  Data Source:          {data_source}")
print(f"  Payload Format:       {payload_format}")
print(f"  Total Rows:           {total_rows:,}")
print("-" * 60)
print(f"  {'Modality':<12} {'Instances':>10} {'Studies':>10} {'Series':>10}")
print("-" * 60)
for row in summary_df.collect():
    print(f"  {row['modality']:<12} {row['instance_count']:>10,} {row['study_count']:>10,} {row['series_count']:>10,}")
print("-" * 60)
print(f"  LOCALIZER/SCOUT:      {localizer_count:,}")
print(f"  Tags per instance:    {tag_stats['min_tags']:.0f}–{tag_stats['max_tags']:.0f} (avg {tag_stats['avg_tags']:.0f})")
print("=" * 60)
