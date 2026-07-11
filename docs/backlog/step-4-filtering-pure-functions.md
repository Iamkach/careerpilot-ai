# Step 4 — Filtering rework, pure-function half (Plan 1a)

**Priority:** P1 — first user-visible feature; highest value-per-line in the whole roadmap, and
directly answers the user's two standing complaints ("still mostly consulting/staffing companies",
"roles that don't sponsor keep slipping through").
**Depends on:** Step 3
**Blocks:** Step 5 (holds Plan 1b — everything touching `score_jobs_batch()` — until then; see
Conflict C1)
**Size:** S — pure functions, offline-unit-testable, no schema change beyond what Step 2 already
added, no AI call.
**Source plan(s):**
[`refinement-plans/filtering/stage1-filtering-rework.md`](../refinement-plans/filtering/stage1-filtering-rework.md)
§1-2 only (§3-9 are Plan 1b — deferred to Step 5, see below)

## Context

Two independent, purely mechanical bugs in Stage 1's filter layer:

1. **The denylist silently drops real product companies.** `is_skipped_company()`
   (`stage1_scrape.py:265-279`) docstrings "exact-name match" but does a **substring** test. Short
   `SKIP_COMPANIES` entries eat legitimate names: `"ust"` matches `"customer.io"`, `"igate"`
   matches `"navigate"`, `"dice"` matches `"indices"`, `"numero"` matches `"numerous"`.
   `"Qualcomm"` (`settings.py:43`) is a plain wrong entry. These drops happen before the AI ever
   runs and are only visible in the drop log.
2. **The sponsorship regex can't see the text it exists to catch.** `score_jobs_batch()` truncates
   each JD to 1500 chars (line 333). Work-authorization boilerplate lives in the EEO/legal block at
   the *bottom* of a JD — the truncation cuts it off before the model (or the regex safety net)
   ever sees it.

## What to do

### 1. Word-boundary company matching (`scripts/stage1_scrape.py`, `config/settings.py`)

Rewrite `is_skipped_company()` so **Layer 1** (`SKIP_COMPANIES`) matches on token
sub-sequences, not raw substrings. **Layer 2** (`SKIP_COMPANY_KEYWORDS`) intentionally stays
substring/phrase matching — entries like `"solutions llc"` are meant to match loosely; leave it.

Add module-level helpers:

- `_tokens(s)` — `re.findall(r"[a-z0-9]+", s.lower())`.
- `_strip_suffix(toks)` — trims trailing legal suffixes (`inc`, `llc`, `corp`, `ltd`, `co`, `plc`,
  …) so `"BeaconFire Inc."` still matches bare `"BeaconFire"`. Consider **keeping** `"group"`
  significant (don't strip it) — stripping it would broaden `"CGI Group"` to `"cgi"`, but both
  `"CGI Inc"` and `"CGI Group"` are already separate denylist entries, so nothing is lost by
  leaving it alone.
- `_subseq(haystack, needle)` — contiguous token sub-sequence test, anchored at token boundaries,
  so multi-word entries (`"Tata Consultancy"`, `"Booz Allen"`) still match correctly.
- `_SKIP_COMPANY_TOKENS` — precomputed once at import from `SKIP_COMPANIES`.

Also fix the misleading "exact-name match" docstring (line 267).

In `config/settings.py`: remove `"Qualcomm"` (line 43); fix the header comment (lines 18-20),
which currently says both layers are substring-matched.

### 2. Head + tail JD excerpt (`scripts/stage1_scrape.py`)

Add `_jd_excerpt(desc, head=1200, tail=800)`: return `desc` unchanged if short enough, else
`desc[:head] + "\n…[trimmed]…\n" + desc[-tail:]`. Use it in place of `j.get('description','')
[:1500]` wherever the JD is truncated for the AI prompt. Résumé truncation (`[:3000]`) is
unchanged — scoring reads from the top of a résumé and is unaffected.

## Acceptance criteria

- [ ] `is_skipped_company()` unit-tested (pure, no network) against the known false-positive/
      false-negative set:
      ```
      python -c "from scripts.stage1_scrape import is_skipped_company as f; print([f(c) for c in ['Customer.io','Navigate','Indices','Numerous','Qualcomm','Tata Consultancy Services','Jobs via Dice','TCS','BeaconFire','Insight Global']])"
      ```
      Expect `[False, False, False, False, False, True, True, True, True, True]`.
- [ ] `_jd_excerpt('A'*1000 + 'Z'*1000)` result contains both leading `A`s and trailing `Z`s.
- [ ] `"Qualcomm"` removed from `SKIP_COMPANIES`.
- [ ] `config/settings.py` header comment corrected to describe the actual (now word-boundary)
      Layer-1 matching behavior.
- [ ] Live run (`python run.py --stage 1`): confirm no `[COMPANY]` drop for a real product company
      previously caught by a false-positive substring match; confirm known staffing firms are still
      dropped correctly.

## Out of scope (deferred to Step 5 — Plan 1b)

Everything that touches `score_jobs_batch()`'s AI call and return shape: AI `company_type`
classification, the `scored`/fail-open flag, the `Sponsorship` write, `SKIP_COMPANY_TYPES`, the
`run()` drop/write branching on `scored`, and the `ingest_interested_from_notion()` changes.
Conflict **C1** means Plan 1 and Plan 2 both rewrite this function incompatibly — Plan 2's failure
model wins, so that whole surface is deferred to Step 5's merge rather than landed twice.

## Files touched

`scripts/stage1_scrape.py` (`is_skipped_company`, new `_tokens`/`_strip_suffix`/`_subseq`,
`_jd_excerpt`), `config/settings.py` (`SKIP_COMPANIES`, header comment).

## References

- Architecture analysis §D.1 risk register R11 (🟠).
- `refinement-plans/README.md` Step 4 and Conflict C1.
- `refinement-plans/filtering/stage1-filtering-rework.md` §1-2, and its "Verification" items 1-2.
