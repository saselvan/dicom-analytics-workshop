# NWM Pre-flight Checklist — May 11–13

You're back from being out Wed–Fri May 6–8. You have three working days to
deploy the workshop artifacts to NWM and verify everything is ready before
Thursday May 14, 1:00 PM.

This checklist is sequenced. Don't skip ahead — each step depends on the prior.

---

## Day 1: Monday May 11 — Coordination

### Owner: Samuel + Kim Sierra (AE) + NWM infra contact

**1. Send pre-workshop note to Kim and Camila**

Brief — confirms timing, format, and asks Kim to nudge Lima on:
- DE volunteer identification (the person who'll drive the litmus test)
- Sample data status (NWM bronze available, or use IDC fallback?)

Sample text:
> "Confirming Thursday May 14, 1:00–2:30 PM at NWM for the DICOM analytics
> workshop with Lima's DE team. Two pre-flight items I need closed by
> Wednesday: (1) Lima identifies a DE volunteer who'll drive the hands-on
> portion — they'll need write access to their `/Users/<them>/.assistant/skills/`
> path; (2) confirmation on whether we're using NWM bronze data or the IDC
> public sample I have queued up. Camila — anything you'd like me to weave
> into the opening, let me know."

**2. Identify NWM infra contact for skill rollout**

You've referenced an "infra-person" pattern at NWM for skill installs. Get the
name and confirm they're available for a 30-min sync Tuesday or Wednesday.

**3. Verify Genie Code Agent mode is enabled in NWM workspace**

Confirm with NWM admin:
- Partner-powered AI features enabled at account + workspace level
- Workspace is in a supported region for Agent mode
- The DE volunteer (once identified) has the necessary permissions

**Blocking:** If Agent mode isn't enabled, the workshop is structurally broken.
This is the single most important pre-flight item. If it's not on, escalate
through Kim immediately.

---

## Day 2: Tuesday May 12 — Deploy

### Owner: Samuel + NWM infra contact

**4. Skill install to DE volunteer's user scope**

Once the DE volunteer is identified:

```bash
cd dicom-analytics-workshop
./scripts/install_skill_to_workspace.sh <de-volunteer-email> nwm
```

If the NWM workspace requires a different install pattern (per the
infra-person's standard), align format with their convention before proceeding.
Don't fight existing patterns — match them.

Verify the skill is at the expected path:
```bash
databricks --profile nwm workspace ls /Users/<de-volunteer>/.assistant/skills/dicom-analytics
```

Should list `SKILL.md` and `reference/`.

**5. Verify `databricks-spark-declarative-pipelines` skill is also present**

The litmus test depends on Genie composing both skills. Either:
- It's already at the user scope (pre-installed by Databricks AI Dev Kit)
- Install it alongside dicom-analytics

Check the current state:
```bash
databricks --profile nwm workspace ls /Users/<de-volunteer>/.assistant/skills/
```

If not present, install from the AI Dev Kit (your infra contact will know the
canonical source).

**6. Deploy the asset bundle to NWM workspace**

```bash
databricks bundle deploy --target nwm
```

This deploys:
- The dicom_silver pipeline (configured but not run)
- The 01_load_sample_data, 02_create_views, 03_smoke_tests notebooks

Validate the deployment via the workspace UI: pipeline should appear in
Lakeflow Pipelines, notebooks in the configured location.

**7. Load sample data**

If using NWM bronze: configure the pipeline's `dicom.bronze_table` parameter
to point at Lima's existing bronze table. Skip step 7.

If using IDC fallback (more likely): run the load_sample_data notebook to
create a demo bronze:

```bash
databricks bundle run load_sample_data --target nwm
```

This creates `<catalog>.dicom_demo.dicom_raw` with ~1,000 synthetic instances.

**8. Run the pipeline once**

```bash
databricks bundle run dicom_silver --target nwm
```

Watch the Lakeflow Pipelines UI for the run. Should complete in 1-2 minutes.
Verify silver materialized:

```sql
SELECT COUNT(*) FROM <catalog>.<schema>.dicom_series
SELECT modality, COUNT(*) FROM <catalog>.<schema>.dicom_series GROUP BY 1
```

**9. Create EAV view and PS3.6 lookup**

```bash
databricks bundle run create_views --target nwm
```

Verify:
```sql
SHOW TABLES IN <catalog>.<schema>
-- expect dicom_series, dicom_tags_long view, ps36_keyword_lookup
```

**10. Run smoke tests**

```bash
databricks bundle run smoke_tests --target nwm
```

All Phase 1 (VARIANT) tests should PASS. Phase 2 (STRING) is optional in NWM —
only run if you want to verify both formats. For workshop prep, Phase 1 is
sufficient.

---

## Day 3: Wednesday May 13 — Dry run

### Owner: Samuel solo

**11. Walk through workshop as Samuel + DE volunteer (acting as both)**

Open `docs/workshop-prompts.md`. Run every prompt yourself in NWM workspace:

- Section 1: Discovery & Announcement (5 min)
  - "Help me query the DICOM data"
  - Verify announcement appears with NWM-specific schema
  - Verify the discovered tag list matches what you expect from the silver

- Section 2: Question Refinement (10 min)
  - "Show me slice thickness" → should ask 2-3 questions
  - "Find CT studies with slice_thickness < 0.75 mm in the last 12 months"
    → should proceed silently, apply LOCALIZER exclusion
  - "I want to understand our scanner fleet" → should show 3-4 candidates

  Spot-check from `tests/test_skill_question_refinement.md`: TC-08, TC-13,
  TC-17, TC-20, TC-25 (one from each category that matters).

- Section 3: The litmus test (30 min) — most important
  - "Add ContrastBolusVolume to silver as a DOUBLE"
  - **Time it.** If it takes more than 3 minutes, identify what's slow:
    - Is Genie taking long to plan? (skill might need pruning)
    - Is the diff complex? (pipelines skill issue)
    - Is the user (you) confused by the diff format? (workshop framing issue)
  - Verify the diff is correct: ds_first call added in both views, with
    correct tag ID 00181041 and DOUBLE type

  After approval, run the pipeline:
  ```bash
  databricks bundle run dicom_silver --target nwm
  ```

  Then: "What's the distribution of contrast_bolus_volume across CT studies?"
  Verify Genie generates a percentile distribution query against silver
  (Template 2 pattern), with default time window mentioned inline.

**If any step fails or feels rough:** debug now. There is no Thursday morning
buffer to fix things — the workshop is at 1 PM.

**12. Brief Camila and Kim**

Send a final pre-workshop note Wednesday evening:
- Confirms everything ready
- Confirms DE volunteer identified
- Brief for Camila: opening welcome (2-3 min, no specific content needed),
  closing takeaways (2-3 min, sample text below)

Sample close-out text for Camila:
> "What we just saw: a working DICOM analytics layer with self-discovering
> skill behavior. Lima's team owns these artifacts as of today — the skill
> at user scope, the pipeline as code in our workspace. Adding tags is now a
> 3-minute ask, not a sprint. Next steps: <to be filled in based on
> conversation during the workshop>."

For Kim:
- No speaking slot. Note-taker / observer.
- Owns the post-meeting summary email (within 24 hrs of the workshop).

---

## What can go wrong and how to recover

### Genie Code Agent mode is OFF

**Detection:** Workspace admin says it's not enabled, or you can't find the
Agent toggle in Lakeflow Pipelines Editor.

**Recovery:** If discovered before Wednesday, escalate immediately through Kim
and the NWM admin. Agent mode requires account-level config; can take 24-48 hours
to enable. If discovered Wednesday afternoon, you have a problem — pivot the
workshop to a Chat-mode demo of skill content (read aloud the SKILL.md, walk
through the templates) and reschedule the hands-on portion.

### Skill doesn't appear in Agent mode

**Detection:** You install the skill, open the editor, but Agent mode doesn't
load it.

**Recovery:**
- Verify path is exactly `/Users/<email>/.assistant/skills/dicom-analytics/SKILL.md`
- Verify SKILL.md has the YAML frontmatter (name + description)
- Check workspace-level skill discovery setting (some workspaces require
  explicit registration)
- Worst case: install at a known-working path used by other Databricks skills
  in the workspace

### Discovery announces wrong schema

**Detection:** Genie's announcement names a different payload column or
identifier columns than expected.

**Recovery:** This is what Discovery is for — let Genie announce, correct it
in chat ("Actually, the payload column is X, not Y"). This becomes a positive
demo of the gated-discovery pattern. Samuel can frame it: "And this is exactly
why we don't let Genie just generate SQL — it tells us what it found, we
correct it, then it proceeds."

### Litmus test is slow

**Detection:** Adding ContrastBolusVolume takes > 3 minutes.

**Recovery:**
- Don't time it explicitly during the workshop if it's slow — let it complete
  naturally
- Talk through what Genie is doing while it works
- After approval, frame the speed as "first time loading both skills always
  takes a moment; subsequent edits are faster"

### DE volunteer is hesitant to drive

**Detection:** Awkward silence, "I don't know what to type," etc.

**Recovery:** Sit next to them, not across. Read the prompt aloud from the
sheet you printed. Let them paste it. They drive Enter. Frame it: "These are
the exact prompts I'd use; you're not improvising."

---

## Post-workshop (May 14, after the session)

**13. Capture session signals**

Before you leave NWM:
- Did the litmus test work in under 3 minutes? (yes/no/with caveats)
- Did the DE volunteer report they could repeat it unsupervised? (yes/no)
- Did Lima's team express interest in extending the skill? (specifics)
- Did Camila signal any next-step appetite? (specifics)
- Any ad-hoc questions during the session that the skill couldn't handle? (capture)

Email yourself the notes from the session. Will feed into the post-meeting
summary Kim owns.

**14. Update the skill if any gaps surfaced**

If during the workshop Genie generated wrong SQL or missed a clarifying
question, log it. Update the SKILL.md within a week. Lima's team should see
that ownership is shared and the skill improves over time.

**15. Capture this as a SA Intelligence Vault signal**

Use `:capture:` Slack reaction in your relevant Databricks channels for any
post-workshop notes. The vault MCP will pick them up.
