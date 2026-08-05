# End goal

**Already true (Phases 1-2, shipped):** every job at `Reviewed`/`Resume Tailored` gets routed by
channel, has its answerable fields resolved from `APPLICATION_PROFILE` (never guessed for
eligibility/salary/sponsorship), and — for Greenhouse/Lever — gets a real browser pre-fill,
stopping before submit. Nothing here claims `Applied` on its own.

**What's still open (Phase 3 — deliberate submit):** for a narrow, low-risk class only —
Greenhouse-hosted forms with zero custom knockout questions and no captcha — a human can opt into
one flag (`--submit --yes-i-mean-it`) that drives the actual submit click, under a hard daily cap.
Every other class stays semi-auto or manual forever. This phase is deferred by choice, not blocked
on missing capability — the research argues against rushing it (ATSes score application velocity
and flag high-volume submitters as low-intent), so the trigger to pick it up is real usage data
from the fill path, not a calendar date.

**What's still open (Phase 4 — agentic long tail via Playwright):** for the unattended-run case
only — an agentic driver that can navigate Workday's multi-page, account-gated forms and other
long-tail custom sites without a human physically present, always pausing for human confirmation
before anything submits. The interactive case (a human standing on the form) is already solved by
`spec/application-prefill-extension/`; this phase only remains relevant if hands-off,
unattended applying to the long tail becomes an actual goal.
