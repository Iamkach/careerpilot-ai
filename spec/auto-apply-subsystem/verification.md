# Verification

**Automated (Phases 1-2, already green):** `pytest tests/test_autoapply_plan.py
tests/test_autoapply_notion.py tests/test_autoapply_browser.py tests/test_autoapply_profile.py
tests/test_setup_notion_schema.py -v`. `tests/test_autoapply_notion.py` specifically asserts
`WRITABLE_STATUSES` excludes `Applied` and that `autoapply_browser.py` has no submit code path.

**Manual, already run:**
- `python run.py --stage 7 --dry-run --limit 341` — full-backlog readiness measurement (2026-07-30):
  channel mix 229 linkedin / 82 indeed / 12 greenhouse / 11 unknown / 7 ashby / 0 lever; of the 12
  Greenhouse rows, 2 READY, 9 NEEDS HUMAN (company-specific knockout questions), 1 PARTIAL (a
  posting that 404s). Net effective Greenhouse fill rate ~17% of an already 3.5%-wide channel
  (2/341 ≈ 0.6% of the full backlog).

**Still to run, before Phase 3/4 work starts (see acceptance-criteria.md's residual-gaps list):**
1. `python run.py --stage 7 --fill` (not `--dry-run`) against a live, currently-open Greenhouse
   job — the Layer-2 fill path has never opened a real browser against a live form.
2. Confirm `python scripts/setup_notion_schema.py --apply` has been run against the live tracker.

**Verification for Phase 3, once started:** a submit attempt on a deliberately non-knockout,
captcha-free Greenhouse posting actually reaches Notion `Applied` only via the explicit
`--submit --yes-i-mean-it` path; confirm the daily cap blocks a submit attempt past the limit;
confirm an Ashby captcha during a submit attempt hands off cleanly rather than retrying.

**Verification for Phase 4, once started:** an agentic run against a real Workday form is observed
end-to-end (not just unit-tested) and confirmed to pause for human confirmation before any submit
action; confirm no field is filled with a guessed eligibility/salary/sponsorship answer.
