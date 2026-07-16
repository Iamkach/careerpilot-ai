# Backlog — remaining work

Steps 0-1, 2-6 (plus both quick-fixes' first item) are implemented and retired — see
[`../CHANGELOG.md`](../CHANGELOG.md) for what shipped and [`../TODO.md`](../TODO.md) for the
small gaps each left behind (a still-plaintext Apify token, a missing `encoding="utf-8"`, an
unlogged bare `except`, two unrun manual QA checks).

Four stories remain open:

| Story | What it does | Depends on | Size |
|---|---|---|---|
| [step-0-rotate-apify-token.md](step-0-rotate-apify-token.md) | Rotate the still-leaked `APIFY_API_TOKEN`, move to env | none — do now | XS |
| [step-7-communications-subsystem.md](step-7-communications-subsystem.md) | Stages 7-8: LinkedIn leads + Hunter-verified cold email, new Leads DB, GitHub Actions | Step 6 (done) | XL |
| [step-8-runtime-ai-mode-flag.md](step-8-runtime-ai-mode-flag.md) | `run.py --ai-mode {metered,hybrid,subscription}` — pick AI provider routing per invocation | none | XS |
| [step-9-evals-testing.md](step-9-evals-testing.md) | Phased pytest harness (mocked AI/Notion) + CI gate, plus a separate opt-in real-API quality eval layer | none | M-L |

Read `docs/TODO.md` first — it's the current index of exactly what's left, cross-referenced
to file:line. Each story here is the full spec for one TODO section.

## Source material

- [`../refinement-plans/README.md`](../refinement-plans/README.md) — the 1 remaining plan doc
  (4 are retired; see `../CHANGELOG.md`).
- [`../architecture/architecture-analysis.md`](../architecture/architecture-analysis.md) — the
  original three-horizon LLD/ERD/component analysis this backlog implements.
