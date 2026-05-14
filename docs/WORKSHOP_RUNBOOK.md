# Workshop Runbook — May 14, 1:00–2:30 PM

90 minutes. NWM on-site. Lima Chatterjee + DE team (audience), Camila Altman
(observer), Kim Sierra (observer, owns post-meeting summary).

This is the minute-by-minute plan. Print or have on a tablet.

---

## Pre-session (12:30–1:00 PM)

- Arrive 30 min early
- Verify projector / screen sharing works
- Open these tabs in your browser:
  1. A fresh notebook with Agent mode enabled (Explore mode — Blocks 2-3)
  2. A SQL Editor tab for Block 3.5 (bronze ceiling queries)
  3. The Lakeflow Pipelines Editor on dicom_silver.py with Agent mode enabled
     (Generate mode — Block 4)
  4. This runbook open in a separate window or printed
- Confirm the DE volunteer is present and at the room
- Confirm the silver table has data: run a quick `SELECT COUNT(*) FROM samuels_fevm_catalog.dicom_demo.dicom_series`
  in the SQL Editor

---

## Block 1: Opening (1:00–1:10) — 10 min

**Owner:** Camila → Samuel

### 1:00–1:03 — Camila welcome

Camila opens. She frames why this matters for NWM (her words, not yours).
You don't need to script her.

If she defers to you: brief greeting, "thanks for hosting," then transition
to your context-setting.

### 1:03–1:10 — Samuel context

Cover three things, conversationally:

1. **What we're going to do** (1 min)
   - "This skill does two things. First, it answers questions about your
     DICOM data directly from bronze — no pipeline needed, day-one value.
     Second, when you hit a question bronze can't answer well, the skill
     generates the pipeline code to build silver. You'll see both today,
     and one of you will drive the pipeline build hands-on."
2. **What this is and isn't** (2 min)
   - "This is a working artifact, not a demo. The skill goes to your user
     scope today. The pipeline is in your workspace as code. Lima's team
     owns these from the moment we leave."
   - "It's not a one-off — the skill is generic across DICOMweb workloads.
     Same thing works at any DICOM-shaped bronze. NWM-specific bits come
     from Discovery, not from the skill itself."
3. **What success looks like** (2 min)
   - "Two litmus tests. First: the skill answers a question about your
     bronze data correctly, with domain rules applied, in under 30 seconds.
     Second: one of you tells the skill to add a tag to silver, and it
     generates the pipeline code — approved, run, queryable — in under
     5 minutes. That's the full loop."
   - "I'll narrate while we go. Interrupt with questions — silence isn't
     useful here."

Show the architecture diagram (architecture.svg from the repo) on screen.
Walk through it in 60 seconds:
- Bronze (DICOMweb JSON, instance-level)
- **Explore mode**: Skill answers questions directly from bronze — SQL
  templates, domain rules, clarifying questions. Day-one value.
- **Generate mode**: When bronze can't answer it cleanly, skill generates
  SDP pipeline code (`@dp.table`) to build silver. The skill IS the
  pipeline builder.
- Silver (curated, series-level, ~30 named columns)
- EAV view (long-format for tag-discovery questions)
- Genie Space on silver + EAV for end-user query surface

---

## Block 2: Explore Mode — Discovery (1:10–1:20) — 10 min

**Owner:** Samuel demos
**Audience:** watching, asking questions
**Mode:** Explore — the skill answers questions from bronze

### Setup

Open a fresh notebook with Agent mode enabled. This is the Explore mode
context — the skill reads your bronze schema and answers questions using
SQL templates and domain rules. No pipeline needed.

(Save the Lakeflow Pipelines Editor for Block 4 — that's Generate mode.)

### 1:10–1:15 — Prompt 1.1

Type into Agent mode:

```
Help me query the DICOM data.
```

Wait for Genie to read the skill and run discovery. (Should take 10-30 sec.)

When the announcement appears, point to specific elements:
- "Notice it didn't generate SQL yet. It told us what it found first."
- "It identified the payload column as `<col>` (VARIANT or STRING — whatever
   Lima's bronze has)."
- "It found `dicom_series` with N tag columns — those are the curated
   tags."
- "It found the EAV view if we created it. It found the PS3.6 keyword lookup."

Talking points:
- "This is the gated discovery pattern. The skill makes Genie pause and announce
   what it discovered before generating any SQL."
- "If anything is wrong — wrong payload column, wrong identifier columns —
   this is where you catch it. Cheaper than catching it in a wrong query
   later."

### 1:15–1:20 — Audience questions on discovery

Pause for questions specifically about the discovery announcement. Common ones:
- "What if the payload column type changes?" → Discovery re-runs on
  schema change or query failure (Error Recovery)
- "What if I have multiple bronze tables?" → Skill discovers per-table; you
  re-run when changing target
- "What if my silver schema isn't materialized yet?" → Discovery falls back
  to bronze with discovered access pattern

If no questions, move forward.

---

## Block 3: Explore Mode — Question Refinement (1:20–1:35) — 15 min

**Owner:** Samuel demos
**Audience:** watching
**Mode:** Still Explore — showing how the skill handles ambiguity

### 1:20–1:25 — Prompt 2.1 (under-specified)

```
Show me slice thickness.
```

Wait for Genie to ask clarifying questions.

Expected: 2-3 questions in one message with labeled options. Modality,
distribution-vs-filter-vs-coverage, time window.

Talking points:
- "Without the skill, Genie picks an interpretation. Probably wrong, and
   you don't know it's wrong until you see the result."
- "With the skill, three labeled options. One message. Not iterative
   interrogation."
- Pick one of the offered options (e.g., distribution, CT, last 12 months)
   and watch Genie generate the query.
- "Notice the LOCALIZER and SCOUT exclusions. That's a domain rule the skill
   applies automatically — slice thickness on a localizer is misleading
   data, and the skill knows it."

### 1:25–1:30 — Prompt 2.2 (precise, should NOT ask)

```
Find CT studies with slice_thickness < 0.75 mm in the last 12 months.
```

Watch Genie proceed without questions.

Talking points:
- "Now look — no questions. Modality, threshold, time window all explicit.
   Nothing to clarify."
- "Genie still applied the LOCALIZER exclusion. That's a domain default
   the skill says to apply by default with inline mention."
- "The placeholder-count rule prevents reflexive question-padding. If the
   request is precise, Genie moves."

### 1:30–1:35 — Prompt 2.3 (vague intent, show-the-consequence)

```
I want to understand our scanner fleet.
```

Watch Genie offer 3-4 candidate question classes with previews of what each
would produce.

Talking points:
- "When the request is genuinely vague, the skill shows what each
   interpretation would produce, not just labels."
- "Volume by manufacturer produces a 5-row table. List of qualifying
   studies produces hundreds of UIDs. Distribution produces percentiles
   per vendor. Each leads somewhere different."
- "The user picks by outcome, not by trying to understand what the question
   meant."

This block is the most novel for the audience. Slow down here. Ask:
- "Does this match how you'd want to interact with your DICOM data?"
- "What other ambiguity dimensions hit you in your day-to-day?"

Capture answers. They feed Lima's roadmap for extending the skill.

---

## Block 3.5: Bronze Ceiling — Why Generate Mode Exists (1:35–1:50) — 15 min

**Owner:** Samuel demos in SQL editor
**Purpose:** Show what bronze exploration looks like via the EAV view, then
hit the wall that motivates silver — and sets up Generate mode in Block 4.

### Setup

Open the SQL editor tab you pre-loaded.

### 1:35–1:40 — Easy wins (EAV view shines)

Run in SQL editor:

```sql
-- What tags do we have?
SELECT tag_keyword, vr, COUNT(*) AS instance_count,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(DISTINCT series_uid)
             FROM samuels_fevm_catalog.dicom_demo.dicom_tags_long), 1) AS pct_series
FROM samuels_fevm_catalog.dicom_demo.dicom_tags_long
GROUP BY tag_keyword, vr
ORDER BY instance_count DESC
LIMIT 20
```

> "No JSON. No hex tags. The EAV view gave us a queryable surface over
> raw bronze in about 30 lines of SQL."

Then single-tag distribution:

```sql
-- SliceThickness distribution
SELECT value, COUNT(*) AS n
FROM samuels_fevm_catalog.dicom_demo.dicom_tags_long
WHERE tag_keyword = 'SliceThickness'
GROUP BY value
ORDER BY n DESC
LIMIT 15
```

> "For tag discovery and single-tag questions, this is all you need."

### 1:40–1:45 — Hit the wall (cross-tag query)

Now run something that requires two tags together:

```sql
-- Slice thickness by manufacturer for CT — EAV requires self-joins
SELECT t2.value AS manufacturer,
       CAST(t1.value AS DOUBLE) AS slice_thickness,
       COUNT(*) AS n
FROM samuels_fevm_catalog.dicom_demo.dicom_tags_long t1
JOIN samuels_fevm_catalog.dicom_demo.dicom_tags_long t2
  ON t1.study_uid = t2.study_uid AND t1.series_uid = t2.series_uid
JOIN samuels_fevm_catalog.dicom_demo.dicom_tags_long t3
  ON t1.study_uid = t3.study_uid AND t1.series_uid = t3.series_uid
WHERE t1.tag_keyword = 'SliceThickness'
  AND t2.tag_keyword = 'Manufacturer'
  AND t3.tag_keyword = 'Modality' AND t3.value = 'CT'
GROUP BY 1, 2
ORDER BY n DESC
LIMIT 15
```

Talking points:
- "Three self-joins on a table with one row per tag per instance. If your
   bronze has 500 tags across 2M series, that's a billion-row table
   joining to itself three times."
- "And notice `t1.value` is a STRING. We had to CAST it. Hope nobody stored
   '1.25mm' with the unit in the string."
- "This works at demo scale. At production scale, it's a performance cliff."

### 1:45–1:50 — The pivot to silver

Same question against silver — run in the same SQL editor:

```sql
SELECT manufacturer, 
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY slice_thickness) AS p50,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slice_thickness) AS p95,
  COUNT(*) AS series_count
FROM samuels_fevm_catalog.dicom_demo.dicom_series
WHERE modality = 'CT'
  AND series_type = 'volumetric'
GROUP BY 1
ORDER BY series_count DESC
```

Talking points:
- "Same question. One table. Named columns. Typed values. No self-joins.
   LOCALIZER exclusion is trivial."
- "Silver exists so your analysts never have to write that three-way
   self-join. The pipeline flattens it once, everyone queries it forever."
- "The EAV view is your exploration tool — 'what tags exist, what values
   do they take.' Silver is your analytics surface — 'what does this data
   tell me about my fleet.'"

Pause. Ask the room:
- "Which questions would your team ask day-to-day — single-tag exploration
   or cross-tag analytics?"

The answer is almost always both. This is the pivot:
- "So we've been in Explore mode — the skill answering questions from
  bronze. That works for single-tag queries. But cross-tag analytics need
  silver. The skill can build that too — that's Generate mode. Let's
  switch contexts."

---

## Block 4: SDP Pipeline Anatomy (1:50–2:00) — 10 min

**Owner:** Samuel walks through code on screen
**Purpose:** Show what silver is made of before asking Genie to modify it

### Setup

Open `dicom_silver.py` in the Lakeflow Pipelines Editor. Scroll to the top.
Walk through top to bottom — don't read every line, hit the landmarks.

### 1:50–1:53 — Configuration + helpers (lines 37–72)

> "Three parameters — bronze table, payload column, rules table. All
> configurable per environment. The pipeline doesn't hardcode catalog names."

> "Line 43 — the type detection — is the only imperative Python in the file.
> It probes the payload column to figure out VARIANT vs STRING. Everything
> after this is SQL."

> "Three small helper functions generate SQL expressions. `_v('00080060')`
> becomes `try_variant_get(dicom_payload, '$.00080060.Value[0]', 'string')`
> for VARIANT, or `get_json_object(...)` for STRING. They're SQL generators,
> not PySpark transformations."

### 1:53–1:56 — Extraction view + silver table (lines 79–260)

> "`bronze_dicom_extracted` is a `@dp.temporary_view` — exists only during
> pipeline execution. A single SQL SELECT projects the raw JSON into 28
> named columns. One line per tag. Adding a tag = adding one line here."

> "`dicom_series` is `@dp.table` — the persistent output. Liquid clustering
> on modality and study_instance_uid. The body is one `spark.sql()` call
> with four CTEs."

Walk each CTE briefly:

| CTE | What it does | Key line |
|-----|-------------|----------|
| `series_agg` | Aggregates instances → series | `first_value(modality, true)`, `COUNT(*) AS instance_count` |
| `with_signals` | Derives classification signals | `image_type[2]` → `image_type_class` (ORIGINAL, LOCALIZER, etc.) |
| `classified` | Joins rules table, picks winner | `MIN_BY(r.series_type, r.priority)` — entire priority engine in one aggregate |
| Final SELECT | LEFT JOIN back, default to 'other' | `COALESCE(c.series_type, 'other')` |

> "Adding a tag to silver is three lines: one in the extraction view, one in
> series_agg, one in the final SELECT. That's what the litmus test will prove."

### 1:56–2:00 — Expectations (lines 267–289)

> "`@dp.expect` decorators — data quality warnings. If a series has multiple
> distinct modalities or manufacturers, something is wrong in the source.
> Pipeline doesn't fail; it tells you."

Pause for questions on the pipeline. If none, move on.

---

## Block 5: Skill Anatomy (2:00–2:10) — 10 min

**Owner:** Samuel walks through skill structure
**Purpose:** Demystify what a Genie Code skill is before the litmus test

### 2:00–2:02 — What is a skill?

> "A skill is a markdown file at `.assistant/skills/{name}/SKILL.md` in your
> workspace. When you enable Agent mode in a notebook or the Pipelines Editor,
> Genie reads the skill. No SDK, no API, no deployment. A markdown file in
> the right place."

### 2:02–2:05 — File map

Show this on screen (or have it printed):

```
skills/dicom-analytics/
├── SKILL.md                          ← Core logic, always loaded
├── domain-rules/
│   ├── exclusions.md                 ← LOCALIZER/SCOUT scope rules
│   ├── normalization.md              ← Manufacturer + body part CASE
│   ├── parsing.md                    ← Age, time, multi-value parsing
│   └── phi.md                        ← PHI handling, date precision
├── sql-patterns/
│   ├── direct-columns.md             ← Top-level column access
│   ├── string.md                     ← STRING JSON extraction
│   └── variant.md                    ← VARIANT colon-path access
├── templates/                        ← SQL patterns per question class
│   ├── bronze-patterns.md, cohort-identification.md,
│   ├── coverage-audit.md, distribution.md,
│   ├── dose-compliance.md, eav-exploration.md,
│   ├── manufacturer-thresholds.md, threshold-filter.md,
│   ├── time-series.md, utilization.md
└── reference/
    └── typical-shape.md              ← Common tag → column mapping
```

> "18 sub-files across 4 directories. Most skills won't need this many —
> DICOM is a complex domain."

### 2:05–2:07 — Why four directories?

| Directory | Contains | When loaded |
|-----------|----------|-------------|
| **domain-rules/** | Non-obvious domain knowledge | With any template that touches those concepts |
| **sql-patterns/** | Type-adaptive SQL extraction | Once during Discovery, based on payload type |
| **templates/** | SQL patterns per question class | When the user's question maps to that class |
| **reference/** | Static lookups, tag mappings | Fallback when runtime lookup unavailable |

> "Progressive disclosure. Genie's context window is finite. Sub-files load
> conditionally — dose question loads `dose-compliance.md`, tag discovery
> loads `eav-exploration.md`. Not all 3,000 lines every time."

### 2:07–2:10 — Three key patterns

**1. Discovery** — schema detection at runtime

> "The skill doesn't hardcode table names. It discovers: payload column,
> VARIANT or STRING, silver table, EAV view, PS3.6 lookup. Announces what
> it found, waits for confirmation. Prevents silent wrong answers."

**2. Question Refinement** — ask only when needed

> "'Show me slice thickness' — distribution? threshold? coverage? The skill
> asks. 'Find CT with slice < 0.75mm last 12 months' — nothing to clarify,
> skill proceeds. Rule: count parameters you'd have to guess. More than
> one → ask. Zero or one → go."

**3. Domain Rules** — the knowledge Genie doesn't have

> "Genie doesn't know SliceThickness on a LOCALIZER is meaningless. Doesn't
> know 'GE' and 'GE MEDICAL SYSTEMS' are the same. The domain-rules sub-files
> encode this. When Genie queries slice thickness, it loads `exclusions.md`
> automatically."

---

## Block 6: Litmus Test — Full Loop (2:10–2:25) — 15 min

**Owner:** DE volunteer drives
**Samuel:** sits next to them, narrates, doesn't take keyboard
**Mode:** Generate — the skill writes pipeline code

### 2:10–2:12 — Setup

> "We've seen the pipeline structure and the skill that powers it. Now let's
> prove the full loop. One of you is going to tell the skill to add a tag."

Move to the Lakeflow Pipelines Editor on `dicom_silver.py`. Agent mode on.

Have the DE volunteer take the keyboard. Hand them the prompt:

```
Add ContrastBolusVolume to silver as a DOUBLE.
```

### 2:12–2:17 — Run the prompt

DE volunteer pastes and presses Enter. Watch Genie work.

Narrate in real time:
- "It's reading both skills — dicom-analytics for tag info, pipelines skill
   for SDP framework."
- "It's looking up ContrastBolusVolume — tag (0018,1041), VR=DS, DOUBLE."
- "Now it's editing. Adding the line in three places — extraction,
   aggregation, final SELECT."

When the diff appears, walk through it:
- Extraction: `_v('00181041', 0, 'double') AS contrast_bolus_volume`
  — the helper generates type-adaptive SQL
- Aggregation: `first_value(contrast_bolus_volume, true)`
- Final SELECT: `s.contrast_bolus_volume`
- Why three spots: instance-level extraction → series-level aggregation →
  pass-through to output

Have the DE volunteer click **Approve**.

**Time check:** if past 2:17 and the diff isn't approved, don't re-prompt.
Frame: "First skill load is always slower; subsequent edits are faster."

### 2:17–2:21 — Run the pipeline

Trigger a full refresh via the UI.

While it runs (1-2 min):
- "This is now in your pipeline as code. Same workflow for any new tag."
- "Your team owns this artifact. Edit it, version it, review it like any
   other code."

Verify after run completes:

```sql
DESCRIBE TABLE samuels_fevm_catalog.dicom_demo.dicom_series
-- contrast_bolus_volume should appear
```

### 2:21–2:25 — Query the new column

DE volunteer types:

```
What's the distribution of contrast_bolus_volume across CT studies?
```

Talking points:
- "Full loop. Explore mode answered questions from bronze. When we hit the
   ceiling, Generate mode built the pipeline. Now querying silver with the
   new column."
- "Prompt to pipeline edit to queryable column — under 5 minutes."
- "Lima's team can do this themselves. No SA needed in the room."

---

## Block 7: Wrap (2:25–2:30) — 5 min

**Owner:** Samuel + Camila close

### 2:25–2:27 — Quick reflection

> "What did you see that you didn't expect?"

If silence:
- "What's the next tag your team would want to add?"
- "What questions do you ask of DICOM data today that this doesn't handle?"

### 2:27–2:29 — Hand-off

Three commitments:

1. **The skill is theirs.** User-scope path — Lima's team edits `SKILL.md`,
   changes apply immediately.
2. **The pipeline is theirs.** Workspace code. Review diffs, version, deploy.
3. **What's next.** Adapt to what the audience surfaced. Likely: Genie space
   for non-technical users, working session in 2 weeks, extending the skill.

### 2:29–2:30 — Camila close

> "One skill that both answers questions from raw DICOM data and builds
> the pipeline when you need more. Lima's team owns both artifacts.
> Adding a tag to silver is a 3-minute ask, not a sprint."

Thank Lima, the DE volunteer by name, Kim, and Camila.

---

## Post-workshop (2:30+)

- Stay 10-15 min for any side conversations Lima or Camila want
- Walk out with concrete asks captured
- See `DEPLOY_TO_NWM.md` step 13 for the post-workshop signal capture

---

## What to do if things go sideways

### Silver table is empty

**Detection:** SELECT COUNT(*) FROM samuels_fevm_catalog.dicom_demo.dicom_series returns 0 at 12:55 PM.

**Recovery:**
- Don't panic. Run the pipeline manually now (from your laptop).
- 1-2 min wait.
- If still empty: bronze itself might be empty. Check.
- If bronze is also empty: load_sample_data didn't run. Run it now.
- Worst case: pivot the workshop to discussion-only, reschedule litmus test.

### Genie Code Agent mode toggle missing

**Detection:** You can't find the Agent mode toggle in the Lakeflow editor.

**Recovery:**
- Check workspace UI settings — partner-powered AI features
- Try the SQL editor instead — Agent mode also works there for non-pipeline
  contexts
- If nothing works: Block 6 (litmus test) is broken. Reframe: walk through
  the SKILL.md content as a "here's what would happen if Agent mode were
  enabled" demo. Capture the gap and follow up post-workshop.

### Litmus test prompt produces wrong diff

**Detection:** Genie generates the wrong extraction expression, uses the wrong
tag ID, or puts the column in only one of the three required locations.

**Recovery:**
- Don't fix it silently. Show the audience what's wrong.
- Frame: "This is what we mean by 'the skill teaches Genie about DICOM' —
  if the skill is wrong, this is exactly the failure mode. Let me show you
  where the skill defines this."
- Open SKILL.md, scroll to the relevant section. Walk through it.
- Manually fix the diff in the editor. Approve.
- Capture the gap; update the skill post-workshop.

### DE volunteer freezes

**Detection:** Awkward pause after they take the keyboard. They look unsure.

**Recovery:**
- "Want me to type the prompt? You're driving Approve when the diff appears."
- This breaks the freeze without taking ownership away.
- After the first prompt, they're usually unstuck.

### Audience hijacks with unrelated questions

**Detection:** Someone asks about DLT/Spark/Unity Catalog/other Databricks topic
that's tangential.

**Recovery:**
- "Great question — let me park that for the wrap discussion so we stay on
  the demo. Make a note: <topic>."
- Come back to it in Block 7 (wrap).
- Don't let the demo derail.
