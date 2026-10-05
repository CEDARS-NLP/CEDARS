---
name: cedars-feature-map
description: Use when answering any question about CEDARS v2 (does a feature exist, how mature or tested it is, which role can use it, how a user reaches it, whether DEV on AWS runs it, how to prove it works), when onboarding someone to CEDARS, or after changing a CEDARS feature so the map stays true.
---

# CEDARS feature map

`features/` describes every CEDARS v2 product area at the behaviour level. For each area it records what exists, the maturity grade with evidence, how a user gets there, and how to drive it with `control-cedars` (the verify-cedars skill). `features/README.md` holds the rubric, the entry contract and the index. Read it first.

To show someone the map, run `.claude/skills/cedars-feature-map/render-map --open`. It turns `features/*.md` into one self-contained page at `/tmp/cedars-feature-map.html`, with tiles by maturity, filters, a journey overlay and per-row detail. It reads the markdown and never edits it, so re-run it after any edit. It exits non-zero when a table row breaks the contract.

**Core rule:** the map is a fast index. The source is the authority. Every answer cites file:line or test evidence and says how fresh it is.

## Answering a question

1. **Find the area.** Use the index in `features/README.md`. For questions that span areas, use `features/multi-surface-journeys.md`.
2. **Read the feature file.** Use the `Sub-features` row for the grade and evidence and `Gotchas` for traps. Don't stop at the first row that looks right.
3. **Check freshness.** Evidence paths are often short (`router.py:42`), so check the area's directories: `git log --oneline <Last verified sha>..HEAD -- backend/app/<area>/ frontend/src/projects/ backend/app/worker.py`. Then run `git status --short` for uncommitted changes, submodules included. If anything touched those paths, re-read the cited source before answering, and update the file (see Maintain).
4. **Deployed?** The grade describes the code at `Last verified`, not what DEV runs. Run `.claude/skills/verify-cedars/control-cedars aws status` (read-only), then compare against the row's `Since` commit. If credentials are expired, or you may not call AWS, say so and use the README snapshot with its date. Nothing calls DEV's app, so "on DEV" always means "DEV runs this code". Write "DEV runs code with this defect", never "I saw it on DEV".
5. **Answer** in this shape:
   - **Answer:** yes/no/partly, in one or two sentences.
   - **Maturity:** the grade and the reason (`beta`: works from the UI, but <gotcha>).
   - **Who:** roles, and whether the UI and the API agree.
   - **Where:** the UI path in on-screen labels, or "API only: `METHOD /path`".
   - **On DEV:** deployed, not deployed, or unknown, plus how you know.
   - **Evidence:** file:line, test names, the date of the last live drive.
   - **Confidence:** high / medium / low, and what would raise it.

For a quick question, fold these into a few sentences, but keep the maturity, the DEV status and at least one piece of evidence. If the map has no entry, answer from the source, label the answer `unmapped`, and add the row.

Evidence paths name the instance that produced them (`/tmp/cedars-verify/<instance>/evidence/`; list one with `CEDARS_VERIFY_INSTANCE=<instance> control-cedars evidence list`). `/tmp` is cleared on reboot. The feature files record the observed values, so a missing evidence file means "not re-checkable", not "failed".

## Grades in one line

`deferred` (out of scope by decision) < `stub` (code exists, doesn't do the job) < `api-only` (works, no UI reaches it) < `beta` (reachable, happy path works, a defect or coverage gap) < `stable` (reachable, tests pass on SQLite and Postgres, no known defect, driven live). Any known defect caps a sub-feature at `beta`. A source-only review writes `beta (stable pending live)`.

**Tests passing ≠ CI green.** `backend-v2.yml` has never passed: all 7 runs since it was added on 2026-07-06 failed (check with `control-cedars ci status`; it ignores runs on commits a force-push removed). The SQLite job fails at Lint, so its pytest step never runs in CI. Grades rely on local `control-cedars test backend [--postgres]` runs at the `Last verified` commit. Say so when test evidence matters to the answer.

## Maintain (pstack loop)

Run this after a feature change, or when step 3 finds drift.

1. **Source wave**, in parallel and read-only: one subagent per affected area file. Each one re-reads the cited source and the tests, re-grades every row, and returns its changes and its top defects. Give each the README contract. Subagents never mutate the shared stack.
2. **Live pass**, sequential, in the README sweep order:
   ```bash
   export CEDARS_VERIFY_INSTANCE=map-$(date +%Y%m%d)   # your own instance; the default is shared by every session in the checkout
   CC=.claude/skills/verify-cedars/control-cedars
   $CC doctor && $CC stack up && $CC seed
   ```
   Then run each file's "Driving it" bullets exactly. Capture ids with `api --field` and wait for async work with `api GET … --until PATH=VALUE`; never `sleep`. Record one `<id> PASS|FAIL|SKIP <evidence> <reason>` line per bullet. Put dates in `Live` only for rows that PASSed.
3. **Close each file** as one of three outcomes:
   - **clean**: no change; bump `Last verified`.
   - **changed**: rows or gotchas updated, with new evidence.
   - **blocked**: say what blocks it (credentials, Bedrock approval, Databricks workspace) and leave the grade.
4. **Prove it end to end.** Run `$CC cleanup --images`, then `$CC evidence list`. The evidence must survive cleanup. Update the README index `Overall` column.

## Common mistakes

| Mistake | Instead |
|---|---|
| Grading from docs, CLAUDE.md or commit messages | Grade what the code does; cite file:line |
| "It's on the branch, so it's live" | DEV lags the branch; check `aws status` against `Since` |
| Writing `stable` from source reading | `beta (stable pending live)` until a live PASS |
| Answering from a stale file | Run the step-3 freshness check first |
| "Tests cover it" without naming them | Name the test function; say whether it ran on Postgres |
| Treating the UI showing a button as permission | Role gating is enforced in the API; a mismatch is a defect |
| Fixing data with SQL to drive a feature | Use the UI or API path. If only SQL reaches the state, report it as a finding. CLAUDE.md allows a data fix only with the user's explicit permission for that statement |
| Putting account IDs, ARNs or internal hostnames in the map | The repo is public: names only |
