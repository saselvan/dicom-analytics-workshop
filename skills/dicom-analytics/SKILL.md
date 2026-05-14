---
name: dicom-analytics
description: "Generic schema-adaptive DICOM imaging metadata analytics on Databricks. Handles DICOMweb-format JSON payloads in bronze (STRING or VARIANT), discovers the user's curated columns and exploration surfaces at runtime, and adapts query generation to whatever silver schema exists. Encodes DICOM domain conventions once for any DICOMweb workload. Use when the user asks about DICOM imaging metadata — modalities, manufacturers, scanner fleet, slice/acquisition parameters, study/series counts, tag exploration, protocol distributions, dose compliance, scanner utilization, cohort identification, or any analytics over the radiology imaging metadata layer."
---

# DICOM Analytics

This skill produces SQL for DICOM imaging metadata workloads on Databricks. It
discovers the user's specific schema at runtime, encodes DICOM domain expertise
(format, conventions, gotchas), and generates SQL adapted to whatever curated
columns exist in the user's silver layer.

The skill is generic across hospitals. Customer-specific knowledge — which tags
are curated, what tables are named — comes from Discovery, not from this file.

## Sub-skill structure

This skill uses progressive disclosure. The core file (this SKILL.md) is always
loaded. Sub-skills load conditionally based on context. Load each sub-skill
**before** generating output that depends on it.

| Trigger | Sub-skill to load |
|---------|-------------------|
| Discovery Step 1 returns VARIANT payload | `sql-patterns/variant.md` |
| Discovery Step 1 returns STRING payload | `sql-patterns/string.md` |
| Discovery Step 1 finds top-level identifier columns | `sql-patterns/direct-columns.md` |
| Question class identified as "Threshold filter / qualification" | `templates/threshold-filter.md` |
| Question class identified as "Distribution / percentiles" | `templates/distribution.md` |
| User specifies different per-manufacturer thresholds | `templates/manufacturer-thresholds.md` |
| Question class identified as "Time series / trend" | `templates/time-series.md` |
| Question class identified as "Coverage / data quality" | `templates/coverage-audit.md` |
| Question class identified as "Dose compliance" | `templates/dose-compliance.md` |
| Question class identified as "Operational / scanner utilization" | `templates/utilization.md` |
| Question class identified as "Cohort / case identification" | `templates/cohort-identification.md` |
| Question routes to bronze tag exploration (EAV view path) | `templates/eav-exploration.md` |
| Question routes to bronze for long-tail / sequence / private vendor tags | `templates/bronze-patterns.md` |
| Generating slice / position / acquisition param query | `domain-rules/exclusions.md` |
| Generating manufacturer or body part filter | `domain-rules/normalization.md` |
| Output includes patient identifiers OR query touches PHI fields | `domain-rules/phi.md` |
| Generating queries that parse patient_age, time, or multi-value DS | `domain-rules/parsing.md` |
| Working dictionary needs reference comparison (column lookup with no PS3.6 source) | `reference/typical-shape.md` |

Load multiple sub-skills when multiple triggers apply. Load conservatively. If a
sub-skill's trigger doesn't clearly apply, don't load it — over-loading bloats the
working set and pushes the actual question and Discovery output out of context.
When uncertain, ask the user to disambiguate before loading.

---

## Context Detection

Determine the execution context before any action:

| Signal | Context | Behavior |
| --- | --- | --- |
| Editing a notebook cell, SQL editor, or ad-hoc analytics query | **Ad-hoc** | Run the Discovery Phase below; adapt SQL to discovered schema |
| Target is `CREATE STREAMING TABLE`, `CREATE MATERIALIZED VIEW`, or file is part of a Lakeflow Spark Declarative Pipeline | **Pipeline (SDP)** | Do NOT run runtime discovery. Require explicit column names. Generate deterministic SQL. If column information is missing, ask the user — do not probe. |

Discovery Phase below applies to Ad-hoc context only. When this skill is loaded
alongside `databricks-spark-declarative-pipelines` in the Lakeflow Pipelines Editor,
the Pipeline context rule takes precedence.

---

## Discovery Phase (Ad-hoc Context Only — REQUIRED)

This phase is required before generating any query against an unfamiliar schema.
The phase ends with an announcement that gates downstream code generation. Do NOT
skip — the entire skill depends on Discovery's output.

### Step 1: Identify the bronze payload column

Run `readTable` (or `DESCRIBE TABLE <bronze_table>`) on the user's bronze table.

Classify columns:
- **VARIANT columns:** payload candidates (no probe needed — VARIANT is pre-parsed).
- **STRING columns:** probe each candidate with a single-row sample to confirm
  JSON content:
  ```sql
  SELECT <candidate_col> FROM <bronze_table>
  WHERE <candidate_col> IS NOT NULL LIMIT 1
  ```
  Classify as a JSON payload candidate if the sampled value starts with `{` or
  `[`. STRING columns that don't pass this probe are not payload candidates.
- **Identifier columns:** top-level columns named like `study_instance_uid`,
  `series_instance_uid`, `sop_instance_uid` (or close variants)
- **Metadata columns:** ingestion timestamps, partition keys

If no VARIANT column exists AND no STRING column passes the JSON probe, halt
and report: "This bronze table doesn't appear to contain a DICOMweb JSON
payload. Expected either a VARIANT column or a STRING column containing JSON
with hex tag keys."

### Step 2: Disambiguate if multiple payload candidates exist

If the table has more than one column that could be the DICOMweb payload, present
them and stop:

> "I found N candidate payload columns:
> - `<col_a>` (TYPE, sample: `{first 80 chars}`)
> - `<col_b>` (TYPE, sample: `{first 80 chars}`)
>
> Which holds the DICOMweb payload?"

**Do NOT proceed to query generation until the user selects one.**

Non-interactive fallback: prefer the VARIANT column. If all candidates are STRING,
prefer one named `dicom_payload`, `payload`, `metadata`, `dicom_json`, or
`dicom_metadata` (in that order). Document the selection.

### Step 3: Validation probe

Sample one row to confirm DICOMweb format:

```sql
SELECT <payload_col> FROM <bronze_table> LIMIT 1
```

DICOMweb format uses 8-character hex tag IDs as JSON keys, with `vr` and `Value`
sub-fields. Verify the sample contains keys matching `[0-9A-F]{8}` — at least one of:
`00080018` (SOPInstanceUID), `00080060` (Modality), `0020000D` (StudyInstanceUID),
`0020000E` (SeriesInstanceUID).

If validation fails, report to user. Do NOT proceed.

### Step 4: Discover companion surfaces by role

Three roles to find:

| Role | What it is | Common name patterns |
|------|-----------|--------------|
| **Curated columnar surface** | Series-level table with named DICOM tags as columns | `*.dicom_series`, `*.curated_series`, `*.dicom_silver`, `silver.*dicom*` |
| **EAV exploration view** | Long-format tag/value view for tag-discovery questions | `*.dicom_tags_long`, `*.dicom_tags_eav`, `*.dicom_tags_explorer` |
| **PS3.6 keyword lookup** | DICOM standard reference table mapping keyword ↔ tag_id | `*.ps36_keyword_lookup`, `*.dicom_keywords`, `reference.dicom_dictionary` |

#### Search scope (bronze catalog first, then expand)

1. Search the catalog of the bronze table first. If bronze is
   `nwm_imaging.bronze.dicom_raw`, search `nwm_imaging.*.*`.
2. If zero matches for a role in the bronze catalog, expand to all catalogs the
   user has access to via `INFORMATION_SCHEMA.TABLES` (filters:
   `table_schema != 'information_schema'`). This handles the common layout where
   bronze is in `raw_data` and silver is in a separate `analytics` catalog.
3. If multiple matches in expanded scope, ask with disambiguating context (the
   existing prompt format below).
4. If still zero, fall through to the "I'll route to bronze" message.

Use `SHOW TABLES IN <catalog>` (or `INFORMATION_SCHEMA.TABLES` for full
metadata) to enumerate candidates.

#### Resolution rules per role

For each role, apply these rules in order:

**Zero matches found** — ask the user explicitly with the patterns shown:

> "I didn't find a `<role>` in `<bronze_catalog>`. I looked for tables matching:
> `<pattern_a>`, `<pattern_b>`, `<pattern_c>`. Do you have one with a different
> name? If yes, give me its full name. If no, I'll route queries that need this
> role to bronze with the discovered access pattern (correct, but slower)."

**Exactly one match** — use it. No user interaction required.

**Multiple matches** — ask with disambiguating context, not just names. Pull row
counts, last-modified timestamps, and the first 3 column names for each candidate:

> "I found N candidate `<role>` tables in `<bronze_catalog>`:
> - `<table_a>` — `<row_count>` rows, last modified `<timestamp>`, columns: `<col_1>`, `<col_2>`, `<col_3>`, …
> - `<table_b>` — `<row_count>` rows, last modified `<timestamp>`, columns: `<col_1>`, `<col_2>`, `<col_3>`, …
>
> Which is the active analytics target?"

**Do NOT proceed to Step 5 until each role's resolution is settled.**

#### Non-interactive fallback (scheduled execution only)

When user response isn't possible (scheduled jobs, automation):
1. Most-recently-modified table wins (active surface, not archive)
2. Largest row count wins (production, not dev)
3. Name without timestamps/version suffixes wins (`dicom_series` beats `dicom_series_2024_v2`)

Document the selection in the response.

### Step 5: Inventory the curated columnar surface (if present)

If a curated columnar surface was found in Step 4, inventory its columns:

```sql
DESCRIBE TABLE EXTENDED <curated_surface>
```

For each column, build a working tag dictionary by mapping it back to its PS3.6
origin. Apply this mapping chain in order; stop at the first match:

1. **Comment-parsed (preferred).** Parse the column comment for a hex tag ID
   pattern matching `\(?[0-9A-Fa-f]{4}\s*[,\s]\s*[0-9A-Fa-f]{4}\)?` (e.g.,
   `(0018,0050)`, `(0018, 0050)`, `0018,0050`). The `\s*[,\s]\s*` handles
   comma, comma-space, and whitespace-padded formats — the latter is how humans
   typically write tag IDs in column comments.
   The comment may also be prefixed with `derived:` or `computed:` to mark
   non-PS3.6 columns:
   - `"DICOM (0018,0050) SliceThickness — DS, mm"` → tag_id `00180050`, origin `direct`
   - `"derived: DICOM (0028,0030)[0] PixelSpacing row component"` → tag_id `00280030`, origin `derived`
   - `"computed: number of DICOM instances per series"` → no tag_id, origin `computed`
2. **Embedded fallback.** If the column comment doesn't contain a hex tag ID,
   load `reference/typical-shape.md` and use that mapping if the column name
   appears there.
3. **PS3.6 lookup table.** If `ps36_keyword_lookup` was discovered in Step 4:
   - **First check the acronym alias table below.** Many high-frequency DICOM
     keywords contain all-caps acronyms (`UID`, `SOP`, `MR`, `RT`, `KVP`) or
     mixed case (`CTDIvol`) that naive snake_case → PascalCase conversion gets
     wrong. The alias table covers these cases explicitly.
   - **If the column name isn't in the alias table**, convert
     snake_case → PascalCase (`slice_thickness` → `SliceThickness`) and look
     up that keyword.

   ### Acronym alias table

   | Column name | PS3.6 keyword |
   |---|---|
   | `kvp` | `KVP` |
   | `ctdi_vol` | `CTDIvol` |
   | `study_instance_uid` | `StudyInstanceUID` |
   | `series_instance_uid` | `SeriesInstanceUID` |
   | `sop_instance_uid` | `SOPInstanceUID` |
   | `sop_class_uid` | `SOPClassUID` |
   | `media_storage_sop_class_uid` | `MediaStorageSOPClassUID` |
   | `media_storage_sop_instance_uid` | `MediaStorageSOPInstanceUID` |
   | `referenced_sop_class_uid` | `ReferencedSOPClassUID` |
   | `referenced_sop_instance_uid` | `ReferencedSOPInstanceUID` |
   | `transfer_syntax_uid` | `TransferSyntaxUID` |
   | `frame_of_reference_uid` | `FrameOfReferenceUID` |
   | `synchronization_frame_of_reference_uid` | `SynchronizationFrameOfReferenceUID` |
   | `implementation_class_uid` | `ImplementationClassUID` |
   | `patient_id` | `PatientID` |
   | `issuer_of_patient_id` | `IssuerOfPatientID` |
   | `study_id` | `StudyID` |
   | `mr_acquisition_type` | `MRAcquisitionType` |
   | `xray_tube_current` | `XRayTubeCurrent` |
   | `xray_tube_current_in_ma` | `XRayTubeCurrentInmA` |
   | `exposure_in_mas` | `ExposureInmAs` |
   | `roi_name` | `ROIName` |
   | `roi_number` | `ROINumber` |
   | `rt_plan_label` | `RTPlanLabel` |
   | `rt_plan_name` | `RTPlanName` |
   | `rt_plan_description` | `RTPlanDescription` |
   | `rt_plan_date` | `RTPlanDate` |
   | `rt_plan_time` | `RTPlanTime` |
   | `rt_plan_geometry` | `RTPlanGeometry` |
   | `rt_referenced_study_sequence` | `RTReferencedStudySequence` |
   | `rt_roi_observations_sequence` | `RTROIObservationsSequence` |

   The table is not exhaustive — it covers the common acronym tags. If a customer
   adds columns for less-common acronym tags (PET, NM, OCT, etc.), extend the
   table. Columns not in this table fall through to the naive PascalCase
   conversion, which works for the ~95% of PS3.6 keywords that don't contain
   acronyms.

4. **Origin: unknown.** If none of the above match, the column is usable in
   queries but has no PS3.6 origin. Mark `origin: "unknown"` and proceed.

For columns with `origin: "derived"` or `origin: "computed"`, do NOT attempt PS3.6
keyword lookup — the comment is authoritative.

Working dictionary structure (held in conversation context):

```
{
  "<column_name>": {
    "type": "<DOUBLE|STRING|ARRAY<STRING>|...>",
    "tag_id": "<hex|null>",
    "keyword": "<PS3.6 keyword|null>",
    "origin": "<direct|derived|computed|unknown>"
  },
  ...
}
```

This dictionary is the working tag list for the rest of the conversation.

### Step 6: Announce assumptions

Before generating any query, report discovered context to the user:

> "Discovered schema:
> - Bronze: `<bronze_table>`, payload column `<col>` (TYPE: VARIANT | STRING)
> - Identifier columns at top level: `<list>` (or 'extracted from payload')
> - Curated columnar surface: `<table>` with N tag columns: `<col_a>`, `<col_b>`, …
>   (or 'not found — analytics will route to bronze')
> - EAV exploration view: `<table>` (or 'not found')
> - SQL access pattern: [VARIANT colon | get_json_object | direct reference]
>
> [conditional advisories — see below]
>
> Proceeding with this configuration. Correct me if any assumption is wrong."

**Conditional advisories** — include in the announcement only when applicable.
These are spoken once at announcement time and not repeated in subsequent turns:

| Condition | Advisory text |
|-----------|---------------|
| Payload type is STRING | "Performance note: STRING bronze pays JSON parse cost per query (materially slower than VARIANT for persisted Delta — exact ratio depends on schema and access pattern). Consider migration to VARIANT for ongoing analytics workloads." |
| Curated surface not discovered | "Note: no curated columnar surface found. Analytics will route to bronze with the discovered access pattern. Performance will be slower than with a curated layer." |
| EAV view not discovered | "Note: no EAV exploration view found. Tag-discovery questions will route to bronze with explicit JSON path enumeration — slower and less convenient." |
| `ps36_keyword_lookup` not discovered AND column comments lack PS3.6 tag IDs | "Note: PS3.6 keyword lookup not available, and silver column comments don't include tag IDs. I'll resolve column→tag_id mappings from the embedded reference shape, but coverage is limited to the ~30 most common tags." |
| ≥5 columns resolved to `origin: "unknown"` after Step 5 paths 1–3 | "Note: N columns in the curated surface couldn't be mapped to a PS3.6 origin (no tag ID in comments, not in the embedded reference, no match in the keyword lookup). Queries against those columns work, but the working dictionary has gaps. Affected columns: `<col_a>`, `<col_b>`, …" |

**Wait for user confirmation or correction before generating queries.**

Once confirmed, proceed silently for subsequent queries against the same schema.
Re-announce only if:
- The target table changes
- A query fails due to schema mismatch
- The user references a column not seen in discovery

---

## Question Refinement (Required Before Generation)

DICOM analytics requests are almost always under-specified on first ask. Modality,
time scope, inclusion criteria, output granularity, and decision-support context
are routinely missing. Generating SQL from an under-specified ask produces silent
wrong answers. Resolve ambiguity through targeted clarification before generating.

Counteract the documented LLM under-clarification bias: when uncertain, ask. Don't
pick an interpretation silently.

### Decision rule: when to ask vs proceed

**Placeholder-count rule:**

1. Map the user's request to a question class (see Question Class Catalog below).
2. Identify which template placeholders the request fills explicitly vs leaves blank.
3. Count placeholders that would require **guessing** — not derivable from the
   working dictionary, prior conversation context, or a documented domain default.
4. **If guessed-placeholder count > 1, ask. If 0–1, proceed.** State any single
   inline assumption clearly.

Carry context forward. If modality was specified earlier in the conversation and
the new question doesn't override it, treat it as filled.

### Question Class Catalog

| Class | Decisions supported | Common dimensions to clarify |
|-------|--------------------|----------------------------|
| **Volume / count** | Reporting, capacity planning, billing reconciliation | modality, time window, granularity (study/series/instance), site/scanner |
| **Distribution / percentiles** | Protocol calibration, outlier detection, fleet characterization | modality, body region, manufacturer (single/normalized/grouped), parameter, exclusions |
| **Threshold filter / qualification** | Research cohort identification, quality compliance, regulatory check | modality, threshold value(s), per-manufacturer thresholds, exclusions |
| **Time series / trend** | Operational monitoring, dose trending, utilization forecasting | modality, time grain, metric, normalization |
| **Cross-modality / cross-vendor comparison** | Protocol harmonization, fleet inventory, vendor evaluation | parameter(s), aggregation, grouping dimension |
| **Coverage / data quality** | Pipeline health, schema completeness, governance | tag(s), modality scope, time window |
| **Outlier / anomaly identification** | QA, dose monitoring, technologist QC | metric, baseline definition, threshold |
| **Cohort / case identification** | Research enrollment, AI training data prep | inclusion criteria (modality + anatomy + parameters + demographics), exclusion criteria |
| **Operational / scanner utilization** | Capacity planning, scheduling optimization | time grain, scanner / site filter, metric |
| **Dose compliance** | Regulatory reporting, patient safety | body region, modality (CT primarily), threshold (DRL), comparison group |
| **Protocol compliance** | Multi-site research consistency, QA | reference protocol parameters, tolerance bands, scope |

### Common ambiguity dimensions (DICOM-specific patterns)

When the user's request is ambiguous on one of these dimensions, use the
corresponding clarifying-question pattern. Provide labeled options, not open-ended
prompts.

#### Modality

> "Which modality?"

Canonical modality list (reference this instead of re-listing in templates):

- **Imaging:** `CT`, `MR`, `US`, `XA`, `PT`, `DX`, `CR`, `MG`, `RF`, `NM`, `ES`, `OT`
- **Non-image objects:** `SR` (structured report), `SEG` (segmentation), `KO` (key object), `PR` (presentation state)
- **Radiation therapy:** `RTSTRUCT`, `RTPLAN`, `RTDOSE`, `RTIMAGE`, `RTRECORD`

Metric-to-modality mapping:
- `KVP`, `CTDIvol`, `DLP`, `SliceThickness` → CT (and XA/RF for KVP)
- `RepetitionTime`, `EchoTime`, `FlipAngle` → MR
- `RTPlan*` fields → RTSTRUCT/RTPLAN/RTDOSE only

If the metric only applies to certain modalities, narrow the question to the
relevant subset instead of offering the full list.

#### Time scope

> "What time window?
> - Last 30 / 90 days / 12 months
> - Calendar year (which?)
> - Custom range (specify start–end)
> - All available data"

If the user's intent suggests an obvious window (e.g., "trends since 2018"
implies 2018–present), use it as an inline assumption rather than asking.

#### Question class (when a request maps to multiple)

If too vague to map to a single class, present 2–4 candidate interpretations with
concrete previews of what each would produce:

> "Two ways to read this — which?
> - **Distribution:** percentile breakdown (P50/P90/P99) of slice_thickness for CT studies, by manufacturer. Result: 5-row table.
> - **Threshold filter:** list of CT studies with slice_thickness ≤ 0.75 mm. Result: list of study/series UIDs (could be hundreds).
> - **Coverage:** % of CT series with slice_thickness populated, by manufacturer. Result: 5-row table with NULL rates.
> - **Other:** something else (describe)."

#### Inclusion / exclusion criteria

For technical parameter analytics, default-apply standard exclusions but surface
when they materially change result count:

> "Default exclusions for slice thickness analytics: LOCALIZER, SCOUT, derived /
> secondary capture series. Apply these defaults, or include all series?"

#### Manufacturer scope

> "Manufacturer scope?
> - All manufacturers, results aggregated
> - All manufacturers, results grouped (typical for fleet comparison)
> - Specific manufacturer (which?)"

Questions that vary intrinsically by vendor usually want grouped — surface that
as the recommended option.

#### Site / scanner scope (multi-site orgs only)

If Discovery Step 5 found a `station_name` or `institution_name` column with
multiple distinct values, ask:

> "Scope?
> - All scanners
> - Specific site or station (which?)
> - Grouped by site / station"

#### Output granularity

> "Result granularity?
> - Study-level (one row per study)
> - Series-level (one row per series — recommended for technical-parameter analyses)
> - Instance-level (rare; only for image-by-image analysis)"

#### Decision-support context (meta-clarifier)

When 3+ dimensions are ambiguous, ask the meta-question:

> "Quick framing — what's this for?
> - Operational reporting (dashboards, monthly review)
> - Research cohort identification (criteria for inclusion)
> - Quality / regulatory compliance (vs reference levels or protocols)
> - Investigation (drilling into a specific signal)"

### Single-message convention

When asking, group all clarifications into ONE message:
- Maximum 3 questions per turn
- Each as labeled options (2–4 choices), not open-ended
- Each with a "something else" or "describe" fallback
- Numbered or bulleted, not paragraph-form

Don't iterate one question at a time. Don't pad with apologies or preamble.

### When NOT to ask

The skill should NOT add clarifying questions when:

- **The request is precise.** Modality + threshold + time window all explicit. Proceed with default exclusions, mention them inline.
- **Context carries forward.** If modality was specified earlier and the new question doesn't override it, don't re-ask.
- **A domain default applies cleanly.** LOCALIZER / SCOUT exclusion is non-optional. Per-body-region grouping for dose compliance is the standard. Date precision follows the precedence rule (see `domain-rules/phi.md`) — apply the right case, don't default to year-truncation.
- **One missing dimension can be handled inline.** "Assuming last 12 months — adjust if you want a different window" is better than asking and waiting.

---

## Available Sources and Routing

Once Discovery completes, route queries based on intent and discovered surfaces:

| Question shape | Source | Sub-skill to load |
|----------------|--------|-------------------|
| Filter / aggregation on a curated tag (the tag exists as a column in the curated surface) | **Curated columnar surface** | Relevant `templates/*.md` |
| Filter / aggregation on a tag NOT in the curated surface | **Bronze** | `templates/bronze-patterns.md` + `sql-patterns/<variant\|string>.md` |
| "What tags exist," value distribution, coverage, cross-modality tag comparison | **EAV exploration view** if discovered; else bronze with explicit JSON enumeration | `templates/eav-exploration.md` |
| Sequence (VR=SQ) tag, private/vendor tag (odd group ID), bulk-data reference | **Bronze** | `templates/bronze-patterns.md` |

If the curated columnar surface doesn't exist, all analytics route to bronze.
Performance will be worse than with a curated layer; this was mentioned once at
announcement time and is not repeated.

---

## Workflow: For Any New Analytics Question

Apply this method to any new question, in this order:

1. **Identify the question class** (per Question Class Catalog).
2. **Identify the DICOM tags involved** — translate domain terms to PS3.6 keywords.
3. **Check Discovery output** — for each tag: in the curated surface, in the EAV view, or bronze-only?
4. **Apply the routing rule** (see Available Sources and Routing above).
5. **Load the relevant sub-skills** based on the load-condition table at the top of this file. Typically: one template, one sql-pattern, one or two domain-rules.
6. **Apply the type-adaptive SQL pattern** from the loaded `sql-patterns/*.md`.
7. **Apply applicable domain rules** from the loaded `domain-rules/*.md`.
8. **Generate the query** — substitute discovered column names from the working dictionary into the appropriate template.

This is the prescriptive method. Templates in the loaded sub-files are inputs to
step 8, not standalone recipes.

---

## Constraints

- **No DDL generation** (`ALTER`, `CREATE`, `DROP`). Schema changes go through Genie Code Agent mode in the Lakeflow Pipelines Editor with `databricks-spark-declarative-pipelines` loaded — never inline in skill responses.
- **No PHI in result sets.** See `domain-rules/phi.md` for full handling.
- **Don't query bronze for whole-tag analytics if the curated surface has the column.** Use the curated surface for filter/aggregate work; bronze only for tags not curated, sequences, or private vendor tags.
- **Don't try to flatten sequence (VR=SQ) tags inline.** Keep them as JSON; use nested access patterns from `templates/bronze-patterns.md`.
- **Exclude LOCALIZER and SCOUT from parameter analytics** (slice/position/acquisition parameters, dose). Non-optional for parameter queries. Does NOT apply to volume, coverage, utilization, or tag-discovery queries — see `domain-rules/exclusions.md` for the full scope table.
- **Manufacturer name and body part are unnormalized in raw data** — use the CASE patterns from `domain-rules/normalization.md`, not direct equality.
- **Substitute discovered column names**, not literal names from the reference shape. Discovery is ground truth.

---

## Error Recovery

Differentiate by error class — don't re-run full Discovery for every failure.

**SQL syntax / typo / column-name typo** (local editing error): retry inline
with a corrected query. Don't re-discover. Don't re-announce.

**Schema mismatch** (column not found, type changed, table restructured):
re-execute Discovery Step 5 (re-inventory the curated surface). Update the
working dictionary. Diff against the previous announcement and re-announce
only the changes — not the full Discovery output.

**JSON path resolution error on bronze** (NULL where non-NULL expected):
re-execute Discovery Step 3 (validation probe on a sample row). If the bronze
type changed (STRING → VARIANT migration), re-execute Step 1. Common causes:
- Discovered access pattern wrong (VARIANT used on STRING column or vice versa)
- Tag IDs in wrong case (DICOMweb uses uppercase hex)
- Tag is a sequence (VR=SQ) — needs nested access, not single-value extraction
- Tag has no `Value` field (some tags appear with only `vr` for empty values)

**Full Discovery rerun** only when the bronze table itself changed (different
table, renamed, or fundamentally restructured).

**On disambiguation failure** (multiple valid matches, no user response in
non-interactive context): apply the documented fallback rules. Document the selection.

