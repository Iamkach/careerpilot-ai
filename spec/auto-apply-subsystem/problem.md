# Problem

## What "auto-apply" means here

Before this subsystem, the pipeline stopped one step short of applying. After `--evaluate`, a job
sits at `Resume Tailored` with a tailored `.docx` and a digest line; **the human opens the job URL
and fills the application by hand.** No stage sets `Applied` — it is a manual Notion edit.

The request: once a job is `Reviewed`, drive the application submission itself. The core question
is *how far that can actually go per source*, and where a human must stay in the loop.

**The single most important finding up front:** there is **no candidate-usable application-submit
API** for the mainstream ATSes. Greenhouse's documented submit endpoint
(`POST /v1/boards/{token}/jobs/{id}`) requires the *employer's* board API key over Basic Auth
([Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)); Lever and Ashby's
submit APIs are likewise employer-authenticated. Only the **read** side (job list, JD, and the
`?questions=true` application-field schema) is public. Therefore **auto-apply is fundamentally a
browser-automation problem, not an API problem** — every real submit path is a rendered web form.

## The two automation levels

| | **Semi-auto (assisted)** | **Fully hands-off** |
|---|---|---|
| Behavior | Auto-fill every resolvable field, upload the tailored resume, then **pause for one human confirm before the final Submit click** | Attempt end-to-end submit with zero human input wherever technically possible |
| Captcha/auth | Hands off to human cleanly (this is the *designed* exit, not a failure) | Must solve or route around — captcha-solving services, residential proxies, stored sessions |
| Error blast radius | Low — human catches a mis-mapped field or wrong-JD before submit | High — a wrong answer to "are you authorized to work without sponsorship?" is submitted silently and is unretractable |
| ToS / ban risk | Low on ATS-hosted forms (candidate is present, one submit); still **do not** touch LinkedIn/Indeed Easy Apply | High — bulk automated submission is exactly what LinkedIn §8.2 and Indeed prohibit and actively flag |
| Reputational cost | You never send a bad application under your name | A hallucinated cover-letter answer or duplicate app reaches a real recruiter under your name |
| Effort to ship | S-M for the first source class | XL, per-site, ongoing maintenance treadmill |

**Recommendation (adopted):** default to **semi-auto everywhere**, and let the *source class*
decide how much of the form is pre-filled before the human confirm. Reserve any fully-hands-off
submit for a single, opt-in, low-risk class (Greenhouse-hosted forms with **zero** custom knockout
questions and no captcha), behind an explicit `--submit --yes-i-mean-it` flag and a hard daily cap.
Never fully automate LinkedIn/Indeed.

## Background: what's already shipped (Phases 1-2)

`scripts/autoapply.py` (Layer 1 — routing, schema read, answer resolution, gating, answer sheet,
Notion writes) and `scripts/autoapply_browser.py` (Layer 2 — Playwright pre-fill, no submit path)
are implemented, tested, and wired into `run.py --stage 7`. See plan.md's "Landed" section for the
full component map. The remainder of this problem statement — and the rest of this feature's
spec — is scoped to what's still open: Phase 3 (deliberate submit) and Phase 4 (the agentic long
tail, Workday/custom, via the Playwright route specifically — the interactive case is now covered
by `spec/application-prefill-extension/`).

## Research findings that shaped what shipped and what's deferred

Six findings from surveying existing open-source auto-appliers, researched before implementing:

1. **The flagship project is dead.** AIHawk / `Auto_Jobs_Applier_AI_Agent` — the most prominent
   open-source auto-applier — was archived read-only on 2026-05-17. Its selector-drift bug reports
   were closed *not planned*. Selector drift is what kills these projects.
2. **Bots lie about success.** AIHawk "claims to apply for jobs on pages where it hasn't actually
   applied."
3. **Recruiter-side bot detection is real.** ATSes flag mass-submitted applications as low-intent
   before a human reads them; mass-apply converts at 0.1-2%.
4. **LinkedIn thresholds quantified** (<15/day safe, 30+ red; ~23% of automation users restricted
   within 90 days), and one AIHawk bug had the bot clicking recruiter *message* buttons
   mid-conversation.
5. **Turnstile stalls silently** rather than erroring.
6. **Greenhouse does not server-side validate required fields**, and `?questions=true` is confirmed
   still live.

Also confirmed: no candidate-usable submit API exists anywhere — Greenhouse's docs explicitly warn
a direct POST "would reveal your secret key to anybody that views source," since the endpoint
authenticates as the employer. The browser-automation premise of this whole feature holds.

Sources: [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html) ·
[applications endpoint](https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_applications.md) ·
[AIHawk issues](https://github.com/AIHawk-FOSS/Auto_Jobs_Applier_AI_Agent/issues) ·
[LinkedIn automation ToS](https://northlight.ai/blog/is-linkedin-automation-against-the-rules) ·
[auto-apply detection](https://www.crossclassify.com/resources/articles/recruitment/how-to-detect-auto-apply-candidate-fraud-before-it-pollutes-your-ats/) ·
[Turnstile under Playwright](https://www.capsolver.com/blog/cloudflare/playwright-blocked-by-cloudflare-turnstile-causes-fix)

## Why the tracker is starved of ATS-fillable rows (measured 2026-07-29)

The often-quoted split (1 Greenhouse / 413 LinkedIn / 90 Indeed / 4 unknown of 508) counts
*posting* hosts, while fillability is decided by the *apply-form* host. A spike measured what
resolving the true apply-form destination (external redirect) would buy, including a live Apify
probe of both keyword actors at 20 fresh listings each:

- **LinkedIn: no apply URL exists.** 0/20 populated across `applyUrl`, `applyLink`,
  `companyApplyUrl`, `externalApplyLink`, `link` — the `job.get("applyUrl")` fallback at
  `scripts/sources.py:186` is dead code, not a discarded signal. Not recoverable later either: an
  unauthenticated fetch of a LinkedIn job page returns a guest page with sign-in/captcha markers
  and zero apply-URL occurrences.
- **Indeed: ~20% of listings**, and only with `followApplyRedirects: True` — under today's
  `False`, all populated `externalApplyLink` values were `indeed.com` wrappers. Cost ~+64%
  wall-clock (33.0s → 54.1s / 20 items) against `_apify_run()`'s 400s poll budget; since that
  helper raises rather than returning a partial dataset, flipping the flag without also raising
  its poll count would turn a slow scrape into a silently empty one.
- **Every reachable destination was a custom career site, not an ATS**: `careers.cisco.com`,
  `careers.baptisthealth.net`, `careers.massmutual.com` (Phenom-style, channel `unknown`). Zero
  Greenhouse/Lever/Ashby/Workday.

**Conclusion:** resolving the apply URL would not feed the shipped Layer 2, so that work is not
worth doing on its own. The pipeline's two dominant sources structurally cannot produce a fillable
apply URL, which makes weighting `ENABLED_SOURCES` toward Greenhouse/Lever/Ashby the **only**
mechanism that puts one in the tracker.
