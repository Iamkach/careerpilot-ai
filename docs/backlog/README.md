# Backlog — implementing the `refinement-plans/` roadmap

Stories for executing the future-state changes identified in
[`../architecture/architecture-analysis.md`](../architecture/architecture-analysis.md) §C
(*Proposed future — `refinement-plans/`*) and detailed in
[`../refinement-plans/README.md`](../refinement-plans/README.md).

Five overlapping plan documents were consolidated into one strict execution spine (Step 0 → 7,
eight named conflicts C1–C8). This directory turns that spine into implementation-ready stories —
one file per step, plus one for the two fixes that don't need to wait for anything.

## Reading order

Work the stories **in numeric order**. Each one exists because it de-risks or unblocks the next;
landing them out of order means writing the same code twice (see the conflict notes inside each
story, and the consolidated list in the refinement-plans README).

| Story | What it does | Depends on | Size |
|---|---|---|---|
| [000-quick-fixes.md](000-quick-fixes.md) | Stage 6 crash fix + Windows encoding crash fix | none — slot anywhere | XS |
| [step-0-rotate-apify-token.md](step-0-rotate-apify-token.md) | Rotate the leaked `APIFY_API_TOKEN`, move to env | none — do now | XS |
| [step-1-sourcing-spike.md](step-1-sourcing-spike.md) | Measure real Stage-1 volume; resolve LinkedIn/Indeed actor questions | Step 0 (secrets hygiene) | S |
| [step-2-notion-schema-migration.md](step-2-notion-schema-migration.md) | Batch-add every new Notion property + fix the silent-failure writer | Step 1 | S |
| [step-3-dedup-selfmatch-fix.md](step-3-dedup-selfmatch-fix.md) | Fix "Interested" intake self-matching itself on dedup | Step 2 | XS |
| [step-4-filtering-pure-functions.md](step-4-filtering-pure-functions.md) | Word-boundary company matching + head/tail JD excerpt | Step 3 | S |
| [step-5-reliability-and-filtering-merge.md](step-5-reliability-and-filtering-merge.md) | Kill fabricated ATS score of 50; provider tiering, retries, `Retry` queue; merge in Plan 1's AI classification | Step 4 | L |
| [step-6-multi-source-phase1.md](step-6-multi-source-phase1.md) | Free ATS board sources (Greenhouse/Lever/Ashby) + cross-source dedup + real freshness | Step 5 | L |
| [step-7-communications-subsystem.md](step-7-communications-subsystem.md) | Stages 7–8: LinkedIn leads + Hunter-verified cold email, new Leads DB, GitHub Actions | Step 6 | XL |

## Conventions used in each story

- **Context** — why this exists, in the user's own problem terms.
- **Current behavior** — what the code does today, cited to `file:line`.
- **Acceptance criteria** — a checklist; a story is done when every box is checked and the listed
  verification steps pass.
- **Out of scope** — explicitly deferred to a later story, so scope doesn't creep sideways.
- **Files touched** — the expected diff surface.
- **References** — the source plan doc(s) and the architecture-analysis section to re-read for
  diagrams (component diagrams, sequence diagrams, the roadmap DAG) before starting.

## Source material

- [`../architecture/architecture-analysis.md`](../architecture/architecture-analysis.md) — the
  three-horizon LLD/ERD/component analysis this backlog implements. §C.7 has the dependency DAG,
  §C.8 the relative-effort Gantt, §D.1 the full risk register (R1–R15), §D.2 the open questions
  this backlog still needs answers to.
- [`../refinement-plans/README.md`](../refinement-plans/README.md) — the conflict analysis (C1–C8)
  and execution-order rationale each story below inherits.
- [`../refinement-plans/filtering/stage1-filtering-rework.md`](../refinement-plans/filtering/stage1-filtering-rework.md),
  [`../refinement-plans/reliability/hybrid-agentic-migration-plan.md`](../refinement-plans/reliability/hybrid-agentic-migration-plan.md),
  [`../refinement-plans/sourcing/scraping-sources.md`](../refinement-plans/sourcing/scraping-sources.md),
  [`../refinement-plans/sourcing/multi-source-sourcing.md`](../refinement-plans/sourcing/multi-source-sourcing.md),
  [`../refinement-plans/communications/communications-subsystem.md`](../refinement-plans/communications/communications-subsystem.md)
  — the five full plan docs. Each story below only excerpts what's needed to implement it; read the
  source doc's own "Verification" section before marking a story done.

## Open questions that block specific steps

These are unresolved decisions (architecture-analysis §D.2) — resolve the one named in a story
before starting it:

- **Q1 / C3 — status name.** `Retry`, `Needs Review`, or reuse `Human Review`? Blocks Step 5.
- **Q2 / C5 — JobSpy vs. Apify actor swap.** Step 1's spike resolves this.
- **Q3 / C4 — extract `classify_company_type()` standalone?** Decide in Step 5; affects Step 7.
- **Q4 — keep Indeed at all?** Zero listings historically; Step 1 informs this.
- **Q5 — Plan 4 Phase 2 ToS posture** (Glassdoor/Wellfound scraping). Not needed until a Phase-2
  story beyond Step 6.
- **Q6 — adopt GitHub Actions?** Required for Step 7; forces a metered-API provider split for CI runs.
- **Q7 — `Sponsorship = unknown` semantics.** Decide in Step 4/5.
