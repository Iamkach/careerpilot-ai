# Problem

Stage 7's Playwright layer (`scripts/autoapply_browser.py`) gates on
`FILLABLE_CHANNELS = {greenhouse, lever}` — 15 of 450 actionable tracker rows. Three defects
compound past that headline:

1. **It rarely fills even where it routes.** `autoapply.py:757-760` — a job with any unresolved
   *required* field is marked `Needs Human: Question` and `continue`s **before** the browser opens.
   Both real-schema answer sheets in `output/applications/` hit that gate (Customer.io 65% of
   fields resolved, Anthropic 45%). Effective Greenhouse fill rate is near zero, not 3%.
   **Confirmed 2026-07-30, no longer an estimate:** a full-backlog dry run (`--stage 7 --dry-run
   --limit 341`, after filling the profile's last 7 blank presets) found 12/341 (3.5%) rows on
   Greenhouse, of which only 2 came back READY — **2/341 ≈ 0.6% of the backlog actually reaches
   the browser.** The other 9 blocked on required, company-specific knockout questions (e.g.
   Customer.io's "have you worked for a company that uses Customer.io") that no generic preset
   bank can ever close — see `spec/auto-apply-subsystem/plan.md` §11 for the full per-job
   breakdown. Zero Lever rows exist in the tracker to measure at all.
2. **It runs anonymous.** `autoapply_browser.py:165-169` — fresh context, no cookies, no storage
   state. Anything behind a login is structurally unreachable. `_classify_block()` runs *once*
   after navigation, so a late-mounting captcha surfaces as `drift`, not `captcha`.
3. **The proposed extension of it has a ~13% ceiling.** `resolve_ats_posting()` + `gh_jid`
   detection + ashby converts ~9/69 sampled rows — and each still has to clear defects 1 and 2.

So the real ceiling is 13% × (fields fully resolved) × (no auth wall) × (no late captcha).

## The scoping error that parked this plan (do not re-derive)

`docs/research/sourcing-bottleneck-analysis.md` sized an extension at "~18 Indeed jobs" and
concluded it wasn't worth building. **That number counted rows the pipeline can auto-route to a
fillable URL.** An extension routes nothing — the human navigates, and it fills whatever form is
on screen. Its denominator is *every application opened by hand*: Workday, Ashby, vanity-domain
Greenhouse, and the Phenom-style career sites reached **through** a LinkedIn posting.

The measured "LinkedIn exposes no apply URL, 0/20" finding constrains *automated routing* and says
nothing about a human already standing on the form. That is the single reason this moved from
parked to queued.

## Why the extension is a different substrate, not an increment

Playwright needs to *derive* the URL, *know* the schema, and *survive* auth/captcha anonymously.
The extension removes all three at once: you navigate, the live DOM is the schema, and you are
already past auth and captcha. Ashby, Workday and arbitrary custom forms become one code path.

**Honest cost:** a second UI surface in a language this repo has no test runner for, an HTTP bridge
that serves personal data to a browser, and it is **interactive only** — it does nothing for an
unattended run, so it complements the Playwright layer rather than replacing it.

**Honestly not solved:** per-ATS account creation and email verification (Workday tenants). Being
logged in helps, but the tenant account must already exist. Do not gate this project on Workday.
