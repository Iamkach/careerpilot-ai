# Stage-1 filtering rework

## Context

The user reports that scraped jobs are "still mostly consulting/staffing companies" and that roles which don't offer visa sponsorship keep slipping through. The earlier plan doc (`plan/reliability-filtering-networking.md` §2, which this document supersedes — removed in `63b64e7`, readable via `git show 1030d71:plan/reliability-filtering-networking.md`) attributes this to substring-only company matching and to `sponsorship == "unknown"` passing through the gate.

Reading the code confirmed those, but found three sharper causes the plan doc missed:

1. **The denylist silently drops real product companies.** `is_skipped_company()` (`scripts/stage1_scrape.py:265-279`) has a docstring claiming "exact-name match," but line 274 does a substring test. Short entries in `SKIP_COMPANIES` therefore eat legitimate names: `"ust"` (settings.py:40) matches `"customer.io"`; `"igate"` matches `"navigate"`; `"dice"` matches `"indices"`; `"numero"` matches `"numerous"`. `"Qualcomm"` (settings.py:43) is a plain false entry. These drops happen before the AI ever runs and only surface in the drop log.

2. **The AI sponsorship check cannot see the text it exists to catch.** `score_jobs_batch()` truncates each JD to 1500 chars (line 333). Work-authorization boilerplate lives in the EEO/legal block at the *bottom* of a JD. The regex `jd_says_no_sponsorship()` (line 315) scans the full description, but the LLM pass — its own docstring calls it "a second-pass safety net" — never sees the end of the JD. It catches almost nothing.

3. **`score_jobs_batch()` fails open, silently.** Lines 380-381: any exception makes the *entire batch* return `score=50, sponsorship="unknown"`. Since the gate only drops `sponsorship == "no"`, every job in a failed batch is written to Notion with a fabricated score. Nothing is logged or raised. The per-job miss at line 369 has the same defect.

**Intended outcome:** company-type becomes AI-classified rather than pattern-matched, the denylist stops producing false positives, the AI can actually read sponsorship clauses, ambiguous sponsorship becomes visible in Notion, and AI failures produce visibly-flagged rows instead of fabricated scores.

**Out of scope** (per user): adding a `MIN_ATS_SCORE` gate, changing the AI provider, and the networking/sourcing stage (§1 and §3 of the plan doc).

## Design decisions (confirmed with user)

- AI batch failure → retry with backoff, then **fail open but flag**: write the jobs, but with `Status = "Needs Review"` and a null ATS score. Never fabricate 50.
- Company type → **fix the denylist AND add AI classification**. Denylist becomes a cheap word-boundary fast path; the LLM is the real net.
- JD truncation → send **head + tail** (~1200 + ~800 chars) so the legal block reaches the model.
- Sponsorship `"unknown"` → **keep the job, surface it in Notion** via a new `Sponsorship` select property. Lenient only; no strict-mode toggle.

---

## Changes

### 1. Word-boundary company matching — `scripts/stage1_scrape.py`, `config/settings.py`

Rewrite `is_skipped_company()` (stage1_scrape.py:265-279) so **Layer 1 (`SKIP_COMPANIES`) matches on token sub-sequences**, not raw substrings. Layer 2 (`SKIP_COMPANY_KEYWORDS`, settings.py:49-70) intentionally stays substring/phrase matching — entries like `"solutions llc"` are meant to match loosely.

Add module-level helpers next to the existing filters:

- `_tokens(s)` — `re.findall(r"[a-z0-9]+", s.lower())`. Normalizes punctuation, so `"BeaconFire Inc."` and `"customer.io"` both tokenize cleanly.
- `_strip_suffix(toks)` — trims trailing legal suffixes (`inc`, `llc`, `corp`, `ltd`, `co`, `plc`, …) so the denylist entry `"BeaconFire Inc."` still matches a bare `"BeaconFire"`.
- `_subseq(haystack, needle)` — contiguous token sub-sequence test. Multi-word entries like `"Tata Consultancy"` and `"Booz Allen"` match with both ends anchored at token boundaries.
- `_SKIP_COMPANY_TOKENS` — precomputed once at import from `SKIP_COMPANIES`.

Also fix the misleading docstring at line 267.

In `config/settings.py`: remove `"Qualcomm"` (line 43), and update the header comment (lines 18-20) which currently says both layers are substring-matched.

Consider dropping `"group"` from the legal-suffix set — stripping it broadens `"CGI Group"` to just `"cgi"`. Both `"CGI Inc"` and `"CGI Group"` are already separate list entries, so nothing is lost by keeping `"group"` significant.

### 2. Head + tail JD excerpt — `scripts/stage1_scrape.py`

Add `_jd_excerpt(desc, head=1200, tail=800)`: return `desc` unchanged if short enough, else `desc[:head] + "\n…[trimmed]…\n" + desc[-tail:]`.

Use it at line 333 in place of `j.get('description','')[:1500]`. Resume truncation (line 346, `[:3000]`) is unchanged — scoring reads from the top of a JD and is unaffected.

### 3. Retry with backoff — `scripts/utils.py`

Add `ai_chat_retry(prompt, system="", max_tokens=4096, quality=False, attempts=3, base_delay=2.0)` alongside `ai_chat` (utils.py:152-160). Retry at the `ai_chat` layer so all four `_BACKENDS` (utils.py:140-145) are covered at once, rather than editing each `_chat_*` function.

It **raises** on final failure — the fail-open policy belongs to the caller, not the wrapper. This is also the shared helper that plan-doc §1 wants for `stage3_outreach.py`; adopting it there is a separate follow-up.

### 4. Explicit failure signal — `score_jobs_batch()` (stage1_scrape.py:322-381)

Extend the prompt (lines 337-355) to also request `company_type: product | staffing_or_consulting | agency | unknown`, alongside the existing `score` / `missing_keywords` / `sponsorship`. Keep it a **single combined call** — a separate classify-first pass would add a second round-trip and a second failure surface to save haiku-priced tokens on a handful of jobs.

Replace the fake-50 defaults with a `scored` flag and a nullable score. Three cases the return shape must distinguish:

| Case | `score` | `scored` | `sponsorship` / `company_type` |
|---|---|---|---|
| AI returned this URL | `int` | `True` | as classified |
| Batch succeeded, URL missing from output | `None` | `False` | `"unknown"` |
| Batch failed after retries | `None` | `False` | `"unknown"` |

Call through `ai_chat_retry`. On exception, return the all-unscored list. Validate `company_type` against the four allowed values, falling back to `"unknown"` — mirroring how `sponsorship` is already normalized at lines 370-372.

`run()` must branch on `s["scored"]`, never on `score == 50`.

### 5. `run()` drop + write logic (stage1_scrape.py:565-592)

**Only apply AI-based drops when `scored` is `True`.** A failed batch marks everything `company_type="unknown"`; dropping on that would discard real jobs.

```
if s["scored"]:
    if EXCLUDE_NO_SPONSORSHIP and s["sponsorship"] == "no":  -> drop, "no-sponsor/AI"
    if s["company_type"] in SKIP_COMPANY_TYPES:              -> drop, "staffing/AI"

status = "Scraped" if s["scored"] else "Needs Review"
db_add_job({..., "ats_score": s["score"], "status": status, "sponsorship": s["sponsorship"]})
```

New setting in `config/settings.py`:

```python
SKIP_COMPANY_TYPES = {"staffing_or_consulting"}   # deliberately NOT "agency"
```

**Keep `agency`.** The label is ambiguous — creative/design/dev agencies hire FTEs and are legitimate employers. Staffing and recruiting agencies are already caught by the denylist, by `SKIP_COMPANY_KEYWORDS`, and by the `staffing_or_consulting` bucket. Putting the drop set in settings means `"agency"` can be added later without touching code.

### 6. `ingest_interested_from_notion()` (stage1_scrape.py:386-439)

Hand-picked jobs bypass every filter and must continue to. This path shares `score_jobs_batch()` (line 423), so it inherits `company_type` and the `scored` flag but applies **neither drop**.

It does adopt the rest: `status = "Scraped" if s["scored"] else "Needs Review"`, `ats_score = s["score"]` (may be `None`), and the `sponsorship` value — all passed through `db_add_job_linked` (utils.py:476-486). Replace the `{"score": 50}` default at line 427 with the unscored default.

### 7. Notion writer/reader — `scripts/utils.py`

`_notion_write_job()` (lines 300-320):
- Accept a caller-supplied status: `job.get("status") or "Scraped"`, replacing the hardcoded `"Scraped"` at line 312.
- Write the new `Sponsorship` select when `job.get("sponsorship")` is one of `yes` / `no` / `unknown`.
- **Change line 315 from `if job.get("ats_score"):` to `if job.get("ats_score") is not None:`.** The current truthiness test silently discards a genuine score of `0`, and is load-bearing for the null-score Needs-Review path.
- **Degrade gracefully if the `Sponsorship` property is missing** (see §8): catch the Notion 400, retry the create once without that property, and log a warning.

`_page_to_job()` (lines 266-282): add a `_prop_select(props, name)` reader beside `_prop_url` / `_prop_number` / `_prop_date` (lines 255-263), and surface `"sponsorship"` in the returned dict.

`_notion_promote_to_scraped()` (lines 400-423): take a `status="Scraped"` parameter, write `Sponsorship`, and apply the same `is not None` fix to its ATS write. `db_add_job_linked()` passes `job.get("status")` through.

`_EXTRA_TO_NOTION` (lines 324-329) needs no change — these are create-time properties. A `sponsorship` entry could be added later if `db_update_status` ever needs to set it.

**`workflow.py` needs no change.** Its `_task_scrape` does not call `stage1_scrape.run()`; `_impl_add_job_to_db` calls `db_add_job` without `status`/`sponsorship`, so it keeps defaulting to `Status="Scraped"` and simply omits the new property.

### 8. Notion schema — one manual step

The user must add one property to the tracker DB by hand:

- **`Sponsorship`** — type **Select**, options `yes`, `no`, `unknown`.

`Status = "Needs Review"` needs no pre-creation: Notion auto-creates new *select option values* when the property itself already exists, and `Status` does.

If the user forgets: Notion returns a 400 on the unknown property, and `_notion_write_job`'s blanket `except Exception: return None` (lines 319-320) collapses it into `db_add_job` raising `RuntimeError("Notion page creation failed")` (line 466) — so **every** stage-1 write dies, not just the sponsorship field. That is exactly why §7 adds the retry-without-`Sponsorship` fallback.

### 9. Drop log, counters, summary (stage1_scrape.py:444-467, 522-525, 596-606)

- Add `"company_type"` and `"needs_review"` to the `counters` dict.
- New drop reason `"staffing/AI"` via the existing `_log_drop()`. (`"no-sponsor/AI"` already exists at line 572.)
- Extend the summary string with `company-type:{n}`. Report `needs-review` separately from the drop counts — it is a *write* count, not a drop (e.g. `Added N (M flagged Needs Review)`).

### 10. Docs — `CLAUDE.md`

- Add `Needs Review` to the documented status pipeline (line 45) as a parallel state for unscored jobs, not a sequential stage.
- Add the `Sponsorship` (select) property to the "Notion database schema" list.
- Note in the stage-1 description that AI-classification failures write the job as `Needs Review` with a blank ATS score and are never dropped.

---

## Critical files

- `scripts/stage1_scrape.py` — filters, scoring prompt, `run()`, ingest path, drop log
- `scripts/utils.py` — `ai_chat_retry`, Notion writers/readers
- `config/settings.py` — `SKIP_COMPANIES`, new `SKIP_COMPANY_TYPES`
- `CLAUDE.md` — schema + status docs

## Verification

1. **Company matcher** (pure, no network):
   ```
   python -c "from scripts.stage1_scrape import is_skipped_company as f; print([f(c) for c in ['Customer.io','Navigate','Indices','Numerous','Qualcomm','Tata Consultancy Services','Jobs via Dice','TCS','BeaconFire','Insight Global']])"
   ```
   Expect `[False, False, False, False, False, True, True, True, True, True]`.

2. **JD excerpt**: `_jd_excerpt('A'*1000 + 'Z'*1000)` — result must contain both leading `A`s and trailing `Z`s.

3. **Failure signal**: monkeypatch `stage1_scrape.claude_chat` to raise, call `score_jobs_batch([...])` — assert every entry has `scored is False` and `score is None`. No `50` anywhere.

4. **Partial-miss signal**: patch `claude_chat` to return `"[]"` — same assertion (this exercises the line-369 path separately from the batch-failure path).

5. **Live run**: `python run.py --stage 1`. In the newest `output/filter_logs/dropped_*.txt`, confirm `[STAFFING/AI]` entries appear for a staffing firm that is *not* in `SKIP_COMPANIES`, confirm no `[COMPANY]` drop for Qualcomm, and confirm the summary shows the new `company-type:` count. In Notion, confirm scraped rows carry a `Sponsorship` value.

6. **Missing-property guard**: temporarily rename the Notion `Sponsorship` property, run one write, and confirm the page is still created with a logged warning rather than a `RuntimeError`.
