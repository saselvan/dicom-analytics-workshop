# DICOM Analytics Workshop — Demo Script

**Date:** May 14, 2026 | 1:00–2:30 PM
**Audience:** Lima Chatterjee's DE team, Camila Altman (observer), Kim Sierra (notes)
**Workspace:** `fe-vm-serverless-stable-udlnh4`
**Catalog:** `samuels_fevm_catalog`

---

## Part 1: The Bronze Layer — What We're Working With (15 min)

### 1.1 The Raw Data

> "Let's start with what we have. This is real public DICOM imaging metadata
> from the NCI Imaging Data Commons — about 8,000 instances across CT and MR."

```sql
SELECT COUNT(*) AS instance_count FROM samuels_fevm_catalog.dicom_demo.dicom_raw
```

Show one row's payload structure:

```sql
SELECT schema_of_variant(dicom_payload) AS payload_schema
FROM samuels_fevm_catalog.dicom_demo.dicom_raw
LIMIT 1
```

> "Every row is a single DICOM instance — one image. The payload is a VARIANT
> column containing the full DICOMweb JSON. ~130 tags per row. The keys are
> 8-character hex tag IDs — `00080060` is Modality, `00080070` is Manufacturer.
> Nobody memorizes these."

### 1.2 The PS3.6 Keyword Lookup

> "DICOM PS3.6 is the data dictionary standard — it maps hex tag IDs to
> human-readable keywords. We loaded all 5,129 standard tags."

```sql
SELECT tag_id, keyword, tag_name, vr
FROM samuels_fevm_catalog.reference.ps36_keyword_lookup
WHERE keyword IN ('Modality', 'Manufacturer', 'SliceThickness', 'ImageType',
                  'BodyPartExamined', 'KVP', 'ContrastBolusVolume')
ORDER BY tag_id
```

> "This is the Rosetta Stone. When someone says 'SliceThickness', this table
> tells us it's tag `00180050`, value representation DS (Decimal String),
> stored as a number. Without this, you're reading hex codes."

### 1.3 The Normalization Tables

> "Real DICOM data has a consistency problem."

**Manufacturer normalization** — show the config table:

```sql
SELECT manufacturer_pattern, manufacturer_group, modality, parameter
FROM samuels_fevm_catalog.dicom_silver.manufacturer_encoding_config
ORDER BY manufacturer_group, modality
```

> "Same manufacturer, five different spellings: 'GE', 'GE MEDICAL SYSTEMS',
> 'GE Healthcare', 'GE HEALTHCARE'. If you GROUP BY manufacturer without
> normalizing, you get five rows instead of one. This config table collapses
> them and also carries per-manufacturer thresholds — Philips uses 0.80mm
> for thin-slice CT, everyone else uses 0.425mm. Those aren't arbitrary numbers,
> they're scanner firmware defaults."

**Series type classification rules:**

```sql
SELECT rule_id, signal_source, match_operator, match_value,
       series_type, priority, description
FROM samuels_fevm_catalog.dicom_silver.series_type_rules
ORDER BY priority
```

> "This is the series classification engine. 13 rules, evaluated by priority.
> A series with ImageType containing 'LOCALIZER' gets classified as 'scout'.
> A series with fewer than 5 images and slice thickness over 50mm — also scout,
> even if ImageType doesn't say so. These are clinical heuristics encoded as
> config, not hardcoded logic."
>
> "Why does this matter? We'll see in a minute."

---

## Part 2: Querying Bronze Directly — Day-One Value and Its Limits (15 min)

### 2.1 Simple extraction works

> "You can query bronze directly. It's not pretty, but it works."

```sql
SELECT
  TRIM(try_variant_get(dicom_payload, '$.00080060.Value[0]', 'string')) AS modality,
  COUNT(*) AS instances
FROM samuels_fevm_catalog.dicom_demo.dicom_raw
GROUP BY 1
ORDER BY 2 DESC
```

> "That's `try_variant_get` with a JSON path — payload, hex tag, Value array,
> first element, cast to string. Every query starts with this incantation."

### 2.2 Cross-tag queries get ugly

> "Now let's ask something real: average slice thickness by manufacturer."

```sql
SELECT
  TRIM(try_variant_get(dicom_payload, '$.00080070.Value[0]', 'string')) AS manufacturer,
  AVG(try_variant_get(dicom_payload, '$.00180050.Value[0]', 'double'))  AS avg_slice_mm,
  COUNT(*) AS instances
FROM samuels_fevm_catalog.dicom_demo.dicom_raw
GROUP BY 1
ORDER BY 2 DESC
```

> "Two tags, two extraction calls, and the numbers look wrong. GE at 14.94mm?
> Merge Healthcare at 140mm? Those aren't slice thicknesses — those are scan
> range lengths from scout/localizer series."

### 2.3 The scout contamination problem

> "Let me break down what's happening in GE's data."

```sql
WITH extracted AS (
  SELECT
    try_variant_get(dicom_payload, '$.00080060.Value[0]', 'string')          AS modality,
    try_variant_get(dicom_payload, '$.00080070.Value[0]', 'string')          AS manufacturer,
    try_variant_get(dicom_payload, '$.00180050.Value[0]', 'double')          AS slice_thickness,
    try_variant_get(dicom_payload, '$.00080008.Value', 'array<string>')      AS image_type,
    CASE WHEN size(try_variant_get(dicom_payload, '$.00080008.Value', 'array<string>')) >= 3
         THEN try_variant_get(dicom_payload, '$.00080008.Value', 'array<string>')[2]
    END AS image_type_class
  FROM samuels_fevm_catalog.dicom_demo.dicom_raw
  WHERE try_variant_get(dicom_payload, '$.00080070.Value[0]', 'string') LIKE '%GE%'
)
SELECT modality, image_type_class,
  ROUND(AVG(slice_thickness), 2) AS avg_mm,
  ROUND(MIN(slice_thickness), 2) AS min_mm,
  ROUND(MAX(slice_thickness), 2) AS max_mm,
  COUNT(*) AS instances
FROM extracted
GROUP BY 1, 2
ORDER BY 3 DESC
```

> "CT ORIGINAL series are averaging 146mm with a max of 1,200mm. Those are
> topograms — the SliceThickness tag encodes total scan coverage, not per-slice
> interval. 14.6% of all CT instances in this dataset are scouts."
>
> "You can filter out LOCALIZER and SCOUT from ImageType, but that only catches
> the labeled ones. Some scouts don't carry those labels — they're just 2 images
> with 600mm thickness. You need series-level context to catch those."

### 2.4 Why bronze doesn't scale

> "Three problems with staying in bronze:
>
> 1. **Every query re-extracts from JSON.** No matter how fast VARIANT is,
>    you're parsing the same tags over and over.
> 2. **No series-level context.** Bronze is instance-level — one row per image.
>    You can't count how many images are in a series from a single row. The
>    compound scout rules ('fewer than 5 images AND thickness > 50mm') need
>    the series aggregate.
> 3. **No normalization.** Every analyst writes their own manufacturer CASE
>    statement. Some remember Philips, some don't. Numbers diverge."

---

## Part 3: Why Silver — Structure and Queries (15 min)

### 3.1 What silver gives you

> "Silver solves all three problems. Let me show you the table."

```sql
DESCRIBE TABLE samuels_fevm_catalog.dicom_demo.dicom_series
```

> "32 columns. Named, typed, series-level. `slice_thickness` is a DOUBLE, not
> a JSON extraction. `modality` is a STRING column, not `try_variant_get(...)`.
> And there's a `series_type` column — that's the classification from those
> 13 rules we looked at earlier."

```sql
SELECT series_type, COUNT(*) AS series_count
FROM samuels_fevm_catalog.dicom_demo.dicom_series
GROUP BY 1
ORDER BY 2 DESC
```

> "4,898 volumetric, 281 scout, 44 reformat, 18 non-volumetric. The classification
> engine separated them. Now watch what happens to slice thickness."

### 3.2 The clean numbers

```sql
SELECT manufacturer,
  ROUND(AVG(slice_thickness), 2) AS avg_mm,
  ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY slice_thickness), 2) AS p50_mm,
  COUNT(*) AS series_count
FROM samuels_fevm_catalog.dicom_demo.dicom_series
WHERE series_type = 'volumetric' AND modality = 'CT'
GROUP BY 1
ORDER BY 4 DESC
```

> "GE drops from 14.94mm to 3.15mm. That's the real number. The query is one
> line of WHERE instead of a 20-line CTE with JSON extraction and manual
> ImageType filtering."

### 3.3 Manufacturer-specific thresholds

> "Lima, this is the query you described in April — different thresholds for
> different manufacturers."

```sql
SELECT
  CASE
    WHEN UPPER(manufacturer) LIKE '%PHILIPS%' AND slice_thickness <= 2.0 THEN 'Philips thin'
    WHEN UPPER(manufacturer) NOT LIKE '%PHILIPS%' AND slice_thickness <= 1.25 THEN 'Other thin'
    ELSE 'Standard'
  END AS cohort,
  manufacturer,
  COUNT(*) AS series_count,
  ROUND(AVG(slice_thickness), 2) AS avg_mm
FROM samuels_fevm_catalog.dicom_demo.dicom_series
WHERE series_type = 'volumetric' AND modality = 'CT'
GROUP BY 1, 2
ORDER BY 1, 4
```

> "With the `manufacturer_encoding_config` table, these thresholds are config-driven
> — not hardcoded in every query. Add a new manufacturer, update one row in the
> config table, and every query picks it up."

---

## Part 4: The SDP Pipeline — How Silver Gets Built (20 min)

### 4.1 What is SDP?

> "Spark Declarative Pipelines — the new name for what was DLT. The key word
> is *declarative*. You define WHAT each table contains, not HOW to compute it.
> The engine handles execution, optimization, dependencies, and refresh."

### 4.2 Pipeline anatomy — open the file

Open `dicom_silver.py` in the Lakeflow Pipelines Editor. Walk through top to bottom.

**Configuration block (lines 37–50):**

> "Three parameters — bronze table, payload column, rules table. All configurable
> per environment. The pipeline doesn't hardcode catalog names."
>
> "The type detection on line 43 is the only imperative Python. It probes the
> payload column to determine VARIANT vs STRING, which decides the SQL extraction
> syntax downstream. Everything after this is SQL."

**Extraction helpers (lines 55–72):**

> "Three small functions that generate SQL expressions. `_v('00080060', 0, 'string')`
> produces `try_variant_get(dicom_payload, '$.00080060.Value[0]', 'string')` for
> VARIANT, or `get_json_object(...)` for STRING. They're SQL generators, not
> PySpark transformations."

**`bronze_dicom_extracted` — the extraction view (lines 79–136):**

> "This is a `@dp.temporary_view` — it exists only during pipeline execution,
> not persisted. It's a single SQL SELECT that projects the raw JSON payload
> into 28 named columns. One line per tag."
>
> "Notice the pattern: every line is `TRIM(_v('TAG_ID')) AS column_name` for
> strings, or `_v('TAG_ID', 0, 'double') AS column_name` for numbers. Adding
> a tag is adding one line. The litmus test later proves this."

**`dicom_series` — the silver table (lines 143–260):**

> "This is `@dp.table` — the persistent, materialized output. Liquid clustering
> on modality and study_instance_uid for query performance."
>
> "The body is a single `spark.sql()` call with four CTEs. Let me walk each one."

**CTE 1 — `series_agg` (lines 155–191):**

> "Aggregates instances to series grain. `first_value(modality, true)` takes the
> first non-null modality per series. `COUNT(*)` gives instance_count — that's
> a series-level signal that doesn't exist at the instance level."

**CTE 2 — `with_signals` (lines 194–198):**

> "Derives classification signals. `image_type[2]` — the third element of the
> ImageType array — is the primary classifier. ORIGINAL, DERIVED, LOCALIZER,
> SECONDARY. This is how DICOM encodes what kind of series it is."

**CTE 3 — `classified` (lines 201–220):**

> "Joins series against the rules table. Each rule specifies a signal_source,
> match_operator, and match_value. The JOIN ON clause evaluates all rule types —
> equals, in, like, not_in, and the compound image_count_thickness rule."
>
> "`MIN_BY(r.series_type, r.priority)` — that's the entire priority engine.
> 'Give me the series_type from the rule with the lowest priority number.'
> No window functions, no ranking, no subquery. One aggregate."

**Final SELECT (lines 222–259):**

> "LEFT JOIN back to the series data. `COALESCE(c.series_type, 'other')` —
> if no rule matched, it's 'other'. That shouldn't happen with catch-all rules,
> but defensive defaults are free."

**Data quality expectations (lines 267–289):**

> "`@dp.expect` decorators on the violations view. These log warnings when a
> series has multiple distinct modalities or manufacturers — which should never
> happen, but does in dirty data. Pipeline doesn't fail; it tells you."

### 4.3 Why this matters architecturally

> "The entire pipeline is one Python file, ~290 lines. The Python is configuration
> and SQL generation. The SQL is declaration. Adding a tag is:
>
> 1. One line in the extraction view — `_v('TAG_ID', 0, 'type') AS name`
> 2. One line in the series_agg CTE — `first_value(name, true) AS name`
> 3. One line in the final SELECT — `s.name`
>
> Three lines, one file, one commit. No schema migration, no downstream breakage.
> The skill can generate these three lines for you — that's the litmus test."

---

## Part 5: The Skill — Teaching Genie Your Domain (15 min)

### 5.1 What is a Genie Code skill?

> "A skill is a markdown file at `.assistant/skills/{name}/SKILL.md` in your
> workspace. When you enable Agent mode in a notebook or the Pipelines Editor,
> Genie reads the skill and uses it to guide its behavior. No SDK, no API,
> no deployment. A markdown file in the right place."

### 5.2 Skill anatomy — file map

```
skills/dicom-analytics/
├── SKILL.md                          ← Core logic, always loaded (~550 lines)
├── domain-rules/
│   ├── exclusions.md                 ← LOCALIZER/SCOUT scope rules
│   ├── normalization.md              ← Manufacturer + body part CASE
│   ├── parsing.md                    ← Age, time, multi-value parsing
│   └── phi.md                        ← PHI handling, date precision
├── sql-patterns/
│   ├── direct-columns.md             ← Top-level column access
│   ├── string.md                     ← STRING JSON extraction
│   └── variant.md                    ← VARIANT colon-path access
├── templates/
│   ├── bronze-patterns.md            ← Vendor tags, sequences, multi-frame
│   ├── cohort-identification.md      ← Multi-criteria cohort assembly
│   ├── coverage-audit.md             ← NULL rate, tag coverage
│   ├── distribution.md               ← Percentile breakdowns
│   ├── dose-compliance.md            ← CTDIvol vs DRLs
│   ├── eav-exploration.md            ← Tag inventory, value distribution
│   ├── manufacturer-thresholds.md    ← Per-vendor threshold logic
│   ├── threshold-filter.md           ← Single-threshold filters
│   ├── time-series.md                ← Trend queries
│   └── utilization.md                ← Scanner throughput
└── reference/
    └── typical-shape.md              ← Common tag → column mapping
```

> "18 sub-files, 3,049 lines across 4 directories. Most skills won't need this
> many — DICOM is a complex domain. A skill for simpler data might be 200 lines
> in a single file."

### 5.3 Why four directories?

| Directory | Contains | When loaded |
|-----------|----------|-------------|
| **domain-rules/** | Non-obvious domain knowledge — exclusions, normalization, PHI | Alongside any template that touches those concepts |
| **sql-patterns/** | Type-adaptive SQL extraction syntax | Once during Discovery, based on payload type |
| **templates/** | SQL patterns for specific question classes | When the user's question maps to that class |
| **reference/** | Static lookups (tag mappings, typical column names) | Fallback when runtime lookup isn't available |

> "This is progressive disclosure. Genie's context window is finite. A 3,000-line
> skill loaded for every question wastes context. Sub-files load conditionally —
> if you ask about dose compliance, only `dose-compliance.md` and `exclusions.md`
> load. If you ask about tag discovery, `eav-exploration.md` loads."

### 5.4 The three key patterns in SKILL.md

**1. Discovery Phase** — schema detection at runtime

> "The skill doesn't hardcode table names. It discovers: What's the payload
> column? VARIANT or STRING? Is there a silver table? What columns does it have?
> Is there an EAV view? A PS3.6 lookup?"
>
> "Discovery runs once per conversation. It announces what it found and waits
> for confirmation before generating any SQL. That prevents silent wrong answers
> from schema mismatches."

**2. Question Refinement** — asking only when needed

> "'Show me slice thickness' — is that a distribution? A threshold filter?
> A coverage audit? The skill asks. 'Find CT studies with slice thickness
> under 0.75mm in the last 12 months' — nothing to clarify. The skill proceeds."
>
> "The rule: count how many parameters you'd have to guess. More than one → ask.
> Zero or one → proceed with inline assumption."

**3. Domain Rules** — the knowledge Genie doesn't have

> "Genie doesn't know that SliceThickness on a LOCALIZER is meaningless.
> It doesn't know that 'GE' and 'GE MEDICAL SYSTEMS' are the same manufacturer.
> It doesn't know that BodyPartExamined is free text with dozens of spelling
> variants for 'CHEST'."
>
> "The domain-rules sub-files encode all of this. When Genie generates a query
> involving slice thickness, it loads `exclusions.md` and applies the scout
> filter automatically. When it groups by manufacturer, it loads `normalization.md`
> and applies the CASE statement."

### 5.5 Explore mode vs Generate mode

> "Same skill, two contexts:
>
> - **Explore mode** (notebook, SQL editor): The skill answers questions. It
>   generates SQL queries against bronze or silver. This is what we've been doing.
>
> - **Generate mode** (Lakeflow Pipelines Editor): The skill writes pipeline code.
>   It knows the SDP syntax, the tag dictionary, the extraction patterns. It
>   generates the three lines needed to add a tag to silver."

---

## Part 6: The Litmus Test — Full Loop (10 min)

> "Let's prove the full loop. One of you is going to tell the skill to add a
> tag to the pipeline."

Switch to the Lakeflow Pipelines Editor on `dicom_silver.py`. Agent mode on.
DE volunteer takes keyboard.

**The prompt:**

```
Add ContrastBolusVolume to silver as a DOUBLE.
```

> "Watch what happens. The skill looks up ContrastBolusVolume — tag 00181041,
> VR is DS, single-value DOUBLE. It generates edits to three locations in the
> file: extraction view, series_agg CTE, final SELECT. Approve the diff, run
> the pipeline, and the column exists in silver."

After approval and pipeline run:

```sql
SELECT contrast_bolus_volume, COUNT(*)
FROM samuels_fevm_catalog.dicom_demo.dicom_series
WHERE contrast_bolus_volume IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
LIMIT 10
```

> "From prompt to queryable column — under 5 minutes. That's the full loop:
> skill answers questions from bronze, skill builds the pipeline when bronze
> can't answer it cleanly, silver is queryable immediately."

---

## Part 7: Wrap and Discussion (10 min)

Three things to leave with:

1. **The skill is yours.** Edit the markdown, changes apply immediately.
   No redeployment, no approval workflow.

2. **The pipeline is yours.** It's code in your workspace. Review diffs,
   version it, extend it.

3. **Adding a tag is a 3-minute ask, not a sprint.**

Open questions for the room:
- "What's the next tag your team would add?"
- "What questions do you ask about DICOM data today that we didn't cover?"
- "Who else should see this?"
