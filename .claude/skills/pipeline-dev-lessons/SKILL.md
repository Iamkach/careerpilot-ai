---
name: pipeline-dev-lessons
description: Working lessons for developing the local-n8n-engine job pipeline — how to verify branch state, audit plans against code, choose agentic vs API AI implementation, and make ATS resume tailoring verifiable. Use before merging branches, turning plan docs into work items, or touching stage2 tailoring / the AI provider layer.
---

# pipeline-dev-lessons

Lessons from a real session on this repo (branch review → merge `feat/maverick` → plan-to-TODO
conversion). Each rule is falsifiable and cites the incident or code that produced it.

## 1. `git fetch` before answering any branch-state question

**Local refs lie about remote state; the answer to "am I up to date?" is only valid post-fetch.**

Why it mattered: asked "do we have all changes from feat/maverick", local `git branch -a`
showed no `feat/maverick` at all and `git log feat/maverick..HEAD` errored with "unknown
revision". After `git fetch origin`, the branch appeared **9 commits ahead** (LinkedIn
Premium, Indeed scraper, Notion intake — real features, not noise). Answering from local
state would have reported "nothing missing."

Rule: run `git fetch origin` first, then compare with `git log --oneline HEAD..origin/<branch>`
(what they have that you don't) *and* the reverse (what you have that they don't). Report both
counts, not just "behind."

## 2. A fast-forward is not a merge — check ancestry before promising a merge commit

**If `HEAD` is an ancestor of the target, `git merge -m "..."` silently ignores your message and moves the pointer.**

Why it mattered: `git merge origin/feat/maverick -m "Merge feat/maverick..."` produced
`Fast-forward (no commit created; -m option ignored)`. Harmless here, but if the task had been
"record this integration as a merge commit" (e.g. so a revert boundary exists), the command
would have appeared to succeed while doing something else.

Rule: before merging, run `git merge-base --is-ancestor HEAD origin/<branch>` — exit 0 means
fast-forward will happen; pass `--no-ff` if a merge commit is actually required. Read the
merge output line, don't just check the exit code.

## 3. Verify absences with grep and pin claims to line numbers

**A claim like "no retry logic exists" is only trustworthy if stated as "zero matches for `retry|backoff|RateLimit` in these two files."**

Why it mattered: `plan/reliability-filtering-networking.md` is unusually reliable *because* it
was rebaselined against the real tip of `feat/maverick` with exact line numbers
(`AI_PROVIDER = "claude_code"` at settings.py:125, `_chat_claude_code` at utils.py:99-107)
and confirmed absences by search. An earlier draft of the same plan targeted a dev branch
that had **reverted** several of these changes — line-pinned claims are what caught that.

Rule: when auditing, cite `file:line` for every "X does Y" and a grep pattern + match count
for every "X doesn't exist." When *consuming* such a doc later, treat line numbers as
of-a-commit: re-grep the symbol names (they survive rebases; line numbers don't).

## 4. Transcribing a plan into a TODO is not thinking — diff the plan against project docs first

**Every plan recommendation that changes a default must carry a companion task to update the doc that states the old default, or the docs and code will diverge silently.**

Why it mattered: the first TODO.md faithfully transcribed the plan's "default `AI_PROVIDER`
to `"claude"` (metered)" — but CLAUDE.md documents `claude_code` as the default provider in
three places (the provider table, the key-design-patterns list, and the claude_code caveats
paragraph). The transcription flagged none of them. It also copied raw line numbers
(settings.py:125, stage1_scrape.py:570-572) that rot on the next commit, and omitted the
plan's own priority signal (§3 networking is gated on an unresolved research spike, yet got
the same checkbox weight as one-line fixes).

Rule: after drafting a TODO from a plan, grep the docs (CLAUDE.md, README, SETUP) for every
setting/behavior the plan changes and add an update task per hit. Replace line numbers with
symbol names. Anything gated on an unresolved decision gets exactly one checkbox: resolve
the gate.

## 5. AI implementation: agentic loop for supervised work, single-shot batched calls for unattended runs

**A 60-turn agentic loop on a capped subscription is the wrong shape for a cron job; deterministic stages with AI only at classification/generation points are.**

Why it mattered in this codebase: `workflow.py` drives the Agent SDK with
`max_turns=_MAX_TURNS` (=60) and forces subscription auth by popping `ANTHROPIC_API_KEY`
(workflow.py:34) — so one unattended morning run makes up to 60 capped calls with no retry,
no persisted state, and nondeterministic tool ordering; a usage-cap error mid-run kills the
process with no resume path. Meanwhile `run.py`'s stages already have the right unattended
shape: Notion-status idempotency (re-runs skip completed jobs), and stage 2's
batch-with-fallback pattern (`tailor_resumes_batch` → per-job `_tailor_resume_single` for
entries the batch parse missed) that turns N calls into 1 + failures.

Rule for this repo (the hybrid):
- **Unattended/scheduled** → `run.py` stages on metered API (`STAGE_AI_PROVIDER = "claude"`),
  every AI call single-shot JSON-out, batched where inputs share a cached prefix, wrapped in
  retry-with-backoff that explicitly does *not* retry usage-cap errors.
- **Interactive/ad hoc** (one outreach draft at the keyboard) → `workflow.py` agentic on
  subscription, where waiting out a cap costs nothing.
- Falsifiable check: if a code path can run from cron, it must not contain a `query()` loop
  with `max_turns > 1`.

## 6. ATS tailoring: an edit pipeline that can't report "edit didn't apply" is broken even when it runs green

**`apply_docx_edits` silently drops any edit whose `old` string doesn't match a paragraph verbatim — the run logs "✓ Saved" either way, so tailoring can be a no-op and nobody knows.**

Why it mattered: the whole stage-2 design hinges on the LLM echoing resume text
character-for-character into `old` (stage2_tailor.py SYSTEM_PROMPT: "character for
character"). But LLMs routinely normalize en-dashes, curly quotes, and double spaces, and
`apply_docx_edits` (render_docx.py) just does `if old in para.text` with no else-branch, no
counter, no log. Three compounding gaps, all confirmed in code:
1. Unmatched edits vanish silently (no applied/skipped count anywhere).
2. The batch path truncates JDs to 2000 chars vs the single path's 8000 — batch and fallback
   see different jobs, so keyword quality silently differs by which path ran.
3. The ATS score is computed once in stage 1 and **never re-scored after tailoring** — the
   pipeline's core metric cannot detect whether tailoring improved anything.

Rule — the best implementation is a closed loop, each step checkable:
1. **Anchor edits to extracted text**: `old` must be validated against
   `extract_docx_text()` output *before* opening the docx; reject the edit set if any `old`
   is unmatched, and retry once, feeding the LLM the exact paragraph it should have quoted.
2. **Normalize before matching**: compare with Unicode NFKC + whitespace-collapse; apply on
   the original run text at the matched paragraph.
3. **Count and log** `applied/skipped` per resume; a skipped edit is a warning in the run
   output, not silence.
4. **Verify after apply**: re-extract the saved docx and assert every `new` string is
   present.
5. **Re-score**: run the same stage-1 ATS scorer on (tailored text, JD) and write
   `ats_score_after` to Notion next to the original — the delta is the stage's only real
   success metric.
6. **Unify JD length** between batch and single paths so the fallback is a true retry, not a
   different experiment.

## 7. Done means pushed — and the deliverable includes the docs the change invalidates

**On this repo a stop hook rejects a turn with untracked files; treat "committed and pushed to the designated branch" as the definition of done, and fold doc updates into the same commit.**

Why it mattered: after writing TODO.md the session was stopped by
`stop-hook-git-check.sh` ("untracked files… commit and push"). The fix was one
add/commit/push — but the general failure it guards is real: work that exists only in a
container working tree is lost when the container is reclaimed.

Rule: end every work unit with `git status` showing clean, `git push -u origin <branch>`
succeeded, and any CLAUDE.md/README statements your change falsified updated in the same
commit (see lesson 4 for how to find them).
