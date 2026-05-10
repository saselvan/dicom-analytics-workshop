# Genie Code Skill Anatomy — How to Build Your Own

A guide for Lima's DE team. Explains how the `dicom-analytics` skill works
and how to build new skills using the same patterns.

---

## What is a Genie Code Skill?

A skill is a markdown file at `.assistant/skills/{name}/SKILL.md` in your
workspace. When you enable **Agent mode** in a notebook, SQL editor, or
Lakeflow Pipelines Editor, Genie reads any skills in your user scope and
uses them to guide its behavior.

That's it. No SDK, no API, no deployment pipeline. A markdown file in the
right place.

```
/Users/<your-email>/.assistant/skills/
└── dicom-analytics/
    └── SKILL.md          ← Genie reads this file
```

Skills are only active in **Agent mode** (not Chat mode). Genie auto-loads
relevant skills based on what you're doing.

---

## The dicom-analytics Skill — File Map

```
skills/dicom-analytics/
├── SKILL.md                          ← 552 lines — core logic, always loaded
├── domain-rules/
│   ├── exclusions.md                 ←  82 lines — LOCALIZER/SCOUT scope rules
│   ├── normalization.md              ← 120 lines — manufacturer + body part CASE
│   ├── parsing.md                    ← 121 lines — age, time, multi-value parsing
│   └── phi.md                        ← 213 lines — PHI handling, date precision
├── sql-patterns/
│   ├── direct-columns.md             ←  84 lines — top-level column access
│   ├── string.md                     ← 106 lines — STRING JSON extraction
│   └── variant.md                    ← 110 lines — VARIANT colon-path access
├── templates/
│   ├── bronze-patterns.md            ← 473 lines — vendor tags, sequences, multi-frame
│   ├── cohort-identification.md      ← 216 lines — multi-criteria cohort assembly
│   ├── coverage-audit.md             ←  99 lines — NULL rate, tag coverage
│   ├── distribution.md               ←  84 lines — percentile breakdowns
│   ├── dose-compliance.md            ← 144 lines — CTDIvol vs DRLs
│   ├── eav-exploration.md            ← 158 lines — tag inventory, value distribution
│   ├── manufacturer-thresholds.md    ← 103 lines — per-vendor threshold logic
│   ├── threshold-filter.md           ←  67 lines — single-threshold filters
│   ├── time-series.md                ←  97 lines — trend queries
│   └── utilization.md                ← 149 lines — scanner throughput, interpatient time
└── reference/
    └── typical-shape.md              ←  71 lines — common tag → column mapping
```

**Total: 18 sub-files, 3,049 lines across 4 directories.**

Most skills won't need this many files. The dicom-analytics skill is large
because DICOM is a complex domain with many question types, two payload
formats, and strict data conventions. A skill for a simpler domain (e.g.,
"query our claims data") might be 200 lines in a single file.

---

## Anatomy of a Skill File

### 1. Frontmatter — Tell Genie What You Are

Every SKILL.md starts with YAML frontmatter:

```yaml
---
name: dicom-analytics
description: |
  Generic schema-adaptive DICOM imaging metadata analytics on Databricks.
  Handles DICOMweb-format JSON payloads in bronze (STRING or VARIANT),
  discovers the user's curated columns at runtime, and adapts query
  generation to whatever silver schema exists.
when_to_use: |
  Use when the user asks about DICOM imaging metadata — modalities,
  manufacturers, scanner fleet, slice/acquisition parameters, study/series
  counts, tag exploration, protocol distributions, dose compliance,
  scanner utilization, cohort identification, or any analytics over the
  radiology imaging metadata layer.
---
```

| Field | What It Does |
|-------|-------------|
| `name` | Unique identifier. Genie uses this to reference the skill. |
| `description` | What the skill does. Genie reads this to decide whether to load it. |
| `when_to_use` | Activation trigger. Be specific — vague triggers cause Genie to load the skill for irrelevant questions, wasting context. |

**Key design choice:** `when_to_use` controls false positives. Too broad
("use for any data question") and the skill loads everywhere, polluting
Genie's context. Too narrow ("use only for CT slice thickness queries")
and users have to know the exact phrase. Match the vocabulary your team
actually uses.

### 2. Core Sections — What Every Skill Needs

The SKILL.md body has these sections (in order):

| Section | Purpose | Required? |
|---------|---------|-----------|
| **Overview** | 2-3 sentences: what domain, what output, what's generic vs customer-specific | Yes |
| **Sub-skill loading table** | Maps triggers → sub-files to load conditionally | Only if you have sub-files |
| **Context Detection** | Distinguish between execution contexts (e.g., ad-hoc vs pipeline) | If behavior varies by context |
| **Discovery Phase** | Runtime schema detection — what tables exist, what columns, what types | If your skill adapts to unknown schemas |
| **Question Refinement** | When to ask clarifying questions vs proceed | If questions are commonly ambiguous |
| **Routing Rules** | Which source to query based on what the user asked | If multiple data sources exist |
| **Workflow** | Step-by-step method for answering any question | Yes |
| **Constraints** | Non-negotiable rules (no DDL, no PHI, etc.) | Yes |
| **Error Recovery** | What to do when queries fail | Recommended |

You don't need all sections. A minimal skill needs: frontmatter + overview +
a few canonical examples + constraints. Everything else is progressive
complexity for complex domains.

### 3. Sub-Skills — Progressive Disclosure

Genie Code loads the entire SKILL.md into its context window. A 3,000-line
single file would waste context on irrelevant content. Sub-skills solve this
by splitting domain knowledge into separate files that load conditionally.

**The loading table** in SKILL.md maps triggers to sub-files:

```markdown
| Trigger | Sub-skill to load |
|---------|-------------------|
| Question class is "Distribution" | `templates/distribution.md` |
| Question class is "Dose compliance" | `templates/dose-compliance.md` |
| Generating manufacturer filter | `domain-rules/normalization.md` |
```

When the trigger condition matches, Genie reads that sub-file. When it
doesn't, the file stays unloaded and doesn't consume context.

**Sub-file format** — each starts with a header and loading trigger:

```markdown
# Template 2: Distribution / percentiles

Load when the user's question maps to "Distribution / percentiles" class.

## Use case
Protocol calibration, outlier detection, fleet characterization.

## Pattern
(SQL template with placeholder column names)

## Worked example
(Concrete SQL with real column names)

## Domain rules to apply
- `domain-rules/exclusions.md` — LOCALIZER/SCOUT
- `domain-rules/normalization.md` — body part CASE
```

No special frontmatter in sub-files. The header + "Load when" line is
sufficient for Genie to understand the file's purpose.

### 4. Four Sub-Skill Categories

| Category | What Goes Here | Example |
|----------|---------------|---------|
| **templates/** | SQL patterns for specific question classes. Each template handles one analytical shape (distribution, threshold, time series, etc.) | `templates/distribution.md` — percentile queries |
| **domain-rules/** | Non-obvious domain knowledge that affects multiple templates. Loaded alongside templates, not instead of them. | `domain-rules/exclusions.md` — which series types to exclude |
| **sql-patterns/** | Type-adaptive SQL access patterns. Loaded once during Discovery based on the payload column type. | `sql-patterns/variant.md` — VARIANT colon-path syntax |
| **reference/** | Static lookup data (tag mappings, typical column names). Loaded as a fallback when runtime lookup isn't available. | `reference/typical-shape.md` — 30 common tag→column mappings |

---

## The Discovery Pattern — Why It Matters

The most important architectural decision in this skill: **don't hardcode
table or column names.** Instead, discover them at runtime.

### Why

If the skill says `FROM silver.dicom_series`, it breaks the moment someone
puts that table in a different catalog, renames it, or hasn't created it yet.
Discovery makes the skill portable across workspaces without configuration
changes.

### How It Works (6 Steps)

```
Step 1: Identify the bronze payload column
        → Is it VARIANT or STRING? Probe a sample row.

Step 2: Disambiguate if multiple candidates
        → Ask the user which column holds the payload.

Step 3: Validate DICOMweb format
        → Confirm hex tag keys (00080060, 0020000D, etc.)

Step 4: Find companion surfaces
        → Search for curated silver, EAV view, PS3.6 lookup

Step 5: Inventory the curated surface
        → Map column names back to PS3.6 tag IDs

Step 6: Announce what was found
        → Tell the user before generating any SQL
```

**Step 6 is the gate.** Genie does NOT generate SQL until it announces
its assumptions and the user confirms. This prevents silent wrong answers
from schema mismatches.

### Adapting Discovery for Your Domain

You don't need 6 steps. For a simpler domain, Discovery might be:

```markdown
### Discovery

1. Run `DESCRIBE TABLE <user's table>` to inventory columns.
2. Announce: "I found columns X, Y, Z. Proceeding with these."
3. Wait for user confirmation before generating queries.
```

The principle: **announce before you generate, then adapt to what you find.**

---

## Question Refinement — Preventing Silent Wrong Answers

DICOM analytics requests are almost always under-specified. "Show me slice
thickness" could mean:

- Distribution (percentiles) — 5-row table
- Threshold filter (< 0.75mm) — list of study UIDs
- Coverage audit (% non-NULL) — data quality metric
- Time series (monthly trend) — line chart data

Without the skill, Genie picks one interpretation silently. With the skill,
it asks — but only when it actually needs to.

### The Placeholder-Count Rule

```
1. Map the request to a question class
2. Count how many parameters you'd have to GUESS
3. If guess count > 1 → ask. If 0-1 → proceed with inline assumption.
```

This prevents two failure modes:
- **Over-asking:** "What modality? What time window? What manufacturer?
  What granularity?" for every question (annoying, the user stops using it)
- **Under-asking:** Silently picking CT when the user meant MR
  (wrong answer, the user loses trust)

### Adapting for Your Domain

Identify your domain's ambiguity dimensions. For DICOM, they're: modality,
time window, manufacturer scope, output granularity. For claims data, they
might be: payer, date range, claim status, provider type.

Build a question class catalog with the common analytical shapes in your
domain. Each class has known parameters — when the user's request doesn't
fill them, ask.

---

## Worked Example: Building a Skill from Scratch

Suppose your team wants a skill for querying NWM's patient scheduling data.

### Step 1: Start with Frontmatter + Examples

```yaml
---
name: scheduling-analytics
description: |
  Query patient scheduling data — appointment volumes, no-show rates,
  wait times, provider utilization. Works on the scheduling silver table
  in Unity Catalog.
when_to_use: |
  Use when the user asks about appointments, scheduling, no-shows,
  wait times, provider schedules, or clinic capacity.
---
```

```markdown
# Scheduling Analytics

## Canonical Examples

### Appointment volume by department
SELECT department, COUNT(*) AS appt_count
FROM silver.appointments
WHERE appt_date >= current_date() - INTERVAL 30 DAYS
GROUP BY 1
ORDER BY 2 DESC

### No-show rate by day of week
SELECT dayofweek(appt_date) AS dow,
       COUNT(*) AS total,
       SUM(CASE WHEN status = 'NO_SHOW' THEN 1 ELSE 0 END) AS no_shows,
       ROUND(100.0 * SUM(CASE WHEN status = 'NO_SHOW' THEN 1 ELSE 0 END)
             / COUNT(*), 1) AS no_show_pct
FROM silver.appointments
WHERE appt_date >= current_date() - INTERVAL 90 DAYS
GROUP BY 1
ORDER BY 1

## Constraints
- No patient names or MRNs in output
- Always filter to a time window (default: last 30 days)
```

**That's a working skill.** ~30 lines. Genie reads it and generates
scheduling queries with the right table, the right conventions, and the
right constraints.

### Step 2: Add Discovery (When Ready)

Once you want portability (the skill works in multiple workspaces without
editing), add a Discovery section that probes for the actual table name
instead of hardcoding `silver.appointments`.

### Step 3: Add Sub-Skills (When the Skill Gets Big)

When your single SKILL.md exceeds ~300 lines and covers multiple distinct
question types, split into sub-files. Add a loading table. Each sub-file
handles one question class.

### Step 4: Add Domain Rules (When You Find Non-Obvious Gotchas)

When your team keeps hitting the same data quality issue (e.g., "appointment
status values are inconsistent across clinics"), encode it as a domain rule
sub-file that Genie loads automatically when generating status-related
queries.

---

## Design Principles

### 1. Start Small, Decompose When Needed

A 30-line skill with 5 examples is better than a 500-line skill that took
a month to write. Ship the small version. Add complexity when you hit real
problems — not before.

### 2. Examples Are the Most Important Content

Genie learns primarily from examples. Five well-chosen SQL examples teach
Genie more than five pages of prose describing your schema. Each example
should show the **question** (as a comment) and the **SQL** (as the answer).

### 3. Constraints Prevent Silent Failures

If there's a rule that should NEVER be violated (no PHI in output, always
exclude test patients, always use a time filter), put it in a `## Constraints`
section. Genie treats constraints as hard rules, not suggestions.

### 4. Discovery Makes Skills Portable

Hardcoded table names break when the skill moves to a different workspace
or catalog. Discovery (even a simple `DESCRIBE TABLE`) makes the skill
adapt to whatever schema it finds.

### 5. Progressive Disclosure Protects Context

Genie's context window is finite. A skill that loads 3,000 lines of domain
rules for every question wastes context on irrelevant content. Sub-skills
with conditional loading triggers keep the working set small.

### 6. Announce Before You Generate

The single most valuable pattern in the dicom-analytics skill: Genie
announces what it discovered and what it's about to do BEFORE generating
SQL. This catches schema mismatches, wrong assumptions, and ambiguous
intent before they become wrong queries.

---

## Quick Reference

| Want To | Do This |
|---------|---------|
| Create a new skill | Write `SKILL.md` with frontmatter + examples + constraints |
| Make it portable | Add a Discovery section that probes `DESCRIBE TABLE` |
| Handle multiple question types | Add sub-files in `templates/`, reference via loading table |
| Encode domain gotchas | Add sub-files in `domain-rules/`, load when relevant |
| Support multiple data formats | Add sub-files in `sql-patterns/`, load based on Discovery |
| Test it | Open Agent mode, ask a question, check the SQL |
| Fix it | Edit the `.md` file. Changes apply immediately — no redeployment. |

---

## File Placement

Skills live at user scope:

```
/Users/<your-email>/.assistant/skills/<skill-name>/SKILL.md
```

Sub-files go in subdirectories under the skill:

```
/Users/<your-email>/.assistant/skills/<skill-name>/
├── SKILL.md
├── domain-rules/
│   └── your-rule.md
├── templates/
│   └── your-template.md
└── reference/
    └── your-lookup.md
```

Changes to any file take effect immediately. No restart, no redeployment,
no approval workflow. Edit → save → ask Genie a question → see the result.
