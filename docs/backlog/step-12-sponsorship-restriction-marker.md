# Step 12 — Per-job sponsorship-restriction marker (vs. hardcoded company list)

**Status:** idea / not started.
**Priority:** low — no user pain today (`RESTRICTED_SPONSORSHIP_COMPANIES` is empty and the
existing gate already works for the one case it was built for).
**Depends on:** Stage 2 sponsorship gate (done) — `_sponsorship_gate()` in
`scripts/stage2_tailor.py:60-89`, `SPONSORSHIP_CONFIRMED_MARKER` release flow, `Notes`-field
plumbing already read by `db_get_jobs()`.
**Size:** S.

## 1. The problem with a hardcoded company list

`RESTRICTED_SPONSORSHIP_COMPANIES` in `config/settings.py` is a static, committed list of
companies believed to sponsor only existing employees, not new hires. Two things make that a
worse fit than it first looks:

- **Sponsorship policy is not static.** While reviewing recent postings, a company that had
  previously stopped sponsoring new hires had since reopened it — plausibly driven by AI-era
  hiring/budget shifts. A name added to the list based on one point-in-time observation would
  silently and permanently hold back every future posting from that company, with nothing
  prompting anyone to go back and re-check whether the block is still accurate.
- **The judgment is subjective.** "Not the right sponsor for me right now" is a personal call,
  not a durable fact about the company. Baking it into `settings.py` puts a subjective,
  time-sensitive opinion into committed source shared across every future run (and any fork of
  this repo), rather than keeping it where the rest of the pipeline's human judgment already
  lives — the user's own per-job review in Notion.

Given both, the decision for now is to leave `RESTRICTED_SPONSORSHIP_COMPANIES` empty rather
than populate it from this round of review.

## 2. Proposed direction — a per-job hold marker, symmetric to the existing release marker

The gate already has a *release* mechanism that is exactly the right shape: the user
personally confirms sponsorship for a new hire, then adds `SPONSORSHIP_CONFIRMED_MARKER`
(`"sponsorship confirmed"`) to that one job's Notion **Notes** field to move it back to
`Reviewed`.

The proposal is to add the mirror-image *hold* marker — e.g. `SPONSORSHIP_RESTRICTED_MARKER`
(`"sponsorship restricted"`) — that the user types into a specific job's Notes when they
personally judge that particular posting unsuitable. No `settings.py` edit, no redeploy, and
critically: the restriction is scoped to **that one posting at that point in time**, not a
standing ban on the company. The same company's next posting starts unrestricted by default,
exactly matching the "policy can change" reality above.

## 3. Design sketch (for whenever this gets built)

`_sponsorship_gate()` in `scripts/stage2_tailor.py:60-89` would hold a job back to
`Human Review` when *either*:

- `matches_company_list(job["company"], RESTRICTED_SPONSORSHIP_COMPANIES)` (existing path,
  kept as an opt-in escape hatch — see open question below), **or**
- `SPONSORSHIP_RESTRICTED_MARKER.lower() in job["notes"].lower()` (new path)

— same as today, unless `SPONSORSHIP_CONFIRMED_MARKER` is also present, in which case it's
released. `job["notes"]` is already populated by `db_get_jobs()` (`scripts/utils.py:446`), so
no schema change is needed — this is pure logic in `_sponsorship_gate()` plus one new setting
in `config/settings.py` (alongside `SPONSORSHIP_CONFIRMED_MARKER`).

Tests would mirror the existing structure in `tests/test_stage2_sponsorship_gate.py` — add
cases for: marker-only hold (no company-list match), marker + confirmed-marker together
(released), and a mixed batch where only the marked job is held.

`CLAUDE.md`'s "Stage 2 Sponsorship Gate" section would need a short addendum documenting the
per-job marker as the primary/expected way to restrict a job, with the company list demoted to
"for a genuinely persistent, well-documented case only."

## 4. Open question

Should `RESTRICTED_SPONSORSHIP_COMPANIES` stay on indefinitely as an opt-in escape hatch for
the rare case where a restriction really is durable and well-documented (e.g. a formal
statement from the company, not just one JD's silence), or should it be retired entirely once
the per-job marker ships, so there's exactly one restriction mechanism instead of two?
