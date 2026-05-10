# Workshop Runbook — May 14, 1:00–2:30 PM

90 minutes. NWM on-site. Lima Chatterjee + DE team (audience), Camila Altman
(observer), Kim Sierra (observer, owns post-meeting summary).

This is the minute-by-minute plan. Print or have on a tablet.

---

## Pre-session (12:30–1:00 PM)

- Arrive 30 min early
- Verify projector / screen sharing works
- Open these tabs in your browser:
  1. The NWM Lakeflow Pipelines UI showing dicom_silver
  2. The Lakeflow Pipelines Editor on dicom_silver.py with Agent mode enabled
  3. A new SQL Editor tab on the workspace
  4. `docs/workshop-prompts.md` open in a separate window or printed
- Confirm the DE volunteer is present and at the room
- Confirm the silver table has data: run a quick `SELECT COUNT(*) FROM silver.dicom_series`
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
   - "Walk through how DICOM analytics works on Databricks with this skill,
     then have one of you drive a hands-on extension. You'll leave with the
     skill and pipeline owned by your team."
2. **What this is and isn't** (2 min)
   - "This is a working artifact, not a demo. The skill goes to your user
     scope today. The pipeline is in your workspace as code. Lima's team
     owns these from the moment we leave."
   - "It's not a one-off — the skill is generic across DICOMweb workloads.
     Same thing works at any DICOM-shaped bronze. NWM-specific bits come
     from Discovery, not from the skill itself."
3. **What success looks like** (2 min)
   - "By 2:30 I want one of you to have added a tag to silver via Genie
     Code Agent mode in under 3 minutes. That's the litmus test. Everything
     before that is setup."
   - "I'll narrate while we go. Interrupt with questions — silence isn't
     useful here."

Show the architecture diagram (architecture.svg from the repo) on screen.
Walk through it in 60 seconds:
- Bronze (DICOMweb JSON, instance-level)
- SDP pipeline (type-adaptive, materializes silver)
- Silver (curated, series-level, ~30 named columns)
- EAV view (long-format for tag-discovery questions)
- Genie Code Agent mode reads two skills, generates SQL or pipeline edits

---

## Block 2: Discovery & Announcement (1:10–1:20) — 10 min

**Owner:** Samuel demos
**Audience:** watching, asking questions

### Setup

Open the Lakeflow Pipelines Editor on `dicom_silver.py`. Confirm Agent mode
is on (the toggle should be visible).

Or if doing this in a notebook is more familiar to the audience: open a fresh
notebook with Agent mode enabled. Either context works for the discovery
demo — the editor matters more for the litmus test in Block 4.

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
- "It found `silver.dicom_series` with N tag columns — those are the curated
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

## Block 3: Question Refinement (1:20–1:35) — 15 min

**Owner:** Samuel demos
**Audience:** watching

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

## Block 4: Litmus Test (1:35–2:05) — 30 min

**Owner:** DE volunteer drives
**Samuel:** sits next to them, narrates, doesn't take keyboard

### 1:35–1:40 — Setup

Move to the Lakeflow Pipelines Editor on `dicom_silver.py`. Agent mode on.

Have the DE volunteer take the keyboard. They sit. Samuel sits next to them.

Hand them the printed page with the prompt:

```
Add ContrastBolusVolume to silver as a DOUBLE.
```

### 1:40–1:50 — Run the prompt

DE volunteer pastes and presses Enter. Watch Genie work.

Narrate in real time:
- "It's reading both skills now — the dicom-analytics skill for tag info,
   and the pipelines skill for SDP framework."
- "It's looking up ContrastBolusVolume — that's tag (0018,1041), VR=DS,
   single-value DOUBLE."
- "Now it's editing the file. Adding the line in two places — the
   bronze projection and the silver aggregation."

When the diff appears, walk through it with them:
- The `ds_first("00181041").alias("contrast_bolus_volume")` line in
   `bronze_dicom_extracted`
- The `F.first("contrast_bolus_volume", ignorenulls=True).alias(...)` line
   in `dicom_series`
- Why both: extraction at instance-level happens once, then aggregates
   to series-level

Have the DE volunteer click Approve.

**Time check:** if you're past 1:50 and the diff isn't approved, something
is slow. Move on — don't re-prompt. Frame: "First skill load is always
slower; subsequent edits are faster."

### 1:50–1:58 — Run the pipeline with the new column

In a separate terminal or via the workspace UI, run the pipeline:

```bash
databricks bundle run dicom_silver --target nwm
```

Or via UI: trigger a full refresh.

While it runs (1-2 min), use the time to talk:
- "This is now in your pipeline as code. Same workflow for any new tag."
- "Your team owns this artifact. Edit it, version it, review it like any
   other code."

Verify in SQL after the run completes:

```sql
DESCRIBE TABLE silver.dicom_series
-- contrast_bolus_volume should appear
```

### 1:58–2:05 — Prompt 3.2 — query the new column

DE volunteer types or pastes:

```
What's the distribution of contrast_bolus_volume across CT studies?
```

Expected: Genie re-runs Discovery (sees the new column), might ask 1-2
clarifying questions (time window, manufacturer scope), generates a
percentile distribution query against silver.

Talking points:
- "From prompt to working pipeline edit to query against the new column —
   under 5 minutes total."
- "Lima's team can do this themselves. You don't need a Databricks SA in the
   room for this."

---

## Block 5: Wrap (2:05–2:30) — 25 min

**Owner:** Samuel + audience discussion → Camila close

### 2:05–2:15 — Audience reflection

Open question: "What did you see that you didn't expect?"

Let it run. The DE team will surface things — confusion, ideas, requests.
Capture them in your notes (or a Slack channel for later vault capture).

If silence, prompt:
- "What's the next tag your team would want to add?"
- "What questions do you ask of DICOM data today that this skill doesn't
   handle?"
- "What about other kinds of imaging metadata — pathology, ophthalmology?"

### 2:15–2:25 — Hand-off and roadmap

Three concrete things you commit to:

1. **The skill is theirs as of today.** Walk through the user-scope path one
   more time. Lima's team can edit `SKILL.md` and the changes apply
   immediately.
2. **The pipeline is theirs.** It's in their workspace as code. They can
   review diffs, version, deploy.
3. **What's next.** This is where you adapt to what the audience surfaced.
   Likely candidates:
   - Connecting silver to a Genie space for non-technical users
   - Adding a third workstream — pathology DICOM, dose monitoring dashboard,
     etc.
   - Working session in 2 weeks to extend the skill based on real questions
     they hit

### 2:25–2:30 — Camila close

Camila wraps. Sample text she can use (give her this Wednesday evening so
she's not improvising):

> "What we just saw: a working DICOM analytics layer with self-discovering
> skill behavior. Lima's team owns these artifacts as of today — the skill
> at user scope, the pipeline as code in our workspace. Adding tags is now
> a 3-minute ask, not a sprint. Where this goes next: <fill in based on the
> conversation>."

If she defers to you, you can deliver the same close.

Thank Lima, the DE volunteer by name, Kim, and Camila.

---

## Post-workshop (2:30+)

- Stay 10-15 min for any side conversations Lima or Camila want
- Walk out with concrete asks captured
- See `DEPLOY_TO_NWM.md` step 13 for the post-workshop signal capture

---

## What to do if things go sideways

### Silver table is empty

**Detection:** SELECT COUNT(*) FROM silver.dicom_series returns 0 at 12:55 PM.

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
- If nothing works: Block 4 (litmus test) is broken. Reframe: walk through
  the SKILL.md content as a "here's what would happen if Agent mode were
  enabled" demo. Capture the gap and follow up post-workshop.

### Litmus test prompt produces wrong diff

**Detection:** Genie generates `cs_first` instead of `ds_first`, or hardcodes
the wrong tag ID.

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
- Come back to it in Block 5.
- Don't let the demo derail.
