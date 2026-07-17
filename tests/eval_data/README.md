# Hand-labeled eval dataset (Step 9 Phase 5)

`jobs.json` — 10 job description + expected-outcome pairs used by `scripts/run_evals.py` to
track the AI's actual *judgment* quality (scoring, sponsorship/company-type classification,
missing-keyword recall, and tailoring lift), against the real Anthropic API. This is **not**
the same thing as `tests/fixtures/recorded_ai_responses/` (Phase 3a) — those are raw recorded
responses replayed by mocked contract tests in CI to check plumbing; this dataset is scored
live, manually, and never touches CI.

## Format

Each entry:

| Field | Meaning |
|---|---|
| `id` | Stable slug, used in eval output |
| `company`, `title`, `url`, `description` | Same shape `score_jobs_batch` expects |
| `expected_score_min` / `expected_score_max` | Human-assigned plausible ATS score range |
| `expected_missing_keywords` | Keywords a competent human reviewer would flag as gaps vs. `config/resume.txt` |
| `expected_sponsorship` | `yes` / `no` / `unknown`, per the JD's actual sponsorship language |
| `expected_company_type` | `product` / `staffing_or_consulting` / `agency` / `unknown` |
| `notes` | Why this entry is in the set / what it's meant to exercise |

Two entries (`empty-description`, `garbled-description`) are **observational only** — their
score range intentionally spans 0-100 and `scripts/run_evals.py` excludes them from the
score-hit-rate / keyword-recall aggregates. They exist to see how the real model actually
responds to a degenerate JD, not to assert a specific outcome.

## Provenance

This initial set is hand-authored to bracket realistic match qualities (strong/medium/weak
tech overlap, a staffing-agency posting, explicit sponsorship denial, an ambiguous
existing-employees-only sponsorship case, and a couple of adversarial/degenerate JDs) against
the resume currently in `config/resume.txt`. It is a seed set, not a substitute for real scraped
JDs — as real jobs get manually reviewed in Notion, swap in ones with genuinely surprising or
disputed scores to keep the dataset honest. Keep it small (8-12 entries): this is a manual,
opt-in check run around prompt/model changes, not a large-scale benchmark.

**If `config/resume.txt` changes meaningfully** (new role, new skills), the `expected_*` fields
here should be re-reviewed by hand — they were labeled against a specific resume snapshot and
will silently go stale otherwise.

## Running

```bash
python scripts/run_evals.py                  # stage 1 scoring + keyword recall only
python scripts/run_evals.py --tailor          # also run stage 2 tailoring + ATS delta
python scripts/run_evals.py --comp-check      # also print a stage 6 negotiation-brief sample
```

Requires a real, working `AI_PROVIDER` (default `claude`, needs `ANTHROPIC_API_KEY`). Costs
real tokens — run manually around prompt or `QUALITY_MODEL`/`AI_MODEL_OVERRIDE` changes, not on
a schedule. Never invoked by `run.py`, `--evaluate`, `nightly-pipeline.yml`, or `tests.yml`.
